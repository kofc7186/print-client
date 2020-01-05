# pylint: disable=inconsistent-return-statements,no-member
"""Listens to a Google Pub/Sub Subscription and prints received documents.

This program only runs on Windows and assumes the following environment variables are set:
GOOGLE_APPLICATION_CREDENTIALS -- the path to the service account JSON credentials file
"""
import argparse
import base64
import csv
import logging
import os
import platform
import subprocess
import sys
import tempfile
import time

from google import auth
from google.cloud import firestore, pubsub_v1  # pylint: disable=no-name-in-module
from google.cloud import logging as stackdriver_logging


ARGS = None


class Printers():
    # pylint: disable=too-few-public-methods
    """ Singleton object that fetches list of printers (including default) using `wmic` command"""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Printers, cls).__new__(cls)
            # Put any initialization here.
            cls._instance.printers = []
            cls._instance.default_printer = None
            # pylint: disable=unexpected-keyword-arg
            printer_list_csv = subprocess.check_output("wmic printer get name,default /format:csv",
                                                       text=True)

            reader = csv.DictReader(printer_list_csv.strip().splitlines(), delimiter=",")
            for row in reader:
                cls._instance.printers.append(row['Name'])
                # there should only be one default so no worries about overwriting here
                if row['Default'] == "TRUE":
                    cls._instance.default_printer = row["Name"]
        return cls._instance


def valid_printer(name):
    """ this checks to ensure that the printer specified exists

    Arguments:
    name -- the name of the printer requested
    """
    logging.debug("Testing printer '%s'", name)
    if name not in Printers().printers:  # pylint: disable=no-member
        raise argparse.ArgumentTypeError("'%s' is not a valid printer name on this system" % name)
    return name


def parse_command_line_args(args):
    """ parses arguments specified on the command line when program is run """
    parser = argparse.ArgumentParser(description='Connect to GCP pub/sub to print labels')
    parser.add_argument('-p', '--printer', type=valid_printer, default=Printers().default_printer,
                        help='name of printer to print to (otherwise default printer is used)')
    parser.add_argument('-n', '--number', choices=['odd', 'even', 'all'], default='all',
                        help='which order numbers to print (default is all)')
    parser.add_argument('-l', '--log',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        default='DEBUG', help='log level for messages to print to console')

    return parser.parse_args(args)


def main(args):
    """ main program flow """

    assert ('Windows' in platform.system()), "This program only runs on Windows!"

    if os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', None) is None:
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS environment variable not set")

    credentials, GCP_PROJECT = auth.default()

    global ARGS  # pylint: disable=global-statement
    ARGS = parse_command_line_args(args)

    log_level = getattr(logging, ARGS.log, None)
    logging.basicConfig(level=log_level)

    # log all messages at level to stdout
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(log_level)
    logging.getLogger().addHandler(stdout_handler)

    # also log all messages at level to stackdriver
    stackdriver_client = stackdriver_logging.Client()
    stackdriver_client.setup_logging(log_level=log_level)

    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(GCP_PROJECT, 'print_queue')

    subscriptions = subscriber.list_subscriptions("projects/%s" % GCP_PROJECT)
    if subscription_path not in [x.name for x in subscriptions]:
        logging.error("The subscription named 'print_queue' in GCP Project '%s' must exist before "
                      "this program can be run!", GCP_PROJECT)
        raise RuntimeError("Subscription %s does not exist" % subscription_path)

    logging.info("Listening for %s messages on %s", ARGS.number, subscription_path)

    # there is no way to print more than one document at a time so no need to parallelize
    subscriber.subscribe(subscription_path, callback=received_message_to_print,
                         flow_control=pubsub_v1.types.FlowControl(max_messages=5))

    while block():
        pass  # pragma: no cover


def block():  # pragma: no cover
    """ function to implement 'while true' logic but stubbed out so we can mock it """
    time.sleep(60)
    return True


class WinNamedTempFile():
    """This class creates a NamedTemporaryFile that persists after the file is flushed to disk.

    We need this class on Windows as the default behavior to flush the writes to disk only
    happens when the file is explicitly closed, and we need to be able to pass the file name
    into the print command.
    """
    def __init__(self, file=None):
        self.file = file

    def __enter__(self):
        self.file = tempfile.NamedTemporaryFile(delete=False)
        return self.file

    def __exit__(self, *_):
        if not self.file.closed:
            self.file.close()
        os.unlink(self.file.name)


