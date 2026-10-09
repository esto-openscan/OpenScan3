"""Opt-in exposure calibration test for a real Picamera2 camera.

Run explicitly on the Raspberry Pi, for example:

    OPENSCAN_RUN_REAL_CAMERA_TESTS=1 \
    .venv/bin/python -m pytest -s \
    tests/controllers/hardware/picamera2/test_exposure_real.py

Set ``OPENSCAN_EXPOSURE_USE_PHOTO_CONFIG=0`` to calibrate in preview mode.
The default is the cropped photo configuration because this test is intended
to inspect the exposure used for the final capture path.
"""

import os
import time

import pytest

from openscan_firmware.config.camera import CameraSettings
from openscan_firmware.controllers.hardware.cameras.camera import (
    create_camera_controller,
    is_camera_type_available,
)
from openscan_firmware.models.camera import Camera, CameraType


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@pytest.fixture
def real_camera_controller():
    if not _env_flag("OPENSCAN_RUN_REAL_CAMERA_TESTS", False):
        pytest.skip("Set OPENSCAN_RUN_REAL_CAMERA_TESTS=1 to access real camera hardware.")

    if not is_camera_type_available(CameraType.PICAMERA2):
        pytest.skip("Picamera2 dependencies are not available.")

    camera_name = os.getenv("OPENSCAN_CAMERA_NAME", "arducam_64mp")
    camera_path = os.getenv("OPENSCAN_CAMERA_PATH", "/dev/video0")
    orientation_flag = int(os.getenv("OPENSCAN_CAMERA_ORIENTATION", "6"))

    camera = Camera(
        type=CameraType.PICAMERA2,
        name=camera_name,
        path=camera_path,
        settings=CameraSettings(
            crop_width=87,
            crop_height=48,
            orientation_flag=orientation_flag,
            shutter=50.0,
            gain=1.0,
        ),
    )

    controller = create_camera_controller(camera)
    try:
        yield controller
    finally:
        controller.cleanup()


def test_real_exposure_calibration_debug(real_camera_controller):
    use_photo_config = _env_flag("OPENSCAN_EXPOSURE_USE_PHOTO_CONFIG", True)
    timeout_s = float(os.getenv("OPENSCAN_EXPOSURE_TIMEOUT_S", "3.0"))

    started = time.monotonic()
    try:
        shutter_ms, analogue_gain = real_camera_controller.calibrate_exposure_and_lock(
            warmup_frames=12,
            stable_frames=4,
            timeout_s=timeout_s,
            use_photo_config=use_photo_config,
        )
    except RuntimeError as exc:
        elapsed_s = time.monotonic() - started
        print(
            "EXPOSURE_DEBUG "
            f"status=failed elapsed_s={elapsed_s:.3f} "
            f"timeout_s={timeout_s:.3f} "
            f"photo_config={use_photo_config} "
            f"crop_width=87 crop_height=48 error={exc}"
        )
        pytest.fail(f"Exposure calibration failed after {elapsed_s:.3f}s: {exc}")

    elapsed_s = time.monotonic() - started
    print(
        "EXPOSURE_DEBUG "
        f"status=success elapsed_s={elapsed_s:.3f} "
        f"timeout_s={timeout_s:.3f} "
        f"photo_config={use_photo_config} "
        f"crop_width=87 crop_height=48 "
        f"shutter_ms={shutter_ms:.3f} analogue_gain={analogue_gain:.3f}"
    )

    assert shutter_ms > 0
    assert analogue_gain == pytest.approx(1.0)
