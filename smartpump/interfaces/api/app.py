from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from threading import RLock
from typing import Any, Literal, Optional

from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from serial.tools import list_ports

from smartpump.domain.recipes import (
    RecipeAlreadyExistsError,
    RecipeConfigError,
    RecipeConflictError,
    RecipeNotFoundError,
    parse_recipe_config,
)
from smartpump.interfaces.api.runtime import ApiRuntime, recipe_document_payload


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConfirmationRequest(StrictModel):
    method: Literal["POST", "DELETE"]
    path: str = Field(pattern=r"^/api/v1/")
    body: dict[str, Any] = Field(default_factory=dict)


class ManualCommandRequest(StrictModel):
    action: Literal[
        "valve.select_channel",
        "valve.home",
        "pump.start",
        "pump.stop",
        "pump.set_flow_rate",
    ]
    parameters: dict[str, Any] = Field(default_factory=dict)


class StartRunRequest(StrictModel):
    recipe_id: str
    recipe_revision: str
    pump_mode: Literal["controlled", "external", "disabled"] = "controlled"
    cycles: Optional[int] = Field(default=1, ge=1)
    start_stopped_pump: bool = False


class StopRunRequest(StrictModel):
    reason: str = "Interrupção solicitada pelo operador"


class RecipeWriteRequest(StrictModel):
    id: Optional[str] = None
    recipe: dict[str, Any]


class DeviceConnectionRequest(StrictModel):
    port: str = Field(min_length=1)
    baud_rate: int = Field(default=9600, gt=0)


class ConfirmationStore:
    def __init__(self, ttl_seconds: float = 60.0):
        self._ttl_seconds = ttl_seconds
        self._tokens: dict[str, tuple[float, str]] = {}
        self._lock = RLock()

    @staticmethod
    def _fingerprint(method: str, path: str, body: dict[str, Any]) -> str:
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(f"{method.upper()}\n{path}\n{canonical}".encode()).hexdigest()

    def prepare(self, method: str, path: str, body: dict[str, Any]) -> tuple[str, float]:
        token = str(uuid.uuid4())
        expires_at = time.time() + self._ttl_seconds
        fingerprint = self._fingerprint(method, path, body)
        with self._lock:
            self._tokens[token] = (expires_at, fingerprint)
        return token, expires_at

    def consume(self, token: Optional[str], method: str, path: str, body: dict[str, Any]) -> None:
        if not token:
            raise HTTPException(
                status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                detail="Confirme a ação antes de enviá-la ao equipamento.",
            )
        with self._lock:
            item = self._tokens.pop(token, None)
        if item is None:
            raise HTTPException(status_code=403, detail="Confirmação inválida ou já utilizada.")
        expires_at, expected = item
        if time.time() > expires_at:
            raise HTTPException(status_code=403, detail="A confirmação expirou.")
        actual = self._fingerprint(method, path, body)
        if actual != expected:
            raise HTTPException(
                status_code=403,
                detail="A confirmação não corresponde à ação solicitada.",
            )


class IdempotencyStore:
    def __init__(self):
        self._values: dict[str, tuple[str, int, dict[str, Any]]] = {}
        self._lock = RLock()

    @staticmethod
    def fingerprint(path: str, body: dict[str, Any]) -> str:
        value = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(f"{path}\n{value}".encode()).hexdigest()

    def get(self, key: Optional[str], path: str, body: dict[str, Any]) -> Optional[tuple[int, dict[str, Any]]]:
        if not key:
            return None
        fingerprint = self.fingerprint(path, body)
        with self._lock:
            previous = self._values.get(key)
        if previous is None:
            return None
        old_fingerprint, code, payload = previous
        if old_fingerprint != fingerprint:
            raise HTTPException(
                status_code=409,
                detail="A chave de idempotência já foi usada com outra requisição.",
            )
        return code, payload

    def put(self, key: Optional[str], path: str, body: dict[str, Any], code: int, payload: dict[str, Any]) -> None:
        if not key:
            return
        with self._lock:
            self._values[key] = (self.fingerprint(path, body), code, payload)


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return slug or "receita"


def strip_etag(value: Optional[str]) -> Optional[str]:
    return value.strip().strip('W/').strip('"') if value else None


