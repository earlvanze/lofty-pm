#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from string import Template
from typing import Any

LEGACY_WORKSPACE_ROOT = "/home/umbrel/.openclaw/workspace"
WORKSPACE_ROOT = Path(os.environ.get("LOFTY_PM_WORKSPACE_ROOT") or LEGACY_WORKSPACE_ROOT)
REAL_ESTATE_ROOT = Path(os.environ.get("LOFTY_PM_REAL_ESTATE_ROOT") or (WORKSPACE_ROOT / "Dropbox" / "Real Estate"))
TMP_ROOT = Path(os.environ.get("LOFTY_PM_TMP_ROOT") or (WORKSPACE_ROOT / "tmp"))

PATH_KEYS = {
    "updates_md",
    "save_payload_file",
    "send_payload_file",
    "get_manager_properties_payload_file",
    "description_md",
    "description_file",
    "description_path",
    "updates_file",
}


def _path_vars() -> dict[str, str]:
    return {
        "LOFTY_PM_WORKSPACE_ROOT": str(WORKSPACE_ROOT),
        "LOFTY_PM_REAL_ESTATE_ROOT": str(REAL_ESTATE_ROOT),
        "LOFTY_PM_TMP_ROOT": str(TMP_ROOT),
    }


def resolve_path(value: str | None) -> str | None:
    if not value:
        return value
    rendered = Template(value).safe_substitute(_path_vars())
    if rendered.startswith(LEGACY_WORKSPACE_ROOT):
        rendered = str(WORKSPACE_ROOT) + rendered[len(LEGACY_WORKSPACE_ROOT):]
    return rendered


def normalize_property_record(prop: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(prop)
    for key in PATH_KEYS:
        if isinstance(out.get(key), str):
            out[key] = resolve_path(out[key])
    return out


def load_property_map(path: str | Path) -> Any:
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        return [normalize_property_record(item) if isinstance(item, dict) else item for item in data]
    out = copy.deepcopy(data)
    if isinstance(out.get("properties"), list):
        out["properties"] = [normalize_property_record(item) if isinstance(item, dict) else item for item in out["properties"]]
    if isinstance(out.get("unresolved"), list):
        out["unresolved"] = [normalize_property_record(item) if isinstance(item, dict) else item for item in out["unresolved"]]
    return out
