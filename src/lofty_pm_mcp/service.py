from __future__ import annotations

import copy
import datetime as dt
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import build_lofty_pm_payloads as payload_builder  # type: ignore
import extract_lofty_lease_begins_dates as lease_extract  # type: ignore
import ingest_atlas_relay_update as atlas_ingest  # type: ignore
from lofty_pm_paths import load_property_map as load_resolved_property_map  # type: ignore
import publish_latest_update_to_lofty as publisher  # type: ignore
import rebuild_property_update_map as map_rebuilder  # type: ignore
import update_lofty_pm_property as replay  # type: ignore
import write_property_update_md as update_writer  # type: ignore

DEFAULT_PROPERTY_MAP = REPO_ROOT / "config" / "property_update_map.json"
STATE_DIR = REPO_ROOT / "state"
GET_MANAGER_PROPERTIES_ENDPOINT = replay.ENDPOINTS["get-manager-properties"]


class LoftyPmError(RuntimeError):
    pass


def _load_property_map(path: str | None = None) -> list[dict[str, Any]]:
    data = load_resolved_property_map(Path(path or DEFAULT_PROPERTY_MAP))
    if isinstance(data, dict):
        return list(data.get("properties") or [])
    return list(data)


def _load_property_candidates(path: str | None = None) -> list[dict[str, Any]]:
    data = load_resolved_property_map(Path(path or DEFAULT_PROPERTY_MAP))
    if isinstance(data, dict):
        return list(data.get("properties") or []) + list(data.get("unresolved") or [])
    return list(data)


def _default_year_month(year: int | None, month: int | None) -> tuple[str, str]:
    now = dt.datetime.now()
    return str(year or now.year), str(month or now.month)


