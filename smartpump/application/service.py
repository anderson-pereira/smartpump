import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Mapping, Optional, Sequence

from smartpump.domain.recipes import (
    ExternalRecipe,
    RecipeDocument,
    RecipeStep,
    normalize_recipe_step,
)
from smartpump.ports.devices import (
    NumericInput,
    PumpCloser,
    PumpController,
    PumpFactory,
    ValveController,
)
from smartpump.ports.recipes import RecipeRepository


UNSPECIFIED_CYCLE_COUNT = object()
EventHandler = Callable[["SmartPumpEvent"], None]


class RecipeRunStopped(RuntimeError):
    """Raised when an interface requests a cooperative recipe stop."""


@dataclass(frozen=True)
class SmartPumpEvent:
    """Structured application event consumed by interfaces such as the CLI."""

    kind: str
    message: str
    data: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SmartPumpStatus:
    """Current device state exposed without leaking driver objects."""

    valve_channel: Optional[str]
    pump_enabled: bool
    pump_running: Optional[bool]


@dataclass(frozen=True)
class ActiveRecipe:
    """Recipe selection owned by the application rather than an interface."""

    steps: tuple[RecipeStep, ...]
    name: str
    cycle_count: Any
    source: str


class SmartPump:
    """Application service coordinating recipes, valve and optional flow pump."""

    def __init__(
        self,
        valve: ValveController,
        pump_factory: Optional[PumpFactory] = None,
        pump_closer: Optional[PumpCloser] = None,
        recipe_repository: Optional[RecipeRepository] = None,
        event_handler: Optional[EventHandler] = None,
        recipe_steps: Optional[Sequence[Sequence[Any]]] = None,
        recipe_name: str = "Receita programada",
        recipe_cycle_count=UNSPECIFIED_CYCLE_COUNT,
        recipe_source: str = "config.py",
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = datetime.now,
    ):
        self._valve: ValveController = valve
        self._pump: Optional[PumpController] = None
        self._pump_factory = pump_factory
        self._pump_closer = pump_closer
        self._recipe_repository = recipe_repository
        self._event_handler = event_handler
        self._active_recipe = ActiveRecipe(
            steps=tuple(
                normalize_recipe_step(step) for step in (recipe_steps or ())
            ),
            name=recipe_name,
            cycle_count=recipe_cycle_count,
            source=recipe_source,
        )
        self._monotonic = monotonic
        self._sleep = sleep
        self._now = now

    @property
    def pump_enabled(self) -> bool:
        return self._pump is not None

    @property
    def active_recipe(self) -> ActiveRecipe:
        return self._active_recipe

    def set_event_handler(
        self,
        event_handler: Optional[EventHandler] = None,
    ) -> None:
        self._event_handler = event_handler

    def _emit(self, kind: str, message: str, **data: Any) -> SmartPumpEvent:
        event = SmartPumpEvent(kind=kind, message=message, data=data)
        if self._event_handler is not None:
            self._event_handler(event)
        return event

    def get_status(self) -> SmartPumpStatus:
        pump = self._pump
        pump_running = pump.is_running() if pump is not None else None
        return SmartPumpStatus(
            valve_channel=self._valve.get_current_channel(),
            pump_enabled=self._pump is not None,
            pump_running=pump_running,
        )

    def get_valve_channel(self) -> Optional[str]:
        return self._valve.get_current_channel()

    def get_valve_status(self) -> Optional[Mapping[str, Any]]:
        return self._valve.get_status()

    def select_channel(self, channel: int) -> bool:
        """Select a channel while preserving the current pump state."""
        pump = self._pump
        pump_was_running = False
        if pump is not None:
            pump_state = pump.is_running()
            if pump_state is None:
                raise RuntimeError(
                    "Não foi possível determinar o estado da bomba. "
                    "A troca de canal foi bloqueada por segurança."
                )
            pump_was_running = pump_state

        self._emit(
            "valve.channel_selecting",
            f"Selecionando canal {channel}.",
            channel=channel,
        )

        def stop_before_change() -> None:
            if pump is None or not pump.stop():
                raise RuntimeError("A bomba não confirmou a parada.")

        def restart_after_change() -> None:
            if pump is None or not pump.restart():
                raise RuntimeError("A bomba não confirmou a retomada.")

        result = self._valve.select_channel(
            channel,
            show=False,
            before_channel_change=(
                stop_before_change
                if pump is not None and pump_was_running
                else None
            ),
            after_channel_change=(
                restart_after_change
                if pump is not None and pump_was_running
                else None
            ),
        )
        self._emit("valve.channel_selected", f"Canal {channel} selecionado.", channel=channel)
        return result

    def home_valve(self) -> bool:
        """Run valve homing after the interface has obtained confirmation."""
        self._emit("valve.homing_started", "Homing da válvula iniciado.")
        result = self._valve.home()
        channel = self._valve.get_current_channel()
        self._emit(
            "valve.homing_completed",
            f"Homing concluído; canal reportado: {channel}.",
            channel=channel,
        )
        return result

    def enable_pump(self) -> PumpController:
        if self._pump is None:
            if self._pump_factory is None:
                raise RuntimeError("Nenhum controlador de bomba foi configurado.")
            self._pump = self._pump_factory()
            self._emit("pump.enabled", "Controle remoto da bomba ativado.")
        return self._pump

    def disable_pump(self) -> None:
        controller = self._pump
        if controller is not None:
            if self._pump_closer is None:
                controller.close()
            else:
                self._pump_closer()
            self._pump = None
            self._emit("pump.disabled", "Controle remoto da bomba desativado.")

    def identify_pump(self) -> Optional[str]:
        return self._require_pump().identify()

    def is_pump_running(self) -> Optional[bool]:
        return self._require_pump().is_running()

    def start_pump(self) -> bool:
        result = self._require_pump().start()
        if result:
            self._emit("pump.started", "Bomba iniciada.")
        return result

    def stop_pump(self) -> bool:
        result = self._require_pump().stop()
        if result:
            self._emit("pump.stopped", "Bomba parada.")
        return result

    def shutdown_pump(self) -> bool:
        result = self._require_pump().shutdown()
        if result:
            self._emit("pump.stopped", "Bomba parada.")
        return result

    def get_pump_speed(self) -> Optional[float]:
        return self._require_pump().get_speed()

    def set_pump_speed(self, speed_rpm: NumericInput) -> bool:
        result = self._require_pump().set_speed(speed_rpm)
        if result:
            self._emit(
                "pump.speed_changed",
                f"Velocidade configurada: {float(speed_rpm):.2f} RPM.",
                speed_rpm=float(speed_rpm),
            )
        return result

    def set_pump_flow_rate(self, flow_rate_ml_min: NumericInput) -> bool:
        result = self._require_pump().set_flow_rate(flow_rate_ml_min)
        if result:
            numeric_flow = float(flow_rate_ml_min)
            self._emit(
                "pump.flow_changed",
                f"Vazão aplicada: {numeric_flow:+g} mL/min.",
                flow_rate_ml_min=numeric_flow,
            )
        return result

    def discover_recipes(self, directory=None):
        return self._require_recipe_repository().discover(directory)

    def get_recipe_document(self, identifier: str) -> RecipeDocument:
        return self._require_recipe_repository().get(identifier)

    def create_recipe(
        self,
        identifier: str,
        data: Mapping[str, Any],
    ) -> RecipeDocument:
        document = self._require_recipe_repository().create(identifier, data)
        self._emit(
            "recipe.created",
            f"Receita criada: {document.recipe.name}.",
            identifier=document.identifier,
            revision=document.revision,
        )
        return document

    def update_recipe(
        self,
        identifier: str,
        data: Mapping[str, Any],
        expected_revision: Optional[str],
    ) -> RecipeDocument:
        document = self._require_recipe_repository().update(
            identifier,
            data,
            expected_revision,
        )
        self._emit(
            "recipe.updated",
            f"Receita atualizada: {document.recipe.name}.",
            identifier=document.identifier,
            revision=document.revision,
        )
        return document

    def delete_recipe(self, identifier: str, expected_revision: str) -> None:
        self._require_recipe_repository().delete(identifier, expected_revision)
        self._emit(
            "recipe.deleted",
            f"Receita excluída: {identifier}.",
            identifier=identifier,
            revision=expected_revision,
        )

    def activate_recipe(self, recipe: ExternalRecipe) -> ActiveRecipe:
        self._active_recipe = ActiveRecipe(
            steps=tuple(recipe.steps),
            name=recipe.name,
            cycle_count=recipe.cycle_count,
            source=recipe.source,
        )
        self._emit(
            "recipe.activated",
            f"Receita ativa alterada para: {recipe.name}.",
            recipe_name=recipe.name,
            source=recipe.source,
        )
        return self._active_recipe

    def configure_active_recipe(
        self,
        steps,
        name,
        cycle_count=UNSPECIFIED_CYCLE_COUNT,
        source="config.py",
    ):
        self._active_recipe = ActiveRecipe(
            steps=tuple(normalize_recipe_step(step) for step in steps),
            name=name,
            cycle_count=cycle_count,
            source=source,
        )
        return self._active_recipe

    def run_active_recipe(
        self,
        cycle_count=UNSPECIFIED_CYCLE_COUNT,
        start_stopped_pump=False,
        time_scale=1.0,
        should_stop: Optional[Callable[[], bool]] = None,
        should_pause: Optional[Callable[[], bool]] = None,
        control_pump: bool = True,
    ):
        recipe = self._active_recipe
        selected_cycles = (
            recipe.cycle_count
            if cycle_count is UNSPECIFIED_CYCLE_COUNT
            else cycle_count
        )
        if selected_cycles is UNSPECIFIED_CYCLE_COUNT:
            raise ValueError("A quantidade de ciclos ainda não foi definida.")
        return self.run_recipe(
            recipe_steps=recipe.steps,
            recipe_name=recipe.name,
            cycle_count=selected_cycles,
            start_stopped_pump=start_stopped_pump,
            time_scale=time_scale,
            should_stop=should_stop,
            should_pause=should_pause,
            control_pump=control_pump,
        )

    def run_recipe(
        self,
        recipe_steps,
        recipe_name,
        cycle_count=1,
        start_stopped_pump=False,
        time_scale=1.0,
        should_stop: Optional[Callable[[], bool]] = None,
        should_pause: Optional[Callable[[], bool]] = None,
        control_pump: bool = True,
    ):
        """Execute a recipe synchronously and report progress through events."""
        try:
            time_scale = float(time_scale)
        except (TypeError, ValueError):
            raise ValueError("A escala de tempo deve ser um número positivo.")
        if not math.isfinite(time_scale) or time_scale <= 0:
            raise ValueError("A escala de tempo deve ser um número positivo.")

        normalized_steps = tuple(normalize_recipe_step(step) for step in recipe_steps)
        if not normalized_steps:
            raise ValueError("A receita está vazia.")

        programmed_durations = tuple(
            duration * 60 for _, _, duration, _ in normalized_steps
        )
        durations = tuple(value * time_scale for value in programmed_durations)
        cycle_duration = sum(durations)

        pump_active = False
        pump_running = False
        pump = self._pump if control_pump else None
        if pump is not None:
            pump_state = pump.is_running()
            if pump_state is None:
                raise RuntimeError("Não foi possível determinar o estado da bomba.")
            pump_active = bool(pump_state or start_stopped_pump)
            pump_running = bool(pump_state)

        if pump_active:
            for step_number, (_, _, _, flow_rate) in enumerate(
                normalized_steps,
                start=1,
            ):
                if flow_rate is None:
                    continue
                try:
                    pump.validate_flow_rate(flow_rate)
                except ValueError as error:
                    raise ValueError(
                        f"Etapa {step_number}: vazão incompatível com a bomba. {error}"
                    )

        stop_requested = should_stop or (lambda: False)
        pause_requested = should_pause or (lambda: False)

        def stop_if_requested() -> None:
            nonlocal pump_running
            if not stop_requested():
                return
            if pump is not None and pump_running:
                pump.stop()
                pump_running = False
            self._emit(
                "recipe.stopped",
                f"Receita interrompida: {recipe_name}.",
                recipe_name=recipe_name,
                stopped_at=self._now(),
            )
            raise RecipeRunStopped(f"Receita interrompida: {recipe_name}.")

        def pause_if_requested(
            flow_rate: Optional[float] = None,
            *,
            resume_pump: bool,
        ) -> float:
            nonlocal pump_running
            if not pause_requested():
                return 0.0

            pump_was_running = pump_running
            if pump is not None and pump_running:
                if not pump.stop():
                    raise RuntimeError("A bomba não confirmou a pausa.")
                pump_running = False

            paused_at = self._monotonic()
            self._emit(
                "recipe.paused",
                f"Receita pausada: {recipe_name}.",
                recipe_name=recipe_name,
                paused_at=self._now(),
            )
            while pause_requested():
                stop_if_requested()
                self._sleep(0.1)

            paused_seconds = max(0.0, self._monotonic() - paused_at)
            if resume_pump and pump is not None and pump_was_running:
                resumed = (
                    pump.restart()
                    if flow_rate is None
                    else pump.set_flow_rate(flow_rate)
                )
                if not resumed:
                    raise RuntimeError("A bomba não confirmou a retomada.")
                pump_running = flow_rate != 0

            self._emit(
                "recipe.resumed",
                f"Receita retomada: {recipe_name}.",
                recipe_name=recipe_name,
                resumed_at=self._now(),
                paused_seconds=paused_seconds,
            )
            return paused_seconds

        stop_if_requested()

        self._emit(
            "recipe.started",
            f"Receita iniciada: {recipe_name}.",
            recipe_name=recipe_name,
            cycle_count=cycle_count,
            started_at=self._now(),
            time_scale=time_scale,
            programmed_duration_seconds=sum(programmed_durations),
        )

        current_cycle = 1
        total_steps = len(normalized_steps)
        while cycle_count is None or current_cycle <= cycle_count:
            stop_if_requested()
            self._emit(
                "recipe.cycle_started",
                f"Ciclo {current_cycle} iniciado.",
                cycle=current_cycle,
                cycle_count=cycle_count,
            )

            for index, step in enumerate(normalized_steps):
                stop_if_requested()
                pause_if_requested(resume_pump=False)
                step_number = index + 1
                channel, solution, duration_minutes, flow_rate = step
                duration_seconds = durations[index]
                remaining_in_cycle = sum(durations[index + 1:])
                remaining_cycles = (
                    0 if cycle_count is None else cycle_count - current_cycle
                )
                remaining_after_step = (
                    None
                    if cycle_count is None
                    else remaining_in_cycle + remaining_cycles * cycle_duration
                )

                self._emit(
                    "recipe.step_started",
                    f"Etapa {step_number}: {solution} no canal {channel}.",
                    cycle=current_cycle,
                    cycle_count=cycle_count,
                    step=step_number,
                    total_steps=total_steps,
                    channel=channel,
                    solution=solution,
                    duration_minutes=duration_minutes,
                    duration_seconds=duration_seconds,
                    flow_rate_ml_min=flow_rate,
                )

                if pump_active:
                    if pump is None:
                        raise RuntimeError("O controle remoto da bomba foi desativado.")
                    if pump_running and not pump.stop():
                        raise RuntimeError("A bomba não confirmou a parada.")
                    pump_running = False
                    self._valve.select_channel(channel, show=False)
                    if flow_rate is None:
                        if not pump.restart():
                            raise RuntimeError("A bomba não confirmou a partida.")
                        pump_running = True
                    else:
                        if not pump.set_flow_rate(flow_rate):
                            raise RuntimeError(
                                "A bomba não confirmou a vazão, o sentido ou o estado."
                            )
                        pump_running = flow_rate != 0
                else:
                    self._valve.select_channel(channel, show=False)

                self._emit(
                    "recipe.channel_selected",
                    f"Canal {channel} selecionado para {solution}.",
                    channel=channel,
                    solution=solution,
                    step=step_number,
                )

                stop_if_requested()

                end_time = self._monotonic() + duration_seconds
                while True:
                    stop_if_requested()
                    end_time += pause_if_requested(
                        flow_rate,
                        resume_pump=True,
                    )
                    remaining_step = max(0, end_time - self._monotonic())
                    total_remaining = (
                        None
                        if remaining_after_step is None
                        else remaining_step + remaining_after_step
                    )
                    self._emit(
                        "recipe.progress",
                        "Progresso da receita atualizado.",
                        cycle=current_cycle,
                        cycle_count=cycle_count,
                        step=step_number,
                        total_steps=total_steps,
                        channel=channel,
                        solution=solution,
                        remaining_step_seconds=remaining_step,
                        remaining_total_seconds=total_remaining,
                    )
                    if remaining_step <= 0:
                        break
                    poll_interval = (
                        0.1
                        if should_stop is not None or should_pause is not None
                        else 1.0
                    )
                    self._sleep(min(poll_interval, remaining_step))

                self._emit(
                    "recipe.step_completed",
                    f"Etapa {step_number} concluída.",
                    cycle=current_cycle,
                    step=step_number,
                )

            self._emit(
                "recipe.cycle_completed",
                f"Ciclo {current_cycle} concluído.",
                cycle=current_cycle,
            )
            current_cycle += 1

        self._emit(
            "recipe.completed",
            f"Receita concluída: {recipe_name}.",
            recipe_name=recipe_name,
            completed_at=self._now(),
        )

    def close(self) -> None:
        self.disable_pump()

    def _require_pump(self) -> PumpController:
        pump = self._pump
        if pump is None:
            raise RuntimeError("O controle remoto da bomba está desativado.")
        return pump

    def _require_recipe_repository(self) -> RecipeRepository:
        repository = self._recipe_repository
        if repository is None:
            raise RuntimeError("Nenhum repositório de receitas foi configurado.")
        return repository
