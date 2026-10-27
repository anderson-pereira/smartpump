import logging
from decimal import Decimal, InvalidOperation

from smartpump.infrastructure.drivers.flow_pump import FlowPumpController
from smartpump.settings import VALVE_CHANNEL_COUNT


logger = logging.getLogger(__name__)


class MockSerialState:
    def __init__(self):
        self.is_open = True


class MockCavroValve:
    """In-memory Cavro valve replacement for local interface testing."""

    def __init__(self, initial_channel=1):
        self.current_channel = int(initial_channel)

    def get_current_channel(self):
        return str(self.current_channel)

    def get_status(self):
        return {"ready": True, "error": 0, "data": str(self.current_channel)}

    def select_channel(
        self,
        channel,
        show=True,
        before_channel_change=None,
        after_channel_change=None,
    ):
        if channel not in range(1, VALVE_CHANNEL_COUNT + 1):
            raise ValueError(f"Canal deve estar entre 1 e {VALVE_CHANNEL_COUNT}.")
        if self.current_channel == channel:
            if show:
                logger.info("[MOCK] Canal %s já está selecionado.", channel)
            return True

        if before_channel_change is not None and before_channel_change() is False:
            raise RuntimeError("[MOCK] A parada da bomba falhou.")
        if show:
            logger.info("[MOCK] Canal %s -> %s", self.current_channel, channel)
        self.current_channel = channel
        if show:
            logger.info("[MOCK] Canal %s confirmado.", channel)
        if after_channel_change is not None and after_channel_change() is False:
            raise RuntimeError("[MOCK] A retomada da bomba falhou.")
        return True

    def home(self):
        self.current_channel = 1
        logger.info("[MOCK] Homing concluído no canal 1.")
        return True


class MockFlowPumpController(FlowPumpController):
    """In-memory pump replacement implementing the production interface."""

    def __init__(self):
        self.serial_connection = MockSerialState()
        self.running = False
        self.speed_rpm = Decimal("10.00")
        self.direction = "clockwise"
        self.stop_delay_seconds = 0
        self.restart_delay_seconds = 0

    def identify(self):
        return "MOCK ISM832"

    def start(self):
        self.running = True
        logger.info("[MOCK] Bomba iniciada.")
        return True

    def stop(self):
        self.running = False
        logger.info("[MOCK] Bomba parada.")
        return True

    def restart(self):
        return self.start()

    def set_clockwise(self):
        self.direction = "clockwise"
        logger.info("[MOCK] Sentido configurado: horário.")
        return True

    def set_counterclockwise(self):
        self.direction = "counterclockwise"
        logger.info("[MOCK] Sentido configurado: anti-horário.")
        return True

    def shutdown(self):
        return self.stop()

    def is_running(self):
        return self.running

    def get_speed(self):
        return float(self.speed_rpm)

    def set_speed(self, speed_rpm):
        try:
            speed = Decimal(str(speed_rpm))
        except (InvalidOperation, ValueError):
            raise ValueError("A velocidade deve ser um número em RPM.")
        if not speed.is_finite() or speed < self.MIN_SPEED_RPM or speed > self.MAX_SPEED_RPM:
            raise ValueError(
                f"A velocidade deve estar entre {self.MIN_SPEED_RPM:.2f} e "
                f"{self.MAX_SPEED_RPM:.2f} RPM."
            )
        self.speed_rpm = speed
        logger.info("[MOCK] Velocidade configurada: %.2f RPM.", speed)
        return True

    def close(self):
        if self.serial_connection is not None:
            self.serial_connection.is_open = False
            self.serial_connection = None
        logger.info("[MOCK] Conexão da bomba fechada.")
