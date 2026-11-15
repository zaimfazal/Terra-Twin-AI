"""Mocked tests for image providers, validation and cross-planetary grouping.

No live NASA service is contacted. Every HTTP response is constructed in-process.
"""

from __future__ import annotations

import httpx
import pytest

from assistant.images.contracts import (
    ImageRecord,
    ImageSearchRequest,
    ImageSource,
)
from assistant.images.orchestrator import ImageRetrievalService
from assistant.images.providers.base import ProviderError, ProviderOutcome, RateLimited
from assistant.images.providers.gibs import GibsProvider
from assistant.images.providers.nasa_library import NasaImageLibraryProvider
from assistant.images.providers.pds import PdsProvider
from assistant.images.validation import (
    UnsafeAssetURL,
    validate_content_type,
    validate_provider_url,
)

NASA_SEARCH = {
    "collection": {
        "items": [
            {
                "data": [
                    {
                        "nasa_id": "PIA12345",
                        "title": "Jezero Crater",
                        "description": "Mars delta.",
                        "date_created": "2021-02-18T00:00:00Z",
                        "center": "JPL",
                    }
                ],
                "links": [
                    {"href": "https://images-assets.nasa.gov/image/PIA12345/thumb.jpg"}
                ],
            }
        ]
    }
}

NASA_ASSET = [
    "https://images-assets.nasa.gov/image/PIA12345/thumb.jpg",
    {"href": "https://images-assets.nasa.gov/image/PIA12345/PIA12345.jpg"},
]


def nasa_transport(routes):
    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        value = routes.get(key)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, httpx.Response):
            return value
        return httpx.Response(200, json=value if value is not None else {})

    return httpx.MockTransport(handler)


def nasa_provider(routes) -> NasaImageLibraryProvider:
    return NasaImageLibraryProvider(transport=nasa_transport(routes))


# ---------------------------------------------------------------------------
# URL / content validation
# ---------------------------------------------------------------------------
def test_url_validation_accepts_only_allowlisted_https_hosts() -> None:
    assert (
        validate_provider_url(
            "https://images-assets.nasa.gov/image/x/x.jpg", "nasa_image_library"
        )
        == "https://images-assets.nasa.gov/image/x/x.jpg"
    )

    for bad in (
        "http://images-assets.nasa.gov/image/x/x.jpg",
        "https://user:pw@images-assets.nasa.gov/x.jpg",
        "https://images-assets.nasa.gov:8443/x.jpg",
        "https://127.0.0.1/x.jpg",
        "https://localhost/x.jpg",
        "https://evil.example/x.jpg",
        "https://images-assets.nasa.gov.evil.example/x.jpg",
        "file:///etc/passwd",
    ):
        with pytest.raises(UnsafeAssetURL):
            validate_provider_url(bad, "nasa_image_library")


def test_content_type_validation() -> None:
    assert validate_content_type("image/jpeg") is True
    assert validate_content_type("image/png; charset=binary") is True
    assert validate_content_type("text/html") is False
    assert validate_content_type("application/json") is False
    assert validate_content_type("application/json", allow_json=True) is True


# ---------------------------------------------------------------------------
# NASA Image Library
# ---------------------------------------------------------------------------
def test_nasa_image_library_success_preserves_metadata_and_urls() -> None:
    provider = nasa_provider(
        {
            ("GET", "/search"): NASA_SEARCH,
            ("GET", "/asset/PIA12345"): NASA_ASSET,
        }
    )
    outcome = provider.search("Jezero Crater", planet="mars", limit=5)
    provider.close()

    assert len(outcome.records) == 1
    record = outcome.records[0]
    assert record.provider_record_id == "PIA12345"
    assert record.planet == "mars"
    assert record.title == "Jezero Crater"
    assert record.thumbnail_url.endswith("thumb.jpg")
    assert record.asset_url.endswith("PIA12345.jpg")
    assert record.date == "2021-02-18T00:00:00Z"
    assert record.date_type == "creation"
    assert record.mission is None and record.instrument is None
    assert record.licence is None
    assert "JPL" in (record.attribution or "")
    assert outcome.sources[0].retrieved_count == 1


def test_nasa_image_library_empty_result_is_explicit() -> None:
    provider = nasa_provider({("GET", "/search"): {"collection": {"items": []}}})

    outcome = provider.search("nothing", planet="mars", limit=5)
    provider.close()

    assert outcome.records == []
    assert outcome.sources[0].retrieved_count == 0


