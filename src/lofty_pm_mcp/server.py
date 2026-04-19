from __future__ import annotations

from typing import Any

from . import __version__, service

try:
    from mcp.server.fastmcp import FastMCP
except Exception as exc:  # pragma: no cover
    FastMCP = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

if FastMCP is not None:
    mcp = FastMCP(
        "lofty-pm",
        instructions=(
            "Lofty PM MCP server for property-manager automation. "
            "Use these tools to inspect manager properties, build or apply property updates, "
            "send owner update emails, and backfill lease_begins_date from the Lofty PM skill workflows."
        ),
    )

    @mcp.tool()
    def get_manager_properties(
        year: int | None = None,
        month: int | None = None,
        property_id: str | None = None,
        property_query: str | None = None,
        close_extra_tabs: bool = True,
    ) -> dict[str, Any]:
        """Fetch the live Lofty manager property list, or one matched property."""
        return service.get_manager_properties(
            year=year,
            month=month,
            property_id=property_id,
            property_query=property_query,
            close_extra_tabs=close_extra_tabs,
        )

    @mcp.tool()
    def build_property_payloads(
        property_id: str | None = None,
        property_query: str | None = None,
        year: int | None = None,
        month: int | None = None,
        close_extra_tabs: bool = True,
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
        property_id: str | None = None,
        payload: dict[str, Any] | None = None,
        patch: dict[str, Any] | None = None,
        property_query: str | None = None,
        close_extra_tabs: bool = True,
    ) -> dict[str, Any]:
        """Apply an update-manager-property mutation through Lofty's in-page runtime."""
        return service.update_manager_property(
            property_id=property_id,
            payload=payload,
            patch=patch,
            property_query=property_query,
            close_extra_tabs=close_extra_tabs,
        )

    @mcp.tool()
    def send_property_updates(
        property_id: str | None = None,
        updates_diff: str | None = None,
        payload: dict[str, Any] | None = None,
        property_query: str | None = None,
        close_extra_tabs: bool = True,
    ) -> dict[str, Any]:
        """Send the owner update email for a Lofty property."""
        return service.send_property_updates(
            property_id=property_id,
            updates_diff=updates_diff,
            payload=payload,
            property_query=property_query,
            close_extra_tabs=close_extra_tabs,
        )

    @mcp.tool()
    def ingest_atlas_relay_update(
        text: str,
        property_query: str | None = None,
        date: str | None = None,
        property_map: str | None = None,
        dry_run: bool = False,
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
        text: str,
        property_query: str | None = None,
        date: str | None = None,
        property_map: str | None = None,
        dry_run: bool = False,
        close_extra_tabs: bool = True,
        force: bool = False,
    ) -> dict[str, Any]:
        """End-to-end Atlas Relay ingest into UPDATES.md, then publish to Lofty PM."""
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
        property_query: str,
        text: str,
        date: str | None = None,
        property_map: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Write a canonical dated entry into a property's UPDATES.md."""
        return service.write_property_update(
            property_query=property_query,
            text=text,
            date=date,
            property_map=property_map,
            dry_run=dry_run,
        )

    @mcp.tool()
    def publish_latest_property_update(
        property_query: str,
        property_map: str | None = None,
        dry_run: bool = False,
        close_extra_tabs: bool = True,
        force: bool = False,
    ) -> dict[str, Any]:
        """Push the canonical property update history to Lofty and optionally send owner email."""
        return service.publish_latest_property_update(
            property_query=property_query,
            property_map=property_map,
            dry_run=dry_run,
            close_extra_tabs=close_extra_tabs,
            force=force,
        )

    @mcp.tool()
    def rebuild_property_map(
        property_map: str | None = None,
        dry_run: bool = True,
        year: int | None = None,
        month: int | None = None,
    ) -> dict[str, Any]:
        """Rebuild property_update_map.json from live Lofty manager properties and the Real Estate corpus."""
        return service.rebuild_property_map(
            property_map=property_map,
            dry_run=dry_run,
            year=year,
            month=month,
        )

    @mcp.tool()
    def extract_lease_begins_dates(
        property_query: str | None = None,
        multi_date_strategy: str = "ambiguous",
        status: str | None = None,
        property_map: str | None = None,
    ) -> dict[str, Any]:
        """Audit lease_begins_date candidates from DESCRIPTION.md and PMA fallbacks."""
        return service.extract_lease_begins_dates(
            property_query=property_query,
            multi_date_strategy=multi_date_strategy,
            status=status,
            property_map=property_map,
        )

    @mcp.tool()
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
        """Prepare or apply lease_begins_date updates using the skill's fallback logic."""
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

    @mcp.tool()
    def webpack_get_manager_properties(
        year: int | None = None,
        month: int | None = None,
        property_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch all manager properties via CDP webpack injection (no auth capture needed)."""
        return service.webpack_get_manager_properties(
            year=year,
            month=month,
            property_id=property_id,
        )

    @mcp.tool()
    def webpack_update_property(
        property_id: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a Lofty property via CDP webpack injection (no auth capture needed)."""
        return service.webpack_update_property(
            property_id=property_id,
            patch=patch,
        )

    @mcp.tool()
    def extract_property_data(
        property_query: str | None = None,
        property_id: str | None = None,
        batch: bool = False,
        property_map: str | None = None,
    ) -> dict[str, Any]:
        """Extract property details and financials from Lofty owner pages."""
        return service.extract_property_data(
            property_query=property_query,
            property_id=property_id,
            batch=batch,
            property_map=property_map,
        )

    @mcp.tool()
    def backfill_updates_history(
        property_query: str | None = None,
        property_map: str | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Backfill UPDATES.md history from live Lofty property data."""
        return service.backfill_updates_history(
            property_query=property_query,
            property_map=property_map,
            dry_run=dry_run,
        )

    @mcp.tool()
    def read_description_md(
        property_query: str | None = None,
        property_id: str | None = None,
        property_map: str | None = None,
    ) -> dict[str, Any]:
        """Read and parse a property's DESCRIPTION.md into sections."""
        return service.read_description_md(
            property_query=property_query,
            property_id=property_id,
            property_map=property_map,
        )

    @mcp.tool()
    def write_description_md(
        property_query: str | None = None,
        property_id: str | None = None,
        property_map: str | None = None,
        content: str | None = None,
        sections: dict[str, str] | None = None,
        opening: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Write or update a property's DESCRIPTION.md (full replace or section merge)."""
        return service.write_description_md(
            property_query=property_query,
            property_id=property_id,
            property_map=property_map,
            content=content,
            sections=sections,
            opening=opening,
            dry_run=dry_run,
        )

    @mcp.tool()
    def push_property_data(
        property_query: str | None = None,
        property_id: str | None = None,
        property_map: str | None = None,
        include_details: bool = True,
        include_financials: bool = True,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Push local DETAILS.md / FINANCIALS.md data back to Lofty."""
        return service.push_property_data(
            property_query=property_query,
            property_id=property_id,
            property_map=property_map,
            include_details=include_details,
            include_financials=include_financials,
            dry_run=dry_run,
        )

    @mcp.tool()
    def webpack_get_pl_cutoff_config() -> dict[str, Any]:
        """Get P\u0026L cutoff configuration from Lofty."""
        return service.webpack_get_pl_cutoff_config()

    @mcp.tool()
    def webpack_get_pl_entry(
        property_id: str,
        year: int | None = None,
        month: int | None = None,
    ) -> dict[str, Any]:
        """Get a P\u0026L entry for a property."""
        return service.webpack_get_pl_entry(
            property_id=property_id,
            year=year,
            month=month,
        )

    @mcp.tool()
    def webpack_create_pl_entry(
        property_id: str,
        year: int | None = None,
        month: int | None = None,
        pl_entry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a P\u0026L entry for a property via webpack injection."""
        return service.webpack_create_pl_entry(
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
