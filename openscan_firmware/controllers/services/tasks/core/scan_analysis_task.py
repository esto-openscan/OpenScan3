"""Core task for collecting camera frames for scan setup analysis."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncGenerator

from openscan_firmware.controllers.services.tasks.base_task import BaseTask
from openscan_firmware.models.paths import PolarPoint3D
from openscan_firmware.models.task import TaskProgress
from openscan_firmware.utils.photos.analysis import (
    AnalysisFrame,
    analyze_cropping_roi,
    prepare_analysis_frame,
)

logger = logging.getLogger(__name__)

DEFAULT_TURNTABLE_OFFSETS = (0.0, 120.0, -120.0)
DEFAULT_FOCUS_VALUES = (10.0, 12.0, 15.0)


class ScanAnalysisTask(BaseTask):
    """Capture and analyze a small set of RGB frames for scan setup."""

    task_name = "scan_analysis_task"
    task_category = "core"
    is_exclusive = True

    async def run(
        self,
        camera_name: str,
        turntable_offsets: list[float] | None = None,
        settle_time_s: float = 0.25,
        focus_values: list[float] | None = None,
        debug_images: bool = False,
    ) -> AsyncGenerator[TaskProgress, None]:
        """Capture RGB arrays at relative turntable positions."""
        offsets = list(DEFAULT_TURNTABLE_OFFSETS if turntable_offsets is None else turntable_offsets)
        focus_values = list(DEFAULT_FOCUS_VALUES if not focus_values else focus_values)
        focus_values = [float(value) for value in focus_values]

        capture_plan = [("autofocus", None)]
        capture_plan.extend(("manual", value) for value in focus_values)

        # Keep hardware imports inside run so task discovery has no side effects.
        from openscan_firmware.controllers.hardware import motors
        from openscan_firmware.controllers.hardware.cameras.camera import get_camera_controller

        camera = get_camera_controller(camera_name)
        rotor = motors.get_motor_controller("rotor")
        turntable = motors.get_motor_controller("turntable")
        original_position = PolarPoint3D(
            theta=float(rotor.model.angle),
            fi=float(turntable.model.angle),
            r=1.0,
        )

        camera_settings = getattr(camera, "settings", None)
        original_camera_settings = None
        if camera_settings is not None and hasattr(camera_settings, "model"):
            original_camera_settings = camera_settings.model.model_copy(deep=True)

        # Only small analysis images are kept between captures. Raw camera arrays
        # are released before the next capture starts.
        focus_series: dict[str, list[AnalysisFrame]] = {}
        captured_frames: list[tuple[AnalysisFrame, dict[str, Any]]] = []
        total_captures = len(offsets) * len(capture_plan)

        try:
            for index, offset in enumerate(offsets):
                await self.wait_for_pause()
                if self.is_cancelled():
                    return

                position = PolarPoint3D(
                    theta=original_position.theta,
                    fi=original_position.fi + float(offset),
                    r=1.0,
                )
                await motors.move_to_point(position)
                if settle_time_s:
                    await asyncio.sleep(settle_time_s)

                for capture_index, (focus_mode, requested_focus) in enumerate(capture_plan):
                    await self.wait_for_pause()
                    if self.is_cancelled():
                        return

                    frame, frame_report = await self._capture_frame(
                        camera=camera,
                        camera_settings=camera_settings,
                        position=position,
                        index=index,
                        capture_index=capture_index,
                        offset=offset,
                        focus_mode=focus_mode,
                        requested_focus=requested_focus,
                    )

                    if debug_images:
                        captured_frames.append((frame, frame_report))
                    series_name = (
                        "autofocus"
                        if focus_mode == "autofocus"
                        else str(requested_focus)
                    )
                    focus_series.setdefault(series_name, []).append(frame)

                    current = index * len(capture_plan) + capture_index + 1
                    yield TaskProgress(
                        current=current,
                        total=total_captures + 1,
                        message=(
                            f"Captured analysis frame {current} of {total_captures}."
                        ),
                    )

            analysis = analyze_cropping_roi(
                focus_series,
                captured_frames=captured_frames if debug_images else None,
            )
            result = self._build_result(
                analysis=analysis,
            )

            self._task_model.result = result
            yield TaskProgress(
                current=total_captures + 1,
                total=total_captures + 1,
                message="Analysis frames captured.",
            )
        finally:
            if original_camera_settings is not None:
                try:
                    await _restore_camera_settings(camera_settings, original_camera_settings)
                except Exception:
                    logger.exception("Failed to restore camera settings after scan analysis.")
            try:
                await motors.move_to_point(original_position)
            except Exception:
                logger.exception("Failed to restore motor position after scan analysis.")

    async def _capture_frame(
        self,
        camera: Any,
        camera_settings: Any,
        position: PolarPoint3D,
        index: int,
        capture_index: int,
        offset: float,
        focus_mode: str,
        requested_focus: float | None,
    ) -> tuple[AnalysisFrame, dict[str, Any]]:
        """Apply one focus setting, capture a frame, and build its report."""
        if focus_mode == "autofocus":
            await _update_focus(camera_settings, autofocus=True)
        elif focus_mode == "manual":
            await _update_focus(camera_settings, autofocus=False, focus=requested_focus)

        photo = await camera.photo_async(image_format="rgb_array")
        try:
            frame = prepare_analysis_frame(photo, position, index)
            metadata = frame.camera_metadata.model_dump(mode="json")
            raw_metadata = metadata.get("raw_metadata", {})
            frame_report = {
                "index": index,
                "capture_index": capture_index,
                "turntable_offset": float(offset),
                "turntable_angle": float(position.fi % 360),
                "focus_mode": focus_mode,
                "requested_focus": requested_focus,
                "actual_lens_position": raw_metadata.get("LensPosition"),
                "focus_fom": raw_metadata.get("FocusFoM"),
                "camera_metadata": metadata,
            }
            return frame, frame_report
        finally:
            del photo

    @staticmethod
    def _build_result(
        analysis: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the persisted task result from capture and analysis data."""
        result: dict[str, Any] = {
            "report_version": 5,
            "analysis_type": "scan_analysis",
            "crop_recommendation": analysis["crop_recommendation"],
            "position_analysis": analysis["position_analysis"],
        }
        if "debug_images" in analysis:
            result["debug_images"] = analysis["debug_images"]
        return result


async def _update_focus(settings: Any, autofocus: bool, focus: float | None = None) -> None:
    """Apply one focus mode without blocking the task event loop."""
    if settings is None:
        raise ValueError("The camera does not expose settings for focus analysis.")
    values: dict[str, Any] = {"AF": autofocus}
    if focus is not None:
        values["manual_focus"] = focus
    await asyncio.to_thread(settings.update, **values)


async def _restore_camera_settings(settings: Any, original_settings: Any) -> None:
    """Restore the complete camera settings model after the focus sweep."""
    await asyncio.to_thread(settings.replace, original_settings)
