# pylint: disable=redefined-outer-name
"""Unit tests for print-client"""

from argparse import Namespace
import datetime
import os
import time

import pytest
import pytz

from six.moves import queue

from google.api_core import datetime_helpers
from google.cloud.pubsub_v1 import types
from google.cloud.pubsub_v1.subscriber import message
from google.protobuf.timestamp_pb2 import Timestamp

import pywintypes

import main


def test_gcp_project_envvar(monkeypatch):
    # clear environment
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    with pytest.raises(Exception) as exc:
        main.main([])
        assert str(exc) == "GCP_PROJECT environment variable not set"


def test_winnamedtempfile_1():
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


def mock_open_printer_handle(printer_name):
    if printer_name != 'default_printer':
        raise pywintypes.error(1801, 'OpenPrinter', 'The printer name is invalid.')


@pytest.fixture(autouse=True)
def default_mocker_patches(mocker):
    mocker.patch("win32print.GetDefaultPrinter", return_value="default_printer")
    mocker.patch("win32print.OpenPrinter", side_effect=mock_open_printer_handle)
    mocker.patch("win32print.ClosePrinter")
    mocker.patch.object(main, "ARGS", Namespace(printer="default_printer", number="all"))


def test_invalid_printer():
    with pytest.raises(SystemExit) as system_exit_e:
        main.main(["-p", "INVALID"])
    assert system_exit_e.type == SystemExit
    assert system_exit_e.value.code == 2


def test_invalid_number_filter():
    with pytest.raises(SystemExit) as system_exit_e:
        main.main(["-n", "bogus"])
    assert system_exit_e.type == SystemExit
    assert system_exit_e.value.code == 2


def test_invalid_log_level():
    with pytest.raises(SystemExit) as system_exit_e:
        main.main(["-l", "bogus"])
    assert system_exit_e.type == SystemExit
    assert system_exit_e.value.code == 2


RECEIVED = datetime.datetime(2012, 4, 21, 15, 0, tzinfo=pytz.utc)
RECEIVED_SECONDS = datetime_helpers.to_milliseconds(RECEIVED) // 1000
PUBLISHED_MICROS = 123456
PUBLISHED = RECEIVED + datetime.timedelta(days=1, microseconds=PUBLISHED_MICROS)
PUBLISHED_SECONDS = datetime_helpers.to_milliseconds(PUBLISHED) // 1000


@pytest.fixture
def receive_messsage_unit_test_fixture(mocker):
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


def test_successful_print(mocker, receive_messsage_unit_test_fixture):
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_print = mocker.patch('win32api.ShellExecute')

    data = b'1234'
    attributes = {"order_number": "1234"}
    msg = receive_messsage_unit_test_fixture(data, attributes)

    main.received_message_to_print(msg)

    mock_ack.assert_called_once()
    mock_nack.assert_not_called()
    mock_print.assert_called_once()


def test_no_message_attributes(mocker, receive_messsage_unit_test_fixture):
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_print = mocker.patch('win32api.ShellExecute')

    data = b'1234'
    attributes = {}
    msg = receive_messsage_unit_test_fixture(data, attributes)

    main.received_message_to_print(msg)

    mock_ack.assert_called_once()
    mock_nack.assert_not_called()
    mock_print.assert_not_called()


def test_no_even_messages_printed(mocker, receive_messsage_unit_test_fixture):
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_print = mocker.patch('win32api.ShellExecute')

    data = b'1234'
    attributes = {"order_number": "5678"}
    msg = receive_messsage_unit_test_fixture(data, attributes)

    mocker.patch('main.ARGS.number', return_value="odd")
    main.received_message_to_print(msg)

    mock_ack.assert_not_called()
    mock_nack.assert_called_once()
    mock_print.assert_not_called()


def test_no_odd_messages_printed(mocker, receive_messsage_unit_test_fixture):
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_print = mocker.patch('win32api.ShellExecute')

    data = b'1234'
    attributes = {"order_number": "5679"}
    msg = receive_messsage_unit_test_fixture(data, attributes)

    mocker.patch('main.ARGS.number', return_value="even")
    main.received_message_to_print(msg)

    mock_ack.assert_not_called()
    mock_nack.assert_called_once()
    mock_print.assert_not_called()


def test_invalid_order_number(mocker, receive_messsage_unit_test_fixture):
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_print = mocker.patch('win32api.ShellExecute')

    data = b'1234'
    attributes = {"order_number": "not_a_number"}
    msg = receive_messsage_unit_test_fixture(data, attributes)

    main.received_message_to_print(msg)

    mock_ack.assert_called_once()
    mock_nack.assert_not_called()
    mock_print.assert_not_called()


def test_other_attributes_but_no_order_number(mocker, receive_messsage_unit_test_fixture):
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_print = mocker.patch('win32api.ShellExecute')

    data = b'1234'
    attributes = {"another_attr": "abc123"}
    msg = receive_messsage_unit_test_fixture(data, attributes)

    main.received_message_to_print(msg)

    mock_ack.assert_called_once()
    mock_nack.assert_not_called()
    mock_print.assert_not_called()


def throw_print_exception(*args, **kwargs):
    raise pywintypes.error(1801, 'ShellExecute', 'Unknown Printing Error.')


def test_printer_failure(mocker, receive_messsage_unit_test_fixture):
    mock_ack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.ack')
    mock_nack = mocker.patch('google.cloud.pubsub_v1.subscriber.message.Message.nack')
    mock_shell_execute = mocker.patch('win32api.ShellExecute', side_effect=throw_print_exception)

    data = b'1234'
    attributes = {"order_number": "123"}
    msg = receive_messsage_unit_test_fixture(data, attributes)

    main.received_message_to_print(msg)

    mock_shell_execute.assert_called_once()
    # ensure message is nacked, not acked to ensure we try to re-print this
    mock_ack.assert_not_called()
    mock_nack.assert_called_once()


def test_missing_subscription(mocker):
    mocker.patch('google.cloud.pubsub_v1.SubscriberClient')
    mocker.patch('google.cloud.pubsub_v1.SubscriberClient.list_subscriptions', return_value=[])

    # use defaults
    with pytest.raises(Exception) as exc:
        main.main([])
        assert str(exc) == "Subscription projects/%s/subscriptions/print_queue does not exist" % \
                           (os.environ["GCP_PROJECT"])
