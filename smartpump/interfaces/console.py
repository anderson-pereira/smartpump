import math
from pathlib import Path

import serial

from smartpump.application.service import SmartPumpEvent, UNSPECIFIED_CYCLE_COUNT
from smartpump.infrastructure.drivers.cavro import CAVRO_VALVE_ERRORS
from smartpump.interfaces.recipe_console import (
    choose_cycling,
    format_flow_rate,
    format_time,
    show_recipe,
)
from smartpump.settings import VALVE_CHANNEL_COUNT


INTERACTIVE_CYCLE_COUNT = UNSPECIFIED_CYCLE_COUNT


def render_application_event(event: SmartPumpEvent):
    """Render application events without leaking terminal concerns into services."""
    if event.kind == "recipe.progress":
        data = event.data
        cycle_count = data["cycle_count"]
        cycle_text = (
            str(data["cycle"])
            if cycle_count is None
            else f"{data['cycle']}/{cycle_count}"
        )
        total_text = ""
        if data["remaining_total_seconds"] is not None:
            total_text = (
                f" | Total: {format_time(math.ceil(data['remaining_total_seconds']))}"
            )
        print(
            f"\rCiclo {cycle_text} | Passo {data['step']}/{data['total_steps']}"
            f" | Canal {data['channel']} | {data['solution']}"
            f" | Etapa: {format_time(math.ceil(data['remaining_step_seconds']))}"
            f"{total_text}",
            end="",
            flush=True,
        )
        if data["remaining_step_seconds"] <= 0:
            print()
        return

    if event.kind == "recipe.step_started":
        data = event.data
        print()
        print("=" * 72)
        print(event.message)
        print(f"Tempo: {data['duration_minutes']:g} min")
        print(f"Vazão: {format_flow_rate(data['flow_rate_ml_min'])}")
        print("=" * 72)
        return

    print(event.message)


def manual_control(smart_pump):
    print()
    print("=" * 60)
    print("CONTROLE MANUAL")
    print("=" * 60)
    print()
    print("1 ... 6  -> selecionar canal")
    print("p        -> consultar canal atual")
    print("s        -> consultar status")
    print("h        -> homing da válvula")
    print("m        -> voltar ao menu principal")
    print("q        -> encerrar programa")

    while True:
        current_channel = smart_pump.get_valve_channel()
        print()
        print(f"Canal atual: {current_channel}")
        command = input("Manual > ").strip().lower()

        if command == "m":
            return "menu"
        if command in ("q", "quit", "exit"):
            return "sair"
        if command == "p":
            current_channel = smart_pump.get_valve_channel()
            print(f"Canal atual: {current_channel}")
            continue
        if command == "s":
            response = smart_pump.get_valve_status()
            if response is None:
                print("Sem resposta da válvula.")
            else:
                print("Estado:", "READY" if response["ready"] else "BUSY")
                print(
                    f"Erro: {response['error']} - "
                    f"{CAVRO_VALVE_ERRORS.get(response['error'], 'Desconhecido')}"
                )
            continue
        if command == "h":
            try:
                confirmation = input("Executar homing da válvula? [s/N]: ")
                if confirmation.strip().lower() in ("s", "sim", "y", "yes"):
                    smart_pump.home_valve()
                else:
                    print("Homing cancelado.")
            except Exception as error:
                print()
                print(f"Erro durante homing: {error}")
            continue

        try:
            channel = int(command)
        except ValueError:
            print("Comando inválido.")
            continue
        if channel not in range(1, VALVE_CHANNEL_COUNT + 1):
            print(f"Escolha um canal entre 1 e {VALVE_CHANNEL_COUNT}.")
            continue

        try:
            print()
            smart_pump.select_channel(channel)
        except Exception as error:
            print()
            print(f"ERRO: {error}")


def configure_flow_pump(smart_pump):
    """Ask whether to load the optional remote flow-pump controller."""
    print()
    enabled = input("Utilizar controle remoto da bomba? [s/N]: ").strip().lower()
    if enabled not in ("s", "sim", "y", "yes"):
        smart_pump.disable_pump()
        print("Controle remoto da bomba desativado.")
        return

    if smart_pump.pump_enabled:
        print("Controle remoto da bomba já está ativado.")
        return

    try:
        smart_pump.enable_pump()
    except Exception as error:
        print(f"Não foi possível carregar o controle da bomba: {error}")
        return

    print("Controle remoto da bomba ativado.")


def ask_shutdown_at_recipe_end():
    answer = input("Ao fim da receita, desligar a bomba? [s/N]: ").strip().lower()
    return answer in ("s", "sim", "y", "yes")


def confirm_application_exit():
    """Return True only after an explicit exit confirmation."""
    while True:
        try:
            answer = input("Deseja realmente encerrar a aplicação? [s/N]: ")
        except KeyboardInterrupt:
            print()
            print("A saída ainda não foi confirmada.")
            continue
        return answer.strip().lower() in ("s", "sim", "y", "yes")


