from cavro_valve import CAVRO_VALVE_ERRORS
from config import VALVE_CHANNEL_COUNT
from flow_pump_loader import load_flow_pump_controller
from recipe import choose_cycling, run_recipe, show_recipe


def select_channel_with_flow_pump(cavro_valve, channel, flow_pump_controller):
    """Coordinate the optional flow pump around a Cavro valve movement."""
    cavro_valve.select_channel(
        channel,
        show=True,
        before_channel_change=(
            flow_pump_controller.stop if flow_pump_controller is not None else None
        ),
        after_channel_change=(
            flow_pump_controller.restart if flow_pump_controller is not None else None
        ),
    )


def manual_control(cavro_valve, flow_pump_controller):
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
        current_channel = cavro_valve.get_current_channel()
        print()
        print(f"Canal atual: {current_channel}")
        command = input("Manual > ").strip().lower()

        if command == "m":
            return "menu"
        if command in ("q", "quit", "exit"):
            return "sair"
        if command == "p":
            current_channel = cavro_valve.get_current_channel()
            print(f"Canal atual: {current_channel}")
            continue
        if command == "s":
            response = cavro_valve.get_status()
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
                cavro_valve.home()
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
            select_channel_with_flow_pump(
                cavro_valve,
                channel,
                flow_pump_controller,
            )
        except Exception as error:
            print()
            print(f"ERRO: {error}")


def configure_flow_pump(current_flow_pump_controller):
    """Ask whether to load the optional remote flow-pump controller."""
    print()
    enabled = input("Utilizar controle remoto da bomba? [s/N]: ").strip().lower()
    if enabled not in ("s", "sim", "y", "yes"):
        if current_flow_pump_controller is not None:
            current_flow_pump_controller.close()
        print("Controle remoto da bomba desativado.")
        return None

    try:
        flow_pump_controller = load_flow_pump_controller()
    except Exception as error:
        print(f"Não foi possível carregar o controle da bomba: {error}")
        return current_flow_pump_controller

    if current_flow_pump_controller is not None:
        current_flow_pump_controller.close()
    print("Controle remoto da bomba ativado.")
    return flow_pump_controller


def ask_shutdown_at_recipe_end():
    answer = input("Ao fim da receita, desligar a bomba? [s/N]: ").strip().lower()
    return answer in ("s", "sim", "y", "yes")


def close_flow_pump_controller(flow_pump_controller):
    if flow_pump_controller is not None:
        flow_pump_controller.close()


def main_menu(cavro_valve):
    flow_pump_controller = None

    while True:
        current_channel = cavro_valve.get_current_channel()
        flow_pump_status = (
            "ATIVADO" if flow_pump_controller is not None else "DESATIVADO"
        )

        print()
        print("=" * 72)
        print("CONTROLE DA VÁLVULA CAVRO")
        print("=" * 72)
        print(f"Canal atual: {current_channel}")
        print(f"Controle remoto da bomba: {flow_pump_status}")
        print()
        print("[1] Executar receita automática")
        print("[2] Controle manual")
        print("[3] Mostrar receita")
        print("[4] Homing da válvula")
        print("[5] Configurar controle remoto da bomba")
        print("[Q] Sair")
        print()
        option = input("Selecione uma opção: ").strip().lower()

        if option == "1":
            show_recipe()
            cycles = choose_cycling()
            if cycles == "cancelar":
                print("Execução cancelada.")
                continue

            shutdown_at_end = False
            if flow_pump_controller is not None:
                shutdown_at_end = ask_shutdown_at_recipe_end()

            print()
            if cycles is None:
                print("Modo selecionado: CONTÍNUO")
            elif cycles == 1:
                print("Modo selecionado: 1 ciclo")
            else:
                print(f"Modo selecionado: {cycles} ciclos")
            print()
            confirmation = input("Pressione ENTER para iniciar ou Q para cancelar: ").strip().lower()
            if confirmation == "q":
                print("Receita cancelada.")
                continue

            try:
                run_recipe(
                    cavro_valve,
                    cycle_count=cycles,
                    flow_pump_controller=flow_pump_controller,
                )
                if shutdown_at_end:
                    flow_pump_controller.shutdown()
            except KeyboardInterrupt:
                print()
                print()
                print("=" * 72)
                print("RECEITA INTERROMPIDA PELO USUÁRIO")
                print("=" * 72)
                print("A válvula permanecerá no canal atualmente selecionado.")
            except Exception as error:
                print()
                print("=" * 72)
                print("ERRO DURANTE A RECEITA")
                print("=" * 72)
                print(error)
        elif option == "2":
            result = manual_control(cavro_valve, flow_pump_controller)
            if result == "sair":
                close_flow_pump_controller(flow_pump_controller)
                return
        elif option == "3":
            show_recipe()
        elif option == "4":
            try:
                cavro_valve.home()
            except Exception as error:
                print()
                print("=" * 60)
                print("ERRO DURANTE O HOMING")
                print("=" * 60)
                print(error)
        elif option == "5":
            flow_pump_controller = configure_flow_pump(flow_pump_controller)
        elif option in ("q", "quit", "exit"):
            close_flow_pump_controller(flow_pump_controller)
            return
        else:
            print("Opção inválida.")
