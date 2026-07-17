from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import netCDF4 as nc
import numpy as np
import rasterio
import requests
from rasterio.transform import from_origin
from rasterio.windows import Window


FILES_BASE_URL = "https://files.isimip.org"

# Requested datasets (ISIMIP3a / GeoClaw / obsclim / historical / flddph).
DATASETS: dict[str, str] = {
    "tidesmean": (
        "ISIMIP3a/InputData/climate/tropical_cyclones_flooding/obsclim/global/storm/"
        "historical/GeoClaw/geoclaw_obsclim_historical_flddph_tidesmean_30arcsec"
    ),
    "tidesmax": (
        "ISIMIP3a/InputData/climate/tropical_cyclones_flooding/obsclim/global/storm/"
        "historical/GeoClaw/geoclaw_obsclim_historical_flddph_tidesmax_30arcsec"
    ),
    "tidesmin": (
        "ISIMIP3a/InputData/climate/tropical_cyclones_flooding/obsclim/global/storm/"
        "historical/GeoClaw/geoclaw_obsclim_historical_flddph_tidesmin_30arcsec"
    ),
}
TIDE_STATS = tuple(DATASETS.keys())

YEAR_START = 1995
YEAR_END = 2024
TIMEOUT_SECONDS = 120

# Requested save location.
OUTPUT_ROOT = Path("/soge-home/projects/mistral/ji/bigdata_cyclonetide_isimip")

# Full globe coverage requested: no clipping/cropping.
COVERAGE_NOTE = "global extent (-180..180, -90..90), no crop"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download ISIMIP cyclone-tide yearly NetCDF files and optionally build "
            "global GeoTIFF climatology maps."
        )
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip download step and only run map building from existing raw_nc files.",
    )
    parser.add_argument(
        "--build-global-maps",
        action="store_true",
        help="Build GeoTIFF climatology maps from raw_nc files.",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=YEAR_START,
        help=f"Start year for download/map processing (default: {YEAR_START}).",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=YEAR_END,
        help=f"End year for download/map processing (default: {YEAR_END}).",
    )
    parser.add_argument(
        "--lat-chunk",
        type=int,
        default=8,
        help="Latitude chunk size used for memory-safe GeoTIFF aggregation.",
    )
    parser.add_argument(
        "--tide-stat",
        action="append",
        choices=TIDE_STATS,
        help=(
            "Tide scenario to process (repeatable). "
            "Defaults to all: tidesmean, tidesmax, tidesmin."
        ),
    )
    return parser.parse_args()


def resolve_tide_stats(tide_stat_args: list[str] | None) -> tuple[str, ...]:
    if not tide_stat_args:
        return TIDE_STATS
    # Keep deterministic output order matching DATASETS declaration.
    selected_set = set(tide_stat_args)
    return tuple(tide_stat for tide_stat in TIDE_STATS if tide_stat in selected_set)


def sha512sum(file_path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha512()
    with file_path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def fetch_json(url: str, timeout_seconds: int) -> dict[str, Any]:
    response = requests.get(url, timeout=timeout_seconds)
    response.raise_for_status()
    # ISIMIP metadata sometimes includes NaN values; stdlib json loader handles these.
    return json.loads(response.text)


def resolve_year_file_info(dataset_base_path: str, year: int, timeout_seconds: int) -> dict[str, Any]:
    json_url = f"{FILES_BASE_URL}/{dataset_base_path}_{year}.json"
    payload = fetch_json(json_url, timeout_seconds=timeout_seconds)

    rel_path = payload.get("path")
    if not isinstance(rel_path, str) or not rel_path.endswith(".nc"):
        raise ValueError(f"Unexpected metadata format for {json_url}: missing NetCDF path")

    checksum = payload.get("checksum")
    checksum_type = payload.get("checksum_type")
    size = payload.get("size")

    return {
        "json_url": json_url,
        "download_url": f"{FILES_BASE_URL}/{rel_path}",
        "relative_path": rel_path,
        "filename": Path(rel_path).name,
        "checksum": checksum,
        "checksum_type": checksum_type,
        "size": int(size) if size is not None else None,
    }


def download_file(
    url: str,
    output_file: Path,
    expected_size: int | None,
    expected_sha512: str | None,
) -> None:
    if output_file.exists():
        if expected_size is not None and output_file.stat().st_size != expected_size:
            print(f"Size mismatch for existing file, will re-download: {output_file.name}", flush=True)
        elif expected_sha512 is not None:
            existing_sha = sha512sum(output_file)
            if existing_sha == expected_sha512:
                print(f"Skip download (already verified): {output_file.name}", flush=True)
                return
            print(f"Checksum mismatch for existing file, will re-download: {output_file.name}", flush=True)
        else:
            print(f"Skip download (already exists): {output_file.name}", flush=True)
            return

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=TIMEOUT_SECONDS) as response:
        response.raise_for_status()
        with output_file.open("wb") as f:
            for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                if chunk:
                    f.write(chunk)

    if expected_size is not None:
        actual_size = output_file.stat().st_size
        if actual_size != expected_size:
            raise ValueError(
                f"Downloaded size mismatch for {output_file.name}: {actual_size} != {expected_size}"
            )

    if expected_sha512 is not None:
        actual_sha = sha512sum(output_file)
        if actual_sha != expected_sha512:
            raise ValueError(f"Checksum mismatch for {output_file.name}")


