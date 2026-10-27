import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from smartpump.application.service import SmartPump
from smartpump.domain.recipes import (
    RecipeConfigError,
    RecipeConflictError,
    parse_recipe_config,
)
from smartpump.infrastructure.recipes.files import (
    FileRecipeRepository,
    discover_recipe_configs,
    load_recipe_config,
)
from smartpump.interfaces import cli as main


VALID_RECIPE = {
    "schema_version": 1,
    "name": "Teste externo",
    "description": "Receita usada apenas nos testes.",
    "cycles": 2,
    "steps": [
        {
            "channel": 1,
            "solution": "H2O",
            "duration_minutes": 0.25,
            "flow_rate_ml_min": 4,
        },
        {
            "channel": 2,
            "solution": "PBS",
            "duration_minutes": 1,
            "flow_rate_ml_min": None,
        },
    ],
}


class RecipeConfigTests(unittest.TestCase):
    def test_valid_recipe_is_normalized_for_the_current_executor(self):
        recipe = parse_recipe_config(VALID_RECIPE, source="test.json")

        self.assertEqual(recipe.name, "Teste externo")
        self.assertEqual(recipe.cycle_count, 2)
        self.assertEqual(
            recipe.steps,
            ((1, "H2O", 0.25, 4), (2, "PBS", 1, None)),
        )
        self.assertEqual(recipe.source, "test.json")

    def test_example_file_is_loadable(self):
        path = Path(__file__).parents[1] / "recipes" / "example.json"
        recipe = load_recipe_config(path)

        self.assertEqual(recipe.name, "Exemplo externo")
        self.assertEqual(len(recipe.steps), 5)

    def test_invalid_steps_are_rejected(self):
        invalid_steps = (
            {"channel": 0, "solution": "H2O", "duration_minutes": 1},
            {"channel": True, "solution": "H2O", "duration_minutes": 1},
            {"channel": 1, "solution": "", "duration_minutes": 1},
            {"channel": 1, "solution": "H2O", "duration_minutes": 0},
            {"channel": 1, "solution": "H2O", "duration_minutes": True},
            {
                "channel": 1,
                "solution": "H2O",
                "duration_minutes": 1,
                "flow_rate_ml_min": True,
            },
            {
                "channel": 1,
                "solution": "H2O",
                "duration_minutes": 1,
                "flow_rate_ml_min": float("inf"),
            },
        )
        for step in invalid_steps:
            data = dict(VALID_RECIPE, steps=[step])
            with self.subTest(step=step):
                with self.assertRaises(RecipeConfigError):
                    parse_recipe_config(data)

    def test_unknown_fields_and_unsupported_schema_are_rejected(self):
        with self.assertRaises(RecipeConfigError):
            parse_recipe_config(dict(VALID_RECIPE, unexpected=True))
        with self.assertRaises(RecipeConfigError):
            parse_recipe_config(dict(VALID_RECIPE, schema_version=2))

    def test_total_duration_is_limited(self):
        data = dict(
            VALID_RECIPE,
            cycles=8,
            steps=[
                {"channel": 1, "solution": "H2O", "duration_minutes": 24 * 60}
            ],
        )
        with self.assertRaises(RecipeConfigError):
            parse_recipe_config(data)

    def test_catalog_discovers_valid_files_and_reports_invalid_ones(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            (directory / "valid.json").write_text(
                json.dumps(VALID_RECIPE),
                encoding="utf-8",
            )
            (directory / "invalid.json").write_text("{invalid", encoding="utf-8")

            catalog = discover_recipe_configs(directory)

        self.assertEqual([item.name for item in catalog.recipes], ["Teste externo"])
        self.assertEqual(len(catalog.errors), 1)
        self.assertTrue(catalog.errors[0][0].endswith("invalid.json"))

    def test_signed_and_zero_flow_rates_are_valid_recipe_data(self):
        data = dict(
            VALID_RECIPE,
            steps=[
                {
                    "channel": 1,
                    "solution": "Etanol",
                    "duration_minutes": 5,
                    "flow_rate_ml_min": -0.4,
                },
                {
                    "channel": 2,
                    "solution": "Parada",
                    "duration_minutes": 1,
                    "flow_rate_ml_min": 0,
                },
            ],
        )

        external_recipe = parse_recipe_config(data)

        self.assertEqual(external_recipe.steps[0][3], -0.4)
        self.assertEqual(external_recipe.steps[1][3], 0)

    def test_nested_cycles_expand_with_flow_rate_inheritance(self):
        data = {
            "schema_version": 1,
            "name": "Ciclos independentes",
            "flow_rate_ml_min": 1,
            "cycles": 2,
            "steps": [
                {
                    "name": "Bloco rápido",
                    "cycles": 2,
                    "flow_rate_ml_min": 2,
                    "steps": [
                        {
                            "channel": 1,
                            "solution": "H2O",
                            "duration_minutes": 0.25,
                        },
                        {
                            "channel": 2,
                            "solution": "Etanol",
                            "duration_minutes": 0.25,
                            "flow_rate_ml_min": -0.4,
                        },
                    ],
                },
                {
                    "channel": 3,
                    "solution": "PBS",
                    "duration_minutes": 0.25,
                },
                {
                    "name": "Sem vazão programada",
                    "flow_rate_ml_min": None,
                    "steps": [
                        {
                            "channel": 4,
                            "solution": "Manter configuração",
                            "duration_minutes": 0.25,
                        }
                    ],
                },
            ],
        }

        recipe = parse_recipe_config(data)

        self.assertEqual(recipe.cycle_count, 2)
        self.assertEqual(
            recipe.steps,
            (
                (1, "H2O", 0.25, 2),
                (2, "Etanol", 0.25, -0.4),
                (1, "H2O", 0.25, 2),
                (2, "Etanol", 0.25, -0.4),
                (3, "PBS", 0.25, 1),
                (4, "Manter configuração", 0.25, None),
            ),
        )

    def test_nested_cycles_must_be_finite_positive_integers(self):
        for cycles in (None, 0, -1, True, 1.5):
            data = dict(
                VALID_RECIPE,
                steps=[
                    {
                        "cycles": cycles,
                        "steps": [
                            {
                                "channel": 1,
                                "solution": "H2O",
                                "duration_minutes": 1,
                            }
                        ],
                    }
                ],
            )
            with self.subTest(cycles=cycles):
                with self.assertRaisesRegex(RecipeConfigError, "cycles"):
                    parse_recipe_config(data)

    def test_blocks_can_be_nested_and_repeat_independently(self):
        data = {
            "schema_version": 1,
            "name": "Blocos aninhados",
            "flow_rate_ml_min": 1,
            "steps": [
                {
                    "cycles": 2,
                    "steps": [
                        {
                            "cycles": 3,
                            "flow_rate_ml_min": -0.5,
                            "steps": [
                                {
                                    "channel": 1,
                                    "solution": "H2O",
                                    "duration_minutes": 0.25,
                                }
                            ],
                        },
                        {
                            "channel": 2,
                            "solution": "PBS",
                            "duration_minutes": 0.25,
                        },
                    ],
                }
            ],
        }

        recipe = parse_recipe_config(data)

        self.assertEqual(
            recipe.steps,
            (
                (1, "H2O", 0.25, -0.5),
                (1, "H2O", 0.25, -0.5),
                (1, "H2O", 0.25, -0.5),
                (2, "PBS", 0.25, 1),
                (1, "H2O", 0.25, -0.5),
                (1, "H2O", 0.25, -0.5),
                (1, "H2O", 0.25, -0.5),
                (2, "PBS", 0.25, 1),
            ),
        )

    def test_nested_cycles_are_included_in_duration_limit(self):
        data = dict(
            VALID_RECIPE,
            cycles=1,
            steps=[
                {
                    "cycles": 2,
                    "steps": [
                        {
                            "channel": 1,
                            "solution": "H2O",
                            "duration_minutes": 4 * 24 * 60,
                        }
                    ],
                }
            ],
        )

        with self.assertRaisesRegex(RecipeConfigError, "7 dias"):
            parse_recipe_config(data)

    def test_nested_expansion_respects_the_step_limit(self):
        data = dict(
            VALID_RECIPE,
            steps=[
                {
                    "cycles": 10001,
                    "steps": [
                        {
                            "channel": 1,
                            "solution": "H2O",
                            "duration_minutes": 0.25,
                        }
                    ],
                }
            ],
        )

        with self.assertRaisesRegex(RecipeConfigError, "10.000 etapas"):
            parse_recipe_config(data)


class FileRecipeRepositoryTests(unittest.TestCase):
    def test_application_service_creates_and_updates_a_valid_recipe(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = FileRecipeRepository(temporary_directory)
            events = []
            service = SmartPump(
                Mock(),
                recipe_repository=repository,
                event_handler=events.append,
            )

            created = service.create_recipe("new.json", VALID_RECIPE)
            service.activate_recipe(created.recipe)

            updated_data = json.loads(json.dumps(VALID_RECIPE))
            updated_data["name"] = "Receita atualizada"
            updated = service.update_recipe(
                "new.json",
                updated_data,
                expected_revision=created.revision,
            )

            self.assertNotEqual(created.revision, updated.revision)
            self.assertEqual(updated.recipe.name, "Receita atualizada")
            self.assertEqual(repository.get("new.json").revision, updated.revision)
            self.assertEqual(service.active_recipe.name, "Teste externo")
            self.assertEqual(
                [event.kind for event in events],
                ["recipe.created", "recipe.activated", "recipe.updated"],
            )

    def test_update_rejects_an_outdated_revision(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = FileRecipeRepository(temporary_directory)
            created = repository.create("recipe.json", VALID_RECIPE)
            updated_data = dict(VALID_RECIPE, description="Nova descrição")
            repository.update(
                "recipe.json",
                updated_data,
                expected_revision=created.revision,
            )

            with self.assertRaises(RecipeConflictError):
                repository.update(
                    "recipe.json",
                    VALID_RECIPE,
                    expected_revision=created.revision,
                )

    def test_invalid_recipe_is_not_persisted(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = FileRecipeRepository(temporary_directory)
            invalid = dict(VALID_RECIPE, steps=[])

            with self.assertRaises(RecipeConfigError):
                repository.create("invalid.json", invalid)

            self.assertFalse(Path(temporary_directory, "invalid.json").exists())

    def test_identifier_cannot_escape_the_recipe_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = FileRecipeRepository(temporary_directory)

            with self.assertRaises(ValueError):
                repository.create("../outside.json", VALID_RECIPE)


class RecipeCliTests(unittest.TestCase):
    def test_cli_cycles_override_the_file(self):
        parser = main.build_argument_parser()
        path = Path(__file__).parents[1] / "recipes" / "example.json"
        arguments = parser.parse_args(["--recipe", str(path), "--cycles", "3"])

        _steps, name, cycle_count, _source = main.resolve_recipe_options(
            arguments,
            parser,
        )

        self.assertEqual(name, "Exemplo externo")
        self.assertEqual(cycle_count, 3)

    @patch("smartpump.interfaces.cli.run_application")
    @patch("builtins.print")
    def test_validate_only_does_not_open_hardware(self, _print, run_application):
        path = Path(__file__).parents[1] / "recipes" / "example.json"

        main.main(["--recipe", str(path), "--validate-only"])

        run_application.assert_not_called()

    @patch("smartpump.interfaces.cli.show_recipe")
    def test_direct_controlled_execution_uses_the_application_service(
        self,
        _show_recipe,
    ):
        smart_pump = Mock()
        smart_pump.pump_enabled = True
        steps = ((1, "H2O", 0.25),)
        smart_pump.active_recipe.steps = steps
        smart_pump.active_recipe.name = "Teste"

        main.execute_recipe_from_cli(
            smart_pump,
            1,
            control_pump=True,
            assume_yes=True,
        )

        smart_pump.enable_pump.assert_called_once_with()
        smart_pump.run_active_recipe.assert_called_once_with(
            cycle_count=1,
            start_stopped_pump=True,
            time_scale=1.0,
        )
        smart_pump.shutdown_pump.assert_called_once_with()


class RecipeExecutionTests(unittest.TestCase):
    def build_service(self, valve, controller=None, monotonic=None, events=None):
        if monotonic is None:
            monotonic = Mock(side_effect=[0, 0])
        if events is None:
            events = []
        service = SmartPump(
            valve,
            pump_factory=Mock(return_value=controller),
            pump_closer=Mock(),
            event_handler=events.append,
            monotonic=monotonic,
            sleep=Mock(),
        )
        if controller is not None:
            service.enable_pump()
        return service, events

    def test_recipe_preflights_flow_against_pump_before_moving_valve(self):
        valve = Mock()
        controller = Mock()
        controller.is_running.return_value = True
        controller.validate_flow_rate.side_effect = ValueError("RPM abaixo do mínimo")
        service, _events = self.build_service(valve, controller)

        with self.assertRaisesRegex(ValueError, "Etapa 1.*RPM abaixo do mínimo"):
            service.run_recipe(
                cycle_count=1,
                recipe_steps=((1, "Etanol", 5, 0.09),),
                recipe_name="Teste",
            )

        valve.select_channel.assert_not_called()

    def test_time_scale_accelerates_recipe_without_changing_programmed_steps(
        self,
    ):
        valve = Mock()
        sleep = Mock()
        service = SmartPump(
            valve,
            monotonic=Mock(side_effect=[0, 0.6]),
            sleep=sleep,
        )

        service.run_recipe(
            cycle_count=1,
            recipe_steps=((1, "H2O", 1),),
            recipe_name="Teste",
            time_scale=0.01,
        )

        sleep.assert_not_called()
        valve.select_channel.assert_called_once_with(1, show=False)

    def test_recipe_asks_and_starts_a_controlled_pump_that_was_stopped(
        self,
    ):
        valve = Mock()
        controller = Mock()
        controller.is_running.return_value = False
        controller.restart.return_value = True
        service, _events = self.build_service(valve, controller)

        service.run_recipe(
            cycle_count=1,
            recipe_steps=((1, "H2O", 0),),
            recipe_name="Teste",
            start_stopped_pump=True,
        )

        controller.restart.assert_called_once_with()
        valve.select_channel.assert_called_once()

    def test_recipe_can_continue_with_a_stopped_pump(
        self,
    ):
        valve = Mock()
        controller = Mock()
        controller.is_running.return_value = False
        service, _events = self.build_service(valve, controller)

        service.run_recipe(
            cycle_count=1,
            recipe_steps=((1, "H2O", 0, 4),),
            recipe_name="Teste",
        )

        controller.set_flow_rate.assert_not_called()
        controller.restart.assert_not_called()
        valve.select_channel.assert_called_once_with(1, show=False)

    def test_recipe_applies_signed_flow_without_a_second_restart(
        self,
    ):
        valve = Mock()
        controller = Mock()
        controller.is_running.return_value = True
        controller.stop.return_value = True
        controller.set_flow_rate.return_value = True
        controller.restart.return_value = True
        service, _events = self.build_service(valve, controller)

        service.run_recipe(
            cycle_count=1,
            recipe_steps=((2, "PBS", 0, 4),),
            recipe_name="Teste",
        )

        controller.stop.assert_called_once_with()
        valve.select_channel.assert_called_once_with(2, show=False)
        controller.set_flow_rate.assert_called_once_with(4)
        controller.restart.assert_not_called()

    def test_zero_flow_keeps_pump_stopped_during_step(self):
        valve = Mock()
        controller = Mock()
        controller.is_running.return_value = True
        controller.stop.return_value = True
        controller.set_flow_rate.return_value = True
        service, _events = self.build_service(valve, controller)

        service.run_recipe(
            cycle_count=1,
            recipe_steps=((2, "Pausa", 0, 0),),
            recipe_name="Teste",
        )

        controller.stop.assert_called_once_with()
        controller.set_flow_rate.assert_called_once_with(0)
        controller.restart.assert_not_called()

    def test_pause_freezes_step_and_restores_controlled_pump(self):
        valve = Mock()
        controller = Mock()
        controller.is_running.return_value = True
        controller.stop.return_value = True
        controller.set_flow_rate.return_value = True
        pause_requested = Mock(side_effect=[False, True, True, False])
        events = []
        service = SmartPump(
            valve,
            pump_factory=Mock(return_value=controller),
            pump_closer=Mock(),
            event_handler=events.append,
            monotonic=Mock(side_effect=[0, 0, 1, 1.6]),
            sleep=Mock(),
        )
        service.enable_pump()

        service.run_recipe(
            cycle_count=1,
            recipe_steps=((2, "PBS", 0.01, 4),),
            recipe_name="Teste",
            should_pause=pause_requested,
        )

        self.assertEqual(controller.stop.call_count, 2)
        self.assertEqual(controller.set_flow_rate.call_count, 2)
        self.assertEqual(
            [event.kind for event in events if event.kind in {"recipe.paused", "recipe.resumed"}],
            ["recipe.paused", "recipe.resumed"],
        )

    def test_recipe_rejects_unknown_controlled_pump_state(self):
        valve = Mock()
        controller = Mock()
        controller.is_running.return_value = None
        service, _events = self.build_service(valve, controller)

        with self.assertRaises(RuntimeError):
            service.run_recipe(
                cycle_count=1,
                recipe_steps=((1, "H2O", 0),),
                recipe_name="Teste",
            )

        valve.select_channel.assert_not_called()

    @patch("smartpump.interfaces.cli.show_recipe")
    def test_direct_interruption_still_stops_controlled_pump(
        self,
        _show_recipe,
    ):
        smart_pump = Mock()
        smart_pump.pump_enabled = True
        smart_pump.run_active_recipe.side_effect = KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            main.execute_recipe_from_cli(
                smart_pump,
                1,
                control_pump=True,
                assume_yes=True,
            )

        smart_pump.shutdown_pump.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
