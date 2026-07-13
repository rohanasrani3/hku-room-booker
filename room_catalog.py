"""Load HKU room targets and static facility data from JSON."""

from dataclasses import dataclass
import json
from pathlib import Path

CATALOG_FILE = Path(__file__).parent / "data" / "room_catalog.json"


@dataclass(frozen=True)
class TargetRule:
    description: str
    library_keywords: tuple[str, ...] = ()
    type_keywords: tuple[str, ...] = ()
    type_exact: tuple[str, ...] = ()
    exclude_type_keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class FacilityCandidate:
    library_id: int
    library_name: str
    ftype_id: int
    type_name: str
    facility_id: int
    facility_name: str


def _tuple(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError("Room catalog keyword fields must be string lists.")
    return tuple(raw)


def _load_catalog() -> dict:
    with open(CATALOG_FILE) as f:
        catalog = json.load(f)
    if not isinstance(catalog, dict):
        raise ValueError("Room catalog must contain a JSON object.")
    return catalog


def _build_target_rules(catalog: dict) -> dict[str, TargetRule]:
    targets = catalog.get("targets", {})
    if not isinstance(targets, dict):
        raise ValueError("Room catalog 'targets' must be an object.")

    rules: dict[str, TargetRule] = {}
    for key, raw in targets.items():
        if not isinstance(raw, dict):
            raise ValueError(f"Room target '{key}' must be an object.")
        description = raw.get("description")
        if not isinstance(description, str):
            raise ValueError(f"Room target '{key}' needs a description.")
        rules[key] = TargetRule(
            description=description,
            library_keywords=_tuple(raw.get("library_keywords")),
            type_keywords=_tuple(raw.get("type_keywords")),
            type_exact=_tuple(raw.get("type_exact")),
            exclude_type_keywords=_tuple(raw.get("exclude_type_keywords")),
        )
    return rules


def _build_group(catalog: dict, group_name: str) -> list[FacilityCandidate]:
    groups = catalog.get("facility_groups", {})
    if not isinstance(groups, dict):
        raise ValueError("Room catalog 'facility_groups' must be an object.")

    raw = groups.get(group_name)
    if not isinstance(raw, dict):
        raise ValueError(f"Facility group '{group_name}' is missing from room catalog.")

    facilities = raw.get("facilities", [])
    if not isinstance(facilities, list):
        raise ValueError(f"Facility group '{group_name}' facilities must be a list.")

    return [
        FacilityCandidate(
            library_id=int(raw["library_id"]),
            library_name=str(raw["library_name"]),
            ftype_id=int(raw["ftype_id"]),
            type_name=str(raw["type_name"]),
            facility_id=int(facility["id"]),
            facility_name=str(facility["name"]),
        )
        for facility in facilities
    ]


def _build_static_targets(catalog: dict) -> dict[str, list[FacilityCandidate]]:
    targets = catalog.get("targets", {})
    static_targets: dict[str, list[FacilityCandidate]] = {}
    for target_name, raw in targets.items():
        if not isinstance(raw, dict):
            continue
        group_names = raw.get("facility_groups")
        if group_names is None:
            continue
        if not isinstance(group_names, list) or not all(isinstance(name, str) for name in group_names):
            raise ValueError(f"Room target '{target_name}' facility_groups must be a string list.")

        candidates: list[FacilityCandidate] = []
        for group_name in group_names:
            candidates.extend(_build_group(catalog, group_name))
        static_targets[target_name] = candidates
    return static_targets


def _build_aliases(catalog: dict) -> dict[str, str]:
    aliases = catalog.get("aliases", {})
    if not isinstance(aliases, dict):
        raise ValueError("Room catalog 'aliases' must be an object.")
    return {str(alias): str(target) for alias, target in aliases.items()}


CATALOG = _load_catalog()
TARGET_RULES = _build_target_rules(CATALOG)
TARGET_ALIASES = _build_aliases(CATALOG)
STATIC_TARGET_FACILITIES = _build_static_targets(CATALOG)
BOOKING_TARGETS = tuple(sorted((*TARGET_RULES.keys(), *TARGET_ALIASES.keys())))


def normalize_target(room_target: str) -> str:
    normalized = room_target.strip().lower().replace("-", "_")
    normalized = TARGET_ALIASES.get(normalized, normalized)
    if normalized not in TARGET_RULES:
        known = ", ".join(sorted(TARGET_RULES))
        raise ValueError(f"Unknown room target '{room_target}'. Known targets: {known}")
    return normalized
