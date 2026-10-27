import json
import tempfile
import time
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from smartpump.application.service import SmartPump
from smartpump.infrastructure.recipes.files import FileRecipeRepository
from smartpump.interfaces.api.app import create_app
from smartpump.interfaces.api.cli import build_runtime
from smartpump.interfaces.api.devices import DeviceManager
from smartpump.interfaces.api.runtime import ApiRuntime


RECIPE = {
    "schema_version": 1,
    "name": "Receita da API",
    "description": "Receita de teste",
    "cycles": 1,
    "steps": [
        {
            "channel": 2,
            "solution": "H2O",
            "duration_minutes": 0.01,
            "flow_rate_ml_min": 0.4,
        }
    ],
}


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.root = root
        recipes = root / "recipes"
        recipes.mkdir()
        (recipes / "test.json").write_text(
            json.dumps(RECIPE, ensure_ascii=False), encoding="utf-8"
        )
        static = root / "web"
        static.mkdir()
        (static / "index.html").write_text("<h1>SmartPump</h1>", encoding="utf-8")

        manager = DeviceManager(mock_mode=True, pump_port="MOCK-PUMP")
        service = SmartPump(
            manager.valve,
            pump_factory=manager.create_pump,
            recipe_repository=FileRecipeRepository(recipes),
        )
        manager.bind(service)
        manager.connect("valve", "MOCK-VALVE", 9600)
        manager.connect("pump", "MOCK-PUMP", 9600)
        runtime = ApiRuntime(
            service,
            mock_mode=True,
            time_scale=0.001,
            device_manager=manager,
        )
        self.client_context = TestClient(create_app(runtime, static_dir=static))
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.temporary.cleanup()

    def confirm(self, path, body):
        response = self.client.post(
            "/api/v1/control/confirmations",
            json={"method": "POST", "path": path, "body": body},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["token"]

    def test_same_application_serves_api_and_spa(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertIn("SmartPump", self.client.get("/recipes/test").text)
        status_response = self.client.get("/api/v1/status")
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.json()["mode"], "mock")

    def test_hardware_server_starts_disconnected_when_default_valve_fails(self):
        arguments = Namespace(
            recipes=self.root / "recipes",
            mock=False,
            pump_port="COM21",
            valve_port="COM22",
            time_scale=None,
        )
        with patch(
            "smartpump.interfaces.api.cli.DeviceManager.connect",
            side_effect=RuntimeError("porta inexistente"),
        ):
            runtime = build_runtime(arguments)
        try:
            status_payload = runtime.status()
            self.assertFalse(status_payload["valve"]["connected"])
            self.assertEqual(status_payload["alerts"][0]["device"], "valve")
            self.assertIn("COM22", status_payload["alerts"][0]["message"])
        finally:
            runtime.close()

    def test_recipe_crud_uses_revision_for_concurrency(self):
        listing = self.client.get("/api/v1/recipes").json()
        self.assertEqual([item["id"] for item in listing["items"]], ["test"])

        current = self.client.get("/api/v1/recipes/test")
        revision = current.json()["revision"]
        updated = dict(RECIPE, description="Atualizada")
        response = self.client.put(
            "/api/v1/recipes/test",
            headers={"If-Match": f'"{revision}"'},
            json={"recipe": updated},
        )
        self.assertEqual(response.status_code, 200, response.text)
        new_revision = response.json()["revision"]
        self.assertNotEqual(revision, new_revision)

        conflict = self.client.put(
            "/api/v1/recipes/test",
            headers={"If-Match": f'"{revision}"'},
            json={"recipe": RECIPE},
        )
        self.assertEqual(conflict.status_code, 409)

        deleted = self.client.delete(
            "/api/v1/recipes/test", headers={"If-Match": f'"{new_revision}"'}
        )
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get("/api/v1/recipes/test").status_code, 404)

    def test_physical_commands_require_matching_single_use_confirmation(self):
        body = {
            "action": "valve.select_channel",
            "parameters": {"channel": 4},
        }
        path = "/api/v1/control/commands"
        self.assertEqual(self.client.post(path, json=body).status_code, 428)

        token = self.confirm(path, body)
        response = self.client.post(
            path,
            json=body,
            headers={"X-Confirmation-Token": token, "Idempotency-Key": "manual-1"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["valve"]["channel"], "4")

        reuse = self.client.post(
            path,
            json=body,
            headers={"X-Confirmation-Token": token, "Idempotency-Key": "manual-2"},
        )
        self.assertEqual(reuse.status_code, 403)

    def test_devices_can_be_disconnected_and_reconnected_from_selected_ports(self):
        disconnect_path = "/api/v1/devices/pump/disconnect"
        token = self.confirm(disconnect_path, {})
        disconnected = self.client.post(
            disconnect_path, headers={"X-Confirmation-Token": token}
        )
        self.assertEqual(disconnected.status_code, 200, disconnected.text)
        self.assertFalse(disconnected.json()["pump"]["connected"])

        connect_path = "/api/v1/devices/pump/connect"
        body = {"port": "MOCK-NEW", "baud_rate": 9600}
        token = self.confirm(connect_path, body)
        connected = self.client.post(
            connect_path, json=body, headers={"X-Confirmation-Token": token}
        )
        self.assertEqual(connected.status_code, 200, connected.text)
        self.assertEqual(connected.json()["pump"]["port"], "MOCK-NEW")

    def test_recipe_execution_runs_in_background(self):
        recipe = self.client.get("/api/v1/recipes/test").json()
        body = {
            "recipe_id": "test",
            "recipe_revision": recipe["revision"],
            "pump_mode": "controlled",
            "cycles": 1,
            "start_stopped_pump": True,
        }
        path = "/api/v1/runs"
        token = self.confirm(path, body)
        started = self.client.post(
            path,
            json=body,
            headers={"X-Confirmation-Token": token, "Idempotency-Key": "run-1"},
        )
        self.assertEqual(started.status_code, 202, started.text)
        run_id = started.json()["id"]

        deadline = time.monotonic() + 2
        state = None
        while time.monotonic() < deadline:
            state = self.client.get(f"/api/v1/runs/{run_id}").json()["state"]
            if state not in {"starting", "running", "stopping"}:
                break
            time.sleep(0.01)
        self.assertEqual(state, "completed")
        self.assertFalse(self.client.get("/api/v1/status").json()["pump"]["running"])

    def test_recipe_can_be_paused_and_resumed(self):
        recipe_response = self.client.get("/api/v1/recipes/test")
        recipe = recipe_response.json()
        long_recipe = dict(RECIPE)
        long_recipe["steps"] = [dict(RECIPE["steps"][0], duration_minutes=10)]
        updated = self.client.put(
            "/api/v1/recipes/test",
            headers={"If-Match": f'"{recipe["revision"]}"'},
            json={"recipe": long_recipe},
        ).json()
        body = {
            "recipe_id": "test",
            "recipe_revision": updated["revision"],
            "pump_mode": "controlled",
            "cycles": 1,
            "start_stopped_pump": True,
        }
        start_path = "/api/v1/runs"
        started = self.client.post(
            start_path,
            json=body,
            headers={
                "X-Confirmation-Token": self.confirm(start_path, body),
                "Idempotency-Key": "pause-run",
            },
        )
        self.assertEqual(started.status_code, 202, started.text)
        run_id = started.json()["id"]

        pause_path = f"/api/v1/runs/{run_id}/pause"
        action = {"reason": "Teste de pausa"}
        paused = self.client.post(
            pause_path,
            json=action,
            headers={
                "X-Confirmation-Token": self.confirm(pause_path, action),
                "Idempotency-Key": "pause-1",
            },
        )
        self.assertEqual(paused.status_code, 202, paused.text)
        self.assertEqual(paused.json()["state"], "paused")

        time.sleep(0.05)
        self.assertEqual(
            self.client.get(f"/api/v1/runs/{run_id}").json()["state"],
            "paused",
        )

        resume_path = f"/api/v1/runs/{run_id}/resume"
        resumed = self.client.post(
            resume_path,
            json=action,
            headers={
                "X-Confirmation-Token": self.confirm(resume_path, action),
                "Idempotency-Key": "resume-1",
            },
        )
        self.assertEqual(resumed.status_code, 202, resumed.text)
        self.assertEqual(resumed.json()["state"], "running")


if __name__ == "__main__":
    unittest.main()
