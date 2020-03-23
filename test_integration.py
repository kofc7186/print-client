# pylint: disable=redefined-outer-name
"""Unit tests for print-client"""

from argparse import Namespace
import base64
import platform
import subprocess
import time
from unittest import mock

from google.auth import credentials
from google.cloud import firestore, pubsub_v1  # pylint: disable=no-name-in-module
from google.protobuf.timestamp_pb2 import Timestamp

import pytest

import main


@pytest.fixture(autouse=True)
def default_mocker_patches(mocker, monkeypatch):
    """ Common mocks across all of the integration tests in this file

        - ensure that the program exits after 2 seconds
        - ensure that default values are passed in for printers
    """
    mocker.patch.object(platform, "system", return_value="Windows")

    mocker.patch('google.cloud.logging.Client')
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "some.json")
    mocker.patch('google.auth.default', return_value=(mock.Mock(spec=credentials.Credentials),
                                                      "print-client-123456"))
    mocker.patch('main.block', side_effect=lambda: bool(time.sleep(2)))
    mock_printers = mocker.patch.object(main.Printers, "_instance")
    mock_printers.default_printer = "default_printer"
    mock_printers.printers = ["default_printer", "good_printer"]
    mocker.patch.object(main, "ARGS", Namespace(printer="default_printer", number="all"))


TEST_EVENT_DATE = '1900-01-01'
GCP_PROJECT = "print-client-123456"
TOPIC_PATH = "projects/%s/topics/%s" % (GCP_PROJECT, "print_queue")
SUBSCRIPTION_PATH = "projects/%s/subscriptions/%s" % (GCP_PROJECT, "print_queue")


@pytest.fixture
def publisher_client():
    """ Factory as fixture that creates a topic on the emulator for messages and ensures that the
        subscription for 'print_queue' exists before the test case(s) are started

        This fixture also ensures that all prior messages are ignored by each test case by using the
        seek function of GCP pubsub to ignore all messages received before the test case was run
    """
    # pylint: disable=no-member
    publisher_client = pubsub_v1.PublisherClient()
    topics = publisher_client.list_topics("projects/%s" % GCP_PROJECT)
    if TOPIC_PATH not in [x.name for x in topics]:
        publisher_client.create_topic(TOPIC_PATH)

    # must create subscription before message is sent
    subscriber_client = pubsub_v1.SubscriberClient()
    subscriptions = subscriber_client.list_subscriptions("projects/%s" % GCP_PROJECT)
    if SUBSCRIPTION_PATH not in [x.name for x in subscriptions]:
        subscriber_client.create_subscription(SUBSCRIPTION_PATH, TOPIC_PATH,
                                              retain_acked_messages=True)

    # ack all messages before the test case starts
    now = time.time()
    seconds = int(now)
    reset_ts = Timestamp(seconds=seconds, nanos=int((now-seconds) * 10**9))
    subscriber_client.seek(subscription=SUBSCRIPTION_PATH, time=reset_ts)

    return publisher_client


@pytest.fixture
def add_label_to_print():
    """ Factory as fixture that publishes a message with specified order number, attributes, and
        the contents of a real PDF file to the topic on the emulator
    """
    def _loader(filename, publisher_client, order_number, event_date, attributes=None):
        with open(filename, "rb") as pdf:
            pdf_data = base64.b64encode(pdf.read())

        args = {}
        if order_number:
            args['order_number'] = str(order_number)
        if event_date:
            args['event_date'] = str(event_date)
        if attributes:
            # only set event_date if we were passed a non-null attribute set
            args.update(attributes)
        publisher_client.publish(TOPIC_PATH, data=pdf_data, **args)

    return _loader


@pytest.fixture()
def gen_mock_firestore_client(*_args, **_kwargs):
    """ creates the correct firestore emulator client to use in tests; also deletes all relevant
        documents before each test case is run
    """
    client = firestore.Client()

    # we need to iterate through the relevant collection and delete all documents
    docs = client.collection(f'events/{TEST_EVENT_DATE}/print_queue').stream()
    for doc in docs:
        doc.reference.delete()

    return client


def test_no_message_attributes(mocker, publisher_client, add_label_to_print):
    """ Tests that a message received with no message attributes (i.e. missing the order number)
        will be squelched
    """
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_print = mocker.patch('subprocess.run')
    order_number = None
    event_date = TEST_EVENT_DATE
    add_label_to_print("tests/test_label.pdf", publisher_client, order_number, event_date)
    # use default printer and all order numbers
    main.main([])
    # ensure message is acked
    mock_ack.assert_called_once()
    # ensure print was not called
    mock_print.assert_not_called()


