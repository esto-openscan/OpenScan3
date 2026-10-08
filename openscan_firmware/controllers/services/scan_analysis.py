"""Service layer for scan setup analysis tasks."""
from __future__ import annotations

from openscan_firmware.controllers.services.tasks.task_manager import get_task_manager
from openscan_firmware.models.task import Task


async def start_scan_analysis(
    camera_name: str,
    turntable_offsets: list[float] | None = None,
    settle_time_s: float = 0.25,
    focus_values: list[float] | None = None,
    debug_images: bool = False,
    depends_on: str | None = None,
) -> Task:
    """Start a scan setup analysis task through the task manager."""
    return await get_task_manager().create_and_run_task(
        "scan_analysis_task",
        camera_name=camera_name,
        turntable_offsets=turntable_offsets,
        settle_time_s=settle_time_s,
        focus_values=focus_values,
        debug_images=debug_images,
        depends_on=depends_on,
    )
