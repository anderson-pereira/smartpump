from importlib import import_module
from typing import Callable, Optional

from smartpump.ports.devices import ManagedPumpController


_active_flow_pump_controller: Optional[ManagedPumpController] = None
_flow_pump_controller_factory: Optional[
    Callable[[], ManagedPumpController]
] = None


def set_flow_pump_controller_factory(
    factory: Optional[Callable[[], ManagedPumpController]] = None,
) -> None:
    """Override the controller factory, primarily for hardware-free simulation."""
    global _flow_pump_controller_factory
    _flow_pump_controller_factory = factory


def load_flow_pump_controller() -> ManagedPumpController:
    """Load the optional flow-pump integration only when it is enabled."""
    global _active_flow_pump_controller

    if _active_flow_pump_controller is not None:
        connection = _active_flow_pump_controller.serial_connection
        if connection is not None and connection.is_open:
            return _active_flow_pump_controller

    if _flow_pump_controller_factory is None:
        flow_pump_module = import_module(
            "smartpump.infrastructure.drivers.flow_pump"
        )
        factory = flow_pump_module.FlowPumpController
    else:
        factory = _flow_pump_controller_factory
    _active_flow_pump_controller = factory()
    return _active_flow_pump_controller


def close_active_flow_pump_controller() -> None:
    """Close the optional pump port when the application exits."""
    global _active_flow_pump_controller

    if _active_flow_pump_controller is not None:
        controller = _active_flow_pump_controller
        controller.close()
        _active_flow_pump_controller = None