def test_no_odd_messages_printed(mocker, publisher_client, add_label_to_print):
    """ Tests that a message received with an odd order number will not be printed when the
        command line value of 'even' was specified
    """
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_print = mocker.patch('subprocess.run')
    order_number = 1
    event_date = TEST_EVENT_DATE
    add_label_to_print("tests/test_label.pdf", publisher_client, order_number, event_date)
    # use default printer and only even order numbers
    main.main(["-n", "even"])
    # ensure message is nacked, not acked
    mock_nack.assert_called_once()
    mock_ack.assert_not_called()
    # ensure print was not called
    mock_print.assert_not_called()


def test_no_even_messages_printed(mocker, publisher_client, add_label_to_print):
    """ Tests that a message received with an even order number will not be printed when the
        command line value of 'odd' was specified
    """
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_print = mocker.patch('subprocess.run')
    order_number = 2
    event_date = TEST_EVENT_DATE
    add_label_to_print("tests/test_label.pdf", publisher_client, order_number, event_date)
    # use default printer and only odd order numbers
    main.main(["-n", "odd"])
    # ensure message is nacked, not acked
    mock_nack.assert_called_once()
    mock_ack.assert_not_called()
    # ensure print was not called
    mock_print.assert_not_called()


def test_invalid_order_number(mocker, publisher_client, add_label_to_print):
    """ Tests that a message received with a non-integer order number will not be printed and
        appropriately squelched
    """
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_print = mocker.patch('subprocess.run')
    order_number = "not_a_number"
    event_date = TEST_EVENT_DATE
    add_label_to_print("tests/test_label.pdf", publisher_client, order_number, event_date)
    # use default printer and all order numbers
    main.main([])
    # ensure message is acked (discarded)
    mock_ack.assert_called_once()
    # ensure print was not called
    mock_print.assert_not_called()


def test_other_attributes_but_no_order_number(mocker, publisher_client, add_label_to_print):
    """ Tests that a message received with insufficient message attributes (i.e. missing the order
        number) will be squelched
    """
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_print = mocker.patch('subprocess.run')
    order_number = None
    event_date = TEST_EVENT_DATE
    attributes = {"a": "1"}
    add_label_to_print("tests/test_label.pdf", publisher_client, order_number, event_date, attributes)
    # use default printer and all order numbers
    main.main([])
    # ensure message is acked (discarded)
    mock_ack.assert_called_once()
    # ensure print was not called
    mock_print.assert_not_called()


def test_printer_failure(mocker, publisher_client, add_label_to_print, gen_mock_firestore_client):
    """ Tests that if there is a problem printing the label, we will place the request back on the
        subscription to be reprinted
    """
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mocker.patch('google.cloud.firestore.Client', return_value=gen_mock_firestore_client)
    mock_print = mocker.patch('subprocess.run',
                              side_effect=subprocess.CalledProcessError(cmd="gswin64.exe",
                                                                        returncode=1))
    order_number = 1
    event_date = TEST_EVENT_DATE
    add_label_to_print("tests/test_label.pdf", publisher_client, order_number, event_date)
    # use default printer and all order numbers
    main.main([])
    # ensure print was called
    mock_print.assert_called_once()
    # ensure message is nacked, not acked to ensure we try to re-print this
    mock_nack.assert_called_once()
    mock_ack.assert_not_called()


def test_print_success(mocker, publisher_client, add_label_to_print, gen_mock_firestore_client):
    """ Tests good path for a valid message that should be sent to the printer """
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mocker.patch('google.cloud.firestore.Client', return_value=gen_mock_firestore_client)
    mock_print = mocker.patch('subprocess.run')

    order_number = 1
    event_date = TEST_EVENT_DATE
    add_label_to_print("tests/test_label.pdf", publisher_client, order_number, event_date)
    # use default printer and all order numbers
    main.main([])
    # ensure print was called
    mock_print.assert_called_once()
    # ensure message is nacked, not acked to ensure we try to re-print this
    mock_ack.assert_called_once()
    mock_nack.assert_not_called()
    # check firestore to see that record was put in
    db_conn = gen_mock_firestore_client.collection(f'events/{event_date}/print_queue')
    db_results = db_conn.where(u'order_number', u'==', order_number)
    # ensure we have a single record in the DB
    assert len(list(db_results.stream())) == 1


