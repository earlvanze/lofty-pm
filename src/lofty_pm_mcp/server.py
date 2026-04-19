from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from . import __version__, service

try:
    from mcp.server.fastmcp import FastMCP
except Exception as exc:  # pragma: no cover
    FastMCP = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

if FastMCP is not None:
    # ---------------------------------------------------------------------------
    # Shared parameter descriptions — single source of truth for small models
    # ---------------------------------------------------------------------------
    _P = {
        "property_id": "Lofty property ID (e.g. '01J020EQJ0M9S7MXBZJQGMESWB'). Look up with webpack_get_manager_properties if unknown.",
        "property_query": "Fuzzy search string matching a property name or address (e.g. 'Wild Olive', '49 Bannbury'). Used when property_id is unknown.",
        "year": "Year for property data (e.g. 2026). Defaults to current year.",
        "month": "Month number 1-12 (e.g. 4 for April). Defaults to current month.",
        "close_extra_tabs": "Close duplicate Lofty tabs after operation. Keep True unless you need multiple tabs open.",
        "dry_run": "Preview changes without writing. Always set True first before applying for real.",
        "property_map": "Path to property_update_map.json. Defaults to config/property_update_map.json in the skill repo.",
        "text": "The update text content to write. For Atlas Relay, the raw relay text to ingest.",
        "patch": "Dict of Lofty property fields to update, e.g. {\"lease_begins_date\": \"05/01/2025\", \"updates\": \"...\"}. Keys must match Lofty API field names.",
        "payload": "Full Lofty API payload dict (rarely needed — prefer patch for partial updates).",
        "sections": "Dict of DESCRIPTION.md section names to new content, e.g. {\"Occupancy Status\": \"Vacant as of 04/20/2026\"}. Use this for partial updates.",
        "content": "Full replacement text for a file. WARNING: replaces the entire file. Prefer sections= for partial updates.",
        "opening": "Replacement text for the opening paragraph of DESCRIPTION.md.",
        "updates_diff": "Plain-text summary of changes to email the owner. Auto-derived if omitted.",
        "force": "Force the operation even if preconditions are not met (e.g. send email without new updates).",
        "date": "Date string for the update entry, e.g. '04/20/2026'. Defaults to today.",
        "multi_date_strategy": "How to handle properties with multiple lease dates: 'ambiguous' (report all), 'earliest', 'latest', or 'first'.",
        "status": "Filter by property status, e.g. 'active', 'vacant'.",
        "batch": "Process all properties in the map instead of one.",
        "include_details": "Include DETAILS.md data in the Lofty push.",
        "include_financials": "Include FINANCIALS.md data in the Lofty push.",
        "pl_entry": "Dict of P&L entry fields, e.g. {\"rent\": 1200, \"expenses\": 450}. Keys must match Lofty P&L field names.",
        "output_dir": "Directory for output files. Defaults to tmp/lofty-pm-lease-dates.",
        "apply": "Apply changes to Lofty. Default False = dry-run only. Always preview first.",
    }

    # Helper to avoid repeating Field(description=...) boilerplate
    def _F(name: str, default=None, **field_kwargs):
        """Create a Field with the shared description for the given param name."""
        desc = _P.get(name, name)
        if default is not None:
            return Field(default=default, description=desc, **field_kwargs)
        return Field(description=desc, **field_kwargs)

    mcp = FastMCP(
        "lofty-pm",
        instructions=(
            "Lofty PM MCP server for property-manager automation. "
            "PREFERRED TOOLS (no auth capture needed): webpack_get_manager_properties, webpack_update_property, "
            "webpack_get_pl_entry, webpack_create_pl_entry, webpack_update_pl_entry, webpack_get_pl_cutoff_config. "
            "For small models: call ONE tool at a time. Never chain 3+ calls without returning results first. "
            "To read properties: webpack_get_manager_properties. "
            "To update a field: webpack_update_property with property_id and patch dict. "
            "To read/write DESCRIPTION.md: read_description_md / write_description_md. "
            "To add an update: write_property_update then publish_latest_property_update. "
            "To ingest Atlas Relay: ingest_and_publish_atlas_relay_update. "
            "Never guess property_id — look it up with webpack_get_manager_properties first."
        ),
    )

    # ==========================================================================
    # Legacy auth-capture tools (prefer webpack equivalents)
    # ==========================================================================

    @mcp.tool()
    def get_manager_properties(
        year: Annotated[int | None, _F("year")] = None,
        month: Annotated[int | None, _F("month")] = None,
        property_id: Annotated[str | None, _F("property_id")] = None,
        property_query: Annotated[str | None, _F("property_query")] = None,
        close_extra_tabs: Annotated[bool, _F("close_extra_tabs")] = True,
    ) -> dict[str, Any]:
        """LEGACY (prefer webpack_get_manager_properties): Fetch the live Lofty manager property list, or one matched property. Requires auth capture."""
        return service.get_manager_properties(
            year=year,
            month=month,
            property_id=property_id,
            property_query=property_query,
            close_extra_tabs=close_extra_tabs,
        )

    @mcp.tool()
    def build_property_payloads(
        property_id: Annotated[str | None, _F("property_id")] = None,
        property_query: Annotated[str | None, _F("property_query")] = None,
        year: Annotated[int | None, _F("year")] = None,
        month: Annotated[int | None, _F("month")] = None,
        close_extra_tabs: Annotated[bool, _F("close_extra_tabs")] = True,
    ) -> dict[str, Any]:
        """Build fresh save/send payloads for a Lofty property from the live manager data."""
        return service.build_property_payloads(
            property_id=property_id,
            property_query=property_query,
            year=year,
            month=month,
            close_extra_tabs=close_extra_tabs,
        )

    @mcp.tool()
    def update_manager_property(
        property_id: Annotated[str | None, _F("property_id")] = None,
        payload: Annotated[dict[str, Any] | None, _F("payload")] = None,
        patch: Annotated[dict[str, Any] | None, _F("patch")] = None,
        property_query: Annotated[str | None, _F("property_query")] = None,
        close_extra_tabs: Annotated[bool, _F("close_extra_tabs")] = True,
    ) -> dict[str, Any]:
        """LEGACY (prefer webpack_update_property): Apply an update-manager-property mutation through Lofty's in-page runtime. Requires auth capture."""
        return service.update_manager_property(
            property_id=property_id,
            payload=payload,
            patch=patch,
            property_query=property_query,
            close_extra_tabs=close_extra_tabs,
        )

    @mcp.tool()
    def send_property_updates(
        property_id: Annotated[str | None, _F("property_id")] = None,
        updates_diff: Annotated[str | None, _F("updates_diff")] = None,
        payload: Annotated[dict[str, Any] | None, _F("payload")] = None,
        property_query: Annotated[str | None, _F("property_query")] = None,
        close_extra_tabs: Annotated[bool, _F("close_extra_tabs")] = True,
    ) -> dict[str, Any]:
        """Send the owner update email for a Lofty property. Use after publish_latest_property_update or with a pre-built payload."""
        return service.send_property_updates(
            property_id=property_id,
            updates_diff=updates_diff,
            payload=payload,
            property_query=property_query,
            close_extra_tabs=close_extra_tabs,
        )

    # ==========================================================================
    # Atlas Relay / update writing tools
    # ==========================================================================

    @mcp.tool()
    def ingest_atlas_relay_update(
        text: Annotated[str, _F("text")],
        property_query: Annotated[str | None, _F("property_query")] = None,
        date: Annotated[str | None, _F("date")] = None,
        property_map: Annotated[str | None, _F("property_map")] = None,
        dry_run: Annotated[bool, _F("dry_run")] = False,
    ) -> dict[str, Any]:
        """Clean Atlas Relay text and write it into canonical UPDATES.md for the matched property."""
        return service.ingest_atlas_relay_update(
            text=text,
            property_query=property_query,
            date=date,
            property_map=property_map,
            dry_run=dry_run,
        )

    @mcp.tool()
    def ingest_and_publish_atlas_relay_update(
        text: Annotated[str, _F("text")],
        property_query: Annotated[str | None, _F("property_query")] = None,
        date: Annotated[str | None, _F("date")] = None,
        property_map: Annotated[str | None, _F("property_map")] = None,
        dry_run: Annotated[bool, _F("dry_run")] = False,
        close_extra_tabs: Annotated[bool, _F("close_extra_tabs")] = True,
        force: Annotated[bool, _F("force")] = False,
    ) -> dict[str, Any]:
        """End-to-end: clean Atlas Relay text, write to UPDATES.md, then publish to Lofty PM and send owner email."""
        return service.ingest_and_publish_atlas_relay_update(
            text=text,
            property_query=property_query,
            date=date,
            property_map=property_map,
            dry_run=dry_run,
            close_extra_tabs=close_extra_tabs,
            force=force,
        )

    @mcp.tool()
    def write_property_update(
        property_query: Annotated[str, _F("property_query")],
        text: Annotated[str, _F("text")],
        date: Annotated[str | None, _F("date")] = None,
        property_map: Annotated[str | None, _F("property_map")] = None,
        dry_run: Annotated[bool, _F("dry_run")] = False,
    ) -> dict[str, Any]:
        """Write a canonical dated entry into a property's UPDATES.md. Pass property_query (name/address) and the update text."""
        return service.write_property_update(
            property_query=property_query,
            text=text,
            date=date,
            property_map=property_map,
            dry_run=dry_run,
        )

    @mcp.tool()
    def publish_latest_property_update(
        property_query: Annotated[str, _F("property_query")],
        property_map: Annotated[str | None, _F("property_map")] = None,
        dry_run: Annotated[bool, _F("dry_run")] = False,
        close_extra_tabs: Annotated[bool, _F("close_extra_tabs")] = True,
        force: Annotated[bool, _F("force")] = False,
    ) -> dict[str, Any]:
        """Push the latest update from UPDATES.md to Lofty PM and send owner email. Always dry_run=true first to preview."""
        return service.publish_latest_property_update(
            property_query=property_query,
            property_map=property_map,
            dry_run=dry_run,
            close_extra_tabs=close_extra_tabs,
            force=force,
        )

    # ==========================================================================
    # Property map tools
    # ==========================================================================

    @mcp.tool()
    def rebuild_property_map(
        property_map: Annotated[str | None, _F("property_map")] = None,
        dry_run: Annotated[bool, _F("dry_run")] = True,
        year: Annotated[int | None, _F("year")] = None,
        month: Annotated[int | None, _F("month")] = None,
    ) -> dict[str, Any]:
        """Rebuild property_update_map.json by fuzzy-matching live Lofty properties against the Dropbox Real Estate corpus. Always dry_run=true first."""
        return service.rebuild_property_map(
            property_map=property_map,
            dry_run=dry_run,
            year=year,
            month=month,
        )

    # ==========================================================================
    # Lease date tools
    # ==========================================================================

    @mcp.tool()
    def extract_lease_begins_dates(
        property_query: Annotated[str | None, _F("property_query")] = None,
        multi_date_strategy: Annotated[str, _F("multi_date_strategy")] = "ambiguous",
        status: Annotated[str | None, _F("status")] = None,
        property_map: Annotated[str | None, _F("property_map")] = None,
    ) -> dict[str, Any]:
        """Audit lease_begins_date candidates from DESCRIPTION.md. Use 'ambiguous' to see all candidates before applying."""
        return service.extract_lease_begins_dates(
            property_query=property_query,
            multi_date_strategy=multi_date_strategy,
            status=status,
            property_map=property_map,
        )

    @mcp.tool()
    def update_lease_begins_dates(
        property_query: Annotated[str | None, _F("property_query")] = None,
        multi_date_strategy: Annotated[str, _F("multi_date_strategy")] = "earliest",
        apply: Annotated[bool, _F("apply")] = False,
        year: Annotated[int | None, _F("year")] = None,
        month: Annotated[int | None, _F("month")] = None,
        close_extra_tabs: Annotated[bool, _F("close_extra_tabs")] = True,
        property_map: Annotated[str | None, _F("property_map")] = None,
        output_dir: Annotated[str | None, _F("output_dir")] = None,
    ) -> dict[str, Any]:
        """Apply lease_begins_date updates to Lofty properties. Always run with apply=False first to preview changes."""
        return service.update_lease_begins_dates(
            property_query=property_query,
            multi_date_strategy=multi_date_strategy,
            apply=apply,
            year=year,
            month=month,
            close_extra_tabs=close_extra_tabs,
            property_map=property_map,
            output_dir=output_dir,
        )

    # ==========================================================================
    # Webpack tools (PREFERRED — no auth capture needed)
    # ==========================================================================

    @mcp.tool()
    def webpack_get_manager_properties(
        year: Annotated[int | None, _F("year")] = None,
        month: Annotated[int | None, _F("month")] = None,
        property_id: Annotated[str | None, _F("property_id")] = None,
    ) -> dict[str, Any]:
        """PREFERRED: Fetch all Lofty manager properties via webpack (no auth capture). Returns list of properties with id, assetName, address, slug, etc. Look up property_id here if unknown."""
        return service.webpack_get_manager_properties(
            year=year,
            month=month,
            property_id=property_id,
        )

    @mcp.tool()
    def webpack_update_property(
        property_id: Annotated[str, _F("property_id")],
        patch: Annotated[dict[str, Any], _F("patch")],
    ) -> dict[str, Any]:
        """PREFERRED: Update a Lofty property via webpack (no auth capture). Pass property_id and patch dict e.g. {\"lease_begins_date\": \"05/01/2025\", \"updates\": \"New update text\"}."""
        return service.webpack_update_property(
            property_id=property_id,
            patch=patch,
        )

    # ==========================================================================
    # Data extraction tools
    # ==========================================================================

    @mcp.tool()
    def extract_property_data(
        property_query: Annotated[str | None, _F("property_query")] = None,
        property_id: Annotated[str | None, _F("property_id")] = None,
        batch: Annotated[bool, _F("batch")] = False,
        property_map: Annotated[str | None, _F("property_map")] = None,
    ) -> dict[str, Any]:
        """Extract property details and financials from Lofty owner pages. Creates/updates local DETAILS.md and FINANCIALS.md."""
        return service.extract_property_data(
            property_query=property_query,
            property_id=property_id,
            batch=batch,
            property_map=property_map,
        )

    @mcp.tool()
    def backfill_updates_history(
        property_query: Annotated[str | None, _F("property_query")] = None,
        property_map: Annotated[str | None, _F("property_map")] = None,
        dry_run: Annotated[bool, _F("dry_run")] = True,
    ) -> dict[str, Any]:
        """Backfill UPDATES.md history from live Lofty property data. Always dry_run=true first to preview."""
        return service.backfill_updates_history(
            property_query=property_query,
            property_map=property_map,
            dry_run=dry_run,
        )

    # ==========================================================================
    # DESCRIPTION.md read/write tools
    # ==========================================================================

    @mcp.tool()
    def read_description_md(
        property_query: Annotated[str | None, _F("property_query")] = None,
        property_id: Annotated[str | None, _F("property_id")] = None,
        property_map: Annotated[str | None, _F("property_map")] = None,
    ) -> dict[str, Any]:
        """Read and parse a property's DESCRIPTION.md into named sections (opening, Offering Details, Property Details, Occupancy Status, etc)."""
        return service.read_description_md(
            property_query=property_query,
            property_id=property_id,
            property_map=property_map,
        )

    @mcp.tool()
    def write_description_md(
        property_query: Annotated[str | None, _F("property_query")] = None,
        property_id: Annotated[str | None, _F("property_id")] = None,
        property_map: Annotated[str | None, _F("property_map")] = None,
        content: Annotated[str | None, _F("content")] = None,
        sections: Annotated[dict[str, str] | None, _F("sections")] = None,
        opening: Annotated[str | None, _F("opening")] = None,
        dry_run: Annotated[bool, _F("dry_run")] = False,
    ) -> dict[str, Any]:
        """Write or update DESCRIPTION.md. Use sections={\"Occupancy Status\": \"new text\"} for partial updates. Use content=\"full text\" ONLY for complete replacement. Always dry_run=true first."""
        return service.write_description_md(
            property_query=property_query,
            property_id=property_id,
            property_map=property_map,
            content=content,
            sections=sections,
            opening=opening,
            dry_run=dry_run,
        )

    # ==========================================================================
    # Push local data to Lofty
    # ==========================================================================

    @mcp.tool()
    def push_property_data(
        property_query: Annotated[str | None, _F("property_query")] = None,
        property_id: Annotated[str | None, _F("property_id")] = None,
        property_map: Annotated[str | None, _F("property_map")] = None,
        include_details: Annotated[bool, _F("include_details")] = True,
        include_financials: Annotated[bool, _F("include_financials")] = True,
        dry_run: Annotated[bool, _F("dry_run")] = False,
    ) -> dict[str, Any]:
        """Push local DETAILS.md / FINANCIALS.md data back to Lofty via webpack. Always dry_run=true first to preview which fields will change."""
        return service.push_property_data(
            property_query=property_query,
            property_id=property_id,
            property_map=property_map,
            include_details=include_details,
            include_financials=include_financials,
            dry_run=dry_run,
        )

    # ==========================================================================
    # P&L tools (webpack — no auth capture)
    # ==========================================================================

    @mcp.tool()
    def webpack_get_pl_cutoff_config() -> dict[str, Any]:
        """Get P&L cutoff config (cutoff day, time, timezone). Lightweight read, no property_id needed."""
        return service.webpack_get_pl_cutoff_config()

    @mcp.tool()
    def webpack_get_pl_entry(
        property_id: Annotated[str, _F("property_id")],
        year: Annotated[int | None, _F("year")] = None,
        month: Annotated[int | None, _F("month")] = None,
    ) -> dict[str, Any]:
        """Get a single P&L entry for a property. Requires property_id. Returns income, expenses, and net for the given month."""
        return service.webpack_get_pl_entry(
            property_id=property_id,
            year=year,
            month=month,
        )

    @mcp.tool()
    def webpack_create_pl_entry(
        property_id: Annotated[str, _F("property_id")],
        year: Annotated[int | None, _F("year")] = None,
        month: Annotated[int | None, _F("month")] = None,
        pl_entry: Annotated[dict[str, Any] | None, _F("pl_entry")] = None,
    ) -> dict[str, Any]:
        """Create a new P&L entry for a property. Requires property_id. Pass pl_entry dict with fields like {\"rent\": 1200, \"expenses\": 450}."""
        return service.webpack_create_pl_entry(
            property_id=property_id,
            year=year,
            month=month,
            pl_entry=pl_entry,
        )

    @mcp.tool()
    def webpack_update_pl_entry(
        property_id: Annotated[str, _F("property_id")],
        year: Annotated[int | None, _F("year")] = None,
        month: Annotated[int | None, _F("month")] = None,
        pl_entry: Annotated[dict[str, Any] | None, _F("pl_entry")] = None,
    ) -> dict[str, Any]:
        """Update an existing P&L entry for a property. Requires property_id. Pass pl_entry dict with fields to update like {\"rent\": 1300}."""
        return service.webpack_update_pl_entry(
            property_id=property_id,
            year=year,
            month=month,
            pl_entry=pl_entry,
        )


def main() -> None:
    if FastMCP is None:  # pragma: no cover
        raise SystemExit(
            "The 'mcp' package is not installed. Install dependencies first, for example: "
            "pip install -e ."
        ) from _IMPORT_ERROR
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()