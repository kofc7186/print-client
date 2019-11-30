import argparse
import logging
import os

import tempfile
import time
import win32api
import win32print

from google.cloud import pubsub_v1

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# this class exists so we can use the file name during the print operation, and be
# sure that the file is closed when we're done with it using a with clause
class WinTempNamedFile(object):
    def __enter__(self):
        self.file = tempfile.NamedTemporaryFile(delete=False)
        return self.file

    def __exit(self):
        os.unlink(self.file.name)

# this checks to ensure that the printer name is valid before we start
def valid_printer(name):
    logging.debug("Testing printer '%s'" % name)
    printer = win32api.OpenPrinter(name)
    if printer:
        win32api.ClosePrinter(printer)
        return name
    else:
        raise argparse.ArgumentTypeError("'%s' is not a valid printer name on this system")

def received_message_to_print(message):
    logging.debug('Received message id: %s; size %s' % (message.message_id, message.size))

    if message.attributes:
        # check for reprint flagexit


        # if we're printing all labels, skip odd/even check
        if args.number != 'all':
            orderNumber = message.attributes.get("orderNumber")
            if orderNumber and int(orderNumber):
                logging.info("Received print message for order number '%s'" % orderNumber)
                if (int(orderNumber) % 2 == 0 and args.number != 'even') or \
                   (int(orderNumber) % 2 == 1 and args.number != 'odd'):
                    logging.warning("Skipping print message for order number '%s' as we are only printing %s numbers" %
                                    (orderNumber, args.number))
                    return message.nack()
            else:
                # message does not have order number, by nack'ing this we may end up in a loop on it
                logging.error("Received message with no order number; discarding")
                return message.ack()
    else:
        # message is malformed, by nack'ing this we may end up in a loop on it
        logging.error("Received message with no message attributes; discarding")
        return message.ack()

    # if we're here, we should try printing the file
    with WinTempNamedFile() as f:
        # write content
        f.write(message.data)

        # flush file to disk
        f.close() # this does not delete file; this will happen when we exit with clause

        try:
            win32api.ShellExecute(0, "print", f.name, '/d:"%s"' % args.printer, ".", 0)
            return message.ack()
        except:
            logging.error("Unexpected printing error: %s" % sys.exc_info()[0])
            return message.nack()

def main():
    parser = argparse.ArgumentParser(description='Connect to GCP pub/sub to print labels')
    parser.add_argument('-p', '--printer', type=valid_printer, default=win32print.GetDefaultPrinter(),
                        help='name of printer to print to (otherwise default printer is used)')
    parser.add_argument('-n', '--number', choices=['odd','even','all'], default='all',
                        help='which order numbers to print (default is all)')

    args = parser.parse_args()

    if not os.environ.get('GCP_PROJECT_ID',None):
        raise Exception("GCP_PROJECT_ID environment variable not set")

    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(os.environ['GCP_PROJECT_ID'], 'print_queue')

    print('Listening for messages on {}'.format(subscription_path))

    #TODO: do we need to keep a record of what we've printed and only reprint when the flag is set?
    # message.ack() is not guaranteed so we are supposed to be idempotent... do we need to query/set a DB flag?
    subscriber.subscribe(subscription_path, callback=received_message_to_print)

    while True:
        time.sleep(60)

if __name__ == '__main__':
    main()
