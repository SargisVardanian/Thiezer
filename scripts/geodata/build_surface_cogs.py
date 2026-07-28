from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import rasterio
from common import ROOT, aoi_polygon, atomic_json, bounds, load_aoi, sha256, utc_now
from rasterio.enums import Resampling
from rasterio.mask import mask
from rasterio.merge import merge
from rasterio.shutil import copy as rio_copy


def build(
    dataset: str,
    source_paths: list[Path],
    destination: Path,
    geometry: dict[str, object],
    resolution: float,
    force: bool,
) -> dict[str, object]:
    if not force and destination.exists() and destination.stat().st_size:
        return inspect(destination)
    sources = [rasterio.open(path) for path in source_paths]
    try:
        resampling = Resampling.nearest if dataset == "worldcover" else Resampling.bilinear
        nodata = 0 if dataset == "worldcover" else -9999
        merged, transform = merge(
            sources, bounds=bounds(geometry), res=resolution, nodata=nodata, resampling=resampling
        )
        profile = sources[0].profile.copy()
        profile.update(
            driver="GTiff",
            height=merged.shape[1],
            width=merged.shape[2],
            transform=transform,
            crs="EPSG:4326",
            count=1,
            nodata=nodata,
            tiled=True,
            blockxsize=512,
            blockysize=512,
            compress="DEFLATE",
            predictor=2 if dataset == "dem" else 1,
            BIGTIFF="IF_SAFER",
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, suffix=".tif", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        with rasterio.open(temporary_path, "w", **profile) as output:
            output.write(merged)
            output.build_overviews([2, 4, 8, 16], resampling)
            output.update_tags(ns="rio_overview", resampling=resampling.name)
        with rasterio.open(temporary_path) as temporary_dataset:
            clipped, clipped_transform = mask(
                temporary_dataset, [geometry], crop=True, nodata=nodata, filled=True
            )
            clipped_profile = temporary_dataset.profile.copy()
            clipped_profile.update(
                height=clipped.shape[1], width=clipped.shape[2], transform=clipped_transform
            )
        with rasterio.open(temporary_path, "w", **clipped_profile) as output:
            output.write(clipped)
            output.build_overviews([2, 4, 8, 16], resampling)
            output.update_tags(
                ns="rio_overview", resampling=resampling.name, thiezer_dataset=dataset
            )
        cog_path = temporary_path.with_suffix(".cog.tif")
        rio_copy(
            temporary_path,
            cog_path,
            driver="COG",
            compress="DEFLATE",
            blocksize=512,
            overview_resampling=resampling.name,
            BIGTIFF="IF_SAFER",
        )
        os.replace(cog_path, destination)
        temporary_path.unlink(missing_ok=True)
    finally:
        for source in sources:
            source.close()
    return inspect(destination)


def inspect(path: Path) -> dict[str, object]:
    with rasterio.open(path) as dataset:
        values = dataset.read(1, masked=True)
        return {
            "path": str(path.relative_to(ROOT)),
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
            "crs": str(dataset.crs),
            "bounds": list(dataset.bounds),
            "resolution": list(dataset.res),
            "nodata": dataset.nodata,
            "dtype": dataset.dtypes[0],
            "width": dataset.width,
            "height": dataset.height,
            "overviews": dataset.overviews(1),
            "statistics": {
                "min": float(values.min()),
                "max": float(values.max()),
                "mean": float(values.mean()),
            },
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aoi", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    aoi = load_aoi(args.aoi)
    geometry = aoi_polygon(aoi)
    with (ROOT / "data/manifests" / f"{aoi['id']}_downloads.json").open() as handle:
        downloads = json.load(handle)
    processed_dir = ROOT / aoi["output_directory"]
    resolution = float(aoi["requested_output_resolution_degrees"])
    outputs = {}
    for name, filename in (("dem", "copernicus_dem.tif"), ("worldcover", "worldcover.tif")):
        assets = downloads["datasets"][name]["assets"]
        source_paths = [ROOT / item["path"] for item in assets]
        outputs[name] = build(
            name,
            source_paths,
            processed_dir / filename,
            geometry,
            resolution,
            args.force,
        )
    atomic_json(
        ROOT / "data/manifests" / f"{aoi['id']}_surface_pack.json",
        {
            "schema_version": "1.0",
            "created_at_utc": utc_now(),
            "aoi": aoi,
            "aoi_geometry_wgs84": geometry,
            "datasets": outputs,
            "sources": downloads["datasets"],
            "viirs": downloads["viirs"],
            "preprocessing": {
                "tool": "rasterio",
                "compression": "DEFLATE",
                "driver": "COG",
                "tiled": True,
                "overviews": [2, 4, 8, 16],
            },
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
