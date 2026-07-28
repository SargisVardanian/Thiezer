#!/usr/bin/env python3
"""Opt-in redacted connectivity smoke test for Thiezer celestial providers.

Run only when deliberate live network access is desired:
    THIEZER_LIVE_SMOKE=1 .venv/bin/python scripts/smoke_celestial_providers.py
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx

PROVIDERS = {
    "simbad": ("https://simbad.cds.unistra.fr/simbad/sim-tap/sync", "Sirius"),
    "gaia": ("https://gea.esac.esa.int/tap-server/tap/sync", "5853498713190525696"),
    "vizier": ("https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync", "M 42"),
    "ned": ("https://ned.ipac.caltech.edu/tap/sync", "M 31"),
    "exoplanet_archive": ("https://exoplanetarchive.ipac.caltech.edu/TAP/sync", "51 Peg b"),
    "horizons": ("https://ssd.jpl.nasa.gov/api/horizons.api", "1"),
}


async def main() -> int:
    if os.environ.get("THIEZER_LIVE_SMOKE") != "1":
        print("Refusing live requests; set THIEZER_LIVE_SMOKE=1 to run this opt-in smoke test.")
        return 2
    summary: dict[str, object] = {"created_at_utc": datetime.now(UTC).isoformat(), "providers": {}}
    async with httpx.AsyncClient(follow_redirects=False) as client:
        for name, (endpoint, sample) in PROVIDERS.items():
            try:
                status = await _probe(client, name, endpoint, sample)
                summary["providers"][name] = {"status": "ok", "http_status": status}
            except (
                Exception
            ) as exc:  # Intentional: smoke report must continue after a provider failure.
                summary["providers"][name] = {"status": "failed", "error_type": type(exc).__name__}
    destination = Path("artifacts/reports/celestial_provider_smoke_redacted.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(destination)
    return 0 if all(item["status"] == "ok" for item in summary["providers"].values()) else 1


async def _probe(client: httpx.AsyncClient, name: str, endpoint: str, sample: str) -> int:
    timeout = httpx.Timeout(connect=5, read=20, write=5, pool=5)
    if name == "horizons":
        response = await client.get(
            endpoint,
            params={"format": "json", "COMMAND": f"'{sample}'", "MAKE_EPHEM": "NO"},
            timeout=timeout,
        )
    else:
        query = _query(name, sample)
        response = await client.post(
            endpoint,
            data={
                "REQUEST": "doQuery",
                "LANG": "ADQL",
                "FORMAT": "json",
                "MAXREC": "1",
                "QUERY": query,
            },
            timeout=timeout,
        )
    response.raise_for_status()
    if len(response.content) > 2_000_000:
        raise ValueError("response_too_large")
    return response.status_code


def _query(name: str, sample: str) -> str:
    literals = {
        "simbad": f"'{sample}'",
        "gaia": sample,
        "vizier": f"'{sample}'",
        "ned": f"'{sample}'",
        "exoplanet_archive": f"'{sample}'",
    }
    return {
        "simbad": "SELECT TOP 1 basic.main_id FROM basic JOIN ident ON basic.oid = ident.oidref "
        f"WHERE ident.id = {literals[name]}",
        "gaia": "SELECT TOP 1 source_id FROM gaiadr3.gaia_source "
        f"WHERE source_id = {literals[name]}",
        "vizier": f'SELECT TOP 1 Name FROM "VII/118/ngc2000" WHERE Name = {literals[name]}',
        "ned": f"SELECT TOP 1 prefname FROM objdir WHERE prefname = {literals[name]}",
        "exoplanet_archive": "SELECT TOP 1 pl_name FROM pscomppars "
        f"WHERE pl_name = {literals[name]}",
    }[name]


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