def discover_yearly_files(raw_dir: Path, tide_stat: str, years: list[int]) -> list[tuple[int, Path]]:
    files: list[tuple[int, Path]] = []
    missing: list[str] = []
    for year in years:
        path = raw_dir / f"geoclaw_obsclim_historical_flddph_{tide_stat}_30arcsec_{year}.nc"
        if path.exists():
            files.append((year, path))
        else:
            missing.append(str(year))

    if missing:
        raise SystemExit(
            f"Missing {tide_stat} files for years: {', '.join(missing)} in {raw_dir}"
        )
    return files


def geotiff_profile_from_coords(lat: np.ndarray, lon: np.ndarray) -> dict[str, Any]:
    nlat = int(lat.shape[0])
    nlon = int(lon.shape[0])
    if nlat < 2 or nlon < 2:
        raise ValueError("Latitude/longitude arrays must have at least 2 values")

    yres = float(abs(lat[1] - lat[0]))
    xres = float(abs(lon[1] - lon[0]))
    west = float(np.min(lon) - xres / 2.0)
    north = float(np.max(lat) + yres / 2.0)

    return {
        "driver": "GTiff",
        "height": nlat,
        "width": nlon,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": from_origin(west, north, xres, yres),
        "compress": "LZW",
        "tiled": True,
        "bigtiff": "IF_SAFER",
        "nodata": np.nan,
    }


def write_global_maps(
    output_root: Path,
    raw_dir: Path,
    years: list[int],
    lat_chunk: int,
    tide_stats: tuple[str, ...],
) -> list[str]:
    global_maps_dir = output_root / "global_maps"
    global_maps_dir.mkdir(parents=True, exist_ok=True)

    start_year = years[0]
    end_year = years[-1]

    created: list[str] = []

    for tide_stat in tide_stats:
        files = discover_yearly_files(raw_dir, tide_stat, years)
        with nc.Dataset(files[0][1], "r") as template:
            lat = np.asarray(template.variables["latitude"][:], dtype=np.float64)
            lon = np.asarray(template.variables["longitude"][:], dtype=np.float64)

        nlat = int(lat.shape[0])
        nlon = int(lon.shape[0])
        profile = geotiff_profile_from_coords(lat, lon)

        mean_tif = global_maps_dir / (
            f"cyclonetide_{tide_stat}_annual_stormmax_clim_mean_{start_year}_{end_year}.tif"
        )
        std_tif = global_maps_dir / (
            f"cyclonetide_{tide_stat}_annual_stormmax_clim_std_{start_year}_{end_year}.tif"
        )

        with rasterio.open(mean_tif, "w", **profile) as mean_dst:
            std_dst = rasterio.open(std_tif, "w", **profile)
            try:
                for i0 in range(0, nlat, lat_chunk):
                    i1 = min(i0 + lat_chunk, nlat)
                    rows = i1 - i0

                    sum_chunk = np.zeros((rows, nlon), dtype=np.float64)
                    sumsq_chunk = np.zeros((rows, nlon), dtype=np.float64)
                    count_chunk = np.zeros((rows, nlon), dtype=np.int16)

                    for year, path in files:
                        with nc.Dataset(path, "r") as ds:
                            arr = np.asarray(ds.variables["flddph"][:, i0:i1, :], dtype=np.float32)

                        # Use annual storm-wise max for all tide scenarios.
                        annual_value = np.nanmax(arr, axis=0)

                        valid = np.isfinite(annual_value)
                        sum_chunk[valid] += annual_value[valid]
                        sumsq_chunk[valid] += annual_value[valid].astype(np.float64) ** 2
                        count_chunk[valid] += 1

                        print(
                            f"Global map {tide_stat}: processed year={year}, lat_rows={i0}:{i1}",
                            flush=True,
                        )

                    mean_chunk = np.full((rows, nlon), np.nan, dtype=np.float32)
                    std_chunk = np.full((rows, nlon), np.nan, dtype=np.float32)
                    valid_cells = count_chunk > 0
                    if np.any(valid_cells):
                        c = count_chunk[valid_cells].astype(np.float64)
                        m = sum_chunk[valid_cells] / c
                        var = (sumsq_chunk[valid_cells] / c) - (m ** 2)
                        var[var < 0] = 0.0
                        s = np.sqrt(var)
                        mean_chunk[valid_cells] = m.astype(np.float32)
                        std_chunk[valid_cells] = s.astype(np.float32)

                    # Input lat is south->north, GeoTIFF row order is north->south.
                    row_off = nlat - i1
                    window = Window(col_off=0, row_off=row_off, width=nlon, height=rows)
                    mean_dst.write(np.flipud(mean_chunk), 1, window=window)
                    std_dst.write(np.flipud(std_chunk), 1, window=window)

                    print(
                        f"Global map {tide_stat}: wrote rows={i0}:{i1}",
                        flush=True,
                    )
            finally:
                std_dst.close()

        created.append(str(mean_tif))
        created.append(str(std_tif))
        print(f"Built maps: {mean_tif.name}, {std_tif.name}", flush=True)

    return created


