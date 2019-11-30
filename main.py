"""Listens to a Google Pub/Sub Subscription and prints received documents.

This program only runs on Windows and assumes the following environment variables are set:
GCP_PROJECT_ID                 -- the project ID where the pub/sub subscription exists
GOOGLE_APPLICATION_CREDENTIALS -- the path to the service account JSON credentials file
"""
import argparse
import logging
import os
import tempfile
import time

from google.cloud import pubsub_v1
import pywintypes
import win32api
import win32print


LOGGER = logging.getLogger(__name__)
LOGGER.getLogger('google.cloud').addHandler(logging.NullHandler())


def valid_printer(name):
    """ this checks to ensure that the printer specified exists

    Arguments:
    name -- the name of the printer requested
    """
    LOGGER.debug("Testing printer '%s'", name)
    try:
        win32print.ClosePrinter(win32print.OpenPrinter(name))
        return name
    except Exception:
        raise argparse.ArgumentTypeError("'%s' is not a valid printer name on this system" % name)


# parse cmd line args
PARSER = argparse.ArgumentParser(description='Connect to GCP pub/sub to print labels')
PARSER.add_argument('-p', '--printer', type=valid_printer, default=win32print.GetDefaultPrinter(),
                    help='name of printer to print to (otherwise default printer is used)')
PARSER.add_argument('-n', '--number', choices=['odd', 'even', 'all'], default='all',
                    help='which order numbers to print (default is all)')
PARSER.add_argument('-l', '--log', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                    default='INFO', help='which order numbers to print (default is all)')

ARGS = PARSER.parse_args()
logging.basicConfig(level=getattr(logging, ARGS.log, None))


def main():
    """ main program flow """
    # pylint: disable=no-member
    if not os.environ.get('GCP_PROJECT_ID', None):
        raise Exception("GCP_PROJECT_ID environment variable not set")

    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(os.environ['GCP_PROJECT_ID'], 'print_queue')

    LOGGER.info("Listening for %s messages on %s", ARGS.number, subscription_path)

    # there is no way to print more than one document at a time so no need to parallelize
    subscriber.subscribe(subscription_path, callback=received_message_to_print,
                         flow_control=pubsub_v1.types.FlowControl(max_messages=1))

    while True:
        time.sleep(60)


def received_message_to_print(message):
    """ Callback for processing a message received over subscription.

    Note: message.ack() is not guaranteed so this method needs to be idempotent
    """
    LOGGER.debug('Received message id: %s; size %s', message.message_id, message.size)

    if message.attributes:
        # if reprint flag is not set, check to see if we have marked this label as printed already
        if not message.attributes.get("reprint"):
            # TODO: query database for printed timestamp
            pass

        # if we're printing all labels, skip odd/even check
        if ARGS.number != 'all':
            order_number = message.attributes.get("orderNumber")
            if order_number:
                LOGGER.info("Received print message for order number '%s'", order_number)
                try:
                    if (int(order_number) % 2 == 0 and ARGS.number != 'even') or \
                       (int(order_number) % 2 == 1 and ARGS.number != 'odd'):
                        LOGGER.warning("Skipping print message for order number '%s' as we are "
                                       "only printing %s numbers", order_number, ARGS.number)
                        return message.nack()
                except ValueError:
                    LOGGER.warning("Received message with invalid order number; discarding")
                    return message.ack()
            else:
                # message does not have order number, by nack'ing this we may end up in a loop on it
                LOGGER.warning("Received message with no order number; discarding")
                return message.ack()
    else:
        # message is malformed, by nack'ing this we may end up in a loop on it
        LOGGER.warning("Received message with no message attributes; discarding")
        return message.ack()

    class WinTempNamedFile():
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
            os.unlink(self.file.name)

    # if we're here, we should try printing the file
    with WinTempNamedFile() as temp_file:
        # write content
        temp_file.write(message.data)

        # flush file to disk
        temp_file.close()  # this does not delete file; this will happen when we exit with clause

        try:
            win32api.ShellExecute(0, "print", temp_file.name, '/d:"%s"' % ARGS.printer, ".", 0)
            # TODO: write printed timestamp to database
            return message.ack()
        except pywintypes.error as ex:
            LOGGER.error("Unexpected printing error: %s", str(ex))
            # TODO: insert sleep here; if there was a printing error we'll be back here in ms
            message.nack()
            time.sleep(3)


if __name__ == '__main__':
    main()