def validate_message_attributes(message):
    """ validates that the message taken from the subscription has sufficient and valid attributes
        to be successfully processed.

        Throws an exception if the message fails validation
    """
    if not message.attributes:
        # msg is malformed, by nack'ing this we may end up in a loop on it
        error_msg = "Received message with no message attributes; discarding"
        logging.warning(error_msg)
        raise ValueError(error_msg)

    if message.attributes.get("event_id") is None:
        # msg doesn't have event ID, by nack'ing this we may end up in a loop on it
        error_msg = "Received message without event ID; discarding"
        logging.warning(error_msg)
        raise ValueError(error_msg)

    try:
        _ = int(message.attributes.get("order_number", None))
    except TypeError as type_error:
        # msg does not have order number, by nack'ing this we may end up in a loop on it
        logging.warning("Received message with no order number; discarding")
        raise type_error
    except ValueError as value_error:
        # msg doesn't have integer order number, by nack'ing this we may end up in a loop on it
        logging.warning("Received message with invalid order number; discarding")
        raise value_error


def get_database_connection(event_id):
    """ returns connection to database """
    db_ref = firestore.Client()
    return db_ref.collection(u'print_queue/%s/orders' % event_id)


def received_message_to_print(message):
    """ Callback for processing a message received over subscription.

    Note: message.ack() is not guaranteed so this method needs to be idempotent
    """
    logging.debug('Received message id: %s; size %s', message.message_id, message.size)

    try:
        validate_message_attributes(message)
    except Exception:  # pylint: disable=broad-except
        # if any exception is thrown, ack the message so we don't process it again
        return message.ack()

    event_id = message.attributes.get("event_id")
    order_number = int(message.attributes.get("order_number"))
    logging.debug("Received print message for event ID '%s', order number '%s'", event_id,
                  order_number)

    if ARGS.number != 'all':
        if (order_number % 2 == 0 and ARGS.number != 'even') or \
           (order_number % 2 == 1 and ARGS.number != 'odd'):
            logging.warning("Skipping print message for order number '%s' as we are only printing "
                            "%s numbers", order_number, ARGS.number)
            return message.nack()

    # TODO: document use of subcollections to separate by event;
    # TODO: something needs to create the event document within the firestore collection
    print_queue_ref = None
    try:
        print_queue_ref = get_database_connection(event_id)

        # if reprint flag is not set, check to see if this label has been printed already
        if message.attributes.get("reprint", None) is None:
            query = print_queue_ref.where(u'order_number', u'==', order_number).stream()
            # if more than one document is returned, then we should assume this is a duplicate
            # message and we should quietly squelch this
            if len(list(query)) > 0:
                logging.warning("Received duplicate print message for order number '%s'"
                                " without reprint attribute set; squelching", order_number)
                return message.ack()
    except Exception as exc:  # pylint: disable=broad-except
        logging.warning("Exception raised while checking to see if we've printed this label before:"
                        " %s", exc)

    # if we're here, we should try printing the file
    with WinNamedTempFile() as temp_file:
        # write content
        try:
            temp_file.write(base64.b64decode(message.data))
        except base64.binascii.Error as exc:
            logging.error("Could not base64 decode data!")
            message.ack()
            return

        # flush file to disk
        temp_file.close()  # this does not delete file; this will happen when we exit with clause

        try:
            logging.info("Printing label for order number #%s to printer '%s'...", order_number,
                         ARGS.printer)
            # we need spaces around the executable given the space in 'Program Files', and as it is
            # a possibility that the printer name and path to temp_file would have spaces in them as
            # well, we wrap them in quotes too
            print_cmd = '"c:\\\\Program Files\\gs\\gs9.50\\bin\\gswin64c.exe" -dPrinted -dBATCH ' \
                        '-dNOPAUSE -dNOSAFER -q -dNumCopies=1 -dPDFFitPage -sDEVICE=mswinpr2 ' \
                        '-dNoCancel ' \
                        '-sOutputFile="%printer%{}" "{}"'.format(ARGS.printer, temp_file.name)
            subprocess.run(print_cmd, shell=True, check=True)
        except subprocess.CalledProcessError as ex:
            logging.error("Unexpected printing error: %s", str(ex))
            # we failed to print, we nack() to retry
            message.nack()
            # sleep 3 seconds as to not overwhelm client
            time.sleep(3)
            return

        try:
            if print_queue_ref is None:
                print_queue_ref = get_database_connection(event_id)

            print_queue_ref.add({
                u'order_number': order_number,
                u'printer_name': str(ARGS.printer),
                u'hostname': str(platform.node()),
                u'message_id': str(message.message_id),
                u'message_publish_time': str(message.publish_time),
                u'print_timestamp': firestore.SERVER_TIMESTAMP,
            })
        except Exception as exc:  # pylint: disable=broad-except
            logging.warning("Error raised while adding doc to firestore after printing: %s", exc)
        finally:
            message.ack()


if __name__ == '__main__':  # pragma: no cover
    main(sys.argv[1:])
