import time

import serial

from config import (
    FLOW_PUMP_ADDRESS,
    FLOW_PUMP_BAUD_RATE,
    FLOW_PUMP_RESTART_DELAY_SECONDS,
    FLOW_PUMP_SERIAL_PORT,
    FLOW_PUMP_STOP_DELAY_SECONDS,
)


class FlowPumpController:
    """Control an Ismatec ISM832 external flow pump over serial."""

    def __init__(
        self,
        serial_port=FLOW_PUMP_SERIAL_PORT,
        address=FLOW_PUMP_ADDRESS,
        baud_rate=FLOW_PUMP_BAUD_RATE,
        stop_delay_seconds=FLOW_PUMP_STOP_DELAY_SECONDS,
        restart_delay_seconds=FLOW_PUMP_RESTART_DELAY_SECONDS,
    ):
        self.address = address
        self.stop_delay_seconds = stop_delay_seconds
        self.restart_delay_seconds = restart_delay_seconds
        self.serial_connection = serial.Serial(
            port=serial_port,
            baudrate=baud_rate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1.0,
        )
        time.sleep(0.2)

    def _write_command(self, command):
        message = f"{self.address}{command}\r"
        self.serial_connection.reset_input_buffer()
        print(f"TX: {message!r}")
        self.serial_connection.write(message.encode("ascii"))
        self.serial_connection.flush()

    def _send_character_command(self, command):
        self._write_command(command)
        response = self.serial_connection.read(1).decode("ascii", errors="replace")
        print(f"RX: {response!r}")
        return response

    def _send_line_command(self, command):
        self._write_command(command)
        response = self.serial_connection.read_until(b"\n").decode(
            "ascii",
            errors="replace",
        ).strip()
        print(f"RX: {response!r}")
        return response

    def identify(self):
        """Return the pump identification string."""
        return self._send_line_command("#")

    def start(self):
        """Start the pump and report whether it accepted the command."""
        response = self._send_character_command("H")
        if response == "*":
            print("Bomba iniciada.")
            return True
        print(f"Falha ao iniciar: {response!r}")
        return False

    def stop(self):
        """Stop the pump and report whether it accepted the command."""
        response = self._send_character_command("I")
        if response == "*":
            print("Bomba parada.")
            time.sleep(self.stop_delay_seconds)
            return True
        print(f"Falha ao parar: {response!r}")
        return False

    def restart(self):
        """Restart the pump after the valve has completed a channel change."""
        time.sleep(self.restart_delay_seconds)
        return self.start()

    def shutdown(self):
        """Stop pumping at the end of an automatic recipe."""
        return self.stop()

    def is_running(self):
        """Return True, False, or None when the pump state is not understood."""
        response = self._send_character_command("E")
        if response == "+":
            return True
        if response == "-":
            return False
        return None

    def get_speed(self):
        """Return the configured speed in rpm, when the pump reports a number."""
        response = self._send_line_command("S")
        try:
            return float(response)
        except ValueError:
            return None

    def close(self):
        """Close the serial connection to the external pump."""
        if self.serial_connection.is_open:
            self.serial_connection.close()
