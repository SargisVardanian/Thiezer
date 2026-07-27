from fastapi import APIRouter
from pydantic import BaseModel, Field

from thiezer.domain.contracts import ObservationMode, SkyScoreBreakdown, TargetKind
from thiezer.domain.scoring import ScoreInputs, calculate_sky_score

router = APIRouter(prefix="/v1/scoring", tags=["scoring"])


class ScorePreviewRequest(BaseModel):
    target: TargetKind
    mode: ObservationMode
    cloud_clearance: float = Field(ge=0.0, le=1.0)
    darkness: float = Field(ge=0.0, le=1.0)
    transparency: float = Field(ge=0.0, le=1.0)
    moon_conditions: float = Field(ge=0.0, le=1.0)
    dew_margin: float = Field(ge=0.0, le=1.0)
    wind: float = Field(ge=0.0, le=1.0)
    target_altitude: float = Field(ge=0.0, le=1.0)
    accessibility: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    sun_dark_enough: bool = True
    target_above_horizon: bool = True
    severe_cloud: bool = False
    place_accessible: bool = True
    normalized_drive_cost: float = Field(default=0.0, ge=0.0, le=1.0)
    normalized_risk: float = Field(default=0.0, ge=0.0, le=1.0)


@router.post("/preview", response_model=SkyScoreBreakdown)
async def preview_score(request: ScorePreviewRequest) -> SkyScoreBreakdown:
    return calculate_sky_score(
        target=request.target,
        mode=request.mode,
        inputs=ScoreInputs(**request.model_dump(exclude={"target", "mode"})),
    )
