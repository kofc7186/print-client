# pylint: disable=redefined-outer-name,unused-argument
"""Unit tests for print-client"""

import argparse
import base64
import datetime
import os
import platform
import queue
import subprocess
import time

import pytest
import pytz

from google.auth import credentials
from google.api_core import datetime_helpers
from google.cloud.pubsub_v1 import types
from google.cloud.pubsub_v1.subscriber import message
from google.protobuf.timestamp_pb2 import Timestamp
from unittest import mock

import main

TEST_EVENT_ID = 'test_integration'


WMIC_OUTPUT_ONE_DEFAULT = """

Node,Default,Name
ADMIN-PC,FALSE,Fax
ADMIN-PC,TRUE,Dymo LabelMaker 450 Turbo
ADMIN-PC,FALSE,Microsoft Print to PDF
"""
WMIC_OUTPUT_NO_DEFAULT = """

Node,Default,Name
ADMIN-PC,FALSE,Fax
ADMIN-PC,FALSE,Dymo LabelMaker 450 Turbo
ADMIN-PC,FALSE,Microsoft Print to PDF
"""
WMIC_OUTPUT_NO_PRINTERS = """

Default,Name
"""
WMIC_ERROR = """
Error! Not a CSV
"""


@pytest.fixture
def delete_printer_singleton(monkeypatch):
    """ clears the printers singleton contents for unit testing"""
    monkeypatch.setattr(main.Printers, "_instance", None)


@pytest.fixture(autouse=True)
def default_mocker_patches(request, mocker, monkeypatch):
    """ Common mocks across most of the unit tests in this file; will not be applied if the custom
        pytest mark named 'noprintermark' is denoted on the test case

        creates two printers 'default_printer' and 'good_printer', and sets the default accordingly
        also sets the default order numbers to be processed as 'all'
    """
    mocker.patch.object(platform, 'system', return_value="Windows")
    mocker.patch('google.cloud.logging.Client')
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "path.json")
    mocker.patch('google.auth.default', return_value=(mock.Mock(spec=credentials.Credentials),
                                                      "print-client-123456"))
    if 'noprintermock' not in request.keywords:
        mock_printers = mocker.patch.object(main.Printers, "_instance")
        mock_printers.default_printer = "default_printer"
        mock_printers.printers = ["default_printer", "good_printer"]
        mocker.patch.object(main, "ARGS", argparse.Namespace(printer="default_printer",
                                                             number="all"))


RECEIVED = datetime.datetime(2012, 4, 21, 15, 0, tzinfo=pytz.utc)
RECEIVED_SECONDS = datetime_helpers.to_milliseconds(RECEIVED) // 1000
PUBLISHED_MICROS = 123456
PUBLISHED = RECEIVED + datetime.timedelta(days=1, microseconds=PUBLISHED_MICROS)
PUBLISHED_SECONDS = datetime_helpers.to_milliseconds(PUBLISHED) // 1000


@pytest.fixture
def receive_messsage_unit_test_fixture(mocker):
    """ Factory as fixture that creates a correctly formatted pubsub message to be passed to
        the callback function specified for the subscription
    """
    def _loader(data, attrs, ack_id="ACKID"):
        mocker.patch.object(time, "time", return_value=RECEIVED_SECONDS)
        msg = message.Message(
            types.PubsubMessage(  # pylint: disable=no-member
                attributes=attrs,
                data=data,
                message_id="message_id",
                publish_time=Timestamp(
                    seconds=PUBLISHED_SECONDS, nanos=PUBLISHED_MICROS * 1000
                ),
            ),
            ack_id,
            queue.Queue(),
        )
        return msg

    return _loader


@pytest.mark.parametrize("system", ["Linux", "Darwin", "Java"])
def test_runs_only_on_windows(system, mocker):
    """ tests that program will not run on any system type other than windows"""
    mocker.patch.object(platform, "system", return_value=system)
    with pytest.raises(AssertionError) as exc:
        main.main([])
    assert str(exc.value) == "This program only runs on Windows!"


def test_gac_envvar(monkeypatch):
    """ tests that program will not run without GOOGLE_APPLICATION_CREDENTIALS environment variable
        being set
    """
    # clear environment
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    with pytest.raises(RuntimeError) as exc:
        main.main([])
    assert str(exc.value) == "GOOGLE_APPLICATION_CREDENTIALS environment variable not set"


def test_winnamedtempfile_notdeletedwithinwithscope():
    """ ensures that when we create a temp file, write its contents, and close it (to flush
        contents to disk), that the file is not deleted until we exit the scope of the 'with'
        statement
    """
    # need to test that file is not deleted until object is deleted
    name = ""
    with main.WinNamedTempFile() as temp_file:
        name = temp_file.name
        assert os.path.exists(name)
        temp_file.write(b'1')
        temp_file.close()
        # ensure that the file wasn't deleted when we called close()
        assert os.path.exists(name)
        # ensure the content got flushed to the file
        assert open(name, 'rb').read() == b'1'
    # now that we have dropped scope, the file should have been deleted
    assert not os.path.exists(name)


