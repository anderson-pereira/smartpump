from __future__ import annotations

import threading
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional

from smartpump.application.service import RecipeRunStopped, SmartPump, SmartPumpEvent
from smartpump.domain.recipes import RecipeConflictError, RecipeDocument

if TYPE_CHECKING:
    from smartpump.interfaces.api.devices import DeviceManager


ACTIVE_RUN_STATES = {"starting", "running", "paused", "stopping"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def public_recipe_id(identifier: str) -> str:
    return identifier[:-5] if identifier.lower().endswith(".json") else identifier


def repository_recipe_id(identifier: str) -> str:
    return identifier if identifier.lower().endswith(".json") else f"{identifier}.json"


def recipe_document_payload(document: RecipeDocument) -> dict[str, Any]:
    recipe = document.recipe
    return {
        "id": public_recipe_id(document.identifier),
        "revision": document.revision,
        "name": recipe.name,
        "description": recipe.description,
        "cycles": recipe.cycle_count,
        "executable_steps": len(recipe.steps),
        "duration_minutes_per_cycle": sum(step[2] for step in recipe.steps),
        "recipe": deepcopy(dict(document.data)),
    }


@dataclass
class RunRecord:
    id: str
    recipe_id: str
    recipe_revision: str
    recipe_name: str
    pump_mode: str
    requested_cycles: Optional[int]
    state: str = "starting"
    created_at: str = field(default_factory=utc_now)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    progress: dict[str, Any] = field(default_factory=dict)
    stop_event: threading.Event = field(default_factory=threading.Event, repr=False)
    pause_event: threading.Event = field(default_factory=threading.Event, repr=False)

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "recipe_id": self.recipe_id,
            "recipe_revision": self.recipe_revision,
            "recipe_name": self.recipe_name,
            "pump_mode": self.pump_mode,
            "requested_cycles": self.requested_cycles,
            "state": self.state,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "progress": deepcopy(self.progress),
        }


