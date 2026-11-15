"""Deterministic natural-language parser for place (candidate) queries.

The parser is rule-based on purpose: it runs without a model, cannot invent a
value, and only emits filters backed by the team's actual Analog fields.
Anything the records cannot support becomes an ``UnavailableField`` warning.

No threshold is invented from an adjective. A numeric range is created only
when the user states an explicit number.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from assistant.places.contracts import (
    CandidateSearchFilters,
    NumericRange,
    PlanetName,
    UnavailableField,
)

# Query phrase group -> substrings searched in supplied text fields.
TEXT_SYNONYM_GROUPS: dict[str, tuple[str, ...]] = {
    "arid": ("arid", "desert", "deserts", "dry", "hyper-arid"),
    "volcanic": ("volcan", "volcanic", "volcano", "volcanoes", "basalt", "basaltic", "lava", "mafic", "flood basalt"),
    "polar": ("polar", "cryo", "ice", "icy", "glaci", "glacial", "permafrost", "frost", "sub-zero"),
    "salt_flat": ("salt flat", "salt flats", "salt pan", "salt pans", "playa", "evaporite", "salar"),
    "dune": ("dune", "dunes", "aeolian", "sand sheet", "sand sea"),
    "crater": ("crater", "craters", "cratered", "impact basin", "impact structure"),
    "mountain": ("mountain", "mountains", "mountainous", "montane", "alpine", "highland", "highlands", "plateau"),
    "rough": ("rough", "rugged", "rocky"),
    "lunar_mare": ("mare", "maria", "basaltic plain", "basaltic plains"),
    "hydrothermal": ("hydrothermal", "fumarole", "geothermal", "hot spring", "hot springs"),
    "fluvial": ("fluvial", "delta", "deltas", "river", "rivers", "lake", "lakes", "paleo-lake"),
    "sulfate": ("sulfate", "sulphate", "gypsum", "clay", "clays"),
}

PLACE_ALIASES: dict[str, str] = {
    "atacama": "Atacama",
    "yungay": "Yungay",
    "mcmurdo": "McMurdo",
    "dry valleys": "Dry Valleys",
    "university valley": "University Valley",
    "ladakh": "Ladakh",
    "spiti": "Spiti",
    "lonar": "Lonar",
    "askja": "Askja",
    "haughton": "Haughton",
    "mauna loa": "Mauna Loa",
    "death valley": "Death Valley",
    "iceland": "Iceland",
    "chile": "Chile",
    "antarctica": "Antarctica",
    "india": "India",
    "hawaii": "Hawaii",
    "namibia": "Namibia",
    "bolivia": "Bolivia",
    "argentina": "Argentina",
    "australia": "Australia",
    "canada": "Canada",
    "united states": "United States",
    "usa": "USA",
    "china": "China",
    "mongolia": "Mongolia",
    "peru": "Peru",
    "spain": "Spain",
    "italy": "Italy",
}

COUNTRY_ALIASES: dict[str, str] = {
    "chile": "Chile",
    "antarctica": "Antarctica",
    "india": "India",
    "iceland": "Iceland",
    "united states": "United States",
    "usa": "United States",
    "canada": "Canada",
    "australia": "Australia",
    "namibia": "Namibia",
    "bolivia": "Bolivia",
    "argentina": "Argentina",
    "peru": "Peru",
    "china": "China",
    "mongolia": "Mongolia",
    "spain": "Spain",
    "italy": "Italy",
}

TARGET_KEYWORDS: dict[str, str] = {
    "jezero": "mars_jezero",
    "gale crater": "mars_gale",
    "mount sharp": "mars_gale",
    "shackleton": "moon_shackleton",
    "south pole": "moon_south_pole",
    "tranquillitatis": "moon_tranquillitatis",
    "olympus mons": "mars_olympus",
}

METRIC_WORDS: dict[str, str] = {
    "roughness": "roughness",
    "terrain roughness": "roughness",
    "relief": "relief",
    "local relief": "relief",
    "slope": "slope",
    "aridity": "aridity",
    "thermal": "thermal",
    "rockiness": "rockiness",
    "volcanic index": "volcanic",
    "volcanic": "volcanic",
    "access": "access",
    "accessibility": "access",
}

MISSION_PROFILE_HINTS: dict[str, str] = {
    "permanent base": "permanent_base",
    "human base": "permanent_base",
    "habitat": "scientific_habitability",
    "habitability": "scientific_habitability",
    "robotic": "robotic_landing",
    "rover": "robotic_landing",
    "landing": "robotic_landing",
    "surface exploration": "surface_exploration",
    "mobility": "surface_exploration",
}

NUMERIC_ALIASES: dict[str, str] = {
    "elevation": "elevation_numeric",
    "altitude": "elevation_numeric",
    "temperature": "temperature",
    "vegetation": "vegetation",
    "mineralogy": "mineralogy",
    "mineral": "mineralogy",
    "water ice content": "water_ice_indicator",
    "subsurface water": "water_ice_indicator",
}

COMPARATOR_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"(?:above|over|greater than|more than|at least|min(?:imum)?(?: of)?|>|>=)\s*(\d+(?:\.\d+)?)", "minimum"),
    (r"(?:below|under|less than|at most|max(?:imum)?(?: of)?|<|<=)\s*(\d+(?:\.\d+)?)", "maximum"),
)

RANGE_PATTERN = re.compile(
    r"(?:between\s+)?(\d+(?:\.\d+)?)\s*(?:-|to|and)\s*(\d+(?:\.\d+)?)"
)


class ParsedQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filters: CandidateSearchFilters = Field(default_factory=CandidateSearchFilters)
    target_reference: str | None = None
    planetary_reference: PlanetName | None = None
    purpose: str | None = None
    mission_profile_hint: str | None = None
    unavailable_fields: list[UnavailableField] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def _contains(question: str, phrase: str) -> bool:
    if " " in phrase or "-" in phrase:
        return phrase in question
    return re.search(rf"\b{re.escape(phrase)}\b", question) is not None


def _detect_planet(question: str) -> tuple[PlanetName | None, str | None]:
    if _contains(question, "mars") or _contains(question, "martian"):
        return "Mars", "Mars"
    if _contains(question, "moon") or _contains(question, "lunar"):
        return "Moon", "Moon"
    if _contains(question, "earth") or _contains(question, "terrestrial"):
        return "Earth", "Earth"
    return None, None


def _detect_target(question: str) -> str | None:
    for keyword, target_id in TARGET_KEYWORDS.items():
        if keyword in question:
            return target_id
    return None


def _detect_text_terms(question: str) -> list[str]:
    terms: list[str] = []
    for group, phrases in TEXT_SYNONYM_GROUPS.items():
        if any(_contains(question, phrase) for phrase in phrases):
            terms.append(group)
    for alias, canonical in PLACE_ALIASES.items():
        if _contains(question, alias):
            terms.append(canonical)
    return sorted(set(terms))


def _detect_countries(question: str) -> list[str]:
    return sorted({canonical for alias, canonical in COUNTRY_ALIASES.items() if _contains(question, alias)})


def _detect_datasets(question: str) -> list[str]:
    datasets: list[str] = []
    aliases = {
        "nasadem": "NASADEM",
        "modis": "MODIS",
        "aster": "ASTER",
        "landsat": "Landsat",
        "gpm": "GPM",
        "imerg": "IMERG",
        "lola": "LOLA",
        "diviner": "Diviner",
        "hirise": "HiRISE",
        "mola": "MOLA",
    }
    for alias, canonical in aliases.items():
        if _contains(question, alias):
            datasets.append(canonical)
    return sorted(set(datasets))


def _detect_numeric_filters(
    question: str,
) -> tuple[dict[str, NumericRange], list[UnavailableField], list[str]]:
    metrics: dict[str, NumericRange] = {}
    unavailable: list[UnavailableField] = []
    notes: list[str] = []

    # Split into clauses so a number attached to one metric is not applied to
    # a different metric mentioned earlier in the sentence.
    clauses = re.split(r",|;|\band\b(?!\s*\d)|\bwith\b|\bplus\b", question)
    for clause in clauses:
        for word, metric in METRIC_WORDS.items():
            if word not in clause:
                continue
            range_match = RANGE_PATTERN.search(clause)
            if range_match:
                low, high = float(range_match.group(1)), float(range_match.group(2))
                metrics.setdefault(metric, NumericRange(minimum=low, maximum=high))
                continue
            for pattern, bound in COMPARATOR_PATTERNS:
                match = re.search(pattern, clause)
                if match:
                    value = float(match.group(1))
                    if bound == "minimum":
                        metrics.setdefault(metric, NumericRange(minimum=value))
                    else:
                        metrics.setdefault(metric, NumericRange(maximum=value))
                    break

    if any(key in question for key in ("elevation", "altitude")):
        unavailable.append(
            UnavailableField(
                field="elevation_numeric",
                reason=(
                    "The team Analog schema stores elevation as display text with "
                    "embedded units ('1,050 m (NASADEM)'), not a numeric field. No "
                    "numeric elevation filter is applied and no value is derived."
                ),
            )
        )

    if "temperature" in question and re.search(r"\d", question):
        unavailable.append(
            UnavailableField(
                field="temperature",
                reason=(
                    "The team schema supplies a 0-100 'thermal' heuristic index, not "
                    "a temperature measurement. A temperature range is not applied."
                ),
            )
        )

    if "vegetation" in question:
        unavailable.append(
            UnavailableField(
                field="vegetation",
                reason=(
                    "No vegetation attribute exists in the team Analog records. "
                    "This is not treated as absence of vegetation."
                ),
            )
        )

    if "mineral" in question:
        unavailable.append(
            UnavailableField(
                field="mineralogy",
                reason=(
                    "No verified mineralogical attribute exists in the team Analog "
                    "records. Text mentions are not mineralogical measurements."
                ),
            )
        )

    if any(phrase in question for phrase in ("water ice content", "subsurface water", "water content")):
        unavailable.append(
            UnavailableField(
                field="water_ice_indicator",
                reason=(
                    "The team Analog records contain narrative ice/water mentions, "
                    "not a verified water-ice indicator field."
                ),
            )
        )

    for metric, numeric_range in metrics.items():
        for value in (numeric_range.minimum, numeric_range.maximum):
            if value is not None and (value < 0 or value > 100):
                notes.append(
                    f"The requested {metric} bound {value} is outside the platform's "
                    "0-100 index range; it is kept exactly as requested and not clamped."
                )

    if "mission" in question or "profile" in question:
        unavailable.append(
            UnavailableField(
                field="mission_profile",
                reason=(
                    "Mission profiles belong to planetary targets, not to Analog "
                    "candidate records; the filter is not applied to candidates."
                ),
            )
        )

    return metrics, unavailable, notes


def _detect_purpose(question: str) -> tuple[str | None, str | None]:
    match = re.search(
        r"for\s+((?:rover|robotic|human|drill|mobility|landing|surface|base|habitat|exploration)[^.,;]*)",
        question,
    )
    purpose = match.group(1).strip() if match else None
    hint = None
    for phrase, profile in MISSION_PROFILE_HINTS.items():
        if phrase in question:
            hint = profile
            break
    return purpose, hint


def parse_place_query(question: str) -> ParsedQuery:
    text = (question or "").strip().casefold()
    if not text:
        return ParsedQuery()

    filters = CandidateSearchFilters()
    text_terms = _detect_text_terms(text)
    countries = _detect_countries(text)
    datasets = _detect_datasets(text)
    metrics, unavailable, notes = _detect_numeric_filters(text)
    planet_ref, planet_token = _detect_planet(text)
    target_reference = _detect_target(text)
    purpose, mission_hint = _detect_purpose(text)

    if planet_token in {"Mars", "Moon"}:
        filters.primary_planet_analogs.append(planet_token)
    if target_reference:
        filters.target_ids.append(target_reference)

    # Planet names and target ids also act as text terms so the explanation can
    # show why a record matched, without inventing additional filters.
    if text_terms:
        filters.text_terms = text_terms
    if countries:
        filters.countries = countries
    if datasets:
        filters.dataset_terms = datasets
    if metrics:
        filters.metrics = metrics  # type: ignore[assignment]

    return ParsedQuery(
        filters=filters,
        target_reference=target_reference,
        planetary_reference=planet_ref,
        purpose=purpose,
        mission_profile_hint=mission_hint,
        unavailable_fields=unavailable,
        notes=notes,
    )