def test_winnamedtempfile_closedbeforedelete():
    """ ensures that if the file is not explicitly closed before exiting the scope of the
        'with' statement, the file is properly closed before being deleted
    """
    name = ""
    with main.WinNamedTempFile() as temp_file:
        name = temp_file.name
        assert os.path.exists(name)
        temp_file.write(b'1')
        # ensure that the file wasn't deleted when we called close()
        assert os.path.exists(name)
    # now that we have dropped scope, the file should have been deleted
    assert temp_file.closed
    assert not os.path.exists(name)


@pytest.mark.noprintermock
def test_printer_class_one_default(mocker, delete_printer_singleton):
    """ tests the case where there are multiple printers, and a default specified; ensures that
        the values are properly parsed and presented to argparse.ArgumentParser
    """
    # pylint: disable=no-member
    mocker.patch('subprocess.check_output', return_value=WMIC_OUTPUT_ONE_DEFAULT)

    printers = main.Printers()

    assert printers.printers == ['Fax', 'Dymo LabelMaker 450 Turbo', 'Microsoft Print to PDF']
    assert printers.default_printer == "Dymo LabelMaker 450 Turbo"


@pytest.mark.noprintermock
def test_printer_class_no_default(mocker, delete_printer_singleton):
    """ tests the case where there are multiple printers, and no default specified; ensures that
        the values are properly parsed and presented to argparse.ArgumentParser
    """
    # pylint: disable=no-member
    mocker.patch('subprocess.check_output', return_value=WMIC_OUTPUT_NO_DEFAULT)

    printers = main.Printers()

    assert printers.printers == ['Fax', 'Dymo LabelMaker 450 Turbo', 'Microsoft Print to PDF']
    assert printers.default_printer is None


@pytest.mark.noprintermock
def test_printer_class_none(mocker, delete_printer_singleton):
    """ tests the case where there are no printers installed on the system; ensures that
        empty / None values are presented to argparse.ArgumentParser
    """
    # pylint: disable=no-member
    mocker.patch('subprocess.check_output', return_value=WMIC_OUTPUT_NO_PRINTERS)

    printers = main.Printers()

    assert printers.printers == []
    assert printers.default_printer is None


@pytest.mark.noprintermock
def test_printer_class_error(mocker, delete_printer_singleton):
    """ tests the case where there is an error in calling the 'wmic' command and ensures an
        exception is thrown which will cause the argparse.ArgumentParser to fail
    """
    # pylint: disable=no-member
    mocker.patch('subprocess.check_output',
                 side_effect=subprocess.CalledProcessError(cmd="gswin64.exe",
                                                           returncode=1,
                                                           output=WMIC_ERROR))

    with pytest.raises(subprocess.CalledProcessError):
        main.Printers()


def test_good_non_default_printer(mocker):
    """ Tests that a non-default but valid printer can be specified and used """

    args = main.parse_command_line_args(["-p", "good_printer"])

    assert args.printer == "good_printer"


def test_invalid_printer():
    """ Tests that if an non-existant printer is specified on the command line, the program exits
        appropriately
    """
    with pytest.raises(SystemExit) as system_exit_e:
        main.parse_command_line_args(["-p", "INVALID"])
    assert system_exit_e.type == SystemExit
    assert system_exit_e.value.code == 2


def test_invalid_number_filter():
    """ Tests that if an invalid value for order numbers to be handled is specified on the command
        line, the program exits appropriately
    """
    with pytest.raises(SystemExit) as system_exit_e:
        main.parse_command_line_args(["-n", "bogus"])
    assert system_exit_e.type == SystemExit
    assert system_exit_e.value.code == 2


def test_invalid_log_level():
    """ Tests that if an invalid log level is specified on the command line, the program exits
        appropriately
    """
    with pytest.raises(SystemExit) as system_exit_e:
        main.parse_command_line_args(["-l", "bogus"])
    assert system_exit_e.type == SystemExit
    assert system_exit_e.value.code == 2


def test_non_base64_data(mocker, receive_messsage_unit_test_fixture):
    """ Tests good path for a valid message that should be sent to the printer """
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_client = mocker.patch('google.cloud.firestore.Client')
    mock_client.return_value.collection.return_value.where.return_value.stream.return_value = []
    mock_print = mocker.patch('subprocess.run')

    data = b'%234'  # % is not a valid character in a base64 string, so this should fail
    attributes = {"order_number": "1234", "event_id": TEST_EVENT_ID}
    msg = receive_messsage_unit_test_fixture(data, attributes)

    main.received_message_to_print(msg)

    mock_ack.assert_called_once()
    mock_nack.assert_not_called()
    mock_print.assert_not_called()


