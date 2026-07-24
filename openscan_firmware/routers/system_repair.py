"""System repair API endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from openscan_firmware.system_update import UpdateConflictError, run_repair_openscan3


router = APIRouter(
    prefix="/system/repair",
    tags=["system repair"],
    responses={404: {"description": "Not found"}},
)


def _json(status_code: int, payload: dict) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=payload)


@router.post("/openscan3")
async def repair_openscan3() -> JSONResponse:
    try:
        status_code, payload = await run_repair_openscan3()
    except UpdateConflictError as exc:
        payload = {
            "ok": False,
            "command": "repair_openscan3",
            "error": {"type": exc.error_type, "message": exc.message},
        }
        status_code = 409
    return _json(status_code, payload)
