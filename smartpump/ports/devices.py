from decimal import Decimal
from typing import Any, Callable, Mapping, Optional, Protocol, Tuple, Union


NumericInput = Union[str, int, float, Decimal]
ChannelChangeCallback = Optional[Callable[[], None]]


class ValveController(Protocol):
    """Operations the application requires from a valve driver."""

    def get_current_channel(self) -> Optional[str]:
        ...

    def get_status(self) -> Optional[Mapping[str, Any]]:
        ...

    def select_channel(
        self,
        channel: int,
        show: bool = True,
        before_channel_change: ChannelChangeCallback = None,
        after_channel_change: ChannelChangeCallback = None,
    ) -> bool:
        ...

    def home(self) -> bool:
        ...


class PumpController(Protocol):
    """Operations the application requires from a flow-pump driver."""

    def identify(self) -> Optional[str]:
        ...

    def start(self) -> bool:
        ...

    def stop(self) -> bool:
        ...

    def restart(self) -> bool:
        ...

    def shutdown(self) -> bool:
        ...

    def is_running(self) -> Optional[bool]:
        ...

    def get_speed(self) -> Optional[float]:
        ...

    def set_speed(self, speed_rpm: NumericInput) -> bool:
        ...

    def set_flow_rate(self, flow_rate_ml_min: NumericInput) -> bool:
        ...

    def validate_flow_rate(
        self,
        flow_rate_ml_min: NumericInput,
    ) -> Tuple[Decimal, Decimal]:
        ...

    def close(self) -> None:
        ...


class SerialConnection(Protocol):
    is_open: bool

    def close(self) -> None:
        ...


class ManagedPumpController(PumpController, Protocol):
    """Pump controller whose serial-resource lifecycle is externally managed."""

    serial_connection: Optional[SerialConnection]


PumpFactory = Callable[[], PumpController]
PumpCloser = Callable[[], None]
