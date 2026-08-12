import pytest
from unittest.mock import MagicMock, patch
from engine.command_engine import CommandEngine, EngineState
from engine.base_command import BaseCommand


class MockCommand(BaseCommand):
    def __init__(self, timeout=1.0):
        super().__init__(timeout=timeout)

    @property
    def command_string(self):
        return "ping"

    def parse_response(self, raw_data):
        return "OK"


@pytest.fixture
def engine():
    mock_serial = MagicMock()
    return CommandEngine(mock_serial)


def test_command_timeout_logic(engine):
    """Verifies that the engine resets to IDLE after timeout expires."""
    cmd = MockCommand(timeout=1.0)
    error_callback = MagicMock()
    success_callback = MagicMock()

    # 1. Start command execution
    with patch(
        "time.monotonic", return_value=100.0
    ):  # initial start time at 100.0 in engine.execute
        engine.execute(cmd, success_callback, error_callback)

    assert engine.state == EngineState.WAITING_FOR_REPLY

    # 2. Simulate time passing beyond timeout while no data arrives
    # We patch time.monotonic to simulate the clock jumping forward 2 seconds
    with patch("time.monotonic", return_value=102.0):  # current time is now 102.0
        # Mock serial returning no data
        engine.serial.get_next_message.return_value = None

        # The next call to process_incoming_data should trigger timeout
        engine.process_incoming_data()

    # 3. Assertions: Engine must be IDLE and error callback called
    assert engine.state == EngineState.IDLE
    assert engine._current_command is None
    error_callback.assert_called_with("Serial connection has timed out.")


def test_data_resets_timeout_clock(engine):
    """Verifies that arrival of data resets the timer, preventing timeout during transfer."""
    cmd = MockCommand(timeout=2.0)
    engine.execute(cmd, MagicMock(), MagicMock())

    with patch("time.monotonic", return_value=100.0):  # Time 100: Command issued
        # Simulate arrival of data at time 101.5 (still within 2s window)
        with patch("time.monotonic", return_value=101.5):
            engine.serial.get_next_message.return_value = "Echo\n"
            engine.process_incoming_data()

            # Engine should now be in COLLECTING state and clock reset
            assert engine.state == EngineState.COLLECTING
            assert engine._state_timeout == 101.5

            # Now simulate time passing from the NEW checkpoint (101.5 + 2 seconds)
            with patch(
                "time.monotonic", return_value=104.0
            ):  # That's 2.5s since last packet
                engine.serial.get_next_message.return_value = None
                engine.process_incoming_data()
                assert (
                    engine.state == EngineState.IDLE
                )  # Should still timeout after data-reset clock expires
