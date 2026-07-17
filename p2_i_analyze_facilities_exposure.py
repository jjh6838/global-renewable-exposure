#!/usr/bin/env python3
"""Overlay IRIS cyclone rasters with facilities GeoParquet by country.

For each facilities_{ISO3}_add_v2.parquet file, this script samples each asset
geometry (using representative points) against IRIS RP rasters and writes
country-level output parquet(s) named facilities_{ISO3}_exposure.parquet with exposure fields:

- exposed_cyclone_rp10
- exposed_cyclone_rp100
- exposed_cyclone_rp500

Exposure is recorded as 1 when sampled IRIS wind speed is >= 33 m/s,
otherwise 0.
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
DEFAULT_FACILITIES_DIR = Path(
    "/soge-home/projects/mistral/ji/bigdata_global_renewable_dataset_p1/2050_supply_100%_add_v2"
)
DEFAULT_OUTPUT_DIR = Path("output_per_country/parquet_facilities_exposure")
DEFAULT_GLOBAL_OUTPUT = Path("output_global/facilities_global_exposure.gpkg")
DEFAULT_RPS = [10, 100, 500]
WIND_EXPOSURE_THRESHOLD_MS = 33.0

ISO3_RE = re.compile(r"^facilities_([A-Za-z0-9]{3})_add_v2\.parquet$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze facility exposure using IRIS cyclone RP GeoTIFF maps."
    )
    parser.add_argument(
        "--hazard-dir",
        type=Path,
        default=DEFAULT_HAZARD_DIR,
        help="Directory containing IRIS_vmax_maps_PRESENT_RP*.tif",
    )
    parser.add_argument(
        "--facilities-dir",
        type=Path,
        default=DEFAULT_FACILITIES_DIR,
        help="Directory containing facilities_{ISO3}_add_v2.parquet files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for per-country exposure parquet files",
    )
    parser.add_argument(
        "--global-output",
        type=Path,
        default=DEFAULT_GLOBAL_OUTPUT,
        help="Optional output path for combined global file (default: output_global/facilities_global_exposure.gpkg)",
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
        help="Also write one combined global file from processed countries",
    )
    return parser.parse_args()


def resolve_path(base_dir: Path, path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (base_dir / path).resolve()


def iso3_from_filename(path: Path) -> str | None:
    match = ISO3_RE.match(path.name)
    if not match:
        return None
    return match.group(1).upper()


def find_country_files(facilities_dir: Path, iso3_filter: set[str] | None) -> list[tuple[str, Path]]:
    files = sorted(facilities_dir.glob("facilities_*_add_v2.parquet"))
    if not files:
        raise FileNotFoundError(
            f"No facilities parquet files found in {facilities_dir} with pattern facilities_*_add_v2.parquet"
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
                f"No facilities files found for requested ISO3 list: {sorted(iso3_filter)}"
            )
        raise FileNotFoundError("No valid facilities_{ISO3}_add_v2.parquet files were found")

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


def exposure_from_values(values: np.ndarray, nodata: float | int | None) -> np.ndarray:
    exposed = np.ones(values.shape[0], dtype=np.uint8)

    nan_mask = np.isnan(values)
    exposed[nan_mask] = 0

    if nodata is not None:
        if isinstance(nodata, float) and np.isnan(nodata):
            exposed[np.isnan(values)] = 0
        else:
            exposed[values == nodata] = 0

    exposed[values < WIND_EXPOSURE_THRESHOLD_MS] = 0
    return exposed


def sample_exposure_for_rp(gdf: gpd.GeoDataFrame, raster_path: Path) -> np.ndarray:
    with rasterio.open(raster_path) as src:
        if gdf.crs is None:
            raise ValueError("Input facilities data has no CRS metadata")

        gdf_in_raster_crs = gdf.to_crs(src.crs)
        geom = gdf_in_raster_crs.geometry

        valid_geom = geom.notna() & (~geom.is_empty)
        result = np.zeros(len(gdf_in_raster_crs), dtype=np.uint8)

        if not valid_geom.any():
            return result

        sample_points = geom[valid_geom].representative_point()
        coords = np.column_stack((sample_points.x.to_numpy(), sample_points.y.to_numpy()))

        sampled = np.array([row[0] for row in src.sample(coords)], dtype=np.float32)
        exposed = exposure_from_values(sampled, src.nodata)

        result[valid_geom.to_numpy()] = exposed
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
        # Facilities files are expected in WGS84.
        gdf = gdf.set_crs("EPSG:4326", allow_override=True)

    gdf = gdf.copy()
    gdf["iso3"] = iso3

    rp_cols: list[str] = []
    for rp, raster_path in raster_paths.items():
        col = f"exposed_cyclone_rp{rp}"
        gdf[col] = sample_exposure_for_rp(gdf, raster_path)
        rp_cols.append(col)

    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / f"facilities_{iso3}_exposure.parquet"
    gdf.to_parquet(out_file, index=False)

    total_assets = len(gdf)
    exposure_summary = {col: int(gdf[col].sum()) for col in rp_cols}
    print(
        f"Processed {iso3}: assets={total_assets}, exposed_by_rp={exposure_summary}, output={out_file}",
        flush=True,
    )
    return gdf


def main() -> None:
    args = parse_args()
    script_dir = Path(__file__).resolve().parent

    hazard_dir = resolve_path(script_dir, args.hazard_dir)
    facilities_dir = resolve_path(script_dir, args.facilities_dir)
    output_dir = resolve_path(script_dir, args.output_dir)
    global_output = resolve_path(script_dir, args.global_output)

    iso3_filter = None if args.iso3 is None else {c.upper() for c in args.iso3}

    country_files = find_country_files(facilities_dir, iso3_filter)
    raster_paths = load_raster_paths(hazard_dir, args.rps)

    print(f"Hazard directory: {hazard_dir}", flush=True)
    print(f"Facilities directory: {facilities_dir}", flush=True)
    print(f"Countries to process: {len(country_files)}", flush=True)
    print(f"RPs: {sorted(raster_paths.keys())}", flush=True)

    processed: list[gpd.GeoDataFrame] = []
    for iso3, input_file in country_files:
        processed_gdf = process_country(
            iso3=iso3,
            input_file=input_file,
            output_dir=output_dir,
            raster_paths=raster_paths,
        )
        if args.write_global:
            processed.append(processed_gdf)

    if args.write_global:
        combined = gpd.GeoDataFrame(
            pd.concat(processed, ignore_index=True),
            geometry="geometry",
            crs=processed[0].crs if processed else "EPSG:4326",
        )
        global_output.parent.mkdir(parents=True, exist_ok=True)
        if global_output.suffix.lower() == ".gpkg":
            combined.to_file(global_output, layer="facilities_global_exposure", driver="GPKG", mode="w")
            print(f"Wrote global GeoPackage: {global_output} (rows={len(combined)})", flush=True)
        else:
            combined.to_parquet(global_output, index=False)
            print(f"Wrote global parquet: {global_output} (rows={len(combined)})", flush=True)


if __name__ == "__main__":
    main()
