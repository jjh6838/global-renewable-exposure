#!/usr/bin/env python3
"""Overlay IRIS cyclone rasters with polyline GeoParquet by country.

For each polylines_{ISO3}_add_v2.parquet file, this script samples line
geometries against IRIS RP rasters and writes country-level parquet output(s)
named polylines_{ISO3}_exposure.parquet with exposure fields:

- exposed_cyclone_rp10
- exposed_cyclone_rp100
- exposed_cyclone_rp500

Exposure is recorded as 1 when the maximum sampled IRIS wind speed along a
polyline is >= 33 m/s, otherwise 0.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio


DEFAULT_HAZARD_DIR = Path("/soge-home/projects/mistral/ji/bigdata_cyclone_iris/global_maps")
DEFAULT_POLYLINES_DIR = Path(
    "/soge-home/projects/mistral/ji/bigdata_global_renewable_dataset_p1/2050_supply_100%_add_v2"
)
DEFAULT_OUTPUT_DIR = Path("output_per_country/parquet_polylines_exposure")
DEFAULT_GLOBAL_OUTPUT = Path("output_global/polylines_global_exposure.gpkg")
DEFAULT_RPS = [10, 100, 500]
WIND_EXPOSURE_THRESHOLD_MS = 33.0
MAX_SAMPLES_PER_GEOMETRY = 21

ISO3_RE = re.compile(r"^polylines_([A-Za-z0-9]{3})_add_v2\.parquet$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze polyline exposure using IRIS cyclone RP GeoTIFF maps."
    )
    parser.add_argument(
        "--hazard-dir",
        type=Path,
        default=DEFAULT_HAZARD_DIR,
        help="Directory containing IRIS_vmax_maps_PRESENT_RP*.tif",
    )
    parser.add_argument(
        "--polylines-dir",
        type=Path,
        default=DEFAULT_POLYLINES_DIR,
        help="Directory containing polylines_{ISO3}_add_v2.parquet files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for per-country polyline exposure parquet files",
    )
    parser.add_argument(
        "--global-output",
        type=Path,
        default=DEFAULT_GLOBAL_OUTPUT,
        help="Optional output path for combined global file (default: output_global/polylines_global_exposure.gpkg)",
    )
    parser.add_argument(
        "--rps",
        type=int,
        nargs="+",
        default=DEFAULT_RPS,
        help="Return periods to evaluate (space-separated)",
    )
    parser.add_argument(
        "--iso3",
        nargs="+",
        default=None,
        help="Optional ISO3 filter for testing, e.g. --iso3 KOR",
    )
    parser.add_argument(
        "--write-global",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Build global file from existing per-country outputs in --output-dir",
    )
    return parser.parse_args()


def resolve_path(base_dir: Path, path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (base_dir / path).resolve()


def iso3_from_filename(path: Path) -> str | None:
    match = ISO3_RE.match(path.name)
    if not match:
        return None
    return match.group(1).upper()


def find_country_files(polylines_dir: Path, iso3_filter: set[str] | None) -> list[tuple[str, Path]]:
    files = sorted(polylines_dir.glob("polylines_*_add_v2.parquet"))
    if not files:
        raise FileNotFoundError(
            f"No polyline parquet files found in {polylines_dir} with pattern polylines_*_add_v2.parquet"
        )

    discovered: list[tuple[str, Path]] = []
    skipped = 0
    for fp in files:
        iso3 = iso3_from_filename(fp)
        if iso3 is None:
            skipped += 1
            continue
        if iso3_filter is not None and iso3 not in iso3_filter:
            continue
        discovered.append((iso3, fp))

    if not discovered:
        if iso3_filter:
            raise FileNotFoundError(
                f"No polyline files found for requested ISO3 list: {sorted(iso3_filter)}"
            )
        raise FileNotFoundError("No valid polylines_{ISO3}_add_v2.parquet files were found")

    if skipped:
        print(f"Skipped {skipped} file(s) with unexpected naming.", flush=True)

    return discovered


def load_raster_paths(hazard_dir: Path, rps: list[int]) -> dict[int, Path]:
    raster_paths: dict[int, Path] = {}
    missing: list[str] = []
    for rp in rps:
        tif = hazard_dir / f"IRIS_vmax_maps_PRESENT_RP{rp}.tif"
        if not tif.exists():
            missing.append(str(tif))
        else:
            raster_paths[rp] = tif

    if missing:
        joined = "\n".join(missing)
        raise FileNotFoundError(f"Missing hazard rasters:\n{joined}")

    return raster_paths


def _coords_for_geometry(geom, max_samples: int = MAX_SAMPLES_PER_GEOMETRY) -> list[tuple[float, float]]:
    if geom is None or geom.is_empty:
        return []

    geom_type = geom.geom_type
    if geom_type == "Point":
        return [(geom.x, geom.y)]

    if geom_type == "MultiPoint":
        points = list(geom.geoms)
        if not points:
            return []
        if len(points) <= max_samples:
            return [(pt.x, pt.y) for pt in points]
        idx = np.linspace(0, len(points) - 1, num=max_samples).astype(int)
        return [(points[i].x, points[i].y) for i in idx]

    if geom_type == "LineString":
        n = max(2, min(max_samples, len(geom.coords)))
        fractions = np.linspace(0.0, 1.0, num=n)
        sampled_points = [geom.interpolate(float(f), normalized=True) for f in fractions]
        return [(pt.x, pt.y) for pt in sampled_points]

    if geom_type == "MultiLineString":
        line_parts = [part for part in geom.geoms if not part.is_empty]
        if not line_parts:
            return []

        per_part = max(2, max_samples // max(1, len(line_parts)))
        coords: list[tuple[float, float]] = []
        for part in line_parts:
            fractions = np.linspace(0.0, 1.0, num=per_part)
            coords.extend((pt.x, pt.y) for pt in (part.interpolate(float(f), normalized=True) for f in fractions))

        if len(coords) <= max_samples:
            return coords

        idx = np.linspace(0, len(coords) - 1, num=max_samples).astype(int)
        return [coords[i] for i in idx]

    rp = geom.representative_point()
    return [(rp.x, rp.y)]


def _max_valid_sample_value(sampled_values: np.ndarray, nodata: float | int | None) -> float:
    if sampled_values.size == 0:
        return np.nan

    valid = ~np.isnan(sampled_values)
    if nodata is not None:
        if isinstance(nodata, float) and np.isnan(nodata):
            valid &= ~np.isnan(sampled_values)
        else:
            valid &= sampled_values != nodata

    if not valid.any():
        return np.nan

    return float(np.nanmax(sampled_values[valid]))


def sample_exposure_for_rp(gdf: gpd.GeoDataFrame, raster_path: Path) -> np.ndarray:
    with rasterio.open(raster_path) as src:
        if gdf.crs is None:
            raise ValueError("Input polyline data has no CRS metadata")

        gdf_in_raster_crs = gdf.to_crs(src.crs)
        result = np.zeros(len(gdf_in_raster_crs), dtype=np.uint8)

        for idx, geom in enumerate(gdf_in_raster_crs.geometry):
            if geom is None or geom.is_empty:
                continue

            coords = _coords_for_geometry(geom)
            if not coords:
                continue

            sampled = np.array([row[0] for row in src.sample(coords)], dtype=np.float32)
            max_value = _max_valid_sample_value(sampled, src.nodata)

            if not np.isnan(max_value) and max_value >= WIND_EXPOSURE_THRESHOLD_MS:
                result[idx] = 1

        return result


def process_country(
    iso3: str,
    input_file: Path,
    output_dir: Path,
    raster_paths: dict[int, Path],
) -> gpd.GeoDataFrame:
    gdf = gpd.read_parquet(input_file)
    if not isinstance(gdf, gpd.GeoDataFrame):
        gdf = gpd.GeoDataFrame(gdf, geometry="geometry")

    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326", allow_override=True)

    gdf = gdf.copy()
    gdf["iso3"] = iso3

    rp_cols: list[str] = []
    for rp, raster_path in raster_paths.items():
        col = f"exposed_cyclone_rp{rp}"
        gdf[col] = sample_exposure_for_rp(gdf, raster_path)
        rp_cols.append(col)

    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / f"polylines_{iso3}_exposure.parquet"
    gdf.to_parquet(out_file, index=False)

    total_assets = len(gdf)
    exposure_summary = {col: int(gdf[col].sum()) for col in rp_cols}
    print(
        f"Processed {iso3}: rows={total_assets}, exposed_by_rp={exposure_summary}, output={out_file}",
        flush=True,
    )
    return gdf


def build_global_from_per_country(output_dir: Path, global_output: Path) -> None:
    files = sorted(output_dir.glob("polylines_*_exposure.parquet"))
    if not files:
        raise FileNotFoundError(
            f"No per-country polyline exposure files found in {output_dir}. "
            "Run per-country processing first."
        )

    parts = [gpd.read_parquet(fp) for fp in files]
    combined = gpd.GeoDataFrame(
        pd.concat(parts, ignore_index=True),
        geometry="geometry",
        crs=parts[0].crs if parts else "EPSG:4326",
    )

    global_output.parent.mkdir(parents=True, exist_ok=True)
    if global_output.suffix.lower() == ".gpkg":
        combined.to_file(global_output, layer="polylines_global_exposure", driver="GPKG", mode="w")
        print(f"Wrote global GeoPackage: {global_output} (rows={len(combined)})", flush=True)
    else:
        combined.to_parquet(global_output, index=False)
        print(f"Wrote global parquet: {global_output} (rows={len(combined)})", flush=True)


def main() -> None:
    args = parse_args()
    script_dir = Path(__file__).resolve().parent

    output_dir = resolve_path(script_dir, args.output_dir)
    global_output = resolve_path(script_dir, args.global_output)

    if args.write_global:
        if args.iso3 is not None:
            raise SystemExit(
                "--write-global cannot be combined with --iso3. Build global from existing per-country outputs."
            )
        build_global_from_per_country(output_dir, global_output)
        return

    hazard_dir = resolve_path(script_dir, args.hazard_dir)
    polylines_dir = resolve_path(script_dir, args.polylines_dir)

    iso3_filter = None if args.iso3 is None else {c.upper() for c in args.iso3}

    country_files = find_country_files(polylines_dir, iso3_filter)
    raster_paths = load_raster_paths(hazard_dir, args.rps)

    print(f"Hazard directory: {hazard_dir}", flush=True)
    print(f"Polylines directory: {polylines_dir}", flush=True)
    print(f"Countries to process: {len(country_files)}", flush=True)
    print(f"RPs: {sorted(raster_paths.keys())}", flush=True)

    for iso3, input_file in country_files:
        process_country(
            iso3=iso3,
            input_file=input_file,
            output_dir=output_dir,
            raster_paths=raster_paths,
        )


if __name__ == "__main__":
    main()
