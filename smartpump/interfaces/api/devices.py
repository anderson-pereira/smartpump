from __future__ import annotations

import threading
import time
from typing import Any, Mapping, Optional

import serial

from smartpump.application.service import SmartPump
from smartpump.infrastructure.drivers.cavro import CavroValve
from smartpump.infrastructure.drivers.flow_pump import FlowPumpController
from smartpump.infrastructure.drivers.mocks import MockCavroValve, MockFlowPumpController
from smartpump.settings import FLOW_PUMP_BAUD_RATE, VALVE_BAUD_RATE


class SwitchableValve:
    """Stable valve port whose concrete serial driver can be replaced safely."""

    def __init__(self):
        self._controller = None
        self._serial = None
        self._lock = threading.RLock()
        self.port: Optional[str] = None

    @property
    def connected(self) -> bool:
        return self._controller is not None

    def connect(self, port: str, baud_rate: int, mock_mode: bool) -> None:
        with self._lock:
            self.disconnect()
            if mock_mode:
                self._controller = MockCavroValve()
                self.port = port
                return
            connection = None
            try:
                connection = serial.Serial(
                    port,
                    baud_rate,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=1,
                )
                time.sleep(0.3)
                controller = CavroValve(connection)
                firmware = controller.send_command("&")
                if firmware is None or firmware["error"] != 0:
                    raise RuntimeError("Não foi possível comunicar com a válvula Cavro.")
            except (KeyboardInterrupt, SystemExit):
                if connection is not None:
                    connection.close()
                raise
            except Exception as error:
                if connection is not None:
                    connection.close()
                raise RuntimeError(
                    f"Não foi possível conectar a válvula em {port}: {error}"
                ) from error
            self._serial = connection
            self._controller = controller
            self.port = port

    def disconnect(self) -> None:
        with self._lock:
            connection = self._serial
            self._controller = None
            self._serial = None
            self.port = None
            if connection is not None and connection.is_open:
                connection.close()

    def _require(self):
        if self._controller is None:
            raise RuntimeError("A válvula está desconectada.")
        return self._controller

    def get_current_channel(self) -> Optional[str]:
        return None if self._controller is None else self._controller.get_current_channel()

    def get_status(self) -> Optional[Mapping[str, Any]]:
        return None if self._controller is None else self._controller.get_status()

    def select_channel(self, channel, show=True, before_channel_change=None, after_channel_change=None):
        return self._require().select_channel(
            channel,
            show=show,
            before_channel_change=before_channel_change,
            after_channel_change=after_channel_change,
        )

    def home(self):
        return self._require().home()


class DeviceManager:
    def __init__(self, *, mock_mode: bool, pump_port: Optional[str] = None):
        self.mock_mode = mock_mode
        self.valve = SwitchableValve()
        self.pump_port = pump_port
        self.pump_baud_rate = FLOW_PUMP_BAUD_RATE
        self._service: Optional[SmartPump] = None

    def bind(self, service: SmartPump) -> None:
        self._service = service

    def create_pump(self):
        if self.mock_mode:
            return MockFlowPumpController()
        if not self.pump_port:
            raise RuntimeError("Selecione a porta serial da bomba antes de conectar.")
        return FlowPumpController(
            serial_port=self.pump_port,
            baud_rate=self.pump_baud_rate,
        )

    def connect(self, device: str, port: str, baud_rate: int) -> None:
        service = self._require_service()
        if device == "valve":
            self.valve.connect(port, baud_rate or VALVE_BAUD_RATE, self.mock_mode)
        elif device == "pump":
            if service.pump_enabled:
                service.disable_pump()
            self.pump_port = port
            self.pump_baud_rate = baud_rate or FLOW_PUMP_BAUD_RATE
            try:
                service.enable_pump()
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as error:
                raise RuntimeError(
                    f"Não foi possível conectar a bomba em {port}: {error}"
                ) from error
        else:
            raise ValueError(f"Dispositivo desconhecido: {device}")

    def disconnect(self, device: str) -> None:
        service = self._require_service()
        if device == "valve":
            self.valve.disconnect()
        elif device == "pump":
            if service.pump_enabled:
                service.disable_pump()
        else:
            raise ValueError(f"Dispositivo desconhecido: {device}")

    def status(self) -> dict[str, Any]:
        service = self._require_service()
        return {
            "valve": {"connected": self.valve.connected, "port": self.valve.port},
            "pump": {"connected": service.pump_enabled, "port": self.pump_port},
        }

    def close(self) -> None:
        self.valve.disconnect()

    def _require_service(self) -> SmartPump:
        if self._service is None:
            raise RuntimeError("Gerenciador de dispositivos ainda não inicializado.")
        return self._service
