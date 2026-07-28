from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import rasterio
from common import ROOT, atomic_json, load_aoi, utc_now


def validate(path: Path, *, categorical: bool) -> dict[str, object]:
    with rasterio.open(path) as dataset:
        if dataset.driver != "GTiff" or not dataset.is_tiled or not dataset.overviews(1):
            raise ValueError(f"{path} is not tiled with internal overviews")
        if dataset.crs is None or dataset.nodata is None or dataset.count != 1:
            raise ValueError(f"{path} has incomplete raster metadata")
        values = dataset.read(1, masked=True)
        if values.count() == 0:
            raise ValueError(f"{path} has no valid pixels")
        if categorical:
            allowed = {10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100}
            classes = {int(value) for value in values.compressed()}
            if not classes <= allowed:
                raise ValueError(f"{path} has unknown WorldCover classes: {classes - allowed}")
        return {
            "path": str(path.relative_to(ROOT)),
            "valid": True,
            "crs": str(dataset.crs),
            "bounds": list(dataset.bounds),
            "resolution": list(dataset.res),
            "nodata": dataset.nodata,
            "dtype": dataset.dtypes[0],
            "overviews": dataset.overviews(1),
            "min": float(values.min()),
            "max": float(values.max()),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aoi", required=True)
    args = parser.parse_args()
    aoi = load_aoi(args.aoi)
    directory = ROOT / aoi["output_directory"]
    report = {
        "created_at_utc": utc_now(),
        "aoi": aoi["id"],
        "dem": validate(directory / "copernicus_dem.tif", categorical=False),
        "worldcover": validate(directory / "worldcover.tif", categorical=True),
        "viirs": {"status": "blocked", "reason": "NASA Earthdata credential not configured"},
    }
    atomic_json(ROOT / "artifacts/reports" / f"{aoi['id']}_cog_validation.json", report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