def test_nasa_image_library_rejects_untrusted_asset_host() -> None:
    provider = nasa_provider(
        {
            ("GET", "/search"): NASA_SEARCH,
            ("GET", "/asset/PIA12345"): [
                {"href": "https://evil.example/PIA12345.jpg"}
            ],
        }
    )

    outcome = provider.search("Jezero", planet="mars", limit=5)
    provider.close()

    assert len(outcome.records) == 1
    assert outcome.records[0].asset_url.endswith("thumb.jpg")
    assert outcome.rejected_assets
    assert "not an allowed" in outcome.rejected_assets[0].reason


def test_nasa_image_library_handles_missing_thumbnail() -> None:
    no_links = {
        "collection": {
            "items": [
                {
                    "data": [{"nasa_id": "PIA1", "title": "No thumb"}],
                }
            ]
        }
    }
    provider = nasa_provider(
        {
            ("GET", "/search"): no_links,
            ("GET", "/asset/PIA1"): [
                {"href": "https://images-assets.nasa.gov/image/PIA1/PIA1.jpg"}
            ],
        }
    )

    outcome = provider.search("Mars", planet="mars", limit=5)
    provider.close()

    assert len(outcome.records) == 1
    assert outcome.records[0].thumbnail_url is None
    assert outcome.records[0].asset_url.endswith("PIA1.jpg")


def test_nasa_image_library_timeout_and_rate_limit() -> None:
    timeout_provider = nasa_provider(
        {("GET", "/search"): httpx.ConnectTimeout("slow")}
    )
    with pytest.raises(ProviderError):
        timeout_provider.search("Mars", planet="mars", limit=5)
    timeout_provider.close()

    limited_provider = nasa_provider(
        {
            ("GET", "/search"): httpx.Response(
                429, headers={"retry-after": "30"}, json={}
            )
        }
    )
    with pytest.raises(RateLimited) as excinfo:
        limited_provider.search("Mars", planet="mars", limit=5)
    limited_provider.close()
    assert excinfo.value.retry_after == "30"


# ---------------------------------------------------------------------------
# GIBS
# ---------------------------------------------------------------------------
def test_gibs_builds_validated_wms_request_for_earth() -> None:
    provider = GibsProvider()

    outcome = provider.layer_image(
        layer="MODIS_Terra_CorrectedReflectance_TrueColor",
        latitude=-24.08,
        longitude=-70.02,
        target_layer_date="2024-01-15",
        related_candidate_id="earth_atacama",
    )
    provider.close()

    assert len(outcome.records) == 1
    record = outcome.records[0]
    assert record.planet == "earth"
    assert record.image_type == "visualization"
    assert record.provider == "gibs"
    assert record.asset_url
    assert "LAYERS=MODIS_Terra_CorrectedReflectance_TrueColor" in record.asset_url
    assert "TIME=2024-01-15" in record.asset_url
    assert record.latitude == -24.08


def test_gibs_refuses_unsupported_layer_and_invalid_date() -> None:
    provider = GibsProvider()

    bad_layer = provider.layer_image(
        layer="MADE_UP_LAYER",
        latitude=1.0,
        longitude=2.0,
        target_layer_date=None,
    )
    bad_date = provider.layer_image(
        layer="MODIS_Terra_CorrectedReflectance_TrueColor",
        latitude=1.0,
        longitude=2.0,
        target_layer_date="15-01-2024",
    )
    provider.close()

    assert bad_layer.records == []
    assert any("not in the supported layer list" in x for x in bad_layer.limitations)
    assert bad_date.records == []
    assert any("YYYY-MM-DD" in x for x in bad_date.limitations)


def test_gibs_skips_without_coordinates_and_never_invents_them() -> None:
    provider = GibsProvider()

    outcome = provider.layer_image(
        layer=None, latitude=None, longitude=None, target_layer_date=None
    )
    provider.close()

    assert outcome.records == []
    assert any("Coordinates are never invented" in x for x in outcome.limitations)


# ---------------------------------------------------------------------------
# PDS
# ---------------------------------------------------------------------------
def test_pds_returns_browse_product_and_missing_preview() -> None:
    payload = {
        "Products": [
            {
                "ProductId": "MRO_HIRISE_1",
                "Title": "HiRISE target",
                "BrowseUrl": "https://hirise.lpl.arizona.edu/images/1.jpg",
                "ProductUrl": "https://hirise.lpl.arizona.edu/product/1",
                "Mission": "Mars Reconnaissance Orbiter",
                "Instrument": "HiRISE",
                "StartTime": "2020-05-01T00:00:00Z",
            },
            {
                "ProductId": "MRO_HIRISE_2",
                "Title": "No browse product",
                "ProductUrl": "https://hirise.lpl.arizona.edu/product/2",
            },
        ]
    }
    provider = PdsProvider(transport=nasa_transport({("GET", "/live2/"): payload}))

    outcome = provider.search(target="mars", keywords=["crater"], limit=5)
    provider.close()

    assert len(outcome.records) == 1
    record = outcome.records[0]
    assert record.planet == "mars"
    assert record.instrument == "HiRISE"
    assert record.date_type == "acquisition"
    assert len(outcome.missing_previews) == 1
    assert outcome.missing_previews[0].provider_record_id == "MRO_HIRISE_2"
    assert outcome.missing_previews[0].product_url.endswith("/product/2")


