"""Typed contracts for cross-planetary image retrieval.

Image relevance and visual resemblance are kept explicitly separate from
geological analogy, environmental analogy, scientific similarity and mission
usefulness. No score is derived from an image.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from assistant.contracts import DataProvenanceMode

ImageProvider = Literal["nasa_image_library", "gibs", "pds"]
PlanetGroup = Literal["earth", "moon", "mars"]
ImageType = Literal[
    "photograph",
    "satellite_image",
    "browse_image",
    "visualization",
    "product",
]
DateType = Literal["acquisition", "publication", "creation", "unknown"]


class ImageRecord(BaseModel):
    """One verified provider image/product record.

    Missing metadata remains ``None``. A URL is only present after host and
    scheme validation against the provider allowlist.
    """

    model_config = ConfigDict(extra="forbid")

    image_id: str
    provider: ImageProvider
    provider_record_id: str | None = None
    title: str | None = None
    description: str | None = None
    planet: PlanetGroup
    location_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    mission: str | None = None
    instrument: str | None = None
    date: str | None = None
    date_type: DateType | None = None
    image_type: ImageType
    thumbnail_url: str | None = None
    asset_url: str | None = None
    source_record_url: str | None = None
    attribution: str | None = None
    licence: str | None = None
    related_candidate_id: str | None = None
    related_target_id: str | None = None
    relevance_explanation: str | None = None
    preview_available: bool = True
    provenance_notes: list[str] = Field(default_factory=list)
    is_fixture: bool = False


class ImageSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: ImageProvider
    collection_url: str
    query: str | None = None
    retrieved_count: int = 0
    attribution: str | None = None


class MissingPreview(BaseModel):
    """A real product with no browse/preview image available."""

    model_config = ConfigDict(extra="forbid")

    provider: ImageProvider = "pds"
    provider_record_id: str | None = None
    title: str | None = None
    product_url: str | None = None
    reason: str = "No browse/preview product was supplied for this record."


class RejectedAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: ImageProvider
    url: str | None = None
    reason: str


class ImageSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str | None = Field(default=None, max_length=200)
    candidate_id: str | None = Field(default=None, max_length=200)
    planets: list[PlanetGroup] = Field(
        default_factory=lambda: ["earth", "moon", "mars"]
    )
    image_types: list[ImageType] = Field(default_factory=list)
    feature_keywords: list[str] = Field(default_factory=list)
    max_per_planet: int = Field(default=5, ge=1, le=20)

    @model_validator(mode="after")
    def _unique_planets(self) -> ImageSearchRequest:
        seen: list[PlanetGroup] = []
        for planet in self.planets:
            if planet not in seen:
                seen.append(planet)
        self.planets = seen
        return self


class ImageSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    earth: list[ImageRecord] = Field(default_factory=list)
    moon: list[ImageRecord] = Field(default_factory=list)
    mars: list[ImageRecord] = Field(default_factory=list)
    sources: list[ImageSource] = Field(default_factory=list)
    missing_previews: list[MissingPreview] = Field(default_factory=list)
    rejected_assets: list[RejectedAsset] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    providers_used: list[ImageProvider] = Field(default_factory=list)
    resolved_target_id: str | None = None
    resolved_candidate_id: str | None = None
    data_provenance_mode: DataProvenanceMode = DataProvenanceMode.PLATFORM
    notice: str = (
        "Image relevance and visual resemblance are not geological evidence and "
        "do not establish scientific equivalence. No scientific similarity score "
        "is derived from images. The platform's existing image matcher is a "
        "heuristic visual demonstration, not a trained or verified measurement."
    )
