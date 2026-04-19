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


def main() -> None:
    if FastMCP is None:  # pragma: no cover
        raise SystemExit(
            "The 'mcp' package is not installed. Install dependencies first, for example: "
            "pip install -e ."
        ) from _IMPORT_ERROR
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