def test_pds_unrecognised_response_returns_no_fabricated_products() -> None:
    provider = PdsProvider(
        transport=nasa_transport({("GET", "/live2/"): {"unexpected": "shape"}})
    )

    outcome = provider.search(target="moon", keywords=[], limit=5)
    provider.close()

    assert outcome.records == []
    assert any("not recognised" in x for x in outcome.limitations)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
class FakeNasa:
    def __init__(self, records, error=None):
        self.records = records
        self.error = error
        self.queries = []

    def search(self, query, *, planet, limit, **kwargs):
        self.queries.append((query, planet))
        if self.error:
            raise self.error
        outcome = ProviderOutcome()
        outcome.records = [r for r in self.records if r.planet == planet][:limit]
        outcome.sources = [
            ImageSource(
                provider="nasa_image_library",
                collection_url="https://images-api.nasa.gov/search",
                query=query,
                retrieved_count=len(outcome.records),
            )
        ]
        return outcome

    def close(self):
        pass


class FakeGibs:
    def __init__(self, records):
        self.records = records

    def layer_image(self, **kwargs):
        outcome = ProviderOutcome()
        outcome.records = [r for r in self.records if r.planet == "earth"]
        outcome.sources = [
            ImageSource(
                provider="gibs",
                collection_url="https://gibs.earthdata.nasa.gov/wms",
                retrieved_count=len(outcome.records),
            )
        ]
        return outcome

    def close(self):
        pass


class FakePds:
    def __init__(self, records):
        self.records = records

    def search(self, *, target, keywords, limit, **kwargs):
        outcome = ProviderOutcome()
        outcome.records = [r for r in self.records if r.planet == target][:limit]
        return outcome

    def close(self):
        pass


class ImageAdapter:
    data_provenance_mode = "platform"
    backend_name = "fake_team_backend"

    def __init__(self, candidate=None, target=None):
        self.candidate = candidate
        self.target = target

    def get_analog(self, candidate_id):
        return self.candidate if self.candidate and self.candidate.analog_id == candidate_id else None

    def find_target(self, target_id):
        return self.target


def image_record(image_id: str, planet: str, provider: str = "nasa_image_library"):
    return ImageRecord(
        image_id=image_id,
        provider=provider,  # type: ignore[arg-type]
        planet=planet,  # type: ignore[arg-type]
        title=image_id,
        image_type="photograph" if provider == "nasa_image_library" else "visualization",
        asset_url=f"https://images-assets.nasa.gov/image/{image_id}/{image_id}.jpg",
    )


class Candidate:
    analog_id = "earth_atacama"
    name = "Atacama"
    country = "Chile"
    morphology = "HYPER-ARID REGOLITH"
    target_match_id = "mars_jezero"
    latitude = -24.08
    longitude = -70.02


class Target:
    target_id = "mars_jezero"
    name = "Jezero Crater"
    scientific_targets = ["deltaic sediments"]


def make_image_service(nasa=None, gibs=None, pds=None, candidate=Candidate(), target=Target()):
    adapter = ImageAdapter(candidate=candidate, target=target)
    return ImageRetrievalService(
        adapter,
        nasa_library=nasa or FakeNasa([]),
        gibs=gibs or FakeGibs([]),
        pds=pds or FakePds([]),
    )


def test_orchestrator_groups_earth_moon_and_mars_and_deduplicates() -> None:
    nasa = FakeNasa(
        [
            image_record("e1", "earth"),
            image_record("e1", "earth"),
            image_record("m1", "moon"),
            image_record("ma1", "mars"),
        ]
    )
    service = make_image_service(
        nasa=nasa,
        gibs=FakeGibs([image_record("g1", "earth", provider="gibs")]),
        pds=FakePds([image_record("p1", "mars", provider="pds")]),
    )

    response = service.search(
        ImageSearchRequest(candidate_id="earth_atacama", max_per_planet=2)
    )

    assert [r.image_id for r in response.earth] == ["e1", "g1"]
    assert [r.image_id for r in response.moon] == ["m1"]
    assert [r.image_id for r in response.mars] == ["ma1", "p1"]
    assert set(response.providers_used) == {"nasa_image_library", "gibs", "pds"}
    assert any("Earth" in query for query, _ in nasa.queries)
    assert response.resolved_candidate_id == "earth_atacama"
    assert response.resolved_target_id == "mars_jezero"
    assert "not geological evidence" in response.notice


