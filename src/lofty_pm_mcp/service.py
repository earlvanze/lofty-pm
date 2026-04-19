from __future__ import annotations

import copy
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import build_lofty_pm_payloads as payload_builder  # type: ignore
import extract_lofty_lease_begins_dates as lease_extract  # type: ignore
import update_lofty_pm_property as replay  # type: ignore

DEFAULT_PROPERTY_MAP = REPO_ROOT / "config" / "property_update_map.json"
STATE_DIR = REPO_ROOT / "state"
GET_MANAGER_PROPERTIES_ENDPOINT = replay.ENDPOINTS["get-manager-properties"]


class LoftyPmError(RuntimeError):
    pass


def _load_property_map(path: str | None = None) -> list[dict[str, Any]]:
    return lease_extract.load_json(Path(path or DEFAULT_PROPERTY_MAP))


def _default_year_month(year: int | None, month: int | None) -> tuple[str, str]:
    now = dt.datetime.now()
    return str(year or now.year), str(month or now.month)


def _request_json(method: str, endpoint: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    response = replay.request(method, endpoint, headers, payload)
    if not response.ok:
        raise LoftyPmError(f"Lofty request failed: {response.status_code} {response.text[:1000]}")
    return response.json()


def get_manager_properties(
    year: int | None = None,
    month: int | None = None,
    property_id: str | None = None,
    property_query: str | None = None,
    close_extra_tabs: bool = True,
) -> dict[str, Any]:
    y, m = _default_year_month(year, month)
    payload = {"year": y, "month": m}
    fresh = replay.capture_fresh(
        "get-manager-properties",
        property_id=property_id,
        close_extra_tabs=close_extra_tabs,
        payload=payload,
    )
    headers = replay.build_headers(fresh)
    replay.validate_auth(headers)
    data = _request_json("GET", GET_MANAGER_PROPERTIES_ENDPOINT, headers, payload)
    properties = (((data or {}).get("data") or {}).get("properties") or [])

    if property_id or property_query:
        match = payload_builder.find_property(data, property_id=property_id, key=property_query)
        return {
            "query": {
                "property_id": property_id,
                "property_query": property_query,
                "year": y,
                "month": m,
            },
            "property": match,
        }

    return {
        "query": {"year": y, "month": m},
        "count": len(properties),
        "properties": properties,
    }


def build_property_payloads(
    property_id: str | None = None,
    property_query: str | None = None,
    year: int | None = None,
    month: int | None = None,
    close_extra_tabs: bool = True,
) -> dict[str, Any]:
    y, m = _default_year_month(year, month)
    data = get_manager_properties(
        year=int(y),
        month=int(m),
        property_id=property_id,
        property_query=property_query,
        close_extra_tabs=close_extra_tabs,
    )
    prop = data["property"]
    pid = prop["id"]
    return {
        "property_id": pid,
        "property_name": prop.get("address") or prop.get("assetName"),
        "save_payload": {"propertyId": pid, "patch": prop},
        "send_payload": {"propertyId": pid, "updatesDiff": prop.get("updates", "") or ""},
        "source_query": data["query"],
    }


def update_manager_property(
    property_id: str | None = None,
    payload: dict[str, Any] | None = None,
    patch: dict[str, Any] | None = None,
    property_query: str | None = None,
    close_extra_tabs: bool = True,
) -> dict[str, Any]:
    if payload is None:
        if not (property_id or property_query):
            raise LoftyPmError("update_manager_property requires either payload or property_id/property_query")
        payload = build_property_payloads(
            property_id=property_id,
            property_query=property_query,
            close_extra_tabs=close_extra_tabs,
        )["save_payload"]
    else:
        payload = copy.deepcopy(payload)

    if property_id:
        payload["propertyId"] = property_id
        payload.setdefault("patch", {})["id"] = property_id
    else:
        property_id = payload.get("propertyId")

    if patch:
        payload["patch"] = replay.merge_patch(payload.get("patch", {}), patch)

    return replay.request_via_runtime(
        "update-manager-property",
        payload,
        property_id=property_id,
        close_extra_tabs=close_extra_tabs,
    )


def send_property_updates(
    property_id: str | None = None,
    updates_diff: str | None = None,
    payload: dict[str, Any] | None = None,
    property_query: str | None = None,
    close_extra_tabs: bool = True,
) -> dict[str, Any]:
    if payload is None:
        if not (property_id or property_query):
            raise LoftyPmError("send_property_updates requires either payload or property_id/property_query")
        payload = build_property_payloads(
            property_id=property_id,
            property_query=property_query,
            close_extra_tabs=close_extra_tabs,
        )["send_payload"]
    else:
        payload = copy.deepcopy(payload)

    if property_id:
        payload["propertyId"] = property_id
    else:
        property_id = payload.get("propertyId")

    if updates_diff is not None:
        payload["updatesDiff"] = updates_diff

    if not payload.get("updatesDiff"):
        raise LoftyPmError("send_property_updates requires updatesDiff content")

    return replay.request_via_runtime(
        "send-property-updates",
        payload,
        property_id=property_id,
        close_extra_tabs=close_extra_tabs,
    )


def extract_lease_begins_dates(
    property_query: str | None = None,
    multi_date_strategy: str = "ambiguous",
    status: str | None = None,
    property_map: str | None = None,
) -> dict[str, Any]:
    props = lease_extract.filter_properties(_load_property_map(property_map), property_query)
    if property_query and not props:
        raise LoftyPmError(f"No property matched {property_query!r}")

    results = [lease_extract.analyze_property(prop, multi_date_strategy) for prop in props]
    if status:
        requested = {token.strip() for token in status.split(",") if token.strip()}
        results = [row for row in results if row["status"] in requested]
    return {
        "summary": lease_extract.summarize(results),
        "properties": results,
    }


def update_lease_begins_dates(
    property_query: str | None = None,
    multi_date_strategy: str = "earliest",
    apply: bool = False,
    year: int | None = None,
    month: int | None = None,
    close_extra_tabs: bool = True,
    property_map: str | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    props = lease_extract.filter_properties(_load_property_map(property_map), property_query)
    if property_query and not props:
        raise LoftyPmError(f"No property matched {property_query!r}")

    target_dir = Path(output_dir) if output_dir else (STATE_DIR / "lease-begins-date-runs")
    target_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    for prop in props:
        analysis = lease_extract.analyze_property(prop, multi_date_strategy)
        row = {
            "property_name": analysis["property_name"],
            "lofty_property_id": analysis["lofty_property_id"],
            "status": analysis["status"],
            "description_path": analysis["description_path"],
            "chosen": analysis.get("chosen"),
        }
        if not analysis.get("chosen"):
            row["action"] = "skipped"
            rows.append(row)
            continue

        paths = _build_lease_update_paths(prop, target_dir)
        for path in paths.values():
            path.parent.mkdir(parents=True, exist_ok=True)
        _ensure_gmp_payload(paths["gmp_payload_file"], year, month)
        patch_payload = {"lease_begins_date": analysis["chosen"]["display"]}
        paths["patch_file"].write_text(json.dumps(patch_payload, indent=2) + "\n")

        row["patch_file"] = str(paths["patch_file"])
        row["save_payload_file"] = str(paths["save_payload_file"])
        row["get_manager_properties_payload_file"] = str(paths["gmp_payload_file"])

        payloads = build_property_payloads(
            property_id=prop["lofty_property_id"],
            property_query=prop.get("property_name") or prop.get("full_address"),
            year=year,
            month=month,
            close_extra_tabs=close_extra_tabs,
        )
        paths["save_payload_file"].write_text(json.dumps(payloads["save_payload"], indent=2) + "\n")
        send_payload_file = paths["save_payload_file"].with_name(paths["save_payload_file"].name.replace("update-manager-property", "send-property-updates"))
        send_payload_file.write_text(json.dumps(payloads["send_payload"], indent=2) + "\n")

        row["action"] = "dry_run_ready"
        if apply:
            result = update_manager_property(
                property_id=prop["lofty_property_id"],
                payload=payloads["save_payload"],
                patch=patch_payload,
                close_extra_tabs=close_extra_tabs,
            )
            row["result"] = result
            row["action"] = "updated"
        rows.append(row)

    summary = {
        "properties": len(rows),
        "ready_or_updated": sum(1 for row in rows if row["action"] in ("dry_run_ready", "updated")),
        "skipped": sum(1 for row in rows if row["action"] == "skipped"),
        "failed": sum(1 for row in rows if row["action"] == "failed"),
        "applied": apply,
        "multi_date_strategy": multi_date_strategy,
        "output_dir": str(target_dir),
    }
    return {"summary": summary, "properties": rows}


def _ensure_gmp_payload(path: Path, year: int | None, month: int | None) -> None:
    if path.exists():
        return
    y, m = _default_year_month(year, month)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"year": y, "month": m}, indent=2) + "\n")


def _build_lease_update_paths(prop: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    pid = prop["lofty_property_id"]
    root = output_dir / pid
    return {
        "gmp_payload_file": root / "manager.get-manager-properties.payload.json",
        "save_payload_file": root / f"{pid}.update-manager-property.payload.json",
        "patch_file": root / f"{pid}.lease_begins_date.patch.json",
    }