def describe_flow_pump_state(running):
    if running is True:
        return "EM FUNCIONAMENTO"
    if running is False:
        return "PARADA"
    return "DESCONHECIDO"


def control_flow_pump(smart_pump):
    """Provide direct manual controls for the connected flow pump."""
    if not smart_pump.pump_enabled:
        print()
        print("O controle remoto da bomba está desativado.")
        print("Ative-o primeiro na opção [5] do menu principal.")
        return

    while True:
        print()
        print("=" * 60)
        print("CONTROLE MANUAL DA BOMBA")
        print("=" * 60)
        print()
        print("[1] Identificar bomba")
        print("[2] Consultar estado")
        print("[3] Definir vazão, sentido e funcionamento")
        print("[4] Iniciar/retomar com a configuração atual")
        print("[5] Parar bomba")
        print("[6] Consultar velocidade")
        print("[7] Configurar velocidade em RPM (avançado)")
        print("[M] Voltar ao menu principal")
        print()
        option = input("Bomba > ").strip().lower()

        try:
            if option == "1":
                identification = smart_pump.identify_pump()
                print(f"Identificação: {identification or 'sem resposta'}")
            elif option == "2":
                print(f"Estado: {describe_flow_pump_state(smart_pump.is_pump_running())}")
            elif option == "3":
                value = input(
                    "Vazão (-10 a +10 mL/min; + horário, - anti-horário, 0 parar): "
                ).strip().replace(",", ".")
                numeric_value = float(value)
                if not math.isfinite(numeric_value):
                    raise ValueError("A vazão deve ser um número finito.")
                description = format_flow_rate(numeric_value)
                confirmation = input(f"Aplicar {description}? [s/N]: ").strip().lower()
                if confirmation in ("s", "sim", "y", "yes"):
                    smart_pump.set_pump_flow_rate(value)
                else:
                    print("Alteração cancelada.")
            elif option == "4":
                confirmation = input("Iniciar a bomba agora? [s/N]: ").strip().lower()
                if confirmation in ("s", "sim", "y", "yes"):
                    smart_pump.start_pump()
                else:
                    print("Partida cancelada.")
            elif option == "5":
                smart_pump.stop_pump()
            elif option == "6":
                speed = smart_pump.get_pump_speed()
                if speed is None:
                    print("Não foi possível consultar a velocidade.")
                else:
                    print(f"Velocidade configurada: {speed:.2f} RPM")
            elif option == "7":
                value = input("Nova velocidade (1,60 a 160,00 RPM): ").strip()
                value = value.replace(",", ".")
                confirmation = input(
                    f"Configurar a velocidade para {value} RPM? [s/N]: "
                ).strip().lower()
                if confirmation in ("s", "sim", "y", "yes"):
                    smart_pump.set_pump_speed(value)
                else:
                    print("Alteração cancelada.")
            elif option in ("m", "menu", "voltar"):
                return
            else:
                print("Opção inválida.")
        except ValueError as error:
            print(f"Valor inválido: {error}")
        except serial.SerialException as error:
            print(f"Erro de comunicação com a bomba: {error}")
        except Exception as error:
            print(f"Falha ao controlar a bomba: {error}")


def select_recipe_from_catalog(smart_pump, recipe_directory=None):
    """Discover recipes on every refresh and let the operator select one."""
    while True:
        catalog = smart_pump.discover_recipes(recipe_directory)

        print()
        print("=" * 72)
        print("CATÁLOGO DE RECEITAS")
        print("=" * 72)
        print(f"Pasta: {catalog.directory}")
        print()

        if catalog.recipes:
            for index, external_recipe in enumerate(catalog.recipes, start=1):
                cycle_text = (
                    "contínuo"
                    if external_recipe.cycle_count is None
                    else str(external_recipe.cycle_count)
                )
                filename = Path(external_recipe.source).name
                print(
                    f"[{index}] {external_recipe.name} | {len(external_recipe.steps)} "
                    f"etapa(s) | ciclos: {cycle_text} | {filename}"
                )
        else:
            print("Nenhuma receita válida encontrada.")

        if catalog.errors:
            print()
            print("Arquivos ignorados por erro:")
            for source, error in catalog.errors:
                print(f"- {Path(source).name}: {error}")

        print()
        print("[R] Atualizar catálogo")
        print("[M] Voltar ao menu principal")
        choice = input("Receita > ").strip().lower()

        if choice in ("m", "menu", "voltar"):
            return None
        if choice in ("r", "refresh", "atualizar"):
            continue
        try:
            recipe_index = int(choice) - 1
        except ValueError:
            print("Opção inválida.")
            continue
        if recipe_index not in range(len(catalog.recipes)):
            print("Escolha uma receita da lista.")
            continue
        return catalog.recipes[recipe_index]