class ExecutionManager:
    """Owns the single background recipe execution allowed by the device."""

    def __init__(self, service: SmartPump, time_scale: float = 1.0):
        self._service = service
        self._time_scale = time_scale
        self._lock = threading.RLock()
        self._runs: dict[str, RunRecord] = {}
        self._workers: dict[str, threading.Thread] = {}
        self._current_id: Optional[str] = None
        self._service.set_event_handler(self.handle_event)

    def start(
        self,
        document: RecipeDocument,
        *,
        cycles: Optional[int],
        pump_mode: str,
        start_stopped_pump: bool,
    ) -> dict[str, Any]:
        with self._lock:
            current = self._current_record()
            if current is not None and current.state in ACTIVE_RUN_STATES:
                raise RuntimeError("Já existe uma receita em execução.")

            self._service.activate_recipe(document.recipe)
            if pump_mode == "controlled" and not self._service.pump_enabled:
                self._service.enable_pump()

            record = RunRecord(
                id=str(uuid.uuid4()),
                recipe_id=public_recipe_id(document.identifier),
                recipe_revision=document.revision,
                recipe_name=document.recipe.name,
                pump_mode=pump_mode,
                requested_cycles=cycles,
            )
            self._runs[record.id] = record
            self._current_id = record.id

            worker = threading.Thread(
                target=self._run,
                args=(record, start_stopped_pump),
                daemon=True,
                name=f"smartpump-run-{record.id[:8]}",
            )
            self._workers[record.id] = worker
            worker.start()
            return record.payload()

    def _run(self, record: RunRecord, start_stopped_pump: bool) -> None:
        try:
            self._service.run_active_recipe(
                cycle_count=record.requested_cycles,
                start_stopped_pump=start_stopped_pump,
                time_scale=self._time_scale,
                should_stop=record.stop_event.is_set,
                should_pause=record.pause_event.is_set,
                control_pump=record.pump_mode == "controlled",
            )
            with self._lock:
                record.state = "completed"
        except RecipeRunStopped:
            with self._lock:
                record.state = "stopped"
        except Exception as error:
            with self._lock:
                record.state = "failed"
                record.error = str(error)
        finally:
            if record.pump_mode == "controlled" and self._service.pump_enabled:
                try:
                    self._service.stop_pump()
                except Exception as error:
                    with self._lock:
                        if record.error is None:
                            record.error = f"Falha ao parar a bomba: {error}"
                            record.state = "failed"
            with self._lock:
                record.finished_at = utc_now()

    def stop(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                raise KeyError(run_id)
            if record.state in ACTIVE_RUN_STATES:
                record.state = "stopping"
                record.stop_event.set()
            return record.payload()

    def pause(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                raise KeyError(run_id)
            if record.state not in {"starting", "running"}:
                raise RuntimeError("Somente uma receita em execução pode ser pausada.")
            record.pause_event.set()
            record.state = "paused"
            return record.payload()

    def resume(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                raise KeyError(run_id)
            if record.state != "paused":
                raise RuntimeError("Somente uma receita pausada pode ser retomada.")
            record.pause_event.clear()
            record.state = "running"
            return record.payload()

    def get(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                raise KeyError(run_id)
            return record.payload()

    def current(self) -> Optional[dict[str, Any]]:
        with self._lock:
            record = self._current_record()
            return None if record is None else record.payload()

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [record.payload() for record in reversed(tuple(self._runs.values()))]

    def active(self) -> bool:
        with self._lock:
            record = self._current_record()
            return record is not None and record.state in ACTIVE_RUN_STATES

    def shutdown(self, timeout: float = 2.0) -> None:
        with self._lock:
            record = self._current_record()
            worker = None if record is None else self._workers.get(record.id)
            if record is not None and record.state in ACTIVE_RUN_STATES:
                record.state = "stopping"
                record.stop_event.set()
        if worker is not None and worker.is_alive():
            worker.join(timeout=timeout)

    def handle_event(self, event: SmartPumpEvent) -> None:
        with self._lock:
            record = self._current_record()
            if record is None:
                return
            if event.kind == "recipe.started":
                record.state = "paused" if record.pause_event.is_set() else "running"
                record.started_at = utc_now()
            elif event.kind == "recipe.paused":
                record.state = "paused"
            elif event.kind == "recipe.resumed":
                record.state = "running"
            if event.kind.startswith("recipe."):
                data = {
                    key: value.isoformat() if isinstance(value, datetime) else value
                    for key, value in event.data.items()
                }
                record.progress.update(data)
                record.progress["event"] = event.kind
                record.progress["message"] = event.message
                record.progress["updated_at"] = utc_now()

    def _current_record(self) -> Optional[RunRecord]:
        return None if self._current_id is None else self._runs.get(self._current_id)


class ApiRuntime:
    """Interface-neutral state and orchestration used by the HTTP adapter."""

    def __init__(
        self,
        service: SmartPump,
        *,
        mock_mode: bool,
        time_scale: float = 1.0,
        on_close: Optional[Callable[[], None]] = None,
        device_manager: Optional["DeviceManager"] = None,
        startup_warnings: Optional[Mapping[str, str]] = None,
    ):
        self.service = service
        self.mock_mode = mock_mode
        self._on_close = on_close
        self.device_manager = device_manager
        self.startup_warnings = dict(startup_warnings or {})
        self.executions = ExecutionManager(service, time_scale=time_scale)

    def status(self) -> dict[str, Any]:
        device = self.service.get_status()
        connections = self.device_manager.status() if self.device_manager else None
        speed = None
        if device.pump_enabled:
            try:
                speed = self.service.get_pump_speed()
            except Exception:
                speed = None
        alerts = []
        if connections is not None:
            for device_name, message in self.startup_warnings.items():
                if not connections.get(device_name, {}).get("connected", False):
                    alerts.append(
                        {
                            "kind": "connection",
                            "device": device_name,
                            "message": message,
                        }
                    )
        return {
            "mode": "mock" if self.mock_mode else "hardware",
            "valve": {
                "connected": connections["valve"]["connected"] if connections else True,
                "port": connections["valve"]["port"] if connections else None,
                "channel": device.valve_channel,
            },
            "pump": {
                "connected": connections["pump"]["connected"] if connections else device.pump_enabled,
                "port": connections["pump"]["port"] if connections else None,
                "running": device.pump_running,
                "speed_rpm": speed,
            },
            "run": self.executions.current(),
            "alerts": alerts,
        }

    def list_recipes(self) -> dict[str, Any]:
        catalog = self.service.discover_recipes()
        documents = []
        for recipe in catalog.recipes:
            documents.append(recipe_document_payload(self.service.get_recipe_document(recipe.source.rsplit("\\", 1)[-1].rsplit("/", 1)[-1])))
        return {
            "items": documents,
            "errors": [
                {"source": source, "message": message}
                for source, message in catalog.errors
            ],
        }

    def get_recipe(self, recipe_id: str) -> RecipeDocument:
        return self.service.get_recipe_document(repository_recipe_id(recipe_id))

    def create_recipe(self, recipe_id: str, data: Mapping[str, Any]) -> RecipeDocument:
        return self.service.create_recipe(repository_recipe_id(recipe_id), data)

    def update_recipe(
        self,
        recipe_id: str,
        data: Mapping[str, Any],
        expected_revision: Optional[str],
    ) -> RecipeDocument:
        if not expected_revision:
            raise RecipeConflictError("Informe a revisão lida antes de salvar.")
        return self.service.update_recipe(
            repository_recipe_id(recipe_id), data, expected_revision
        )

    def delete_recipe(self, recipe_id: str, expected_revision: Optional[str]) -> None:
        if not expected_revision:
            raise RecipeConflictError("Informe a revisão lida antes de excluir.")
        self.service.delete_recipe(repository_recipe_id(recipe_id), expected_revision)

    def ensure_manual_control_available(self) -> None:
        if self.executions.active():
            raise RuntimeError(
                "O controle manual fica bloqueado durante a execução de uma receita."
            )

    def connect_device(self, device: str, port: str, baud_rate: int) -> dict[str, Any]:
        self.ensure_manual_control_available()
        if self.device_manager is None:
            raise RuntimeError("A seleção dinâmica de portas não está configurada.")
        self.device_manager.connect(device, port, baud_rate)
        self.startup_warnings.pop(device, None)
        return self.status()

    def disconnect_device(self, device: str) -> dict[str, Any]:
        self.ensure_manual_control_available()
        if self.device_manager is None:
            raise RuntimeError("A seleção dinâmica de portas não está configurada.")
        self.device_manager.disconnect(device)
        return self.status()

    def manual_command(self, action: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
        self.ensure_manual_control_available()
        if action == "valve.select_channel":
            self.service.select_channel(int(parameters["channel"]))
        elif action == "valve.home":
            self.service.home_valve()
        elif action == "pump.start":
            if not self.service.pump_enabled:
                self.service.enable_pump()
            self.service.start_pump()
        elif action == "pump.stop":
            self.service.stop_pump()
        elif action == "pump.set_flow_rate":
            if not self.service.pump_enabled:
                self.service.enable_pump()
            self.service.set_pump_flow_rate(parameters["flow_rate_ml_min"])
        else:
            raise ValueError(f"Comando manual desconhecido: {action}")
        return self.status()

    def close(self) -> None:
        self.executions.shutdown()
        self.service.close()
        if self.device_manager is not None:
            self.device_manager.close()
        if self._on_close is not None:
            self._on_close()
