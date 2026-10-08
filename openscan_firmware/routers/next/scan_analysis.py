"""API endpoints for scan setup analysis."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from openscan_firmware.controllers.services import scan_analysis as scan_analysis_service
from openscan_firmware.models.task import Task


router = APIRouter(prefix="/scan-analysis", tags=["scan_analysis"])


class ScanAnalysisRequest(BaseModel):
    """Parameters for a scan setup analysis capture."""

    camera_name: str = Field(
        min_length=1,
        description="Name of the camera used for the analysis capture.",
    )
    turntable_offsets: list[float] = Field(
        default_factory=lambda: [0.0, 120.0, -120.0],
        min_length=2,
        description="Relative turntable offsets in degrees. At least two views are required.",
    )
    settle_time_s: float = Field(
        default=0.25,
        ge=0.0,
        le=10.0,
        description="Time to wait after moving the turntable, in seconds.",
    )
    focus_values: list[
        Annotated[
            float,
            Field(
                ge=0.0,
                le=15.0,
                description="Manual focus position in diopters.",
            ),
        ]
    ] = Field(
        default_factory=lambda: [10.0, 12.0, 15.0],
        min_length=1,
        description=(
            "Manual focus positions to capture in addition to the mandatory autofocus "
            "frame at each turntable position."
        ),
    )
    debug_images: bool = Field(
        default=False,
        description="Include diagnostic images in the task result.",
    )
    depends_on: str | None = Field(
        default=None,
        description="Optional task ID that must complete successfully before this task runs.",
    )

    @field_validator("focus_values")
    @classmethod
    def validate_focus_values(
        cls,
        focus_values: list[float],
    ) -> list[float]:
        """Reject duplicate manual focus positions."""
        if len(set(focus_values)) != len(focus_values):
            raise ValueError("focus_values must not contain duplicates.")
        return focus_values


class CropRecommendation(BaseModel):
    """Recommended crop values for the detected object extent."""

    bbox: list[int] | None = Field(
        description="Detected object bounding box as x, y, width, height.",
    )
    rect: list[int] | None = Field(
        description="Centered crop rectangle as x, y, width, height.",
    )
    crop_width: float | None = Field(
        description="Percentage of image width that can be cropped.",
    )
    crop_height: float | None = Field(
        description="Percentage of image height that can be cropped.",
    )


class PositionAnalysis(BaseModel):
    """Indicators for uneven object placement in the image."""

    vertical_imbalance: float = Field(
        description="Relative imbalance between the upper and lower image areas.",
    )
    horizontal_imbalance: float = Field(
        description="Relative imbalance between the left and right image areas.",
    )


class ScanAnalysisResult(BaseModel):
    """Public result of the scan setup analysis."""

    report_version: int
    analysis_type: Literal["scan_analysis"]
    crop_recommendation: CropRecommendation
    position_analysis: PositionAnalysis
    debug_images: dict[str, Any] | None = Field(
        default=None,
        description="Optional diagnostic images requested with debug_images.",
    )


class ScanAnalysisTaskResponse(Task):
    """Task envelope with the typed scan analysis result."""

    result: ScanAnalysisResult | None = None


@router.post(
    "",
    response_model=ScanAnalysisTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_scan_analysis(request: ScanAnalysisRequest) -> ScanAnalysisTaskResponse:
    """Start a scan setup analysis task."""
    try:
        return await scan_analysis_service.start_scan_analysis(
            camera_name=request.camera_name,
            turntable_offsets=request.turntable_offsets,
            settle_time_s=request.settle_time_s,
            focus_values=request.focus_values,
            debug_images=request.debug_images,
            depends_on=request.depends_on,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
