from importlib import import_module


_active_flow_pump_controller = None


def load_flow_pump_controller():
    """Load the optional flow-pump integration only when it is enabled."""
    global _active_flow_pump_controller

    flow_pump_module = import_module("flow_pump")
    _active_flow_pump_controller = flow_pump_module.FlowPumpController()
    return _active_flow_pump_controller


def close_active_flow_pump_controller():
    """Close the optional pump port when the application exits."""
    global _active_flow_pump_controller

    if _active_flow_pump_controller is not None:
        _active_flow_pump_controller.close()
        _active_flow_pump_controller = None