def test_successful_print(mocker, receive_messsage_unit_test_fixture):
    """ Tests good path for a valid message that should be sent to the printer """
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_client = mocker.patch('google.cloud.firestore.Client')
    mock_client.return_value.collection.return_value.where.return_value.stream.return_value = []
    mock_print = mocker.patch('subprocess.run')

    data = base64.b64encode(b'1234')
    attributes = {"order_number": "1234", "event_id": TEST_EVENT_ID}
    msg = receive_messsage_unit_test_fixture(data, attributes)

    main.received_message_to_print(msg)

    mock_ack.assert_called_once()
    mock_nack.assert_not_called()
    mock_print.assert_called_once()


def test_successful_reprint(mocker, receive_messsage_unit_test_fixture):
    """ Tests good path for a valid reprint message that should be sent to the printer """
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mocker.patch('google.cloud.firestore.Client')
    mock_print = mocker.patch('subprocess.run')

    data = base64.b64encode(b'1234')
    attributes = {"order_number": "1234", "event_id": TEST_EVENT_ID, "reprint": "True"}
    msg = receive_messsage_unit_test_fixture(data, attributes)

    main.received_message_to_print(msg)

    mock_ack.assert_called_once()
    mock_nack.assert_not_called()
    mock_print.assert_called_once()


def test_idempotent_impl(mocker, receive_messsage_unit_test_fixture):
    """ Tests the idempotent nature of the callback function; that is, that the same message
        received twice will only be printed once.
    """
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_client = mocker.patch('google.cloud.firestore.Client')
    mock_client.return_value.collection.return_value.where.return_value.stream.return_value = ['1']
    mock_print = mocker.patch('subprocess.run')

    data = base64.b64encode(b'1234')
    attributes = {"order_number": "1234", "event_id": TEST_EVENT_ID}  # reprint not specified here
    msg = receive_messsage_unit_test_fixture(data, attributes)

    main.received_message_to_print(msg)

    mock_ack.assert_called_once()
    mock_nack.assert_not_called()
    mock_print.assert_not_called()


def test_no_message_attributes(mocker, receive_messsage_unit_test_fixture):
    """ Tests that a message received with no message attributes (i.e. missing the order number)
        will be squelched
    """
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_print = mocker.patch('subprocess.run')

    data = base64.b64encode(b'1234')
    attributes = {}
    msg = receive_messsage_unit_test_fixture(data, attributes)

    main.received_message_to_print(msg)

    mock_ack.assert_called_once()
    mock_nack.assert_not_called()
    mock_print.assert_not_called()


def test_no_even_messages_printed(mocker, receive_messsage_unit_test_fixture):
    """ Tests that a message received with an even order number will not be printed when the
        command line value of 'odd' was specified
    """
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_print = mocker.patch('subprocess.run')

    data = base64.b64encode(b'1234')
    attributes = {"order_number": "5678", "event_id": TEST_EVENT_ID}
    msg = receive_messsage_unit_test_fixture(data, attributes)

    main.ARGS.number = "odd"
    main.received_message_to_print(msg)

    mock_ack.assert_not_called()
    mock_nack.assert_called_once()
    mock_print.assert_not_called()


def test_no_odd_messages_printed(mocker, receive_messsage_unit_test_fixture):
    """ Tests that a message received with an odd order number will not be printed when the
        command line value of 'even' was specified
    """
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_print = mocker.patch('subprocess.run')

    data = base64.b64encode(b'1234')
    attributes = {"order_number": "5679", "event_id": TEST_EVENT_ID}
    msg = receive_messsage_unit_test_fixture(data, attributes)

    main.ARGS.number = "even"
    main.received_message_to_print(msg)

    mock_ack.assert_not_called()
    mock_nack.assert_called_once()
    mock_print.assert_not_called()


def test_invalid_order_number(mocker, receive_messsage_unit_test_fixture):
    """ Tests that a message received with a non-integer order number will not be printed and
        appropriately squelched
    """
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_print = mocker.patch('subprocess.run')

    data = base64.b64encode(b'1234')
    attributes = {"order_number": "not_a_number", "event_id": TEST_EVENT_ID}
    msg = receive_messsage_unit_test_fixture(data, attributes)

    main.received_message_to_print(msg)

    mock_ack.assert_called_once()
    mock_nack.assert_not_called()
    mock_print.assert_not_called()


