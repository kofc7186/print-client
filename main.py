# pylint: disable=inconsistent-return-statements
"""Listens to a Google Pub/Sub Subscription and prints received documents.

This program only runs on Windows and assumes the following environment variables are set:
GCP_PROJECT                    -- the project ID where the pub/sub subscription exists
GOOGLE_APPLICATION_CREDENTIALS -- the path to the service account JSON credentials file
"""
import argparse
import logging
import os
import sys
import tempfile
import time

from google.cloud import pubsub_v1
import win32api
import win32print


# squelch google cloud logging
logging.getLogger('google.cloud').addHandler(logging.NullHandler())

ARGS = None


def valid_printer(name):
    """ this checks to ensure that the printer specified exists

    Arguments:
    name -- the name of the printer requested
    """
    logging.debug("Testing printer '%s'", name)
    try:
        win32print.ClosePrinter(win32print.OpenPrinter(name))
        return name
    except Exception:
        raise argparse.ArgumentTypeError("'%s' is not a valid printer name on this system" % name)


def main(args):
    """ main program flow """
    # pylint: disable=no-member
    if not os.environ.get('GCP_PROJECT', None):
        raise Exception("GCP_PROJECT environment variable not set")

    # parse cmd line args
    parser = argparse.ArgumentParser(description='Connect to GCP pub/sub to print labels')
    parser.add_argument('-p', '--printer', type=valid_printer,
                        default=win32print.GetDefaultPrinter(),
                        help='name of printer to print to (otherwise default printer is used)')
    parser.add_argument('-n', '--number', choices=['odd', 'even', 'all'], default='all',
                        help='which order numbers to print (default is all)')
    parser.add_argument('-l', '--log',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        default='INFO', help='which order numbers to print (default is all)')

    global ARGS  # pylint: disable=global-statement
    ARGS = parser.parse_args(args)
    logging.basicConfig(level=getattr(logging, ARGS.log, None))

    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(os.environ['GCP_PROJECT'], 'print_queue')

    logging.info("Listening for %s messages on %s", ARGS.number, subscription_path)

    subscriptions = subscriber.list_subscriptions("projects/%s" % os.environ["GCP_PROJECT"])
    if subscription_path not in [x.name for x in subscriptions]:
        logging.error("The subscription named 'print_queue' in this GCP Project must exist before" \
                      " this program can be run!")
        raise Exception("Subscription %s does not exist" % subscription_path)

    # there is no way to print more than one document at a time so no need to parallelize
    subscriber.subscribe(subscription_path, callback=received_message_to_print,
                         flow_control=pubsub_v1.types.FlowControl(max_messages=5))

    while block():
        pass


# this is broken into a function so we can break out in unit tests
def block():
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


def received_message_to_print(message):
    """ Callback for processing a message received over subscription.

    Note: message.ack() is not guaranteed so this method needs to be idempotent
    """
    logging.debug('Received message id: %s; size %s', message.message_id, message.size)

    if message.attributes:
        # if reprint flag is not set, check to see if we have marked this label as printed already
        if not message.attributes.get("reprint"):
            # TODO: query database for printed timestamp
            pass

        try:
            order_number = int(message.attributes.get("order_number", None))
            logging.debug("Received print message for order number '%s'", order_number)
            if ARGS.number != 'all':
                if (order_number % 2 == 0 and ARGS.number != 'even') or \
                   (order_number % 2 == 1 and ARGS.number != 'odd'):
                    logging.warning("Skipping print message for order number '%s' as we are "
                                    "only printing %s numbers", order_number, ARGS.number)
                    return message.nack()
        except TypeError:
            # msg does not have order number, by nack'ing this we may end up in a loop on it
            logging.warning("Received message with no order number; discarding")
            return message.ack()
        except ValueError:
            # msg doesn't have integer order number, by nack'ing this we may end up in a loop on it
            logging.warning("Received message with invalid order number; discarding")
            return message.ack()
    else:
        # msg is malformed, by nack'ing this we may end up in a loop on it
        logging.warning("Received message with no message attributes; discarding")
        return message.ack()

    # if we're here, we should try printing the file
    with WinNamedTempFile() as temp_file:
        # write content
        temp_file.write(message.data)

        # flush file to disk
        temp_file.close()  # this does not delete file; this will happen when we exit with clause

        try:
            win32api.ShellExecute(0, "print", temp_file.name, '/d:"%s"' % ARGS.printer, ".", 0)
        except Exception as ex:
            logging.error("Unexpected printing error: %s", str(ex))
            # we failed to print, we nack() to retry
            message.nack()
            # sleep 3 seconds as to not overwhelm client
            time.sleep(3)
            return
        # TODO: what if we delete the file before the printer is done?
        # TODO: write printed timestamp to database
        return message.ack()


if __name__ == '__main__':
    main(sys.argv[1:])
