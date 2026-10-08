"""Runtime data helpers for camera analysis tasks."""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

from openscan_firmware.models.camera import CameraMetadata, PhotoData
from openscan_firmware.models.paths import PolarPoint3D


@dataclass
class AnalysisFrame:
    """The small in-memory representation used by later analysis steps."""

    index: int
    position: PolarPoint3D
    camera_metadata: CameraMetadata
    analysis_image: np.ndarray


@dataclass
class _CroppingRoiMask:
    """Internal cropping ROI mask built from a turntable series."""

    background: np.ndarray
    variation: np.ndarray
    mask: np.ndarray


_CROPPING_ROI_TAIL_WIDTH_RATIO = 0.4
_CROPPING_ROI_TAIL_MIN_ROWS = 12


def analyze_cropping_roi(
    focus_series: dict[str, list[AnalysisFrame]],
    *,
    captured_frames: list[tuple[AnalysisFrame, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Analyze crop suitability and object position from focus series.

    The object position is reported through vertical and horizontal imbalance
    values calculated from the cropping ROI. When ``captured_frames`` is
    provided, compact debug images are included as well.
    """
    cropping_roi_masks = {
        focus: _detect_cropping_roi_mask(series)
        for focus, series in focus_series.items()
    }
    consensus_cropping_mask = _combine_cropping_roi_masks(cropping_roi_masks)
    object_mask = _remove_narrow_cropping_roi_tail(
        consensus_cropping_mask,
        width_ratio=_CROPPING_ROI_TAIL_WIDTH_RATIO,
        min_rows=_CROPPING_ROI_TAIL_MIN_ROWS,
    )
    crop_recommendation = _crop_recommendation(object_mask)
    position_analysis = _calculate_position_imbalance(object_mask)

    result: dict[str, Any] = {
        "crop_recommendation": crop_recommendation,
        "position_analysis": position_analysis,
    }
    if captured_frames is not None:
        result["debug_images"] = _build_cropping_roi_debug_images(
            captured_frames,
            cropping_roi_masks,
            consensus_cropping_mask,
            object_mask,
        )
    return result


def prepare_analysis_frame(
    photo: PhotoData,
    position: PolarPoint3D,
    index: int,
    max_dimension: int = 640,
) -> AnalysisFrame:
    """Create a small analysis frame without retaining the raw array."""
    image = photo.data
    if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("Analysis frames require an RGB NumPy array.")
    if max_dimension < 1:
        raise ValueError("max_dimension must be positive.")

    orientation_flag = photo.camera_metadata.camera_settings.orientation_flag or 1
    image = apply_orientation(image, orientation_flag)

    height, width = image.shape[:2]
    scale = min(1.0, max_dimension / max(height, width))
    if scale == 1.0:
        analysis_image = image.copy()
    else:
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        analysis_image = np.asarray(
            Image.fromarray(image).resize(size, Image.Resampling.BILINEAR)
        )

    return AnalysisFrame(
        index=index,
        position=position,
        camera_metadata=photo.camera_metadata,
        analysis_image=analysis_image,
    )


def apply_orientation(image: np.ndarray, orientation_flag: int) -> np.ndarray:
    """Apply an EXIF orientation to an RGB array for UI-facing coordinates."""
    transpose = {
        2: Image.Transpose.FLIP_LEFT_RIGHT,
        3: Image.Transpose.ROTATE_180,
        4: Image.Transpose.FLIP_TOP_BOTTOM,
        5: Image.Transpose.TRANSPOSE,
        6: Image.Transpose.ROTATE_270,
        7: Image.Transpose.TRANSVERSE,
        8: Image.Transpose.ROTATE_90,
    }.get(int(orientation_flag or 1))
    if transpose is None:
        return image.copy()
    return np.asarray(Image.fromarray(image).transpose(transpose)).copy()


def _detect_cropping_roi_mask(frames: list[AnalysisFrame]) -> _CroppingRoiMask:
    """Build one cropping ROI mask from multiple turntable views."""
    if len(frames) < 2:
        raise ValueError("Cropping ROI analysis requires at least two frames.")

    images = np.stack([frame.analysis_image for frame in frames]).astype(np.float32)
    if images.ndim != 4 or images.shape[3] != 3:
        raise ValueError("Cropping ROI analysis requires RGB analysis images.")
    if len({tuple(image.shape) for image in images}) != 1:
        raise ValueError("All analysis images must have the same shape.")

    background = np.median(images, axis=0).astype(np.uint8)
    variation = np.ptp(images, axis=0).mean(axis=2)
    threshold = _derive_cropping_roi_threshold(variation)
    return _CroppingRoiMask(
        background=background,
        variation=variation,
        mask=_clean_mask(variation > threshold),
    )


def _encode_analysis_image(image: np.ndarray, quality: int = 82) -> str:
    """Encode one small RGB analysis image as base64 JPEG data."""
    buffer = io.BytesIO()
    Image.fromarray(image).save(buffer, format="JPEG", quality=quality)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _create_cropping_roi_debug_images(detection: _CroppingRoiMask) -> dict[str, str]:
    """Create compact debug images for inspecting a cropping ROI mask."""
    return {
        "background_base64": _encode_analysis_image(detection.background),
        "variation_base64": _encode_gray_image(detection.variation),
        "roi_mask_base64": _encode_gray_image(detection.mask.astype(np.uint8) * 255),
    }


def _calculate_position_imbalance(mask: np.ndarray) -> dict[str, float]:
    """Calculate vertical and horizontal object distribution imbalance."""
    height, width = mask.shape
    half_height = height // 2
    half_width = width // 2
    top = float(mask[:half_height].mean())
    bottom = float(mask[half_height:].mean())
    left = float(mask[:, :half_width].mean())
    right = float(mask[:, half_width:].mean())
    return {
        "vertical_imbalance": round(_imbalance(top, bottom), 6),
        "horizontal_imbalance": round(_imbalance(left, right), 6),
    }


def _combine_cropping_roi_masks(
    roi_masks: dict[str, _CroppingRoiMask],
) -> np.ndarray:
    """Keep pixels detected by a majority of the cropping ROI series."""
    if not roi_masks:
        raise ValueError("At least one cropping ROI mask is required.")
    masks = np.stack([roi_mask.mask for roi_mask in roi_masks.values()])
    required_votes = masks.shape[0] // 2 + 1
    return masks.sum(axis=0) >= required_votes


def _remove_narrow_cropping_roi_tail(
    mask: np.ndarray,
    width_ratio: float = 0.4,
    min_rows: int = 12,
) -> np.ndarray:
    """Remove a long, narrow bottom tail from a cropping ROI mask."""
    if not 0 < width_ratio < 1:
        raise ValueError("width_ratio must be between 0 and 1.")
    if min_rows < 1:
        raise ValueError("min_rows must be positive.")

    row_widths = np.zeros(mask.shape[0], dtype=int)
    for row, values in enumerate(mask):
        columns = np.flatnonzero(values)
        if len(columns):
            row_widths[row] = int(columns[-1] - columns[0] + 1)

    nonzero_widths = row_widths[row_widths > 0]
    if not len(nonzero_widths):
        return mask

    reference_width = float(np.percentile(nonzero_widths, 75))
    width_threshold = max(3.0, reference_width * width_ratio)
    end = int(np.flatnonzero(row_widths > 0)[-1])
    start = end
    while start >= 0 and row_widths[start] <= width_threshold:
        start -= 1

    tail_length = end - start
    if tail_length < min_rows:
        return mask

    trimmed = mask.copy()
    trimmed[start + 1:] = False
    return trimmed


def _crop_recommendation(mask: np.ndarray, margin_ratio: float = 0.0) -> dict[str, object]:
    """Return a centered crop that contains the outer mask extent."""
    if not 0 <= margin_ratio <= 0.25:
        raise ValueError("margin_ratio must be between 0 and 0.25.")
    height, width = mask.shape
    y_coordinates, x_coordinates = np.where(mask)
    if not len(x_coordinates):
        return {"bbox": None, "rect": None, "crop_width": None, "crop_height": None}

    x_min, x_max = int(x_coordinates.min()), int(x_coordinates.max()) + 1
    y_min, y_max = int(y_coordinates.min()), int(y_coordinates.max()) + 1
    bbox = [x_min, y_min, x_max - x_min, y_max - y_min]
    margin_x = width * margin_ratio
    margin_y = height * margin_ratio
    x_min = max(0.0, x_min - margin_x)
    y_min = max(0.0, y_min - margin_y)
    x_max = min(float(width), x_max + margin_x)
    y_max = min(float(height), y_max + margin_y)

    center_x, center_y = width / 2, height / 2
    half_width = max(center_x - x_min, x_max - center_x)
    half_height = max(center_y - y_min, y_max - center_y)
    rect = [
        round(center_x - half_width),
        round(center_y - half_height),
        round(2 * half_width),
        round(2 * half_height),
    ]
    return {
        "bbox": bbox,
        "rect": rect,
        "crop_width": round(100 * (1 - rect[2] / width), 2),
        "crop_height": round(100 * (1 - rect[3] / height), 2),
    }


def _imbalance(first: float, second: float) -> float:
    """Return the relative difference between two area weights."""
    total = first + second
    return abs(first - second) / total if total else 0.0


def _derive_cropping_roi_threshold(variation: np.ndarray) -> float:
    """Derive a noise-aware threshold for the cropping ROI variation."""
    border = np.concatenate(
        (
            variation[0, :],
            variation[-1, :],
            variation[1:-1, 0],
            variation[1:-1, -1],
        )
    )
    median = float(np.median(border))
    mad = float(np.median(np.abs(border - median)))
    return max(12.0, median + 4.0 * max(mad, 1.0))


def _encode_gray_image(image: np.ndarray, quality: int = 82) -> str:
    """Encode a grayscale debug image after normalizing its display range."""
    values = image.astype(np.float32)
    minimum = float(values.min())
    maximum = float(values.max())
    if maximum <= minimum:
        normalized = np.zeros(values.shape, dtype=np.uint8)
    else:
        normalized = ((values - minimum) * 255 / (maximum - minimum)).astype(np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(normalized, mode="L").save(buffer, format="JPEG", quality=quality)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _clean_mask(mask: np.ndarray) -> np.ndarray:
    """Remove isolated noise with a small opening and closing operation."""
    opened = _dilate(_erode(mask))
    return _erode(_dilate(opened))


def _erode(mask: np.ndarray) -> np.ndarray:
    """Keep pixels whose complete 3x3 neighborhood is set."""
    padded = np.pad(mask, 1, mode="constant")
    neighbors = sum(
        padded[row:row + mask.shape[0], column:column + mask.shape[1]]
        for row in range(3)
        for column in range(3)
    )
    return neighbors == 9


def _dilate(mask: np.ndarray) -> np.ndarray:
    """Keep pixels with at least one set pixel in their 3x3 neighborhood."""
    padded = np.pad(mask, 1, mode="constant")
    neighbors = sum(
        padded[row:row + mask.shape[0], column:column + mask.shape[1]]
        for row in range(3)
        for column in range(3)
    )
    return neighbors > 0


def _build_cropping_roi_debug_images(
    captured_frames: list[tuple[AnalysisFrame, dict[str, Any]]],
    cropping_roi_masks: dict[str, _CroppingRoiMask],
    consensus_mask: np.ndarray,
    object_mask: np.ndarray,
) -> dict[str, Any]:
    """Build optional images for inspecting captured frames and cropping ROI masks."""
    return {
        "captured_frames": [
            {
                "index": report["index"],
                "capture_index": report["capture_index"],
                "focus_mode": report["focus_mode"],
                "requested_focus": report["requested_focus"],
                "camera_metadata": report["camera_metadata"],
                "image_base64": _encode_analysis_image(frame.analysis_image),
            }
            for frame, report in captured_frames
        ],
        "cropping_roi_masks": {
            focus: _create_cropping_roi_debug_images(roi_mask)
            for focus, roi_mask in cropping_roi_masks.items()
        },
        "consensus_mask_base64": _encode_gray_image(consensus_mask.astype("uint8") * 255),
        "object_mask_base64": _encode_gray_image(object_mask.astype("uint8") * 255),
    }
