"""Safe wrapper around the local OpenScan updater CLI."""

from __future__ import annotations

import asyncio
import json
import subprocess
from collections import deque
from pathlib import Path
from typing import Any, Final

from openscan_firmware import __version__
from openscan_firmware.controllers.services.tasks.task_manager import get_task_manager
from openscan_firmware.models.task import TaskStatus

BACKEND_API_VERSION: Final = "1"
UPDATER_TIMEOUT_SECONDS: Final = {
    "status": 30,
    "check": 90,
    "update_openscan": 900,
}
MAX_ERROR_TEXT_CHARS: Final = 4096
MAX_LOG_LINES: Final = 200
MAX_LOG_BYTES: Final = 128 * 1024
UPDATER_ENV: Final = {
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
}

UPDATER_COMMANDS: Final[dict[str, list[str]]] = {
    "status": ["sudo", "/usr/bin/openscan-updater", "status", "--json"],
    "check": ["sudo", "/usr/bin/openscan-updater", "check", "--dry-run", "--json"],
    "update_openscan": ["sudo", "/usr/bin/openscan-updater", "update-openscan", "--json"],
}

UPDATER_LOG_FILES: Final[tuple[Path, ...]] = (
    Path("/var/log/openscan-updater/updater.log"),
    Path("/var/log/openscan-updater.log"),
)

_update_lock = asyncio.Lock()


class UpdateConflictError(RuntimeError):
    """Raised when an update cannot be started because another operation is active."""

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message


def _base_response(command: str) -> dict[str, Any]:
    return {
        "backend_api_version": BACKEND_API_VERSION,
        "firmware_version": __version__,
        "command": command,
    }


def _error_response(command: str, error_type: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = _base_response(command)
    payload["ok"] = False
    payload["error"] = {"type": error_type, "message": message, **extra}
    return payload


def _result_response(command: str, result: Any, *, ok: bool = True) -> dict[str, Any]:
    payload = _base_response(command)
    payload["ok"] = ok
    payload["result"] = result
    return payload


async def run_updater_command(command: str) -> tuple[int, dict[str, Any]]:
    """Run one fixed updater command and return an HTTP status plus JSON payload."""
    try:
        argv = UPDATER_COMMANDS[command]
    except KeyError:
        return 501, _error_response(
            command,
            "command_not_implemented",
            f"Updater command is not implemented by this backend: {command}",
        )

    timeout = UPDATER_TIMEOUT_SECONDS[command]
    try:
        completed = await asyncio.to_thread(
            subprocess.run,
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
            env=UPDATER_ENV,
        )
    except subprocess.TimeoutExpired:
        return 500, _error_response(
            command,
            "command_timeout",
            f"openscan-updater command timed out after {timeout} seconds",
            timeout_seconds=timeout,
        )
    except OSError as exc:
        return 500, _error_response(
            command,
            "command_execution_failed",
            "openscan-updater could not be executed",
            detail=str(exc),
        )

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()

    try:
        result = json.loads(stdout) if stdout else None
    except json.JSONDecodeError:
        return 500, _error_response(
            command,
            "invalid_updater_json",
            "openscan-updater did not return valid JSON",
            returncode=completed.returncode,
            stderr=_truncate_text(stderr),
        )

    if completed.returncode != 0:
        payload = _result_response(command, result, ok=False)
        payload["error"] = {
            "type": "command_failed",
            "message": "openscan-updater exited with a non-zero status",
            "returncode": completed.returncode,
            "stderr": _truncate_text(stderr),
        }
        if command == "update_openscan" and result is not None:
            return 200, payload
        return 500, payload

    return 200, _result_response(command, result, ok=True)


async def run_update_openscan() -> tuple[int, dict[str, Any]]:
    """Run the OpenScan update command under a process-local lock."""
    if _update_lock.locked():
        return 409, _error_response(
            "update_openscan",
            "update_active",
            "Another update command is already running.",
        )

    if is_scan_active():
        raise UpdateConflictError(
            "scan_active",
            "Updates cannot be started while a scan is running.",
        )

    await _update_lock.acquire()
    try:
        return await run_updater_command("update_openscan")
    finally:
        _update_lock.release()


def is_scan_active() -> bool:
    """Return true when the firmware task manager reports an active scan task."""
    active_statuses = {TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.PAUSED}
    try:
        tasks = get_task_manager().get_all_tasks_info()
    except Exception:
        return False

    return any(task.task_type == "scan_task" and task.status in active_statuses for task in tasks)


def read_updater_logs(tail: int = MAX_LOG_LINES) -> tuple[int, dict[str, Any]]:
    """Return recent updater logs from fixed known log files only."""
    tail = max(1, min(tail, MAX_LOG_LINES))
    log_path = next((path for path in UPDATER_LOG_FILES if path.is_file()), None)
    if log_path is None:
        return 404, _error_response(
            "logs",
            "log_file_not_found",
            "No updater log file was found.",
        )

    try:
        lines = _tail_text_file(log_path, tail)
    except OSError as exc:
        return 500, _error_response(
            "logs",
            "log_read_failed",
            "Updater log file could not be read.",
            detail=str(exc),
        )

    return 200, _result_response(
        "logs",
        {
            "path": str(log_path),
            "tail": tail,
            "lines": lines,
            "truncated_bytes": MAX_LOG_BYTES,
        },
        ok=True,
    )


def _tail_text_file(path: Path, max_lines: int) -> list[str]:
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - MAX_LOG_BYTES))
        text = handle.read(MAX_LOG_BYTES).decode("utf-8", errors="replace")

    return list(deque(text.splitlines(), maxlen=max_lines))


def _truncate_text(text: str) -> str:
    if len(text) <= MAX_ERROR_TEXT_CHARS:
        return text
    return text[:MAX_ERROR_TEXT_CHARS] + "... [truncated]"
