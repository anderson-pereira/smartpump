import math
import time
from datetime import datetime

from config import RECIPE


def format_time(seconds):
    seconds = max(0, int(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def choose_cycling():
    while True:
        print()
        print("=" * 60)
        print("CICLAGEM DA RECEITA")
        print("=" * 60)
        print()
        print("[1] Executar uma vez")
        print("[2] Executar número definido de ciclos")
        print("[3] Executar continuamente")
        print("[Q] Cancelar")
        print()
        option = input("Selecione o modo: ").strip().lower()

        if option == "1":
            return 1
        if option == "2":
            while True:
                value = input("Número de ciclos: ").strip()
                try:
                    cycles = int(value)
                except ValueError:
                    print("Digite um número inteiro.")
                    continue
                if cycles < 1:
                    print("O número de ciclos deve ser maior que zero.")
                    continue
                return cycles
        if option == "3":
            confirmation = input("Executar continuamente até Ctrl+C? [s/N]: ").strip().lower()
            if confirmation in ("s", "sim", "y", "yes"):
                return None
            continue
        if option in ("q", "quit", "exit"):
            return "cancelar"
        print("Opção inválida.")


def show_recipe():
    print()
    print("=" * 72)
    print("RECEITA PROGRAMADA")
    print("=" * 72)
    total = 0
    for index, step in enumerate(RECIPE, start=1):
        channel, solution, duration = step
        duration_seconds = duration * 60
        total += duration_seconds
        print(f"{index:02d}. Canal {channel} | {solution:<22} | {duration:g} min")
    print("-" * 72)
    print(f"Tempo total programado: {format_time(total)}")
    print("=" * 72)


def run_timing(
    step_number,
    total_steps,
    channel,
    solution,
    duration_seconds,
    remaining_after_step,
):
    end_time = time.monotonic() + duration_seconds
    while True:
        now = time.monotonic()
        remaining = max(0, end_time - now)
        total_remaining = remaining + remaining_after_step
        line = (
            f"\rPasso {step_number}/{total_steps} | Canal {channel} | {solution}"
            f" | Etapa: {format_time(math.ceil(remaining))}"
            f" | Total: {format_time(math.ceil(total_remaining))}"
        )
        print(line, end="", flush=True)
        if remaining <= 0:
            break
        time.sleep(min(1.0, remaining))
    print()


def run_recipe(cavro_valve, cycle_count=1, flow_pump_controller=None):
    """Run the configured recipe."""
    total_steps = len(RECIPE)
    if total_steps == 0:
        print("A receita está vazia.")
        return

    durations = [duration * 60 for _, _, duration in RECIPE]
    cycle_duration = sum(durations)
    current_cycle = 1

    print()
    print("=" * 72)
    print("INÍCIO DA RECEITA")
    print("=" * 72)
    print("Horário de início:", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
    if cycle_count is None:
        print("Modo: CICLAGEM CONTÍNUA")
        print("A receita será repetida até ser interrompida com Ctrl+C.")
    else:
        print(f"Número de ciclos: {cycle_count}")
        print(f"Tempo total programado: {format_time(cycle_duration * cycle_count)}")

    while cycle_count is None or current_cycle <= cycle_count:
        print()
        print("#" * 72)
        if cycle_count is None:
            print(f"CICLO {current_cycle}")
        else:
            print(f"CICLO {current_cycle}/{cycle_count}")
        print("#" * 72)

        for index, step in enumerate(RECIPE):
            step_number = index + 1
            channel, solution, duration_minutes = step
            duration_seconds = duration_minutes * 60
            remaining_in_cycle = sum(durations[index + 1:])
            if cycle_count is None:
                total_remaining = None
            else:
                remaining_cycles = cycle_count - current_cycle
                total_remaining = remaining_in_cycle + (remaining_cycles * cycle_duration)

            print()
            print("=" * 72)
            if cycle_count is None:
                print(f"CICLO {current_cycle} | PASSO {step_number}/{total_steps}")
            else:
                print(f"CICLO {current_cycle}/{cycle_count} | PASSO {step_number}/{total_steps}")
            print("=" * 72)
            print(f"Solução : {solution}")
            print(f"Canal   : {channel}")
            print(f"Tempo   : {format_time(duration_seconds)}")
            print()
            print("Selecionando válvula...")
            cavro_valve.select_channel(
                channel,
                show=True,
                before_channel_change=(
                    flow_pump_controller.stop
                    if flow_pump_controller is not None
                    else None
                ),
                after_channel_change=(
                    flow_pump_controller.restart
                    if flow_pump_controller is not None
                    else None
                ),
            )
            print()
            print(f"Temporização iniciada para {solution}.")

            end_time = time.monotonic() + duration_seconds
            while True:
                now = time.monotonic()
                remaining_step = max(0, end_time - now)
                if cycle_count is None:
                    line = (
                        f"\rCiclo {current_cycle} | Passo {step_number}/{total_steps}"
                        f" | Canal {channel} | {solution}"
                        f" | Etapa: {format_time(math.ceil(remaining_step))}"
                    )
                else:
                    current_total_remaining = remaining_step + total_remaining
                    line = (
                        f"\rCiclo {current_cycle}/{cycle_count}"
                        f" | Passo {step_number}/{total_steps} | Canal {channel}"
                        f" | {solution} | Etapa: {format_time(math.ceil(remaining_step))}"
                        f" | Total: {format_time(math.ceil(current_total_remaining))}"
                    )
                print(line, end="", flush=True)
                if remaining_step <= 0:
                    break
                time.sleep(min(1.0, remaining_step))

            print()
            print(f"Passo {step_number} concluído.")

        print()
        print("-" * 72)
        print(f"CICLO {current_cycle} CONCLUÍDO")
        print("-" * 72)
        current_cycle += 1

    print()
    print("=" * 72)
    print("RECEITA CONCLUÍDA")
    print("=" * 72)
    print("Horário de término:", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
