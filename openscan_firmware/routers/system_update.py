"""System update API endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from openscan_firmware.system_update import (
    UpdateConflictError,
    read_updater_logs,
    run_update_apply,
    run_update_check,
    run_update_openscan,
    run_updater_command,
)

router = APIRouter(
    prefix="/system/update",
    tags=["system update"],
    responses={404: {"description": "Not found"}},
)


def _json(status_code: int, payload: dict) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=payload)


@router.get("/status")
async def get_update_status() -> JSONResponse:
    status_code, payload = await run_updater_command("status")
    return _json(status_code, payload)


@router.post("/check")
async def check_for_updates() -> JSONResponse:
    status_code, payload = await run_update_check()
    return _json(status_code, payload)


@router.post("/apply")
async def apply_updates() -> JSONResponse:
    try:
        status_code, payload = await run_update_apply()
    except UpdateConflictError as exc:
        payload = {
            "ok": False,
            "command": "update_apply",
            "error": {"type": exc.error_type, "message": exc.message},
        }
        status_code = 409
    return _json(status_code, payload)


@router.post("/openscan")
async def update_openscan() -> JSONResponse:
    try:
        status_code, payload = await run_update_openscan()
    except UpdateConflictError as exc:
        payload = {
            "ok": False,
            "command": "update_openscan",
            "error": {"type": exc.error_type, "message": exc.message},
        }
        status_code = 409
    return _json(status_code, payload)


@router.post("/healthcheck")
async def update_healthcheck() -> JSONResponse:
    status_code, payload = await run_updater_command("healthcheck")
    return _json(status_code, payload)


@router.get("/logs")
async def get_update_logs() -> JSONResponse:
    status_code, payload = read_updater_logs()
    return _json(status_code, payload)