def test_missing_event_id(mocker, receive_messsage_unit_test_fixture):
    """ Tests that a message received with a missing event ID will not be printed and
        appropriately squelched
    """
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_print = mocker.patch('subprocess.run')

    data = base64.b64encode(b'1234')
    attributes = {"order_number": "1234"}
    msg = receive_messsage_unit_test_fixture(data, attributes)

    main.received_message_to_print(msg)

    mock_ack.assert_called_once()
    mock_nack.assert_not_called()
    mock_print.assert_not_called()


def test_other_attributes_but_no_order_number(mocker, receive_messsage_unit_test_fixture):
    """ Tests that a message received with insufficient message attributes (i.e. missing the order
        number) will be squelched
    """
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_print = mocker.patch('subprocess.run')

    data = base64.b64encode(b'1234')
    attributes = {"another_attr": "abc123", "event_id": TEST_EVENT_ID}
    msg = receive_messsage_unit_test_fixture(data, attributes)

    main.received_message_to_print(msg)

    mock_ack.assert_called_once()
    mock_nack.assert_not_called()
    mock_print.assert_not_called()


def test_printer_failure(mocker, receive_messsage_unit_test_fixture):
    """ Tests that if there is a problem printing the label, we will place the request back on the
        subscription to be reprinted
    """
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_client = mocker.patch('google.cloud.firestore.Client')
    mock_client.return_value.collection.return_value.where.return_value.stream.return_value = []
    mock_shell_execute = mocker.patch('subprocess.run',
                                      side_effect=subprocess.CalledProcessError(cmd="gswin64.exe",
                                                                                returncode=1))

    data = base64.b64encode(b'1234')
    attributes = {"order_number": "123", "event_id": TEST_EVENT_ID}
    msg = receive_messsage_unit_test_fixture(data, attributes)

    main.received_message_to_print(msg)

    mock_shell_execute.assert_called_once()
    # ensure message is nacked, not acked to ensure we try to re-print this
    mock_ack.assert_not_called()
    mock_nack.assert_called_once()


def test_missing_subscription(mocker):
    """ Tests that if the subscription for 'print_queue' does not exist before the program is run,
        the program exits with a relevant exception
    """
    mock_sc = mocker.patch('google.cloud.pubsub_v1.SubscriberClient')
    mock_sc.return_value.subscription_path.return_value = "projects/%s/subscriptions/%s" % \
                                                          ("print-client-123456", "print_queue")
    mock_sc.return_value.list_subscriptions.return_value = []

    with pytest.raises(Exception) as exc:
        main.main([])
    assert str(exc.value) == "Subscription projects/print-client-123456/subscriptions/print_queue "\
                             "does not exist"


def test_database_error_before_print(mocker, receive_messsage_unit_test_fixture):
    """ Tests that if an error occurs during interaction with the firestore DB before printing,
        printing still succeeds and the message is acked """

    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_client = mocker.patch('google.cloud.firestore.Client')
    mock_client.return_value.collection.return_value.where.side_effect = RuntimeError("Error!")
    mock_print = mocker.patch('subprocess.run')

    data = base64.b64encode(b'1234')
    attributes = {"order_number": "1234", "event_id": TEST_EVENT_ID}
    msg = receive_messsage_unit_test_fixture(data, attributes)

    main.received_message_to_print(msg)

    mock_ack.assert_called_once()
    mock_nack.assert_not_called()
    mock_print.assert_called_once()


def test_database_error_before_and_after_print(mocker, receive_messsage_unit_test_fixture):
    """ Tests that if an error occurs during interaction with the firestore DB, printing still
        succeeds and the message is acked"""

    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mocker.patch('google.cloud.firestore.Client', side_effect=RuntimeError("Connection failed"))
    mock_print = mocker.patch('subprocess.run')

    data = base64.b64encode(b'1234')
    attributes = {"order_number": "1234", "event_id": TEST_EVENT_ID}
    msg = receive_messsage_unit_test_fixture(data, attributes)

    main.received_message_to_print(msg)

    mock_ack.assert_called_once()
    mock_nack.assert_not_called()
    mock_print.assert_called_once()


def test_database_error_after_print(mocker, receive_messsage_unit_test_fixture):
    """ Tests that if an error occurs during interaction with the firestore DB after printing,
        sending the message ack still happens """

    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_client = mocker.patch('google.cloud.firestore.Client')
    mock_client.return_value.collection.return_value.where.return_value.stream.return_value = []
    mock_client.return_value.collection.return_value.add.side_effect = RuntimeError("Error!")
    mock_print = mocker.patch('subprocess.run')

    data = base64.b64encode(b'1234')
    attributes = {"order_number": "1234", "event_id": TEST_EVENT_ID}
    msg = receive_messsage_unit_test_fixture(data, attributes)

    main.received_message_to_print(msg)

    mock_ack.assert_called_once()
    mock_nack.assert_not_called()
    mock_print.assert_called_once()
