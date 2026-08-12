import pytest
import logging
from datetime import datetime
from unittest.mock import MagicMock
from engine.command_engine import CommandEngine, EngineState
from engine.commands import BatteryCheckCommand
from engine.commands import ConsoleTimeoutCommand
from engine.commands import GetTimeCommand
from engine.commands import SetTimeCommand


@pytest.fixture(autouse=True)
def setup_logging():
    """Ensure the command engine logger is at DEBUG level for tests."""
    logger = logging.getLogger("engine.command_engine")
    logger.setLevel(logging.DEBUG)
    yield


@pytest.fixture
def mock_serial_manager():
    manager = MagicMock()
    manager.get_next_message.return_value = None  # Default to empty queue
    return manager


@pytest.fixture
def engine(mock_serial_manager):
    return CommandEngine(mock_serial_manager)


def test_command_cycle_success(engine, mock_serial_manager, caplog):
    """Tests the full lifecycle with the correct 'BAT: <nnnn>mV' string format."""
    # Arrange
    cmd = BatteryCheckCommand()
    command_str = cmd.get_request()  # 'b'
    expected_echo = command_str + "\n"
    # Updated response body to match real hardware format
    response_body = "BAT: 3600mV\n"
    prompt = "DM41 >> "

    callback_mock = MagicMock()
    error_mock = MagicMock()

    # Mock sequence: 1. Echo line, then 2. Data line containing prompt at end
    mock_serial_manager.get_next_message.side_effect = [
        expected_echo,  # Line 1: the echo
        response_body + prompt,  # Line 2: response data + termination prompt
    ]

    # Act part 1: Execute command
    engine.execute(cmd, callback_mock, error_mock)
    assert engine.state == EngineState.WAITING_FOR_REPLY
    mock_serial_manager.send_command.assert_called_with("b")
    # Act part 2: First iteration - receive echo
    engine.process_incoming_data()
    assert engine.state == EngineState.COLLECTING
    # Act part 3: Second iteration - receive response data + prompt
    engine.process_incoming_data()
    # Assertions
    assert engine.state == EngineState.IDLE
    callback_mock.assert_called_once_with(3600)


def test_echo_removal_logic(engine, mock_serial_manager):
    """Verifies that the engine correctly extracts value from padded string format."""
    cmd = BatteryCheckCommand()
    expected_echo = "b\n"
    # Updated to include correct pattern and simulate noise around it
    response_with_noise = f"{expected_echo}  BAT: 3600mV  \nDM41 >> "
    callback_mock = MagicMock()
    error_mock = MagicMock()
    engine.execute(cmd, callback_mock, error_mock)
    mock_serial_manager.get_next_message.return_value = response_with_noise
    engine.process_incoming_data()

    assert engine.state == EngineState.IDLE
    callback_mock.assert_called_once_with(3600)


def test_parsing_error_handling(engine, mock_serial_manager, caplog):
    """Verifies that an incorrectly formatted string triggers appropriate error handling."""
    cmd = BatteryCheckCommand()
    expected_echo = "b\n"
    # This data no longer matches the expected 'BAT: <nnnn>mV' pattern
    bad_response = f"{expected_echo}INVALID_DATA_FORMAT\nDM41 >> "
    callback_mock = MagicMock()
    error_mock = MagicMock()
    engine.execute(cmd, callback_mock, error_mock)
    mock_serial_manager.get_next_message.return_value = bad_response
    engine.process_incoming_data()
    # Assertions: Engine should recover to IDLE and log the error
    assert engine.state == EngineState.IDLE
    assert "Error parsing response for BatteryCheckCommand" in caplog.text


def test_concurrency_protection(engine, mock_serial_manager, caplog):
    """The engine should refuse new commands while one is already executing."""
    cmd = BatteryCheckCommand()
    engine.execute(cmd, MagicMock(), MagicMock())  # First command starts execution

    # Attempt to execute another command immediately while state is not IDLE
    engine.execute(cmd, MagicMock(), MagicMock())

    assert "Cannot execute command while another is in progress." in caplog.text


def test_console_timeout_command_success(engine, mock_serial_manager):
    """Tests sending a timeout value and receiving confirmation."""
    # Arrange
    minutes = 15
    cmd = ConsoleTimeoutCommand([minutes])

    # The command string should be 'ct 15' based on current implementation
    expected_command = f"ct {minutes}"
    expected_echo = expected_command + "\n"

    # Expected confirmation message from hardware
    response_body = f"Console timeout set to {minutes} minutes\n"
    prompt = "DM41 >> "

    callback_mock = MagicMock()
    error_mock = MagicMock()

    # Mock sequence: 1. Echo line, then 2. Response message + termination prompt
    mock_serial_manager.get_next_message.side_effect = [
        expected_echo,  # Line 1: the echo returned by hardware
        response_body + prompt,  # Line 2: success message + terminal prompt
    ]

    # Act part 1: Execute command and verify initial state change
    engine.execute(cmd, callback_mock, error_mock)
    assert engine.state == EngineState.WAITING_FOR_REPLY
    mock_serial_manager.send_command.assert_called_with(expected_command)
    # Act part 2: First iteration - receive the echo line
    engine.process_incoming_data()
    assert engine.state == EngineState.COLLECTING
    # Act part 3: Second iteration - receive response data + prompt signal
    engine.process_incoming_data()
    # Assertions: Check state recovery and correct parsing result
    assert engine.state == EngineState.IDLE
    callback_mock.assert_called_once_with(f"Console timeout set to {minutes} minutes")


