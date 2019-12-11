# pylint: disable=redefined-outer-name
"""Unit tests for print-client"""

import os
import time

from google.cloud import pubsub_v1
from google.protobuf.timestamp_pb2 import Timestamp

import pytest
import pywintypes

import main

def sleep_once():
    time.sleep(2)
    return False


def mock_open_printer_handle(printer_name):
    if printer_name != 'default_printer':
        raise pywintypes.error(1801, 'OpenPrinter', 'The printer name is invalid.')


@pytest.fixture(autouse=True)
def default_mocker_patches(mocker):
    mocker.patch('main.block', side_effect=sleep_once)
    mocker.patch("win32print.GetDefaultPrinter", return_value="default_printer")
    mocker.patch("win32print.OpenPrinter", side_effect=mock_open_printer_handle)
    mocker.patch("win32print.ClosePrinter")

TOPIC_PATH = "projects/%s/topics/%s" % (os.environ["GCP_PROJECT"], "print_queue")
SUBSCRIPTION_PATH = "projects/%s/subscriptions/%s" % (os.environ["GCP_PROJECT"], "print_queue")

# Create a function-scoped fixture to create a topic and a subscription
@pytest.fixture
def publisher_client():
    # pylint: disable=no-member
    publisher_client = pubsub_v1.PublisherClient()
    topics = publisher_client.list_topics("projects/%s" % os.environ["GCP_PROJECT"])
    if not TOPIC_PATH in [x.name for x in topics]:
        publisher_client.create_topic(TOPIC_PATH)

    # must create subscription before message is sent
    subscriber_client = pubsub_v1.SubscriberClient()
    subscriptions = subscriber_client.list_subscriptions("projects/%s" % os.environ["GCP_PROJECT"])
    if not SUBSCRIPTION_PATH in [x.name for x in subscriptions]:
        subscriber_client.create_subscription(SUBSCRIPTION_PATH, TOPIC_PATH,
                                              retain_acked_messages=True)

    # ack all messages before the test case starts
    now = time.time()
    seconds = int(now)
    reset_ts = Timestamp(seconds=seconds, nanos=int((now-seconds) * 10**9))
    subscriber_client.seek(subscription=SUBSCRIPTION_PATH, time=reset_ts)

    return publisher_client


# create a fixture to add a message
@pytest.fixture
def add_label_to_print():
    def _loader(filename, publisher_client, order_number, attributes=None):
        with open(filename, "rb") as pdf:
            pdf_data = pdf.read()

        args = {}
        if order_number:
            args['order_number'] = str(order_number)
        if attributes:
            args.update(attributes)
        publisher_client.publish(TOPIC_PATH, data=pdf_data, **args)

    return _loader


def test_no_message_attributes(mocker, publisher_client, add_label_to_print):
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_shell_execute = mocker.patch('win32api.ShellExecute')
    order_number = None
    add_label_to_print("tests/test_label.pdf", publisher_client, order_number)
    # use default printer and all order numbers
    main.main([])
    #ensure message is acked
    mock_ack.assert_called_once()
    #ensure print was not called
    mock_shell_execute.assert_not_called()


def test_no_even_messages_printed(mocker, publisher_client, add_label_to_print):
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_shell_execute = mocker.patch('win32api.ShellExecute')
    order_number = 1
    add_label_to_print("tests/test_label.pdf", publisher_client, order_number)
    # use default printer and only even order numbers
    main.main(["-n", "even"])
    #ensure message is nacked, not acked
    mock_nack.assert_called_once()
    mock_ack.assert_not_called()
    #ensure print was not called
    mock_shell_execute.assert_not_called()


def test_no_odd_messages_printed(mocker, publisher_client, add_label_to_print):
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_shell_execute = mocker.patch('win32api.ShellExecute')
    order_number = 2
    add_label_to_print("tests/test_label.pdf", publisher_client, order_number)
    # use default printer and only odd order numbers
    main.main(["-n", "odd"])
    #ensure message is nacked, not acked
    mock_nack.assert_called_once()
    mock_ack.assert_not_called()
    #ensure print was not called
    mock_shell_execute.assert_not_called()


def test_invalid_order_number(mocker, publisher_client, add_label_to_print):
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_shell_execute = mocker.patch('win32api.ShellExecute')
    order_number = "not_a_number"
    add_label_to_print("tests/test_label.pdf", publisher_client, order_number)
    # use default printer and all order numbers
    main.main([])
    #ensure message is acked (discarded)
    mock_ack.assert_called_once()
    #ensure print was not called
    mock_shell_execute.assert_not_called()


def test_other_attributes_but_no_order_number(mocker, publisher_client, add_label_to_print):
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_shell_execute = mocker.patch('win32api.ShellExecute')
    order_number = None
    attributes = {"a": "1"}
    add_label_to_print("tests/test_label.pdf", publisher_client, order_number, attributes)
    # use default printer and all order numbers
    main.main([])
    #ensure message is acked (discarded)
    mock_ack.assert_called_once()
    #ensure print was not called
    mock_shell_execute.assert_not_called()


def throw_print_exception(*args, **kwargs):
    raise pywintypes.error(1801, 'ShellExecute', 'Unknown Printing Error.')


def test_printer_failure(mocker, publisher_client, add_label_to_print):
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_shell_execute = mocker.patch('win32api.ShellExecute', side_effect=throw_print_exception)
    order_number = 1
    add_label_to_print("tests/test_label.pdf", publisher_client, order_number)
    # use default printer and all order numbers
    main.main([])
    #ensure print was called
    mock_shell_execute.assert_called_once()
    #ensure message is nacked, not acked to ensure we try to re-print this
    mock_nack.assert_called_once()
    mock_ack.assert_not_called()


def test_print_success(mocker, publisher_client, add_label_to_print):
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_shell_execute = mocker.patch('win32api.ShellExecute')
    order_number = 1
    add_label_to_print("tests/test_label.pdf", publisher_client, order_number)
    # use default printer and all order numbers
    main.main([])
    #ensure print was called
    mock_shell_execute.assert_called_once()
    #ensure message is nacked, not acked to ensure we try to re-print this
    mock_ack.assert_called_once()
    mock_nack.assert_not_called()