def main() -> None:
    args = parse_args()
    if args.start_year > args.end_year:
        raise SystemExit("--start-year must be <= --end-year")
    if args.lat_chunk <= 0:
        raise SystemExit("--lat-chunk must be > 0")

    output_root = OUTPUT_ROOT.resolve()
    raw_dir = output_root / "raw_nc"
    selected_tide_stats = resolve_tide_stats(args.tide_stat)

    years = list(range(args.start_year, args.end_year + 1))
    tasks: list[dict[str, Any]] = []
    for tide_stat in selected_tide_stats:
        dataset_base_path = DATASETS[tide_stat]
        for year in years:
            tasks.append(
                {
                    "tide_stat": tide_stat,
                    "year": year,
                    "dataset_base_path": dataset_base_path,
                }
            )

    output_root.mkdir(parents=True, exist_ok=True)

    if not args.skip_download:
        total = len(tasks)
        print(f"Total files targeted: {total}", flush=True)
        print(f"Tide stats: {', '.join(selected_tide_stats)}", flush=True)
        print(f"Years: {args.start_year}-{args.end_year}", flush=True)
        print(f"Coverage: {COVERAGE_NOTE}", flush=True)

        manifest_rows: list[dict[str, Any]] = []
        for i, task in enumerate(tasks, start=1):
            tide_stat = task["tide_stat"]
            year = task["year"]
            base_path = task["dataset_base_path"]

            print(f"[{i}/{total}] Resolving metadata: {tide_stat} {year}", flush=True)
            info = resolve_year_file_info(base_path, year, timeout_seconds=TIMEOUT_SECONDS)

            raw_file = raw_dir / info["filename"]
            print(f"[{i}/{total}] Downloading: {raw_file.name}", flush=True)
            download_file(
                url=info["download_url"],
                output_file=raw_file,
                expected_size=info["size"],
                expected_sha512=info["checksum"] if info["checksum_type"] == "sha512" else None,
            )
            print(f"[{i}/{total}] Done: {raw_file.name}", flush=True)

            manifest_rows.append(
                {
                    "tide_stat": tide_stat,
                    "year": year,
                    "json_url": info["json_url"],
                    "download_url": info["download_url"],
                    "raw_file": str(raw_file),
                    "crop_applied": False,
                    "size": info["size"],
                    "checksum_type": info["checksum_type"],
                    "checksum": info["checksum"],
                }
            )

        manifest_path = output_root / "download_manifest.json"
        with manifest_path.open("w", encoding="utf-8") as f:
            json.dump(manifest_rows, f, indent=2)
        print(f"Download manifest: {manifest_path}", flush=True)

    if args.build_global_maps:
        created = write_global_maps(
            output_root=output_root,
            raw_dir=raw_dir,
            years=years,
            lat_chunk=args.lat_chunk,
            tide_stats=selected_tide_stats,
        )
        maps_manifest = output_root / "global_maps" / "global_maps_manifest.json"
        with maps_manifest.open("w", encoding="utf-8") as f:
            json.dump(created, f, indent=2)
        print(f"Global maps manifest: {maps_manifest}", flush=True)

    print("Done", flush=True)
    print(f"Output root: {output_root}", flush=True)


if __name__ == "__main__":
    main()
