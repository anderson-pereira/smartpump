from __future__ import annotations

import argparse
import math
from pathlib import Path

import uvicorn

from smartpump.application.service import SmartPump
from smartpump.infrastructure.recipes.files import FileRecipeRepository
from smartpump.interfaces.api.app import create_app
from smartpump.interfaces.api.devices import DeviceManager
from smartpump.interfaces.api.runtime import ApiRuntime
from smartpump.settings import (
    DEFAULT_RECIPE_DIRECTORY,
    FLOW_PUMP_BAUD_RATE,
    FLOW_PUMP_SERIAL_PORT,
    PROJECT_ROOT,
    VALVE_BAUD_RATE,
    VALVE_SERIAL_PORT,
)


def positive_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("deve ser maior que zero")
    return number


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Servidor local da API e interface Web SmartPump."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--mock", action="store_true", help="não abre portas seriais")
    parser.add_argument("--time-scale", type=positive_float, default=None)
    parser.add_argument("--valve-port", default=VALVE_SERIAL_PORT)
    parser.add_argument("--pump-port", default=FLOW_PUMP_SERIAL_PORT)
    parser.add_argument("--recipes", type=Path, default=DEFAULT_RECIPE_DIRECTORY)
    parser.add_argument(
        "--api-only",
        action="store_true",
        help="inicia somente a API; indicado ao usar o servidor Vite em desenvolvimento",
    )
    parser.add_argument(
        "--web-dist",
        type=Path,
        default=PROJECT_ROOT / "web" / "dist" / "client",
        help="diretório do build Vite que será servido pela API",
    )
    return parser


def build_runtime(arguments: argparse.Namespace) -> ApiRuntime:
    repository = FileRecipeRepository(arguments.recipes)
    manager = DeviceManager(
        mock_mode=arguments.mock,
        pump_port=arguments.pump_port,
    )
    service = SmartPump(
        manager.valve,
        pump_factory=manager.create_pump,
        recipe_repository=repository,
    )
    manager.bind(service)
    startup_warnings = {}
    try:
        try:
            manager.connect("valve", arguments.valve_port, VALVE_BAUD_RATE)
        except Exception as error:
            if arguments.mock:
                raise
            startup_warnings["valve"] = (
                f"Válvula não conectada na inicialização ({arguments.valve_port}): {error}"
            )
        if arguments.mock:
            manager.connect("pump", arguments.pump_port, FLOW_PUMP_BAUD_RATE)
        return ApiRuntime(
            service,
            mock_mode=arguments.mock,
            time_scale=(arguments.time_scale or 0.01) if arguments.mock else 1.0,
            device_manager=manager,
            startup_warnings=startup_warnings,
        )
    except BaseException:
        service.close()
        manager.close()
        raise


def main(argv=None) -> int:
    parser = build_argument_parser()
    arguments = parser.parse_args(argv)
    if arguments.time_scale is not None and not arguments.mock:
        parser.error("--time-scale exige --mock.")
    if not arguments.api_only and not arguments.web_dist.is_dir():
        parser.error(
            f"build Web não encontrado em {arguments.web_dist}; execute 'npm run build' em web/."
        )

    runtime = build_runtime(arguments)
    app = create_app(
        runtime,
        static_dir=None if arguments.api_only else arguments.web_dist,
    )
    mode = "simulado" if arguments.mock else "hardware"
    interface = "API" if arguments.api_only else "Web"
    print(f"SmartPump {interface} em http://{arguments.host}:{arguments.port} ({mode})")
    for warning in runtime.startup_warnings.values():
        print(f"AVISO: {warning}")
    if runtime.startup_warnings:
        print("Use a página Dispositivos para selecionar a porta e conectar.")
    uvicorn.run(app, host=arguments.host, port=arguments.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