def test_orchestrator_keeps_other_providers_when_one_fails() -> None:
    nasa = FakeNasa([], error=ProviderError("timeout"))
    service = make_image_service(
        nasa=nasa, pds=FakePds([image_record("p1", "mars", provider="pds")])
    )

    response = service.search(
        ImageSearchRequest(target="Jezero Crater", max_per_planet=2)
    )

    assert [r.image_id for r in response.mars] == ["p1"]
    assert any("NASA Image Library unavailable" in item for item in response.limitations)


def test_orchestrator_respects_planet_selection_and_image_types() -> None:
    nasa = FakeNasa([image_record("e1", "earth"), image_record("m1", "moon")])
    service = make_image_service(nasa=nasa)

    response = service.search(
        ImageSearchRequest(
            candidate_id="earth_atacama",
            planets=["earth"],
            image_types=["photograph"],
        )
    )

    assert [r.image_id for r in response.earth] == ["e1"]
    assert response.moon == [] and response.mars == []
    assert nasa.queries == [
        ("Earth Atacama Chile HYPER-ARID REGOLITH deltaic sediments Jezero Crater", "earth")
    ]


def test_orchestrator_rate_limit_returns_partial_results_with_retry_after() -> None:
    nasa = FakeNasa([], error=RateLimited("limited", retry_after="60"))
    service = make_image_service(
        nasa=nasa,
        pds=FakePds([image_record("p1", "mars", provider="pds")]),
    )

    response = service.search(
        ImageSearchRequest(target="Jezero Crater", max_per_planet=2)
    )

    assert [r.image_id for r in response.mars] == ["p1"]
    assert any(
        "rate limit reached" in item and "retry after 60" in item
        for item in response.limitations
    )


def test_orchestrator_deduplicates_identical_asset_urls_across_providers() -> None:
    shared = "https://images-assets.nasa.gov/image/shared/shared.jpg"
    first = image_record("a1", "earth")
    first.asset_url = shared
    second = image_record("a2", "earth")
    second.asset_url = shared
    service = make_image_service(nasa=FakeNasa([first, second]))

    response = service.search(
        ImageSearchRequest(candidate_id="earth_atacama", planets=["earth"])
    )

    assert [r.image_id for r in response.earth] == ["a1"]


def test_image_response_carries_no_scientific_score_field() -> None:
    from assistant.images.contracts import ImageSearchResponse

    response = make_image_service(
        nasa=FakeNasa([image_record("e1", "earth")])
    ).search(ImageSearchRequest(candidate_id="earth_atacama", planets=["earth"]))

    forbidden = {
        "similarity_score",
        "visual_similarity",
        "geological_analogy_score",
        "confidence",
    }
    assert forbidden.isdisjoint(ImageSearchResponse.model_fields)
    assert forbidden.isdisjoint(response.earth[0].model_fields)
    assert "heuristic visual demonstration" in response.notice


def test_orchestrator_reports_unknown_candidate_without_inventing_imagery() -> None:
    service = make_image_service()

    response = service.search(ImageSearchRequest(candidate_id="missing", planets=["earth"]))

    assert response.resolved_candidate_id is None
    assert any("was not found" in item for item in response.limitations)


def test_api_images_route(test_settings) -> None:
    from fastapi.testclient import TestClient

    from assistant.api import create_app
    from assistant.service import AssistantService

    image_service = make_image_service(
        nasa=FakeNasa([image_record("e1", "earth"), image_record("m1", "moon")])
    )
    service = AssistantService(
        test_settings,
        adapter=ImageAdapter(candidate=Candidate(), target=Target()),
        image_service=image_service,
    )
    try:
        with TestClient(create_app(service=service)) as client:
            response = client.post(
                "/api/assistant/images/search",
                json={"candidate_id": "earth_atacama", "planets": ["earth", "moon"]},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["earth"][0]["image_id"] == "e1"
        assert data["moon"][0]["image_id"] == "m1"
        assert data["mars"] == []
        assert "not geological evidence" in data["notice"]
    finally:
        service.store.close()
