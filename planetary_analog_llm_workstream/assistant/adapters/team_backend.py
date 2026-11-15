"""Read-only HTTP adapter for the team's Node/Express backend.

The Node backend owns MongoDB. This adapter holds **no database credentials**
and never writes scientific records. It issues only:

* ``GET /api/health``
* ``GET /api/analog``
* ``GET /api/analog/{id}``
* ``GET /api/targets``
* ``GET /api/mission-profiles``
* ``GET /api/nasa-datasets``
* ``GET /api/analog/nearby``
* ``POST /api/analog/within-polygon`` (read-only geospatial query)

The two ``POST`` calls are documented read-only queries in the team controller
and do not mutate stored data.

Reference: ``docs/llm/TEAM_INTEGRATION.md``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx

from assistant.adapters.base import AdapterUnavailable
from assistant.adapters.team_records import (
    AnalogRecord,
    DatasetInfo,
    TargetInfo,
    normalise_analog,
    normalise_dataset,
    normalise_target,
)
from assistant.contracts import (
    CandidateRecord,
    ContradictionRecord,
    DatasetProvenance,
    EvidenceItem,
    ReportRecord,
    TargetRecord,
)

READ_ONLY_POST_PATHS = frozenset({"/api/analog/within-polygon"})


class TeamBackendAdapter:
    """Client for the team Express API. Read-only by construction."""

    backend_name = "terratwin_express"
    data_provenance_mode = "platform"
    reports_supported = False
    evidence_supported = False

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 10.0,
        max_retries: int = 1,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = self._validate_base_url(base_url)
        self.timeout_s = timeout_s
        self.max_retries = max(0, max_retries)
        self._owns_client = client is None
        if client is not None:
            self._client = client
        else:
            self._client = httpx.Client(
                timeout=httpx.Timeout(timeout_s, connect=min(5.0, timeout_s)),
                headers={"Accept": "application/json"},
                follow_redirects=False,
                transport=transport,
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> TeamBackendAdapter:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Protocol methods consumed by the existing assistant service
    # ------------------------------------------------------------------
    def get_candidate(self, candidate_id: str) -> CandidateRecord | None:
        analog = self.get_analog(candidate_id)
        return analog.to_candidate_record() if analog is not None else None

    def list_candidates(self, limit: int = 50) -> list[CandidateRecord]:
        return [analog.to_candidate_record() for analog in self.list_analogs(limit=limit)]

    def get_target(self, target_id_or_name: str) -> TargetRecord | None:
        target = self.find_target(target_id_or_name)
        return target.to_target_record() if target is not None else None

    def get_report(self, report_id: str) -> ReportRecord | None:
        # The team backend exposes no report documents. Returning None is the
        # honest answer; it must not be replaced with a synthesised report.
        return None

    def get_reports_for_candidate(self, candidate_id: str) -> list[ReportRecord]:
        return []

    def get_evidence_for_candidate(self, candidate_id: str) -> list[EvidenceItem]:
        # The team API exposes catalog metadata and heuristic indices, not
        # verified feature measurements. Do not promote metrics to evidence.
        return []

    def get_evidence(self, evidence_ids: list[str]) -> list[EvidenceItem]:
        return []

    def get_contradictions(self, candidate_id: str) -> list[ContradictionRecord]:
        return []

    def get_dataset_sources(self, source_ids: list[str]) -> list[DatasetProvenance]:
        wanted = set(source_ids)
        return [
            dataset.to_dataset_provenance()
            for dataset in self.list_datasets()
            if dataset.dataset_key in wanted
        ]

    # ------------------------------------------------------------------
    # Team-specific read methods
    # ------------------------------------------------------------------
    def server_health(self) -> dict[str, Any]:
        return self._request_json("GET", "/api/health") or {}

    def health(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "backend": self.backend_name,
            "base_url": self.base_url,
            "data_provenance_mode": self.data_provenance_mode,
            "reports_supported": self.reports_supported,
            "evidence_supported": self.evidence_supported,
        }
        try:
            body = self.server_health()
        except AdapterUnavailable as exc:
            payload.update({"reachable": False, "error": str(exc)})
            return payload
        payload.update(
            {
                "reachable": True,
                "service": body.get("service"),
                "database": body.get("database"),
                "version": body.get("version"),
            }
        )
        return payload

    def list_analogs(self, limit: int | None = None) -> list[AnalogRecord]:
        body = self._request_json("GET", "/api/analog")
        records = self._extract_list(body, "analogs")
        analogs = [normalise_analog(item) for item in records if isinstance(item, dict)]
        if limit is not None:
            return analogs[: max(0, limit)]
        return analogs

    def get_analog(self, analog_id: str) -> AnalogRecord | None:
        body = self._request_json(
            "GET", f"/api/analog/{analog_id}", allow_404=True
        )
        if body is None:
            return None
        return normalise_analog(body)

    def list_targets(self) -> list[TargetInfo]:
        body = self._request_json("GET", "/api/targets")
        records = self._extract_list(body, "targets")
        return [normalise_target(item) for item in records if isinstance(item, dict)]

    def find_target(self, target_id_or_name: str) -> TargetInfo | None:
        needle = target_id_or_name.strip().casefold()
        for target in self.list_targets():
            if target.target_id.casefold() == needle:
                return target
            if target.name and target.name.casefold() == needle:
                return target
        # Allow a unique substring match ("Jezero") without inventing a target.
        matches = [
            target
            for target in self.list_targets()
            if target.name
            and (
                needle in target.name.casefold()
                or needle in (target.description or "").casefold()
            )
        ]
        return matches[0] if len(matches) == 1 else None

    def list_mission_profiles(self) -> list[dict[str, Any]]:
        body = self._request_json("GET", "/api/mission-profiles")
        records = self._extract_list(body, "mission_profiles")
        return [item for item in records if isinstance(item, dict)]

    def list_datasets(self) -> list[DatasetInfo]:
        body = self._request_json("GET", "/api/nasa-datasets")
        records = self._extract_list(body, "datasets")
        return [normalise_dataset(item) for item in records if isinstance(item, dict)]

    def list_analogs_near(
        self, latitude: float, longitude: float, max_distance_km: float = 5000
    ) -> list[AnalogRecord]:
        body = self._request_json(
            "GET",
            "/api/analog/nearby",
            params={
                "lat": latitude,
                "lon": longitude,
                "maxDistanceKm": max_distance_km,
            },
        )
        records = self._extract_list(body, "results")
        return [normalise_analog(item) for item in records if isinstance(item, dict)]

    def analogs_within_polygon(self, coordinates: list[list[float]]) -> list[AnalogRecord]:
        body = self._request_json(
            "POST",
            "/api/analog/within-polygon",
            json_body={"polygon_coordinates": coordinates},
        )
        records = self._extract_list(body, "results")
        return [normalise_analog(item) for item in records if isinstance(item, dict)]

    # ------------------------------------------------------------------
    # HTTP plumbing
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_base_url(base_url: str) -> str:
        candidate = (base_url or "").strip().rstrip("/")
        parts = urlsplit(candidate)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise AdapterUnavailable(
                "TERRATWIN_BACKEND_URL must be an absolute http(s) URL, e.g. "
                "http://localhost:8000"
            )
        if parts.username or parts.password:
            raise AdapterUnavailable(
                "TERRATWIN_BACKEND_URL must not embed credentials"
            )
        if parts.query or parts.fragment:
            raise AdapterUnavailable(
                "TERRATWIN_BACKEND_URL must not contain a query or fragment"
            )
        return candidate

    @staticmethod
    def _extract_list(body: dict[str, Any] | list[Any] | None, key: str) -> list[Any]:
        if body is None:
            return []
        if isinstance(body, list):
            return list(body)
        value = body.get(key)
        if not isinstance(value, list):
            return []
        return value

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        allow_404: bool = False,
    ) -> dict[str, Any] | list[Any] | None:
        if method != "GET" and path not in READ_ONLY_POST_PATHS:
            raise AdapterUnavailable(
                f"refusing non-read-only request: {method} {path}"
            )

        attempts = 1 + (self.max_retries if method == "GET" else 0)
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                response = self._client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                )
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    continue
                raise AdapterUnavailable(
                    f"team backend timed out after {self.timeout_s}s: {method} {path}"
                ) from exc
            except httpx.TransportError as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    continue
                raise AdapterUnavailable(
                    f"team backend unreachable: {method} {path}: {exc}"
                ) from exc

            if response.status_code == 404 and allow_404:
                return None
            if 300 <= response.status_code < 400:
                raise AdapterUnavailable(
                    f"team backend returned a redirect ({response.status_code}) for "
                    f"{method} {path}; redirects are not followed"
                )
            if response.status_code < 200 or response.status_code >= 300:
                raise AdapterUnavailable(
                    f"team backend returned HTTP {response.status_code} for {method} {path}"
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise AdapterUnavailable(
                    f"team backend returned non-JSON content for {method} {path}"
                ) from exc
            if not isinstance(payload, dict | list):
                raise AdapterUnavailable(
                    f"team backend returned an unexpected JSON shape for {method} {path}"
                )
            return payload

        raise AdapterUnavailable(
            f"team backend request failed: {method} {path}"
        ) from last_error
