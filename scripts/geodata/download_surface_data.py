from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

import planetary_computer
from common import ROOT, aoi_polygon, atomic_json, bounds, load_aoi, sha256, utc_now
from pystac_client import Client

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
DATASETS = {
    "dem": {
        "collection": "cop-dem-glo-90",
        "asset": "data",
        "source_url": "https://planetarycomputer.microsoft.com/dataset/cop-dem-glo-90",
        "license": "Copernicus DEM GLO-90 free and open licence; see official Copernicus terms.",
    },
    "worldcover": {
        "collection": "esa-worldcover",
        "asset": "map",
        "source_url": "https://esa-worldcover.org/en/data-access",
        "license": "CC BY 4.0",
    },
}
STAC_QUERIES = {
    "worldcover": {"esa_worldcover:product_version": {"eq": "2.0.0"}},
}


def download(url: str, destination: Path) -> str:
    if destination.exists() and destination.stat().st_size:
        return sha256(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temporary:
        request = Request(url, headers={"User-Agent": "Thiezer-geodata/1.0"})
        with urlopen(request, timeout=120) as response:
            shutil.copyfileobj(response, temporary)
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, destination)
    return sha256(destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aoi", required=True)
    args = parser.parse_args()
    aoi = load_aoi(args.aoi)
    geometry = aoi_polygon(aoi)
    raw_dir = ROOT / "data/raw" / aoi["id"]
    catalog = Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)
    datasets: dict[str, object] = {}
    for name, dataset in DATASETS.items():
        records: list[dict[str, object]] = []
        for item in catalog.search(
            collections=[str(dataset["collection"])],
            bbox=bounds(geometry),
            query=STAC_QUERIES.get(name),
        ).items():
            asset = item.assets[str(dataset["asset"])]
            destination = raw_dir / name / f"{item.id}.tif"
            records.append(
                {
                    "item_id": item.id,
                    "official_href": asset.href.split("?", 1)[0],
                    "path": str(destination.relative_to(ROOT)),
                    "sha256": download(asset.href, destination),
                    "bytes": destination.stat().st_size,
                }
            )
        if not records:
            raise RuntimeError(f"no {name} STAC assets intersect AOI")
        datasets[name] = {**dataset, "assets": records}
    atomic_json(
        ROOT / "data/manifests" / f"{aoi['id']}_downloads.json",
        {
            "schema_version": "1.0",
            "created_at_utc": utc_now(),
            "aoi": aoi,
            "aoi_geometry_wgs84": geometry,
            "datasets": datasets,
            "viirs": {
                "status": "blocked",
                "product": "VNP46A4",
                "reason": "NASA Earthdata Login is required; set THIEZER_EARTHDATA_TOKEN for a future authenticated downloader. No proxy replaces VIIRS.",
            },
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