def test_get_time_command_success(engine, mock_serial_manager):
    """Verifies that correctly formatted date-time strings pass validation."""
    # Arrange
    cmd = GetTimeCommand()
    expected_echo = "t\n"
    response_body = "2026-07-19 15:30:45 SUN\n"
    prompt = "DM41 >> "

    callback_mock = MagicMock()
    mock_serial_manager.get_next_message.side_effect = [
        expected_echo,
        response_body + prompt,
    ]

    # Act part 1: Execute command
    engine.execute(cmd, callback_mock, MagicMock())
    engine.process_incoming_data()  # First iteration (echo)
    engine.process_incoming_data()  # Second iteration (response + prompt)
    # Assertions
    assert engine.state == EngineState.IDLE
    callback_mock.assert_called_once_with("2026-07-19 15:30:45 SUN")


def test_get_time_command_invalid_format(engine, mock_serial_manager, caplog):
    """Verifies that incorrectly formatted strings raise a ValueError and reset state."""
    # Arrange
    cmd = GetTimeCommand()
    expected_echo = "t\n"
    # This response fails because the time component is malformed
    bad_response = "2026-07-19 15:30 INVALID SUN\nDM41 >> "

    callback_mock = MagicMock()
    error_mock = MagicMock()
    mock_serial_manager.get_next_message.side_effect = [expected_echo, bad_response]

    # Act part 1: Execute command
    engine.execute(cmd, callback_mock, error_mock)
    engine.process_incoming_data()  # First iteration (echo)
    engine.process_incoming_data()  # Second iteration (response + prompt)
    # Assertions
    # 1. The engine should return to IDLE despite the error
    assert engine.state == EngineState.IDLE
    # 2. The exception caught by CommandEngine should be logged with relevant details
    assert "Error parsing response for GetTimeCommand" in caplog.text
    # 3. The callback should NEVER have been called with invalid data
    callback_mock.assert_not_called()


def test_set_time_command_success(engine, mock_serial_manager):
    """Verifies correct timestamp conversion and successful empty response handling."""
    # Arrange 1721398530 is ~2024-07-19 15:35:30 UTC
    test_timestamp = ["20240719", "153530"]
    cmd = SetTimeCommand(test_timestamp)

    # The expected argument after conversion must match our test timestamp exactly
    expected_arg = " ".join(test_timestamp)
    expected_command = f"ts {expected_arg}"
    expected_echo = expected_command + "\n"

    # On success, device returns nothing before the next prompt
    prompt = "DM41 >> "

    callback_mock = MagicMock()
    error_mock = MagicMock()
    mock_serial_manager.get_next_message.side_effect = [
        expected_echo,  # Line 1: Echo of the command sent
        prompt,  # Line 2: termination prompt
    ]

    # Act part 1: Execute command
    engine.execute(cmd, callback_mock, error_mock)
    assert engine.state == EngineState.WAITING_FOR_REPLY
    mock_serial_manager.send_command.assert_called_with(expected_command)
    # Act part 2: First iteration - receive echo
    engine.process_incoming_data()
    assert engine.state == EngineState.COLLECTING
    # Act part 3: Second iteration - receive response data + prompt
    engine.process_incoming_data()
    # Assertions
    assert engine.state == EngineState.IDLE
    callback_mock.assert_called_once_with("")  # Should receive empty string on success


def test_set_time_command_failure(engine, mock_serial_manager):
    """Verifies that unsuccessful commands return the correct help message via callback."""
    # Arrange
    test_timestamp = ["20240719"]
    cmd = SetTimeCommand(test_timestamp)
    expected_command = cmd.command_string
    expected_echo = expected_command + "\n"

    # Help message returned by the hardware on error
    help_message = "Set time\n\n<YYYYMMDD> <HHMMSS>"
    prompt = "DM41 >> "

    callback_mock = MagicMock()
    error_mock = MagicMock()
    mock_serial_manager.get_next_message.side_effect = [
        expected_echo,
        help_message + "\n" + prompt,
    ]

    # Act part 1: Execute command
    engine.execute(cmd, callback_mock, error_mock)
    engine.process_incoming_data()  # Echo line
    assert engine.state == EngineState.COLLECTING

    engine.process_incoming_data()  # Help message line

    # Assertions
    # Note that parse_response returns the help message string to our UI callback
    callback_mock.assert_called_once_with(help_message)
    assert engine.state == EngineState.IDLE
