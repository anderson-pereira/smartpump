from smartpump.domain.recipes import normalize_recipe_step
from smartpump.settings import RECIPE


def format_time(seconds):
    seconds = max(0, int(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def format_flow_rate(flow_rate):
    """Describe signed flow using the operator-facing convention."""
    if flow_rate is None:
        return "não definida"
    if flow_rate == 0:
        return "0 mL/min (bomba parada)"
    direction = "horário" if flow_rate > 0 else "anti-horário"
    return f"{flow_rate:+g} mL/min ({direction})"


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
            confirmation = input(
                "Executar continuamente até Ctrl+C? [s/N]: "
            ).strip().lower()
            if confirmation in ("s", "sim", "y", "yes"):
                return None
            continue
        if option in ("q", "quit", "exit"):
            return "cancelar"
        print("Opção inválida.")


def show_recipe(recipe_steps=None, recipe_name="Receita programada"):
    if recipe_steps is None:
        recipe_steps = RECIPE

    print()
    print("=" * 72)
    print(recipe_name.upper())
    print("=" * 72)
    total = 0
    for index, step in enumerate(recipe_steps, start=1):
        channel, solution, duration, flow_rate = normalize_recipe_step(step)
        duration_seconds = duration * 60
        total += duration_seconds
        flow_rate_text = format_flow_rate(flow_rate)
        print(
            f"{index:02d}. Canal {channel} | {solution:<22} | {duration:g} min"
            f" | Vazão: {flow_rate_text}"
        )
    print("-" * 72)
    print(f"Tempo total programado: {format_time(total)}")
    print("=" * 72)
