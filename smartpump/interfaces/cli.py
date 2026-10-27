import argparse
import math
import time

import serial

from smartpump.application.service import SmartPump
from smartpump.domain.recipes import RecipeConfigError
from smartpump.infrastructure.drivers.cavro import CAVRO_VALVE_ERRORS, CavroValve
from smartpump.infrastructure.drivers.flow_pump_loader import (
    close_active_flow_pump_controller,
    load_flow_pump_controller,
    set_flow_pump_controller_factory,
)
from smartpump.infrastructure.drivers.mocks import (
    MockCavroValve,
    MockFlowPumpController,
)
from smartpump.infrastructure.recipes.files import (
    FileRecipeRepository,
    load_recipe_config,
)
from smartpump.interfaces.console import (
    INTERACTIVE_CYCLE_COUNT,
    confirm_application_exit,
    main_menu,
    render_application_event,
)
from smartpump.interfaces.recipe_console import show_recipe
from smartpump.settings import RECIPE, VALVE_BAUD_RATE, VALVE_SERIAL_PORT


def positive_integer(value):
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("deve ser um número inteiro positivo")
    if number < 1:
        raise argparse.ArgumentTypeError("deve ser maior que zero")
    return number


def positive_float(value):
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("deve ser um número positivo")
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("deve ser maior que zero")
    return number


def build_argument_parser():
    parser = argparse.ArgumentParser(
        description="Controle da válvula Cavro e execução de receitas externas."
    )
    parser.add_argument(
        "--recipe",
        metavar="ARQUIVO.json",
        help="carrega uma receita externa em JSON",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="valida e resume a receita sem abrir portas seriais",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="executa a receita diretamente, sem abrir o menu principal",
    )
    cycle_group = parser.add_mutually_exclusive_group()
    cycle_group.add_argument(
        "--cycles",
        type=positive_integer,
        help="sobrescreve a quantidade de ciclos da receita",
    )
    cycle_group.add_argument(
        "--continuous",
        action="store_true",
        help="executa continuamente até uma interrupção confirmada",
    )
    parser.add_argument(
        "--control-pump",
        action="store_true",
        help="habilita a bomba na execução direta e a para ao final",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="confirma a execução direta sem perguntar no terminal",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="simula válvula e bomba em memória, sem abrir portas seriais",
    )
    parser.add_argument(
        "--time-scale",
        type=positive_float,
        metavar="FATOR",
        help="escala os tempos no modo mock (padrão: 0.01)",
    )
    return parser


def resolve_recipe_options(arguments, parser):
    external_recipe = None
    if arguments.recipe:
        try:
            external_recipe = load_recipe_config(arguments.recipe)
        except RecipeConfigError as error:
            parser.error(str(error))

    if arguments.validate_only and external_recipe is None:
        parser.error("--validate-only exige --recipe.")
    if arguments.validate_only and (
        arguments.execute or arguments.control_pump or arguments.yes
    ):
        parser.error(
            "--validate-only não pode ser combinado com --execute, "
            "--control-pump ou --yes."
        )
    if arguments.control_pump and not arguments.execute:
        parser.error("--control-pump exige --execute.")
    if arguments.yes and not arguments.execute:
        parser.error("--yes exige --execute.")
    if arguments.time_scale is not None and not arguments.mock:
        parser.error("--time-scale exige --mock.")

    if external_recipe is None:
        recipe_steps = tuple(RECIPE)
        recipe_name = "Receita de config.py"
        cycle_count = INTERACTIVE_CYCLE_COUNT
        recipe_source = "config.py"
    else:
        recipe_steps = external_recipe.steps
        recipe_name = external_recipe.name
        cycle_count = external_recipe.cycle_count
        recipe_source = external_recipe.source

    if arguments.cycles is not None:
        cycle_count = arguments.cycles
    elif arguments.continuous:
        cycle_count = None
    elif arguments.execute and cycle_count is INTERACTIVE_CYCLE_COUNT:
        cycle_count = 1

    return recipe_steps, recipe_name, cycle_count, recipe_source


def print_recipe_validation(recipe_steps, recipe_name, cycle_count, source):
    duration_per_cycle = sum(step[2] * 60 for step in recipe_steps)
    print(f"Receita válida: {recipe_name}")
    print(f"Origem: {source}")
    print(f"Etapas por ciclo: {len(recipe_steps)}")
    print(f"Duração por ciclo: {duration_per_cycle:g} segundos")
    if cycle_count is None:
        print("Ciclagem: contínua")
    else:
        print(f"Ciclos: {cycle_count}")


def execute_recipe_from_cli(
    smart_pump,
    cycle_count,
    control_pump=False,
    assume_yes=False,
    time_scale=1.0,
):
    active_recipe = smart_pump.active_recipe
    show_recipe(active_recipe.steps, active_recipe.name)
    print()
    if cycle_count is None:
        print("Ciclagem: CONTÍNUA")
    else:
        print(f"Ciclos: {cycle_count}")
    print(f"Controle da bomba: {'ATIVADO' if control_pump else 'DESATIVADO'}")

    if not assume_yes:
        confirmation = input("Confirmar início da receita? [s/N]: ").strip().lower()
        if confirmation not in ("s", "sim", "y", "yes"):
            print("Execução cancelada.")
            return

    try:
        if control_pump:
            smart_pump.enable_pump()

        smart_pump.run_active_recipe(
            cycle_count=cycle_count,
            start_stopped_pump=True if control_pump else None,
            time_scale=time_scale,
        )
    finally:
        if control_pump and smart_pump.pump_enabled:
            smart_pump.shutdown_pump()


