import unittest
from decimal import Decimal
from unittest.mock import Mock, patch

from smartpump.application.service import SmartPump
from smartpump.domain.recipes import ExternalRecipe, RecipeCatalog
from smartpump.infrastructure.drivers import flow_pump_loader
from smartpump.infrastructure.drivers.flow_pump import FlowPumpController
from smartpump.infrastructure.drivers.mocks import (
    MockCavroValve,
    MockFlowPumpController,
)
from smartpump.interfaces.console import (
    confirm_application_exit,
    control_flow_pump,
    describe_flow_pump_state,
    main_menu,
    run_main_menu_iteration,
    select_recipe_from_catalog,
)


class FakeSerialConnection:
    def __init__(self, is_open=False):
        self.is_open = is_open
        self.port = None
        self.close_calls = 0

    def open(self):
        self.is_open = True

    def close(self):
        self.close_calls += 1
        self.is_open = False


class FlowPumpControllerSpeedTests(unittest.TestCase):
    def setUp(self):
        self.controller = FlowPumpController.__new__(FlowPumpController)
        self.controller._send_character_command = Mock(return_value="*")

    def test_set_speed_formats_hundredths_as_six_digits(self):
        self.assertTrue(self.controller.set_speed("15.55"))
        self.controller._send_character_command.assert_called_once_with("S001555")

    def test_set_speed_accepts_protocol_boundaries(self):
        self.assertTrue(self.controller.set_speed("1.60"))
        self.assertTrue(self.controller.set_speed("160.00"))
        self.assertEqual(
            self.controller._send_character_command.call_args_list,
            [unittest.mock.call("S000160"), unittest.mock.call("S016000")],
        )

    def test_set_speed_rejects_out_of_range_or_excess_precision(self):
        for value in ("1.59", "160.01", "10.001", "abc", "NaN"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.controller.set_speed(value)
        self.controller._send_character_command.assert_not_called()

    def test_set_speed_reports_rejected_command(self):
        self.controller._send_character_command.return_value = "#"
        self.assertFalse(self.controller.set_speed("25"))

    def test_set_flow_rate_uses_the_calibration_constant(self):
        self.controller.is_running = Mock(return_value=False)
        self.controller.set_clockwise = Mock(return_value=True)
        self.controller.set_speed = Mock(return_value=True)
        self.controller.start = Mock(return_value=True)

        self.assertTrue(self.controller.set_flow_rate("0.4"))

        self.controller.set_clockwise.assert_called_once_with()
        self.controller.set_speed.assert_called_once_with(Decimal("6.40"))
        self.controller.start.assert_called_once_with()

    def test_negative_flow_selects_counterclockwise_direction(self):
        self.controller.is_running = Mock(return_value=False)
        self.controller.set_counterclockwise = Mock(return_value=True)
        self.controller.set_speed = Mock(return_value=True)
        self.controller.start = Mock(return_value=True)

        self.assertTrue(self.controller.set_flow_rate("-0.4"))

        self.controller.set_counterclockwise.assert_called_once_with()
        self.controller.set_speed.assert_called_once_with(Decimal("6.40"))
        self.controller.start.assert_called_once_with()

    def test_zero_flow_stops_a_running_pump(self):
        self.controller.is_running = Mock(return_value=True)
        self.controller.stop = Mock(return_value=True)
        self.controller.set_speed = Mock(return_value=True)

        self.assertTrue(self.controller.set_flow_rate("0"))

        self.controller.stop.assert_called_once_with()
        self.controller.set_speed.assert_not_called()

    def test_direction_commands_match_the_ism832_protocol(self):
        self.assertTrue(self.controller.set_clockwise())
        self.assertTrue(self.controller.set_counterclockwise())

        self.assertEqual(
            self.controller._send_character_command.call_args_list,
            [unittest.mock.call("J"), unittest.mock.call("K")],
        )

    def test_set_flow_rate_rejects_values_outside_pump_range(self):
        self.controller.set_speed = Mock(return_value=True)
        for value in ("0.09", "10.01", "NaN", "abc"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.controller.set_flow_rate(value)
        self.controller.set_speed.assert_not_called()


class MockDeviceTests(unittest.TestCase):
    @patch("builtins.print")
    def test_mock_valve_and_pump_keep_state_in_memory(self, _print):
        valve = MockCavroValve()
        pump = MockFlowPumpController()

        valve.select_channel(4)
        pump.set_flow_rate(0.4)

        self.assertEqual(valve.get_current_channel(), "4")
        self.assertEqual(pump.get_speed(), 6.4)
        self.assertEqual(pump.direction, "clockwise")
        self.assertTrue(pump.is_running())
        pump.set_flow_rate(-0.4)
        self.assertEqual(pump.direction, "counterclockwise")
        pump.set_flow_rate(0)
        self.assertFalse(pump.is_running())

    @patch("smartpump.interfaces.cli.serial.Serial")
    @patch("smartpump.interfaces.cli.main_menu")
    @patch("builtins.print")
    def test_mock_application_does_not_open_a_serial_port(
        self,
        _print,
        main_menu,
        serial_class,
    ):
        from smartpump.interfaces.cli import run_application

        run_application(
            ((1, "H2O", 0.25),),
            "Teste mock",
            1,
            mock_mode=True,
            time_scale=0.01,
        )

        serial_class.assert_not_called()
        main_menu.assert_called_once()


class FlowPumpSerialLifecycleTests(unittest.TestCase):
    @patch(
        "smartpump.infrastructure.drivers.flow_pump.time.sleep",
        side_effect=KeyboardInterrupt,
    )
    @patch("smartpump.infrastructure.drivers.flow_pump.serial.Serial")
    def test_interrupted_connection_closes_the_open_port(self, serial_class, _sleep):
        connection = FakeSerialConnection()
        serial_class.return_value = connection

        with self.assertRaises(KeyboardInterrupt):
            FlowPumpController(serial_port="COM_TEST")

        self.assertFalse(connection.is_open)
        self.assertEqual(connection.close_calls, 1)

    def test_close_releases_the_pyserial_object(self):
        controller = FlowPumpController.__new__(FlowPumpController)
        connection = FakeSerialConnection(is_open=True)
        controller.serial_connection = connection

        controller.close()

        self.assertFalse(connection.is_open)
        self.assertEqual(connection.close_calls, 1)
        self.assertIsNone(controller.serial_connection)

    def test_loader_reuses_an_already_open_controller(self):
        previous = flow_pump_loader._active_flow_pump_controller
        controller = Mock()
        controller.serial_connection.is_open = True
        flow_pump_loader._active_flow_pump_controller = controller
        try:
            loaded = flow_pump_loader.load_flow_pump_controller()
        finally:
            flow_pump_loader._active_flow_pump_controller = previous

        self.assertIs(loaded, controller)

    def test_loader_close_releases_and_forgets_the_controller(self):
        previous = flow_pump_loader._active_flow_pump_controller
        controller = Mock()
        flow_pump_loader._active_flow_pump_controller = controller
        try:
            flow_pump_loader.close_active_flow_pump_controller()
            self.assertIsNone(flow_pump_loader._active_flow_pump_controller)
        finally:
            flow_pump_loader._active_flow_pump_controller = previous

        controller.close.assert_called_once_with()


class FlowPumpMenuTests(unittest.TestCase):
    def test_state_labels(self):
        for response, label in (
            (True, "EM FUNCIONAMENTO"),
            (False, "PARADA"),
            (None, "DESCONHECIDO"),
        ):
            with self.subTest(response=response):
                self.assertEqual(describe_flow_pump_state(response), label)

    @patch("builtins.print")
    @patch(
        "builtins.input",
        side_effect=[
            "3", "-0,4", "s",
            "4", "s",
            "5",
            "6",
            "7", "25,5", "s",
            "m",
        ],
    )
    def test_menu_controls_signed_flow_start_stop_and_speed(self, _input, _print):
        smart_pump = Mock()
        smart_pump.pump_enabled = True
        smart_pump.get_pump_speed.return_value = 20.0

        control_flow_pump(smart_pump)

        smart_pump.set_pump_flow_rate.assert_called_once_with("-0.4")
        smart_pump.start_pump.assert_called_once_with()
        smart_pump.stop_pump.assert_called_once_with()
        smart_pump.get_pump_speed.assert_called_once_with()
        smart_pump.set_pump_speed.assert_called_once_with("25.5")

    def test_manual_channel_change_preserves_stopped_pump(self):
        valve = Mock()
        controller = Mock()
        controller.is_running.return_value = False

        service = SmartPump(valve, pump_factory=Mock(return_value=controller))
        service.enable_pump()
        service.select_channel(3)

        valve.select_channel.assert_called_once_with(
            3,
            show=False,
            before_channel_change=None,
            after_channel_change=None,
        )

    def test_manual_channel_change_restarts_pump_only_when_it_was_running(self):
        valve = Mock()
        controller = Mock()
        controller.is_running.return_value = True

        service = SmartPump(valve, pump_factory=Mock(return_value=controller))
        service.enable_pump()
        service.select_channel(3)

        valve.select_channel.assert_called_once()
        _args, keyword_arguments = valve.select_channel.call_args
        keyword_arguments["before_channel_change"]()
        keyword_arguments["after_channel_change"]()
        controller.stop.assert_called_once_with()
        controller.restart.assert_called_once_with()

    def test_manual_channel_change_is_blocked_for_unknown_pump_state(self):
        valve = Mock()
        controller = Mock()
        controller.is_running.return_value = None

        with self.assertRaises(RuntimeError):
            service = SmartPump(valve, pump_factory=Mock(return_value=controller))
            service.enable_pump()
            service.select_channel(3)

        valve.select_channel.assert_not_called()


class InterfaceInterruptTests(unittest.TestCase):
    @patch("builtins.print")
    @patch("builtins.input", side_effect=[KeyboardInterrupt, "n"])
    def test_exit_confirmation_ignores_another_ctrl_c(self, _input, _print):
        self.assertFalse(confirm_application_exit())

    @patch("builtins.input", return_value="s")
    def test_exit_confirmation_accepts_explicit_yes(self, _input):
        self.assertTrue(confirm_application_exit())

    @patch(
        "smartpump.interfaces.console.confirm_application_exit",
        side_effect=[False, True],
    )
    @patch("smartpump.interfaces.console.run_main_menu_iteration")
    def test_main_menu_requires_confirmation_after_ctrl_c(
        self,
        run_iteration,
        _confirm_exit,
    ):
        smart_pump = Mock()
        calls = 0

        def interrupt_twice(received_service, **_recipe_options):
            nonlocal calls
            self.assertIs(received_service, smart_pump)
            calls += 1
            if calls == 1:
                return False
            raise KeyboardInterrupt

        run_iteration.side_effect = interrupt_twice

        main_menu(smart_pump)

        self.assertEqual(calls, 3)
        smart_pump.close.assert_called_once_with()


class DynamicRecipeMenuTests(unittest.TestCase):
    @patch("builtins.print")
    @patch("builtins.input", side_effect=["r", "2"])
    def test_catalog_refresh_discovers_a_new_recipe(
        self,
        _input,
        _print,
    ):
        first = ExternalRecipe("Primeira", "", ((1, "A", 1, None),), 1, "a.json")
        second = ExternalRecipe("Nova", "", ((2, "B", 1, None),), 1, "b.json")
        smart_pump = Mock()
        smart_pump.discover_recipes.side_effect = [
            RecipeCatalog((first,), (), "recipes"),
            RecipeCatalog((first, second), (), "recipes"),
        ]

        selected = select_recipe_from_catalog(smart_pump)

        self.assertIs(selected, second)
        self.assertEqual(smart_pump.discover_recipes.call_count, 2)

    @patch("builtins.print")
    @patch("builtins.input", return_value="7")
    @patch("smartpump.interfaces.console.select_recipe_from_catalog")
    def test_selected_recipe_becomes_active_without_restart(
        self,
        select_recipe,
        _input,
        _print,
    ):
        selected = ExternalRecipe(
            "Nova",
            "",
            ((2, "B", 1, 4),),
            3,
            "new.json",
        )
        select_recipe.return_value = selected
        valve = Mock()
        valve.get_current_channel.return_value = "1"
        smart_pump = SmartPump(
            valve,
            recipe_steps=((1, "A", 1, None),),
            recipe_name="Anterior",
            recipe_cycle_count=1,
            recipe_source="old.json",
        )

        should_exit = run_main_menu_iteration(
            smart_pump,
        )

        self.assertFalse(should_exit)
        self.assertEqual(smart_pump.active_recipe.name, "Nova")
        self.assertEqual(smart_pump.active_recipe.cycle_count, 3)
        self.assertEqual(smart_pump.active_recipe.source, "new.json")


if __name__ == "__main__":
    unittest.main()