def run_main_menu_iteration(
    smart_pump,
    recipe_directory=None,
    time_scale=1.0,
):
    """Run one CLI interaction and return whether exit was confirmed."""
    active_recipe = smart_pump.active_recipe
    recipe_steps = active_recipe.steps
    recipe_name = active_recipe.name
    preset_cycle_count = active_recipe.cycle_count

    current_channel = smart_pump.get_valve_channel()
    flow_pump_status = "ATIVADO" if smart_pump.pump_enabled else "DESATIVADO"

    print()
    print("=" * 72)
    print("CONTROLE DA VÁLVULA CAVRO")
    print("=" * 72)
    print(f"Canal atual: {current_channel}")
    print(f"Controle remoto da bomba: {flow_pump_status}")
    print(f"Receita ativa: {recipe_name}")
    print(f"Origem da receita: {active_recipe.source}")
    print()
    print("[1] Executar receita automática")
    print("[2] Controle manual")
    print("[3] Mostrar receita")
    print("[4] Homing da válvula")
    print("[5] Configurar controle remoto da bomba")
    print("[6] Controle manual da bomba")
    print("[7] Selecionar receita do catálogo")
    print("[Q] Sair")
    print()
    option = input("Selecione uma opção: ").strip().lower()

    if option == "1":
        show_recipe(recipe_steps, recipe_name)
        if preset_cycle_count is INTERACTIVE_CYCLE_COUNT:
            cycles = choose_cycling()
            if cycles == "cancelar":
                print("Execução cancelada.")
                return False
        else:
            cycles = preset_cycle_count
            print("Ciclagem definida pelo arquivo ou pela linha de comando.")

        shutdown_at_end = False
        start_stopped_pump = False
        if smart_pump.pump_enabled:
            shutdown_at_end = ask_shutdown_at_recipe_end()
            pump_running = smart_pump.is_pump_running()
            if pump_running is None:
                raise RuntimeError("Não foi possível determinar o estado da bomba.")
            if not pump_running:
                answer = input(
                    "A bomba está parada. Deseja controlá-la nesta receita? [s/N]: "
                ).strip().lower()
                start_stopped_pump = answer in ("s", "sim", "y", "yes")

        print()
        if cycles is None:
            print("Modo selecionado: CONTÍNUO")
        elif cycles == 1:
            print("Modo selecionado: 1 ciclo")
        else:
            print(f"Modo selecionado: {cycles} ciclos")
        print()
        confirmation = input(
            "Pressione ENTER para iniciar ou Q para cancelar: "
        ).strip().lower()
        if confirmation == "q":
            print("Receita cancelada.")
            return False

        try:
            smart_pump.run_active_recipe(
                cycle_count=cycles,
                start_stopped_pump=start_stopped_pump,
                time_scale=time_scale,
            )
            if shutdown_at_end:
                smart_pump.shutdown_pump()
        except Exception as error:
            print()
            print("=" * 72)
            print("ERRO DURANTE A RECEITA")
            print("=" * 72)
            print(error)
    elif option == "2":
        result = manual_control(smart_pump)
        if result == "sair":
            return confirm_application_exit()
    elif option == "3":
        show_recipe(recipe_steps, recipe_name)
    elif option == "4":
        try:
            confirmation = input("Executar homing da válvula? [s/N]: ")
            if confirmation.strip().lower() in ("s", "sim", "y", "yes"):
                smart_pump.home_valve()
            else:
                print("Homing cancelado.")
        except Exception as error:
            print()
            print("=" * 60)
            print("ERRO DURANTE O HOMING")
            print("=" * 60)
            print(error)
    elif option == "5":
        configure_flow_pump(smart_pump)
    elif option == "6":
        control_flow_pump(smart_pump)
    elif option == "7":
        selected_recipe = select_recipe_from_catalog(smart_pump, recipe_directory)
        if selected_recipe is not None:
            smart_pump.activate_recipe(selected_recipe)
    elif option in ("q", "quit", "exit"):
        return confirm_application_exit()
    else:
        print("Opção inválida.")

    return False


def main_menu(
    smart_pump,
    recipe_directory=None,
    time_scale=1.0,
):
    while True:
        try:
            exit_confirmed = run_main_menu_iteration(
                smart_pump,
                recipe_directory=recipe_directory,
                time_scale=time_scale,
            )
        except KeyboardInterrupt:
            print()
            print()
            print("Ctrl+C recebido: a operação atual foi interrompida.")
            exit_confirmed = confirm_application_exit()
            if not exit_confirmed:
                print("Saída cancelada. Retornando ao menu principal.")

        if exit_confirmed:
            smart_pump.close()
            return