def _request_json(method: str, endpoint: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    response = replay.request(method, endpoint, headers, payload)
    if not response.ok:
        raise LoftyPmError(f"Lofty request failed: {response.status_code} {response.text[:1000]}")
    return response.json()


def _find_mapped_property(property_query: str, property_map: str | None = None) -> dict[str, Any]:
    props = _load_property_map(property_map)
    key = property_query.lower()
    for prop in props:
        candidates = [
            prop.get("property_name", ""),
            prop.get("full_address", ""),
            prop.get("assetUnit", ""),
            prop.get("lofty_property_id", ""),
            prop.get("slug", ""),
            prop.get("updates_md", ""),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            lowered = str(candidate).lower()
            if key == lowered or key in lowered:
                return prop
    raise LoftyPmError(f"No mapped property matched {property_query!r}")


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


def ingest_atlas_relay_update(
    text: str,
    property_query: str | None = None,
    date: str | None = None,
    property_map: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    props = _load_property_map(property_map)
    prop = atlas_ingest.resolve_explicit_property(property_query, props) if property_query else atlas_ingest.find_property(text, props)
    if not prop:
        raise LoftyPmError("Could not resolve property from Atlas Relay text")
    if not prop.get("updates_md"):
        raise LoftyPmError(f"Mapped property {property_query or prop.get('property_name')!r} does not have an updates_md target")
    body = atlas_ingest.clean_update_text(text)
    if not body:
        raise LoftyPmError("No usable Atlas Relay update body after cleanup")
    result = write_property_update(
        property_query=prop.get("lofty_property_id") or prop.get("slug") or prop.get("property_name"),
        text=body,
        date=date,
        property_map=property_map,
        dry_run=dry_run,
    )
    result.update({
        "property_name": prop["property_name"],
        "lofty_property_id": prop["lofty_property_id"],
        "slug": prop.get("slug"),
        "updates_md": prop.get("updates_md"),
        "source": "atlas_relay",
    })
    return result


def ingest_and_publish_atlas_relay_update(
    text: str,
    property_query: str | None = None,
    date: str | None = None,
    property_map: str | None = None,
    dry_run: bool = False,
    close_extra_tabs: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    ingest_result = ingest_atlas_relay_update(
        text=text,
        property_query=property_query,
        date=date,
        property_map=property_map,
        dry_run=dry_run,
    )
    publish_key = property_query or ingest_result.get("lofty_property_id") or ingest_result.get("slug") or ingest_result.get("property_name")
    publish_result = publish_latest_property_update(
        property_query=str(publish_key),
        property_map=property_map,
        dry_run=dry_run,
        close_extra_tabs=close_extra_tabs,
        force=force,
    )
    return {
        "ingest": ingest_result,
        "publish": publish_result,
    }


def write_property_update(
    property_query: str,
    text: str,
    date: str | None = None,
    property_map: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    prop = _find_mapped_property(property_query, property_map)
    if not prop.get("updates_md"):
        raise LoftyPmError(f"Mapped property {property_query!r} does not have an updates_md target")
    body = update_writer.clean_text(text)
    if not body:
        raise LoftyPmError("Empty update text")
    update_date = dt.date.fromisoformat(date) if date else dt.date.today()
    header = f'- Property Update ({update_writer.slugify_date(update_date)}):'
    entry_body = f'{header}\n{body}'.strip()
    entry = f'## {update_date.isoformat()}\n\n{entry_body}\n\n'

    path = Path(prop["updates_md"])
    update_writer.ensure_updates_file(path)
    existing = path.read_text()
    entries = update_writer.parse_entries(existing)
    for existing_entry in entries:
        if existing_entry["date"] == update_date.isoformat() and update_writer.clean_text(existing_entry["body"]) == update_writer.clean_text(entry_body):
            return {
                "property_name": prop["property_name"],
                "lofty_property_id": prop["lofty_property_id"],
                "file": str(path),
                "date": update_date.isoformat(),
                "header": header,
                "deduped": True,
                "dry_run": dry_run,
            }

    if existing.startswith("# Property Updates"):
        rest = existing[len("# Property Updates"):].lstrip("\n")
        rendered = "# Property Updates\n\n" + entry + rest
    else:
        rendered = "# Property Updates\n\n" + entry + existing
    if not dry_run:
        path.write_text(rendered)
    return {
        "property_name": prop["property_name"],
        "lofty_property_id": prop["lofty_property_id"],
        "file": str(path),
        "date": update_date.isoformat(),
        "header": header,
        "deduped": False,
        "dry_run": dry_run,
    }


def publish_latest_property_update(
    property_query: str,
    property_map: str | None = None,
    dry_run: bool = False,
    close_extra_tabs: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    prop = _find_mapped_property(property_query, property_map)
    if not prop.get("updates_md"):
        raise LoftyPmError(f"Mapped property {property_query!r} does not have an updates_md target")
    md_path = Path(prop["updates_md"])
    entries = publisher.parse_entries(md_path.read_text())
    latest = entries[0]
    latest_digest = publisher.digest_for_entry(prop, latest)
    loft_field_text = publisher.combined_lofty_updates(entries)
    field_digest = publisher.digest_for_field(prop, loft_field_text)

    sp = publisher.state_path(prop)
    state = publisher.load_state(sp)
    bootstrap_seeded = False
    if not state.get("last_sent_digest") and not force:
        state["last_sent_digest"] = latest_digest
        state["last_sent_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds") + "Z"
        bootstrap_seeded = True

    last_sent_at = publisher.parse_iso_z(state.get("last_sent_at"))
    now = dt.datetime.now(dt.timezone.utc)
    weekly_window_open = force or last_sent_at is None or (now - last_sent_at) >= dt.timedelta(days=publisher.SEND_INTERVAL_DAYS)
    unsent_entries = publisher.collect_unsent_entries(prop, entries, None if force else state.get("last_sent_digest"))
    batched_send_text = publisher.combined_lofty_updates(unsent_entries)
    should_send = bool(batched_send_text) and weekly_window_open and not bootstrap_seeded

    with tempfile.TemporaryDirectory() as td:
        save_patch_file = Path(td) / "save.patch.json"
        save_payload_file = Path(td) / "save.payload.json"
        send_payload_file = Path(td) / "send.payload.json"
        save_patch_file.write_text(json.dumps({"updates": loft_field_text}, indent=2))

        bootstrap_cmd = [
            sys.executable,
            str(publisher.BOOTSTRAP),
            "--property-id", prop["lofty_property_id"],
            "--property", prop["property_name"],
            "--get-manager-properties-payload-file", prop["get_manager_properties_payload_file"],
            "--save-payload-file", str(save_payload_file),
            "--send-payload-file", str(send_payload_file),
        ]
        if close_extra_tabs:
            bootstrap_cmd.append("--close-extra-tabs")
        if dry_run:
            bootstrap_cmd.append("--dry-run")
        subprocess.run(bootstrap_cmd, check=True)

        cmd = [
            sys.executable,
            str(publisher.WRAPPER),
            "--get-manager-properties-payload-file", prop["get_manager_properties_payload_file"],
            "--save-payload-file", str(save_payload_file),
            "--save-patch-file", str(save_patch_file),
            "--send-payload-file", str(send_payload_file),
            "--property-id", prop["lofty_property_id"],
        ]
        if should_send:
            cmd += ["--updates-diff", batched_send_text]
        else:
            cmd += ["--skip-send"]
        if close_extra_tabs:
            cmd.append("--close-extra-tabs")
        if dry_run:
            cmd.append("--dry-run")
        subprocess.run(cmd, check=True)

    if not dry_run:
        state.update({
            "property_name": prop["property_name"],
            "lofty_property_id": prop["lofty_property_id"],
            "slug": prop.get("slug"),
            "updates_md": str(md_path),
            "last_entry_date": latest["date"],
            "last_posted_digest": field_digest,
            "last_posted_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds") + "Z",
            "last_posted_text": loft_field_text,
        })
        if should_send:
            state.update({
                "last_sent_digest": latest_digest,
                "last_sent_text": batched_send_text,
                "last_sent_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds") + "Z",
                "last_sent_entry_count": len(unsent_entries),
            })
        publisher.save_state(sp, state)

    return {
        "property_name": prop["property_name"],
        "lofty_property_id": prop["lofty_property_id"],
        "updates_md": str(md_path),
        "state_file": str(sp),
        "latest_date": latest["date"],
        "latest_digest": latest_digest,
        "field_digest": field_digest,
        "bootstrap_seeded": bootstrap_seeded,
        "weekly_window_open": weekly_window_open,
        "unsent_entries": len(unsent_entries),
        "will_send": should_send,
        "dry_run": dry_run,
    }


def rebuild_property_map(
    property_map: str | None = None,
    dry_run: bool = True,
    year: int | None = None,
    month: int | None = None,
) -> dict[str, Any]:
    target = property_map or str(DEFAULT_PROPERTY_MAP)
    return map_rebuilder.rebuild_map(map_file=target, dry_run=dry_run, year=year, month=month)


def extract_lease_begins_dates(
    property_query: str | None = None,
    multi_date_strategy: str = "ambiguous",
    status: str | None = None,
    property_map: str | None = None,
) -> dict[str, Any]:
    props = lease_extract.filter_properties(_load_property_candidates(property_map), property_query)
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
    props = lease_extract.filter_properties(_load_property_candidates(property_map), property_query)
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


def webpack_get_manager_properties(
    year: int | None = None,
    month: int | None = None,
    property_id: str | None = None,
) -> dict[str, Any]:
    """Fetch all manager properties via CDP webpack injection (no auth capture needed).

    Uses webpack module 51046 PK function to call get-manager-properties
    directly from the authenticated browser context.
    """
    from lofty_cdp import ensure_lofty_cdp_context
    from capture_lofty_auth_via_cdp import connect_ws

    y, m = _default_year_month(year, month)

    ctx = ensure_lofty_cdp_context(mode="list")
    tid = ctx["targetId"]
    ws = connect_ws(tid)

    msg_id = 0
    def sr(method, params=None, timeout=30):
        nonlocal msg_id
        msg_id += 1
        cid = msg_id
        ws.send(json.dumps({"id": cid, "method": method, "params": params or {}}))
        end = time.time() + timeout
        while time.time() < end:
            try:
                obj = json.loads(ws.recv())
                if obj.get("id") == cid:
                    return obj
            except Exception:
                pass
        raise TimeoutError()

    # Wait for webpack
    for _ in range(15):
        resp = sr("Runtime.evaluate", {
            "expression": 'typeof webpackChunklofty_investing_webapp !== "undefined"',
            "returnByValue": True, "awaitPromise": False,
        })
        if resp.get("result", {}).get("result", {}).get("value") is True:
            break
        time.sleep(2)

    expr = f'''(async () => {{
      let __req;
      webpackChunklofty_investing_webapp.push([[Math.random()], {{}}, function(req){{ __req = req; }}]);
      const mod = __req(51046);
      const data = await mod.PK({{year: "{y}", month: "{m}"}});
      const props = data?.data?.properties || [];
      return JSON.stringify(props);
    }})()'''

    resp = sr("Runtime.evaluate", {
        "expression": expr, "awaitPromise": True, "returnByValue": True, "timeout": 30000,
    })
    ws.close()

    val = resp.get("result", {}).get("result", {}).get("value", "[]")
    properties = json.loads(val) if isinstance(val, str) else val

    if property_id:
        prop = next((p for p in properties if p.get("id") == property_id), None)
        return {"query": {"property_id": property_id, "year": y, "month": m}, "property": prop}

    return {"query": {"year": y, "month": m}, "count": len(properties), "properties": properties}


def webpack_update_property(
    property_id: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Update a Lofty property via CDP webpack injection (no auth capture needed).

    Fetches the current property data via PK, merges the patch, and calls
    mod.so() to apply the update-manager-property mutation.
    """
    from lofty_cdp import ensure_lofty_cdp_context
    from capture_lofty_auth_via_cdp import connect_ws

    import datetime as dt
    now = dt.datetime.now()
    y, m = str(now.year), str(now.month)

    ctx = ensure_lofty_cdp_context(property_id=property_id, mode="edit")
    tid = ctx["targetId"]
    ws = connect_ws(tid)

    msg_id = 0
    def sr(method, params=None, timeout=60):
        nonlocal msg_id
        msg_id += 1
        cid = msg_id
        ws.send(json.dumps({"id": cid, "method": method, "params": params or {}}))
        end = time.time() + timeout
        while time.time() < end:
            try:
                obj = json.loads(ws.recv())
                if obj.get("id") == cid:
                    return obj
            except Exception:
                pass
        raise TimeoutError()

    # Wait for webpack
    for _ in range(15):
        resp = sr("Runtime.evaluate", {
            "expression": 'typeof webpackChunklofty_investing_webapp !== "undefined"',
            "returnByValue": True, "awaitPromise": False,
        })
        if resp.get("result", {}).get("result", {}).get("value") is True:
            break
        time.sleep(2)

    patch_json = json.dumps(patch)
    expr = f'''(async () => {{
      let __req;
      webpackChunklofty_investing_webapp.push([[Math.random()], {{}}, function(req){{ __req = req; }}]);
      const mod = __req(51046);
      const data = await mod.PK({{year: "{y}", month: "{m}"}});
      const props = data?.data?.properties || [];
      const prop = props.find(p => p.id === "{property_id}");
      if (!prop) return JSON.stringify({{error: "property not found"}});
      const payload = {{propertyId: "{property_id}", patch: {{...prop, ...{patch_json}}}}};
      const result = await mod.so(payload);
      return JSON.stringify(result);
    }})()'''

    resp = sr("Runtime.evaluate", {
        "expression": expr, "awaitPromise": True, "returnByValue": True, "timeout": 60000,
    })
    ws.close()

    val = resp.get("result", {}).get("result", {}).get("value", "null")
    result = json.loads(val) if isinstance(val, str) else val
    return {"property_id": property_id, "patch": patch, "result": result}


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