def test_reprint_label(mocker, publisher_client, add_label_to_print, gen_mock_firestore_client):
    """ Tests that a message received with reprint command will be printed and acked """
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mocker.patch('google.cloud.firestore.Client', return_value=gen_mock_firestore_client)
    mock_print = mocker.patch('subprocess.run')
    order_number = 1
    event_date = TEST_EVENT_DATE
    attributes = {"reprint": "True"}
    add_label_to_print("tests/test_label.pdf", publisher_client, order_number, event_date, attributes)
    # use default printer and all order numbers
    main.main([])
    # ensure print was called and we acked message
    mock_ack.assert_called_once()
    mock_print.assert_called_once()
    mock_nack.assert_not_called()
    # check firestore to see that a record was put in
    db_conn = gen_mock_firestore_client.collection(f'events/{event_date}/print_queue')
    db_results = db_conn.where(u'order_number', u'==', order_number)
    # ensure we have one record in the DB
    assert len(list(db_results.stream())) == 1


def test_idempotent_print(mocker, publisher_client, add_label_to_print, gen_mock_firestore_client):
    """ Tests path for a duplicate message that should be squelched """
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mocker.patch('google.cloud.firestore.Client', return_value=gen_mock_firestore_client)
    mock_print = mocker.patch('subprocess.run')

    order_number = 1
    # put an entry into the DB denoting that the label has already been printed
    gen_mock_firestore_client.collection(f'events/{TEST_EVENT_DATE}/print_queue').add({
            u'order_number': order_number,
            u'printer_name': "doesnt_matter",
            u'hostname': "localhost",
            u'message_id': "12345",
            u'message_publish_time': "sometime",
            u'print_timestamp': firestore.SERVER_TIMESTAMP
        })

    event_date = TEST_EVENT_DATE
    add_label_to_print("tests/test_label.pdf", publisher_client, order_number, event_date)
    # use default printer and all order numbers
    main.main([])
    # ensure print was not called
    mock_print.assert_not_called()
    # ensure message is acked and therefore squelched to ensure we didn't incorrectly reprint
    mock_ack.assert_called_once()
    mock_nack.assert_not_called()


def test_database_error_before_print(mocker, publisher_client, add_label_to_print,
                                     gen_mock_firestore_client):
    """ Tests that if an error occurs during interaction with the firestore DB before printing,
        printing still succeeds and the message is acked """

    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mocker.patch('google.cloud.firestore.Client', return_value=gen_mock_firestore_client)
    mocker.patch('google.cloud.firestore.Client.collection.where',
                 side_effect=RuntimeError("Error!"))
    mock_print = mocker.patch('subprocess.run')

    order_number = 1
    event_date = TEST_EVENT_DATE
    add_label_to_print("tests/test_label.pdf", publisher_client, order_number, event_date)
    # use default printer and all order numbers
    main.main([])

    mock_ack.assert_called_once()
    mock_nack.assert_not_called()
    mock_print.assert_called_once()


def test_database_error_before_and_after_print(mocker, publisher_client, add_label_to_print):
    """ Tests that if an error occurs during interaction with the firestore DB, printing still
        succeeds and the message is acked"""

    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mocker.patch('google.cloud.firestore.Client', side_effect=RuntimeError("Connection failed"))
    mock_print = mocker.patch('subprocess.run')

    order_number = 1
    event_date = TEST_EVENT_DATE
    add_label_to_print("tests/test_label.pdf", publisher_client, order_number, event_date)
    # use default printer and all order numbers
    main.main([])

    mock_ack.assert_called_once()
    mock_nack.assert_not_called()
    mock_print.assert_called_once()


def test_database_error_after_print(mocker, publisher_client, add_label_to_print,
                                    gen_mock_firestore_client):
    """ Tests that if an error occurs during interaction with the firestore DB after printing,
        sending the message ack still happens """

    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mocker.patch('google.cloud.firestore.Client', return_value=gen_mock_firestore_client)
    mocker.patch('google.cloud.firestore.Client.collection.add', side_effect=RuntimeError("Error!"))
    mock_print = mocker.patch('subprocess.run')

    order_number = 1
    event_date = TEST_EVENT_DATE
    add_label_to_print("tests/test_label.pdf", publisher_client, order_number, event_date)
    # use default printer and all order numbers
    main.main([])

    mock_ack.assert_called_once()
    mock_nack.assert_not_called()
    mock_print.assert_called_once()
