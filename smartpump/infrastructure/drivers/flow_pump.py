import logging
import time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import serial

from smartpump.settings import (
    FLOW_PUMP_ADDRESS,
    FLOW_PUMP_BAUD_RATE,
    FLOW_PUMP_RESTART_DELAY_SECONDS,
    FLOW_PUMP_SERIAL_PORT,
    FLOW_PUMP_STOP_DELAY_SECONDS,
)


logger = logging.getLogger(__name__)


class FlowPumpController:
    """Control an Ismatec ISM832 external flow pump over serial."""

    MIN_SPEED_RPM = Decimal("1.60")
    MAX_SPEED_RPM = Decimal("160.00")
    RPM_PER_ML_MIN = Decimal("6.4") / Decimal("0.4")

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
            port=None,
            baudrate=baud_rate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1.0,
        )
        try:
            self.serial_connection.port = serial_port
            self.serial_connection.open()
            time.sleep(0.2)
        except BaseException:
            # KeyboardInterrupt is a BaseException.  Closing here prevents a
            # Ctrl+C during connection from leaving the Windows handle open.
            if self.serial_connection.is_open:
                self.serial_connection.close()
            raise

    def _write_command(self, command):
        message = f"{self.address}{command}\r"
        self.serial_connection.reset_input_buffer()
        logger.debug("TX: %r", message)
        self.serial_connection.write(message.encode("ascii"))
        self.serial_connection.flush()

    def _send_character_command(self, command):
        self._write_command(command)
        response = self.serial_connection.read(1).decode("ascii", errors="replace")
        logger.debug("RX: %r", response)
        return response

    def _send_line_command(self, command):
        self._write_command(command)
        response = self.serial_connection.read_until(b"\n").decode(
            "ascii",
            errors="replace",
        ).strip()
        logger.debug("RX: %r", response)
        return response

    def identify(self):
        """Return the pump identification string."""
        return self._send_line_command("#")

    def start(self):
        """Start the pump and report whether it accepted the command."""
        response = self._send_character_command("H")
        if response == "*":
            logger.info("Bomba iniciada.")
            return True
        logger.warning("Falha ao iniciar: %r", response)
        return False

    def stop(self):
        """Stop the pump and report whether it accepted the command."""
        response = self._send_character_command("I")
        if response == "*":
            logger.info("Bomba parada.")
            time.sleep(self.stop_delay_seconds)
            return True
        logger.warning("Falha ao parar: %r", response)
        return False

    def restart(self):
        """Restart the pump after the valve has completed a channel change."""
        time.sleep(self.restart_delay_seconds)
        return self.start()

    def set_clockwise(self):
        """Set clockwise rotation."""
        response = self._send_character_command("J")
        if response == "*":
            logger.info("Sentido configurado: horário.")
            return True
        logger.warning("Falha ao configurar sentido horário: %r", response)
        return False

    def set_counterclockwise(self):
        """Set counter-clockwise rotation."""
        response = self._send_character_command("K")
        if response == "*":
            logger.info("Sentido configurado: anti-horário.")
            return True
        logger.warning("Falha ao configurar sentido anti-horário: %r", response)
        return False

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

    def set_speed(self, speed_rpm):
        """Set speed in rpm using the ISM832 hundredths-of-an-RPM format."""
        try:
            speed = Decimal(str(speed_rpm))
        except (InvalidOperation, ValueError):
            raise ValueError("A velocidade deve ser um número em RPM.")

        if not speed.is_finite():
            raise ValueError("A velocidade deve ser um número finito.")
        if speed < self.MIN_SPEED_RPM or speed > self.MAX_SPEED_RPM:
            raise ValueError(
                "A velocidade da ISM832 deve estar entre "
                f"{self.MIN_SPEED_RPM:.2f} e {self.MAX_SPEED_RPM:.2f} RPM."
            )

        speed_in_hundredths = speed * 100
        if speed_in_hundredths != speed_in_hundredths.to_integral_value():
            raise ValueError("A velocidade aceita no máximo duas casas decimais.")

        command = f"S{int(speed_in_hundredths):06d}"
        response = self._send_character_command(command)
        if response == "*":
            logger.info("Velocidade configurada: %.2f RPM.", speed)
            return True
        logger.warning("Falha ao configurar velocidade: %r", response)
        return False

    def set_flow_rate(self, flow_rate_ml_min):
        """Apply signed flow: direction, speed and start/stop state."""
        flow_rate, speed_rpm = self.validate_flow_rate(flow_rate_ml_min)

        running = self.is_running()
        if running is None:
            raise RuntimeError("Não foi possível determinar o estado da bomba.")

        if flow_rate == 0:
            if not running:
                logger.info("Vazão configurada em zero; a bomba já está parada.")
                return True
            return self.stop()

        if running and not self.stop():
            return False

        set_direction = (
            self.set_clockwise if flow_rate > 0 else self.set_counterclockwise
        )
        if not set_direction():
            return False
        if not self.set_speed(speed_rpm):
            return False
        if not self.start():
            return False

        direction = "horário" if flow_rate > 0 else "anti-horário"
        logger.info(
            "Vazão aplicada: %s mL/min | %.2f RPM | sentido %s.",
            f"{flow_rate:+g}",
            speed_rpm,
            direction,
        )
        return True

    def validate_flow_rate(self, flow_rate_ml_min):
        """Return flow and RPM after checking the pump's actual RPM limits."""
        try:
            flow_rate = Decimal(str(flow_rate_ml_min))
        except (InvalidOperation, ValueError):
            raise ValueError("A vazão deve ser um número em mL/min.")

        if not flow_rate.is_finite():
            raise ValueError("A vazão deve ser um número finito.")

        if flow_rate == 0:
            return flow_rate, Decimal("0.00")

        speed_rpm = (abs(flow_rate) * self.RPM_PER_ML_MIN).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        if speed_rpm < self.MIN_SPEED_RPM or speed_rpm > self.MAX_SPEED_RPM:
            raise ValueError(
                f"A vazão de {flow_rate:g} mL/min corresponde a "
                f"{speed_rpm:.2f} RPM, fora da faixa suportada pela ISM832 "
                f"({self.MIN_SPEED_RPM:.2f} a {self.MAX_SPEED_RPM:.2f} RPM)."
            )

        return flow_rate, speed_rpm

    def close(self):
        """Close the serial connection to the external pump."""
        if self.serial_connection is None:
            return

        connection = self.serial_connection
        if connection.is_open:
            connection.close()
        if connection.is_open:
            raise RuntimeError("A porta serial da bomba permaneceu aberta.")

        # Drop the pyserial object after its native handle has been released.
        self.serial_connection = None
