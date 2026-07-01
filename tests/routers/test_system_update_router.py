from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openscan_firmware.models.task import Task, TaskStatus
from openscan_firmware.routers.system_update import router
from openscan_firmware import system_update


@pytest.fixture
def update_client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/latest")
    with TestClient(app) as client:
        yield client


def _completed(argv: list[str], stdout: str, stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)


def test_fixed_command_map_has_no_request_controlled_package_names():
    assert system_update.UPDATER_COMMANDS == {
        "status": ["sudo", "/usr/bin/openscan-updater", "status", "--json"],
        "check": ["sudo", "/usr/bin/openscan-updater", "check", "--dry-run", "--json"],
        "update_openscan": ["sudo", "/usr/bin/openscan-updater", "update-openscan", "--json"],
        "healthcheck": ["sudo", "/usr/bin/openscan-updater", "healthcheck", "--json"],
    }
    assert all("apt" not in argv for command in system_update.UPDATER_COMMANDS.values() for argv in command)


def test_status_endpoint_returns_parsed_updater_json(monkeypatch, update_client):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return _completed(argv, '{"ok": true, "mode": "idle"}')

    monkeypatch.setattr(system_update.subprocess, "run", fake_run)

    response = update_client.get("/latest/system/update/status")

    assert response.status_code == 200
    assert response.json()["result"] == {"ok": True, "mode": "idle"}
    assert calls[0][0] == system_update.UPDATER_COMMANDS["status"]
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["env"] == system_update.UPDATER_ENV


def test_check_endpoint_returns_parsed_updater_json(monkeypatch, update_client):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return _completed(argv, '{"classification": "openscan_only"}')

    monkeypatch.setattr(system_update.subprocess, "run", fake_run)

    response = update_client.post("/latest/system/update/check", json={"ignored": "input"})

    assert response.status_code == 200
    assert response.json()["result"] == {"classification": "openscan_only"}
    assert calls == [system_update.UPDATER_COMMANDS["check"]]


def test_update_openscan_endpoint_calls_correct_command(monkeypatch, update_client):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return _completed(argv, '{"ok": true, "updated": ["openscan3-firmware"]}')

    monkeypatch.setattr(system_update, "is_scan_active", lambda: False)
    monkeypatch.setattr(system_update.subprocess, "run", fake_run)

    response = update_client.post("/latest/system/update/openscan")

    assert response.status_code == 200
    assert response.json()["result"] == {"ok": True, "updated": ["openscan3-firmware"]}
    assert calls == [system_update.UPDATER_COMMANDS["update_openscan"]]


def test_updater_command_timeout_returns_structured_error(monkeypatch, update_client):
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, timeout=kwargs["timeout"])

    monkeypatch.setattr(system_update.subprocess, "run", fake_run)

    response = update_client.get("/latest/system/update/status")

    assert response.status_code == 500
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]["type"] == "command_timeout"


def test_invalid_json_returns_structured_error(monkeypatch, update_client):
    def fake_run(argv, **kwargs):
        return _completed(argv, "not json")

    monkeypatch.setattr(system_update.subprocess, "run", fake_run)

    response = update_client.get("/latest/system/update/status")

    assert response.status_code == 500
    assert response.json()["error"]["type"] == "invalid_updater_json"


def test_nonzero_exit_returns_structured_error(monkeypatch, update_client):
    def fake_run(argv, **kwargs):
        return _completed(argv, '{"ok": false}', "apt failed", returncode=1)

    monkeypatch.setattr(system_update.subprocess, "run", fake_run)

    response = update_client.post("/latest/system/update/check")

    assert response.status_code == 500
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]["type"] == "command_failed"
    assert payload["error"]["returncode"] == 1


def test_update_blocked_result_is_not_backend_crash(monkeypatch, update_client):
    def fake_run(argv, **kwargs):
        return _completed(
            argv,
            '{"ok": false, "classification": "unsafe_system_packages"}',
            returncode=2,
        )

    monkeypatch.setattr(system_update, "is_scan_active", lambda: False)
    monkeypatch.setattr(system_update.subprocess, "run", fake_run)

    response = update_client.post("/latest/system/update/openscan")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["result"]["classification"] == "unsafe_system_packages"


@pytest.mark.asyncio
async def test_concurrent_update_attempts_are_rejected(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_run(command: str):
        started.set()
        await release.wait()
        return 200, {"ok": True, "command": command, "result": {}}

    monkeypatch.setattr(system_update, "is_scan_active", lambda: False)
    monkeypatch.setattr(system_update, "run_updater_command", fake_run)

    first = asyncio.create_task(system_update.run_update_openscan())
    await started.wait()
    second_status, second_payload = await system_update.run_update_openscan()
    release.set()
    first_status, _ = await first

    assert first_status == 200
    assert second_status == 409
    assert second_payload["error"]["type"] == "update_active"


def test_active_scan_guard_blocks_update(monkeypatch, update_client):
    monkeypatch.setattr(system_update, "is_scan_active", lambda: True)

    response = update_client.post("/latest/system/update/openscan")

    assert response.status_code == 409
    assert response.json()["error"]["type"] == "scan_active"


def test_is_scan_active_uses_task_manager(monkeypatch):
    manager = type(
        "Manager",
        (),
        {
            "get_all_tasks_info": lambda self: [
                Task(name="scan", task_type="scan_task", status=TaskStatus.RUNNING)
            ]
        },
    )()
    monkeypatch.setattr(system_update, "get_task_manager", lambda: manager)

    assert system_update.is_scan_active() is True


def test_logs_endpoint_limits_output_size(monkeypatch, tmp_path: Path, update_client):
    log_file = tmp_path / "updater.log"
    log_file.write_text("\n".join(f"line-{index}" for index in range(300)), encoding="utf-8")
    monkeypatch.setattr(system_update, "UPDATER_LOG_FILES", (log_file,))

    response = update_client.get("/latest/system/update/logs")

    assert response.status_code == 200
    result = response.json()["result"]
    assert len(result["lines"]) == 200
    assert result["lines"][0] == "line-100"
    assert result["lines"][-1] == "line-299"


def test_healthcheck_calls_updater_command(monkeypatch, update_client):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return _completed(argv, '{"ok": true, "checks": []}')

    monkeypatch.setattr(system_update.subprocess, "run", fake_run)

    response = update_client.post("/latest/system/update/healthcheck")

    assert response.status_code == 200
    assert response.json()["result"] == {"ok": True, "checks": []}
    assert calls == [system_update.UPDATER_COMMANDS["healthcheck"]]
