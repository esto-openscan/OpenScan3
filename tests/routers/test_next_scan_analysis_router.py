from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openscan_firmware.models.task import Task, TaskStatus
from openscan_firmware.routers.next import scan_analysis as scan_analysis_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(scan_analysis_router.router, prefix="/next")
    return TestClient(app)


def test_start_scan_analysis_uses_json_request_body(monkeypatch):
    started_task = Task(
        name="scan_analysis_task",
        task_type="scan_analysis_task",
        status=TaskStatus.RUNNING,
        id="task-123",
    )
    start_service = AsyncMock(return_value=started_task)
    monkeypatch.setattr(scan_analysis_router.scan_analysis_service, "start_scan_analysis", start_service)

    with _client() as client:
        response = client.post(
            "/next/scan-analysis",
            json={
                "camera_name": "camera0",
                "turntable_offsets": [-90.0, 90.0],
                "settle_time_s": 0.5,
                "focus_values": [10.0, 12.0, 15.0],
                "debug_images": True,
                "depends_on": "task-prerequisite",
            },
        )

    assert response.status_code == 202
    assert response.json()["id"] == "task-123"
    start_service.assert_awaited_once_with(
        camera_name="camera0",
        turntable_offsets=[-90.0, 90.0],
        settle_time_s=0.5,
        focus_values=[10.0, 12.0, 15.0],
        debug_images=True,
        depends_on="task-prerequisite",
    )


def test_start_scan_analysis_uses_default_offsets(monkeypatch):
    start_service = AsyncMock(
        return_value=Task(name="scan_analysis_task", task_type="scan_analysis_task")
    )
    monkeypatch.setattr(scan_analysis_router.scan_analysis_service, "start_scan_analysis", start_service)

    with _client() as client:
        response = client.post("/next/scan-analysis", json={"camera_name": "camera0"})

    assert response.status_code == 202
    start_service.assert_awaited_once_with(
        camera_name="camera0",
        turntable_offsets=[0.0, 120.0, -120.0],
        settle_time_s=0.25,
        focus_values=[10.0, 12.0, 15.0],
        debug_images=False,
        depends_on=None,
    )


def test_start_scan_analysis_requires_two_offsets():
    with _client() as client:
        response = client.post(
            "/next/scan-analysis",
            json={"camera_name": "camera0", "turntable_offsets": [0.0]},
        )

    assert response.status_code == 422