def create_app(runtime: ApiRuntime, static_dir: Optional[Path] = None) -> FastAPI:
    confirmations = ConfirmationStore()
    idempotency = IdempotencyStore()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        runtime.close()

    app = FastAPI(
        title="SmartPump API",
        version="1.0.0",
        description="API local para operação da válvula, bomba e receitas.",
        lifespan=lifespan,
    )
    app.state.runtime = runtime

    @app.exception_handler(RecipeNotFoundError)
    async def recipe_not_found(_: Request, error: RecipeNotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(RecipeAlreadyExistsError)
    async def recipe_exists(_: Request, error: RecipeAlreadyExistsError):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(RecipeConflictError)
    async def recipe_conflict(_: Request, error: RecipeConflictError):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(RecipeConfigError)
    async def recipe_invalid(_: Request, error: RecipeConfigError):
        return JSONResponse(status_code=422, content={"detail": str(error)})

    @app.exception_handler(RequestValidationError)
    async def request_invalid(_: Request, error: RequestValidationError):
        return JSONResponse(status_code=422, content={"detail": error.errors()})

    @app.exception_handler(KeyError)
    async def key_not_found(_: Request, error: KeyError):
        return JSONResponse(status_code=404, content={"detail": f"Recurso não encontrado: {error.args[0]}"})

    @app.exception_handler(ValueError)
    async def value_invalid(_: Request, error: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(error)})

    @app.exception_handler(RuntimeError)
    async def operation_conflict(_: Request, error: RuntimeError):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.get("/api/v1/status")
    def get_status():
        return runtime.status()

    @app.get("/api/v1/serial-ports")
    def get_serial_ports():
        if runtime.mock_mode:
            return {
                "items": [
                    {"device": "MOCK-VALVE", "description": "Válvula Cavro simulada", "manufacturer": "SmartPump", "vid": None, "pid": None},
                    {"device": "MOCK-PUMP", "description": "Bomba Ismatec simulada", "manufacturer": "SmartPump", "vid": None, "pid": None},
                ]
            }
        return {
            "items": [
                {
                    "device": port.device,
                    "description": port.description,
                    "manufacturer": port.manufacturer,
                    "vid": port.vid,
                    "pid": port.pid,
                }
                for port in list_ports.comports()
            ]
        }

    @app.post("/api/v1/devices/{device}/connect")
    def connect_device(
        device: Literal["valve", "pump"],
        payload: DeviceConnectionRequest,
        request: Request,
        confirmation_token: Optional[str] = Header(default=None, alias="X-Confirmation-Token"),
    ):
        body = payload.model_dump()
        confirmations.consume(confirmation_token, "POST", request.url.path, body)
        return runtime.connect_device(device, payload.port, payload.baud_rate)

    @app.post("/api/v1/devices/{device}/disconnect")
    def disconnect_device(
        device: Literal["valve", "pump"],
        request: Request,
        confirmation_token: Optional[str] = Header(default=None, alias="X-Confirmation-Token"),
    ):
        confirmations.consume(confirmation_token, "POST", request.url.path, {})
        return runtime.disconnect_device(device)

    @app.get("/api/v1/recipes")
    def list_recipes():
        return runtime.list_recipes()

    @app.post("/api/v1/recipes", status_code=201)
    def create_recipe(payload: RecipeWriteRequest, response: Response):
        recipe_id = payload.id or slugify(str(payload.recipe.get("name", "receita")))
        document = runtime.create_recipe(recipe_id, payload.recipe)
        response.headers["ETag"] = f'"{document.revision}"'
        return recipe_document_payload(document)

    @app.post("/api/v1/recipes/preview")
    def preview_recipe(payload: RecipeWriteRequest):
        recipe = parse_recipe_config(payload.recipe)
        return {
            "valid": True,
            "name": recipe.name,
            "cycles": recipe.cycle_count,
            "executable_steps": len(recipe.steps),
            "duration_minutes_per_cycle": sum(step[2] for step in recipe.steps),
        }

    @app.get("/api/v1/recipes/{recipe_id}")
    def get_recipe(recipe_id: str, response: Response):
        document = runtime.get_recipe(recipe_id)
        response.headers["ETag"] = f'"{document.revision}"'
        return recipe_document_payload(document)

    @app.put("/api/v1/recipes/{recipe_id}")
    def update_recipe(
        recipe_id: str,
        payload: RecipeWriteRequest,
        response: Response,
        if_match: Optional[str] = Header(default=None, alias="If-Match"),
    ):
        document = runtime.update_recipe(recipe_id, payload.recipe, strip_etag(if_match))
        response.headers["ETag"] = f'"{document.revision}"'
        return recipe_document_payload(document)

    @app.delete("/api/v1/recipes/{recipe_id}", status_code=204)
    def delete_recipe(
        recipe_id: str,
        if_match: Optional[str] = Header(default=None, alias="If-Match"),
    ):
        runtime.delete_recipe(recipe_id, strip_etag(if_match))
        return Response(status_code=204)

    @app.post("/api/v1/control/confirmations", status_code=201)
    def prepare_confirmation(payload: ConfirmationRequest):
        token, expires_at = confirmations.prepare(payload.method, payload.path, payload.body)
        return {"token": token, "expires_at": expires_at}

    @app.post("/api/v1/control/commands")
    def manual_command(
        payload: ManualCommandRequest,
        request: Request,
        confirmation_token: Optional[str] = Header(default=None, alias="X-Confirmation-Token"),
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ):
        body = payload.model_dump()
        path = request.url.path
        previous = idempotency.get(idempotency_key, path, body)
        if previous is not None:
            return JSONResponse(status_code=previous[0], content=previous[1])
        confirmations.consume(confirmation_token, "POST", path, body)
        result = runtime.manual_command(payload.action, payload.parameters)
        idempotency.put(idempotency_key, path, body, 200, result)
        return result

    @app.get("/api/v1/runs")
    def list_runs():
        return {"items": runtime.executions.list()}

    @app.get("/api/v1/runs/current")
    def current_run():
        current = runtime.executions.current()
        if current is None:
            raise HTTPException(status_code=404, detail="Nenhuma execução foi iniciada.")
        return current

    @app.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str):
        return runtime.executions.get(run_id)

    @app.post("/api/v1/runs", status_code=202)
    def start_run(
        payload: StartRunRequest,
        request: Request,
        confirmation_token: Optional[str] = Header(default=None, alias="X-Confirmation-Token"),
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ):
        body = payload.model_dump()
        path = request.url.path
        previous = idempotency.get(idempotency_key, path, body)
        if previous is not None:
            return JSONResponse(status_code=previous[0], content=previous[1])
        confirmations.consume(confirmation_token, "POST", path, body)
        document = runtime.get_recipe(payload.recipe_id)
        if document.revision != payload.recipe_revision:
            raise RecipeConflictError(
                "A receita mudou desde a seleção; revise-a antes de iniciar."
            )
        result = runtime.executions.start(
            document,
            cycles=payload.cycles,
            pump_mode=payload.pump_mode,
            start_stopped_pump=payload.start_stopped_pump,
        )
        idempotency.put(idempotency_key, path, body, 202, result)
        return result

    @app.post("/api/v1/runs/{run_id}/stop", status_code=202)
    def stop_run(
        run_id: str,
        payload: StopRunRequest,
        request: Request,
        confirmation_token: Optional[str] = Header(default=None, alias="X-Confirmation-Token"),
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ):
        body = payload.model_dump()
        path = request.url.path
        previous = idempotency.get(idempotency_key, path, body)
        if previous is not None:
            return JSONResponse(status_code=previous[0], content=previous[1])
        confirmations.consume(confirmation_token, "POST", path, body)
        result = runtime.executions.stop(run_id)
        idempotency.put(idempotency_key, path, body, 202, result)
        return result

    @app.post("/api/v1/runs/{run_id}/pause", status_code=202)
    def pause_run(
        run_id: str,
        payload: StopRunRequest,
        request: Request,
        confirmation_token: Optional[str] = Header(default=None, alias="X-Confirmation-Token"),
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ):
        body = payload.model_dump()
        path = request.url.path
        previous = idempotency.get(idempotency_key, path, body)
        if previous is not None:
            return JSONResponse(status_code=previous[0], content=previous[1])
        confirmations.consume(confirmation_token, "POST", path, body)
        result = runtime.executions.pause(run_id)
        idempotency.put(idempotency_key, path, body, 202, result)
        return result

    @app.post("/api/v1/runs/{run_id}/resume", status_code=202)
    def resume_run(
        run_id: str,
        payload: StopRunRequest,
        request: Request,
        confirmation_token: Optional[str] = Header(default=None, alias="X-Confirmation-Token"),
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ):
        body = payload.model_dump()
        path = request.url.path
        previous = idempotency.get(idempotency_key, path, body)
        if previous is not None:
            return JSONResponse(status_code=previous[0], content=previous[1])
        confirmations.consume(confirmation_token, "POST", path, body)
        result = runtime.executions.resume(run_id)
        idempotency.put(idempotency_key, path, body, 202, result)
        return result

    resolved_static = Path(static_dir).resolve() if static_dir is not None else None
    if resolved_static is not None and resolved_static.is_dir():
        assets = resolved_static / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{resource_path:path}", include_in_schema=False)
        def serve_web(resource_path: str):
            if resource_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Endpoint não encontrado.")
            candidate = (resolved_static / resource_path).resolve()
            if candidate != resolved_static and resolved_static not in candidate.parents:
                raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
            if resource_path and candidate.is_file():
                return FileResponse(candidate)
            index = resolved_static / "index.html"
            if not index.is_file():
                raise HTTPException(status_code=404, detail="Interface Web não compilada.")
            return FileResponse(index)

    return app
