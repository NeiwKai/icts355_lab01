"""Request and response contracts.

Validation lives here so a malformed request is rejected with 422 and a useful message,
rather than reaching the model and producing a confident number from nonsense.

The bounds mirror src/data.PLAUSIBLE_RANGES. Keep them in step: when Lab 4 adds a data
contract test, the same bounds are what CI asserts against.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field

class PredictRequest(BaseModel):
    temp_c: float = Field(..., ge=-10, le=140)
    vibration_mm_s: float = Field(..., ge=0, le=60)
    pressure_kpa: float = Field(..., ge=0, le=600)
    hours_since_service: float = Field(..., ge=0, le=20000)
    load_pct: float = Field(..., ge=0, le=100)
    ambient_humidity: float = Field(..., ge=0, le=100)

    # Use 'pad' as the Python attribute and alias='_pad' for JSON payload parsing
    pad: Optional[str] = Field(default=None, alias="_pad")

    model_config = {"populate_by_name": True, "extra": "forbid"}


class PredictResponse(BaseModel):
    probability: float
    model_version: str


class BatchRequest(BaseModel):
    rows: list[PredictRequest] = Field(..., min_length=1, max_length=100)


class BatchResponse(BaseModel):
    probabilities: list[float]
    model_version: str


class VertexPredictRequest(BaseModel):
    instances: list[PredictRequest] = Field(..., min_length=1, max_length=100)


# FORCE PYDANTIC TO RESOLVE TYPE ANNOTATIONS AT IMPORT TIME
PredictRequest.model_rebuild()
BatchRequest.model_rebuild()
VertexPredictRequest.model_rebuild()
