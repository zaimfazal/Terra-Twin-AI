"""Normalised read-only records exposed by the team Express backend.

These models are deliberately separate from the evidence contracts in
``assistant.contracts``. The team backend supplies catalog metadata and
heuristic 0-100 indices; it does **not** supply verified feature measurements,
reports or evidence items. Nothing here may be promoted to a verified
``EvidenceItem`` automatically.

Every value is either supplied verbatim or ``None``. A missing metric is never
converted to ``0``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from assistant.contracts import CandidateRecord, Coordinates, DatasetProvenance, TargetRecord

DOCUMENTED_METRIC_KEYS: tuple[str, ...] = (
    "roughness",
    "relief",
    "slope",
    "aridity",
    "thermal",
    "rockiness",
    "volcanic",
    "access",
)

METRIC_PROVENANCE = (
    "platform_heuristic_index (0-100, produced by the team similarity engine; "
    "unverified, not a physical measurement)"
)
SCORE_PROVENANCE = (
    "platform_supplied (schema-backed heuristic value; unverified, defaults may "
    "apply when the record omits it)"
)


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _as_number(value: Any) -> int | float | None:
    """Preserve the supplied JSON number type (no rounding, no coercion)."""

    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return value


def _as_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _coordinates(raw: dict[str, Any]) -> tuple[float | None, float | None, str | None]:
    """Read both coordinate shapes without inventing a value.

    MongoDB ``Analog`` documents use GeoJSON ``location.coordinates = [lon, lat]``.
    The in-memory catalogue uses ``coordinates = {lat, lon}``.
    """

    location = raw.get("location")
    if isinstance(location, dict):
        coords = location.get("coordinates")
        if isinstance(coords, list | tuple) and len(coords) == 2:
            lon = _as_float(coords[0])
            lat = _as_float(coords[1])
            if lat is not None and lon is not None:
                return lat, lon, "geojson_location"

    coords = raw.get("coordinates")
    if isinstance(coords, dict):
        lat = _as_float(coords.get("lat"))
        lon = _as_float(coords.get("lon"))
        if lat is not None and lon is not None:
            return lat, lon, "catalog_coordinates"

    return None, None, None


class AnalogRecord(BaseModel):
    """One Earth analog candidate as supplied by the team backend."""

    model_config = ConfigDict(extra="forbid")

    analog_id: str
    name: str | None = None
    country: str | None = None
    elevation_text: str | None = None
    morphology: str | None = None
    primary_planet_analog: str | None = None
    target_match_id: str | None = None
    nasa_datasets_used: list[str] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)
    metric_provenance: str = METRIC_PROVENANCE
    similarity_score: int | float | None = None
    data_coverage: int | float | None = None
    data_confidence: int | float | None = None
    score_provenance: str = SCORE_PROVENANCE
    scientific_breakdown: dict[str, str] = Field(default_factory=dict)
    latitude: float | None = None
    longitude: float | None = None
    coordinate_source: str | None = None
    image_url: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    provenance_mode: Literal["team_backend_read_only"] = "team_backend_read_only"
    is_fixture: bool = False

    @property
    def has_numeric_elevation(self) -> bool:
        """The team schema stores elevation as display text, not a number."""

        return False

    def to_candidate_record(self) -> CandidateRecord:
        coordinates = None
        if self.latitude is not None and self.longitude is not None:
            coordinates = Coordinates(latitude=self.latitude, longitude=self.longitude)
        return CandidateRecord(
            candidate_id=self.analog_id,
            name=self.name,
            planet="Earth",
            region_name=self.country,
            coordinates=coordinates,
            target_id=self.target_match_id,
            is_fixture=self.is_fixture,
        )


class TargetInfo(BaseModel):
    """A planetary reference target from ``GET /api/targets``."""

    model_config = ConfigDict(extra="forbid")

    target_id: str
    name: str | None = None
    planet: Literal["Moon", "Mars", "Earth", "other"] = "other"
    elevation_text: str | None = None
    mission_profile: str | None = None
    nasa_primary_source: str | None = None
    description: str | None = None
    scientific_targets: list[str] = Field(default_factory=list)
    criteria_signature: dict[str, float] = Field(default_factory=dict)
    criteria_provenance: str = METRIC_PROVENANCE
    latitude: float | None = None
    longitude: float | None = None
    coordinate_source: str | None = None
    image_url: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    is_fixture: bool = False

    def to_target_record(self) -> TargetRecord:
        return TargetRecord(
            target_id=self.target_id,
            name=self.name or self.target_id,
            planet=self.planet,
            mission_profiles=[self.mission_profile] if self.mission_profile else [],
            is_fixture=self.is_fixture,
        )


class DatasetInfo(BaseModel):
    """A dataset catalogue entry from ``GET /api/nasa-datasets``."""

    model_config = ConfigDict(extra="forbid")

    dataset_key: str
    dataset_id: str | None = None
    name: str | None = None
    provider: str | None = None
    instrument: str | None = None
    spatial_resolution: str | None = None
    coverage: str | None = None
    parameters: list[str] = Field(default_factory=list)
    url: str | None = None
    doi: str | None = None
    missing_fields: list[str] = Field(default_factory=list)

    def to_dataset_provenance(self) -> DatasetProvenance:
        return DatasetProvenance(
            source_id=self.dataset_key,
            dataset_name=self.name or self.dataset_key,
            organization=self.provider,
            instrument_or_mission=self.instrument,
            spatial_resolution=self.spatial_resolution,
            url=self.url,
            doi=self.doi,
            is_fixture=False,
        )


def normalise_analog(raw: dict[str, Any]) -> AnalogRecord:
    missing: list[str] = []

    analog_id = _as_text(raw.get("id"))
    if analog_id is None:
        raise ValueError("analog record is missing 'id'")

    metrics: dict[str, float] = {}
    raw_metrics = raw.get("metrics")
    if isinstance(raw_metrics, dict):
        for key in DOCUMENTED_METRIC_KEYS:
            value = _as_float(raw_metrics.get(key))
            if value is None:
                missing.append(f"metrics.{key}")
            else:
                metrics[key] = value
    else:
        missing.extend(f"metrics.{key}" for key in DOCUMENTED_METRIC_KEYS)

    for field in ("name", "country", "elevation", "morphology", "primary_planet_analog"):
        if _as_text(raw.get(field)) is None:
            missing.append(field)

    breakdown: dict[str, str] = {}
    raw_breakdown = raw.get("scientific_breakdown")
    if isinstance(raw_breakdown, dict):
        for key in ("why_analog", "breakdown_limits", "field_test_utility"):
            text = _as_text(raw_breakdown.get(key))
            if text is None:
                missing.append(f"scientific_breakdown.{key}")
            else:
                breakdown[key] = text
    else:
        missing.append("scientific_breakdown")

    latitude, longitude, coordinate_source = _coordinates(raw)
    if latitude is None or longitude is None:
        missing.append("location.coordinates")
    # Elevation is stored as display text with units embedded; a numeric value is
    # never derived here, so numeric elevation is always reported unavailable.
    missing.append("elevation_numeric")

    datasets = raw.get("nasa_datasets_used")
    nasa_datasets_used = (
        [item for item in datasets if isinstance(item, str) and item.strip()]
        if isinstance(datasets, list)
        else []
    )
    if not nasa_datasets_used:
        missing.append("nasa_datasets_used")

    similarity = _as_number(raw.get("similarity_score"))
    coverage = _as_number(raw.get("data_coverage"))
    confidence = _as_number(raw.get("data_confidence"))
    for label, value in (
        ("similarity_score", similarity),
        ("data_coverage", coverage),
        ("data_confidence", confidence),
    ):
        if value is None:
            missing.append(label)

    return AnalogRecord(
        analog_id=analog_id,
        name=_as_text(raw.get("name")),
        country=_as_text(raw.get("country")),
        elevation_text=_as_text(raw.get("elevation")),
        morphology=_as_text(raw.get("morphology")),
        primary_planet_analog=_as_text(raw.get("primary_planet_analog")),
        target_match_id=_as_text(raw.get("target_match_id")),
        nasa_datasets_used=nasa_datasets_used,
        metrics=metrics,
        similarity_score=similarity,
        data_coverage=coverage,
        data_confidence=confidence,
        scientific_breakdown=breakdown,
        latitude=latitude,
        longitude=longitude,
        coordinate_source=coordinate_source,
        image_url=_as_text(raw.get("image")),
        missing_fields=sorted(set(missing)),
    )


def normalise_planet(value: Any) -> Literal["Moon", "Mars", "Earth", "other"]:
    text = (value or "").strip().casefold() if isinstance(value, str) else ""
    if text == "moon":
        return "Moon"
    if text == "mars":
        return "Mars"
    if text == "earth":
        return "Earth"
    return "other"


def normalise_target(raw: dict[str, Any]) -> TargetInfo:
    missing: list[str] = []
    target_id = _as_text(raw.get("id"))
    if target_id is None:
        raise ValueError("target record is missing 'id'")

    signature: dict[str, float] = {}
    raw_signature = raw.get("criteria_signature")
    if isinstance(raw_signature, dict):
        for key in DOCUMENTED_METRIC_KEYS:
            value = _as_float(raw_signature.get(key))
            if value is None:
                missing.append(f"criteria_signature.{key}")
            else:
                signature[key] = value
    else:
        missing.append("criteria_signature")

    for field in ("name", "planet", "elevation", "mission_profile", "nasa_primary_source"):
        if _as_text(raw.get(field)) is None:
            missing.append(field)

    latitude, longitude, coordinate_source = _coordinates(raw)
    if latitude is None or longitude is None:
        missing.append("coordinates")

    targets = raw.get("scientific_targets")
    scientific_targets = (
        [item for item in targets if isinstance(item, str) and item.strip()]
        if isinstance(targets, list)
        else []
    )

    return TargetInfo(
        target_id=target_id,
        name=_as_text(raw.get("name")),
        planet=normalise_planet(raw.get("planet")),
        elevation_text=_as_text(raw.get("elevation")),
        mission_profile=_as_text(raw.get("mission_profile")),
        nasa_primary_source=_as_text(raw.get("nasa_primary_source")),
        description=_as_text(raw.get("description")),
        scientific_targets=scientific_targets,
        criteria_signature=signature,
        latitude=latitude,
        longitude=longitude,
        coordinate_source=coordinate_source,
        image_url=_as_text(raw.get("image")),
        missing_fields=sorted(set(missing)),
    )


def normalise_dataset(raw: dict[str, Any]) -> DatasetInfo:
    missing: list[str] = []
    key = _as_text(raw.get("key"))
    if key is None:
        raise ValueError("dataset record is missing 'key'")

    for field in ("id", "name", "provider", "instrument", "spatial_resolution", "coverage", "url", "doi"):
        if _as_text(raw.get(field)) is None:
            missing.append(field)

    parameters = raw.get("parameters")
    parsed_parameters = (
        [item for item in parameters if isinstance(item, str) and item.strip()]
        if isinstance(parameters, list)
        else []
    )
    if not parsed_parameters:
        missing.append("parameters")

    return DatasetInfo(
        dataset_key=key,
        dataset_id=_as_text(raw.get("id")),
        name=_as_text(raw.get("name")),
        provider=_as_text(raw.get("provider")),
        instrument=_as_text(raw.get("instrument")),
        spatial_resolution=_as_text(raw.get("spatial_resolution")),
        coverage=_as_text(raw.get("coverage")),
        parameters=parsed_parameters,
        url=_as_text(raw.get("url")),
        doi=_as_text(raw.get("doi")),
        missing_fields=sorted(set(missing)),
    )
