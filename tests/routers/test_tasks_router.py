from importlib import import_module
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from openscan_firmware.main import app
from openscan_firmware.models.task import Task


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize(
    ("api_version", "router_module"),
    [
        ("v0.8", "openscan_firmware.routers.v0_8.tasks"),
        ("v0.9", "openscan_firmware.routers.v0_9.tasks"),
        ("next", "openscan_firmware.routers.next.tasks"),
    ],
)
def test_create_task_accepts_dependency(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    api_version: str,
    router_module: str,
) -> None:
    task_manager = MagicMock()
    task_manager.create_and_run_task = AsyncMock(
        return_value=Task(name="focus_stacking_task", task_type="focus_stacking_task")
    )
    monkeypatch.setattr(import_module(router_module), "get_task_manager", lambda: task_manager)

    response = client.post(
        f"/{api_version}/tasks/focus_stacking_task",
        json={
            "args": ["demo-project", 1],
            "kwargs": {"some_option": True},
            "depends_on": "scan-task-id",
        },
    )

    assert response.status_code == 202
    task_manager.create_and_run_task.assert_awaited_once_with(
        "focus_stacking_task",
        "demo-project",
        1,
        depends_on="scan-task-id",
        some_option=True,
    )


@pytest.mark.parametrize(
    ("api_version", "router_module"),
    [
        ("v0.8", "openscan_firmware.routers.v0_8.tasks"),
        ("v0.9", "openscan_firmware.routers.v0_9.tasks"),
        ("next", "openscan_firmware.routers.next.tasks"),
    ],
)
def test_create_task_dependency_is_optional(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    api_version: str,
    router_module: str,
) -> None:
    task_manager = MagicMock()
    task_manager.create_and_run_task = AsyncMock(
        return_value=Task(name="scan_task", task_type="scan_task")
    )
    monkeypatch.setattr(import_module(router_module), "get_task_manager", lambda: task_manager)

    response = client.post(
        f"/{api_version}/tasks/scan_task",
        json={"args": [], "kwargs": {}},
    )

    assert response.status_code == 202
    task_manager.create_and_run_task.assert_awaited_once_with(
        "scan_task",
        depends_on=None,
    )
