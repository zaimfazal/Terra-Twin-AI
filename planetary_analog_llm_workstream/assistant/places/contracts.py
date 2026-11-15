"""Typed contracts for natural-language place (candidate) retrieval."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from assistant.contracts import DataProvenanceMode

MetricName = Literal[
    "roughness",
    "relief",
    "slope",
    "aridity",
    "thermal",
    "rockiness",
    "volcanic",
    "access",
]
PlanetName = Literal["Earth", "Moon", "Mars"]


class NumericRange(BaseModel):
    """A numeric filter on a documented 0-100 platform index.

    Ranges are only created when the user states explicit numbers. Unit is the
    platform's dimensionless index, never a physical measurement.
    """

    model_config = ConfigDict(extra="forbid")

    minimum: float | None = None
    maximum: float | None = None
    unit: str = "platform_index_0_100"

    @model_validator(mode="after")
    def _check_bounds(self) -> NumericRange:
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("minimum must not be greater than maximum")
        return self


class BoundingBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_latitude: float = Field(ge=-90, le=90)
    max_latitude: float = Field(ge=-90, le=90)
    min_longitude: float = Field(ge=-180, le=180)
    max_longitude: float = Field(ge=-180, le=180)

    @model_validator(mode="after")
    def _check_box(self) -> BoundingBox:
        if self.min_latitude > self.max_latitude:
            raise ValueError("min_latitude must not exceed max_latitude")
        return self


class RadiusFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_km: float = Field(gt=0, le=20000)


class CandidateSearchFilters(BaseModel):
    """Only fields that actually exist in the team's Analog records."""

    model_config = ConfigDict(extra="forbid")

    text_terms: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    primary_planet_analogs: list[str] = Field(default_factory=list)
    target_ids: list[str] = Field(default_factory=list)
    dataset_terms: list[str] = Field(default_factory=list)
    metrics: dict[MetricName, NumericRange] = Field(default_factory=dict)
    bounding_box: BoundingBox | None = None
    radius: RadiusFilter | None = None


class UnavailableField(BaseModel):
    """A requested dimension the candidate records cannot support."""

    model_config = ConfigDict(extra="forbid")

    field: str
    reason: str
    requested_value: str | None = None


class MatchExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    kind: Literal["text", "categorical", "numeric_range", "geographic"]
    requested: str
    matched_value: str


class PlaceSearchResult(BaseModel):
    """One candidate, with supplied values echoed and provenance attached."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    name: str | None = None
    country: str | None = None
    primary_planet_analog: str | None = None
    target_match_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    elevation_text: str | None = None
    morphology: str | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    metric_provenance: str | None = None
    similarity_score: int | float | None = None
    data_coverage: int | float | None = None
    data_confidence: int | float | None = None
    score_provenance: str | None = None
    match_explanations: list[MatchExplanation] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    source_reference: str = "/api/analog/{id}"
    is_fixture: bool = False


class PlaceSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str | None = Field(default=None, max_length=2000)
    target: str | None = Field(default=None, max_length=200)
    planetary_reference: PlanetName | None = None
    filters: CandidateSearchFilters | None = None
    max_results: int = Field(default=10, ge=1, le=50)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _require_input(self) -> PlaceSearchRequest:
        if not (self.question and self.question.strip()) and self.filters is None:
            raise ValueError("provide a non-blank question or explicit filters")
        return self


class PlaceSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str | None = None
    interpreted_filters: CandidateSearchFilters
    planetary_reference: PlanetName | None = None
    resolved_target_id: str | None = None
    resolved_target_name: str | None = None
    results: list[PlaceSearchResult] = Field(default_factory=list)
    total_matched: int = 0
    returned: int = 0
    limit: int = 10
    offset: int = 0
    data_provenance_mode: DataProvenanceMode
    backend: str
    ordering: Literal["backend_order_preserved"] = "backend_order_preserved"
    unavailable_fields: list[UnavailableField] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