def run_application(
    recipe_steps,
    recipe_name,
    cycle_count,
    recipe_source="config.py",
    execute_immediately=False,
    control_pump=False,
    assume_yes=False,
    mock_mode=False,
    time_scale=1.0,
):
    """Connect to the valve and run the interactive application."""
    if mock_mode:
        set_flow_pump_controller_factory(MockFlowPumpController)
        try:
            cavro_valve = MockCavroValve()
            smart_pump = SmartPump(
                cavro_valve,
                pump_factory=load_flow_pump_controller,
                pump_closer=close_active_flow_pump_controller,
                recipe_repository=FileRecipeRepository(),
                event_handler=render_application_event,
                recipe_steps=recipe_steps,
                recipe_name=recipe_name,
                recipe_cycle_count=cycle_count,
                recipe_source=recipe_source,
            )
            print()
            print("=" * 72)
            print("MODO SIMULADO — NENHUMA PORTA SERIAL SERÁ ABERTA")
            print("=" * 72)
            print("Válvula: Cavro simulada | Firmware: MOCK-1.0")
            print(f"Canal atual: {cavro_valve.get_current_channel()}")
            print(f"Escala de tempo: {time_scale:g}x")
            if execute_immediately:
                execute_recipe_from_cli(
                    smart_pump,
                    cycle_count,
                    control_pump=control_pump,
                    assume_yes=assume_yes,
                    time_scale=time_scale,
                )
            else:
                main_menu(
                    smart_pump,
                    time_scale=time_scale,
                )
        finally:
            if "smart_pump" in locals():
                smart_pump.close()
            set_flow_pump_controller_factory(None)
        return

    with serial.Serial(
        VALVE_SERIAL_PORT,
        VALVE_BAUD_RATE,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=1,
    ) as serial_connection:
        time.sleep(0.3)
        cavro_valve = CavroValve(serial_connection)
        firmware = cavro_valve.send_command("&")
        if firmware is None:
            raise RuntimeError("Não foi possível comunicar com a válvula.")
        if firmware["error"] != 0:
            raise RuntimeError(
                f"Válvula reportou erro {firmware['error']}: "
                f"{CAVRO_VALVE_ERRORS.get(firmware['error'], 'Desconhecido')}"
            )

        print()
        print("=" * 72)
        print("VÁLVULA CAVRO CONECTADA")
        print("=" * 72)
        print(f"Firmware: {firmware['data']}")
        current_channel = cavro_valve.get_current_channel()
        print(f"Canal atual: {current_channel}")
        smart_pump = SmartPump(
            cavro_valve,
            pump_factory=load_flow_pump_controller,
            pump_closer=close_active_flow_pump_controller,
            recipe_repository=FileRecipeRepository(),
            event_handler=render_application_event,
            recipe_steps=recipe_steps,
            recipe_name=recipe_name,
            recipe_cycle_count=cycle_count,
            recipe_source=recipe_source,
        )
        try:
            if execute_immediately:
                execute_recipe_from_cli(
                    smart_pump,
                    cycle_count,
                    control_pump=control_pump,
                    assume_yes=assume_yes,
                    time_scale=time_scale,
                )
            else:
                main_menu(
                    smart_pump,
                    time_scale=time_scale,
                )
        finally:
            smart_pump.close()


def main(argv=None):
    parser = build_argument_parser()
    arguments = parser.parse_args(argv)
    recipe_steps, recipe_name, cycle_count, recipe_source = resolve_recipe_options(
        arguments,
        parser,
    )

    if arguments.validate_only:
        print_recipe_validation(
            recipe_steps,
            recipe_name,
            cycle_count,
            recipe_source,
        )
        return 0

    time_scale = (
        arguments.time_scale
        if arguments.time_scale is not None
        else (0.01 if arguments.mock else 1.0)
    )
    execute_immediately = arguments.execute
    while True:
        try:
            run_application(
                recipe_steps,
                recipe_name,
                cycle_count,
                recipe_source=recipe_source,
                execute_immediately=execute_immediately,
                control_pump=arguments.control_pump,
                assume_yes=arguments.yes,
                mock_mode=arguments.mock,
                time_scale=time_scale,
            )
            print()
            print("Comunicação encerrada.")
            return 0
        except serial.SerialException as error:
            print()
            print(f"Erro de comunicação serial: {error}")
            return 1
        except KeyboardInterrupt:
            print()
            print()
            print("Ctrl+C recebido durante a inicialização ou o encerramento.")
            if confirm_application_exit():
                print("Programa encerrado pelo usuário.")
                return 130
            if execute_immediately:
                execute_immediately = False
                print("Saída cancelada. A receita não será reiniciada automaticamente.")
                print("Retornando ao modo interativo.")
            else:
                print("Saída cancelada. Reiniciando a comunicação.")
        except Exception as error:
            print()
            print("=" * 72)
            print("ERRO")
            print("=" * 72)
            print(error)
            return 1
        finally:
            close_active_flow_pump_controller()


if __name__ == "__main__":
    raise SystemExit(main())
