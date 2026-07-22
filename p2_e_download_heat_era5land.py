from __future__ import annotations

import argparse
import json
from pathlib import Path

import cdsapi
import numpy as np
import rasterio
from rasterio.transform import from_bounds
import xarray as xr


# ---------------------------------------------------------------------------
# Download constants
# ---------------------------------------------------------------------------

DATASET = "derived-era5-land-daily-statistics"
VARIABLE = "2m_temperature"
DAILY_STATISTIC = "daily_maximum"
TIME_ZONE = "utc+00:00"
FREQUENCY = "1_hourly"

YEARS = tuple(str(year) for year in range(1995, 2025))
MONTHS = tuple(f"{month:02d}" for month in range(1, 13))
DAYS = tuple(f"{day:02d}" for day in range(1, 32))

# Requested save location.
OUTPUT_ROOT = Path("/soge-home/projects/mistral/ji/bigdata_heat_era5land")

# ---------------------------------------------------------------------------
# Global-maps constants
# ---------------------------------------------------------------------------

KELVIN_OFFSET: float = 273.15
THRESHOLDS_C: list[int] = [30, 35, 40]
NC_VAR: str = "t2m"                     # variable name in ERA5-Land NC files


def build_request(year: str, month: str) -> dict[str, str | list[str]]:
    return {
        "variable": [VARIABLE],
        "year": year,
        "month": month,
        "day": list(DAYS),
        "daily_statistic": DAILY_STATISTIC,
        "time_zone": TIME_ZONE,
        "frequency": FREQUENCY,
    }


# ---------------------------------------------------------------------------
# Global-maps helpers
# ---------------------------------------------------------------------------

def nc_files_for_year(raw_root: Path, year: int) -> list[Path]:
    """Return sorted list of monthly NC files for *year*."""
    return sorted((raw_root / str(year)).glob(f"era5land_dailymax_t2m_{year}_*.nc"))


def _detect_dim(da: xr.DataArray, candidates: list[str]) -> str:
    for name in candidates:
        if name in da.dims:
            return name
    raise KeyError(
        f"None of {candidates} found in dims {list(da.dims)}. "
        "Check the NC variable name and coordinate names."
    )


def _detect_coord(da: xr.DataArray, candidates: list[str]) -> str:
    for name in candidates:
        if name in da.coords:
            return name
    raise KeyError(
        f"None of {candidates} found in coords {list(da.coords)}. "
        "Check the NC coordinate names."
    )


def write_geotiff(
    array: np.ndarray,
    lats: np.ndarray,
    lons: np.ndarray,
    out_path: Path,
    nodata: float = -9999.0,
) -> None:
    """Write a 2-D array as a GeoTIFF in EPSG:4326 with LZW compression."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Rasterio expects rows ordered north → south.
    if lats[0] < lats[-1]:
        array = array[::-1, :]
        lats = lats[::-1]

    res_lon = float(lons[1] - lons[0])
    res_lat = float(lats[0] - lats[1])

    transform = from_bounds(
        west=float(lons[0]) - res_lon / 2,
        south=float(lats[-1]) - res_lat / 2,
        east=float(lons[-1]) + res_lon / 2,
        north=float(lats[0]) + res_lat / 2,
        width=len(lons),
        height=len(lats),
    )

    out_array = array.astype(np.float32)
    out_array[~np.isfinite(out_array)] = nodata

    with rasterio.open(
        out_path, "w",
        driver="GTiff",
        height=len(lats), width=len(lons),
        count=1, dtype="float32",
        crs="EPSG:4326", transform=transform,
        nodata=nodata, compress="lzw",
    ) as dst:
        dst.write(out_array, 1)


def compute_exceedance_days(
    raw_root: Path,
    year: int,
    thresholds_c: list[int],
) -> dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] | None:
    """
    Load all monthly NC files for *year*, convert K → °C, count exceedance
    days per threshold.  Returns dict threshold → (count_2d, lats, lons),
    or None if no files found.
    """
    files = nc_files_for_year(raw_root, year)
    if not files:
        print(f"  WARNING: no NC files found for {year} – skipping.", flush=True)
        return None

    expected = {
        raw_root / str(year) / f"era5land_dailymax_t2m_{year}_{m:02d}.nc"
        for m in range(1, 13)
    }
    missing = sorted(expected - set(files))
    if missing:
        print(
            f"  WARNING: {len(missing)} monthly file(s) missing for {year}: "
            f"{[f.name for f in missing]}",
            flush=True,
        )

    datasets = [xr.open_dataset(f) for f in files]
    ds = xr.concat(datasets, dim="valid_time" if "valid_time" in datasets[0].dims else "time")
    t2m_c: xr.DataArray = ds[NC_VAR] - KELVIN_OFFSET

    time_dim = _detect_dim(t2m_c, ["valid_time", "time"])
    lat_coord = _detect_coord(t2m_c, ["latitude", "lat"])
    lon_coord = _detect_coord(t2m_c, ["longitude", "lon"])

    lats: np.ndarray = t2m_c.coords[lat_coord].values
    lons: np.ndarray = t2m_c.coords[lon_coord].values

    results: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for thresh in thresholds_c:
        count = (t2m_c > thresh).sum(dim=time_dim).values.astype(np.float32)
        results[thresh] = (count, lats, lons)

    ds.close()
    for _d in datasets:
        _d.close()
    return results


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download ERA5-Land daily maximum 2 m temperature and/or write "
            "global exceedance-day maps and climatology GeoTIFFs."
        )
    )
    parser.add_argument(
        "--year",
        action="append",
        metavar="YYYY",
        help="Year to download (repeatable). Ignored with --write-global.",
    )
    parser.add_argument(
        "--month",
        action="append",
        metavar="MM",
        help="Month to download (repeatable). Ignored with --write-global.",
    )
    parser.add_argument(
        "--write-global",
        action="store_true",
        default=False,
        help=(
            "Skip downloading; compute yearly exceedance-day maps "
            "(30/35/40 °C) for 1995-2024 and their climatological mean. "
            "Output goes to {OUTPUT_ROOT}/global_maps/."
        ),
    )
    return parser.parse_args()


def resolve_years(year_args: list[str] | None) -> tuple[str, ...]:
    if not year_args:
        return YEARS

    selected = sorted(set(year_args), key=int)
    invalid = [year for year in selected if year not in YEARS]
    if invalid:
        valid_range = f"{YEARS[0]}-{YEARS[-1]}"
        raise SystemExit(
            f"Invalid --year value(s): {', '.join(invalid)}. Valid years: {valid_range}."
        )
    return tuple(selected)


def resolve_months(month_args: list[str] | None) -> tuple[str, ...]:
    if not month_args:
        return MONTHS

    normalized = [f"{int(month):02d}" if month.isdigit() else month for month in month_args]
    selected = sorted(set(normalized), key=int)
    invalid = [month for month in selected if month not in MONTHS]
    if invalid:
        raise SystemExit(
            f"Invalid --month value(s): {', '.join(invalid)}. Valid months: 01-12."
        )
    return tuple(selected)


def main() -> None:
    args = parse_args()

    if args.write_global:
        _run_write_global_maps()
    else:
        _run_download(args)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _run_download(args: argparse.Namespace) -> None:
    selected_years = resolve_years(args.year)
    selected_months = resolve_months(args.month)

    output_root = OUTPUT_ROOT.resolve()
    raw_root = output_root / "raw_nc"
    manifest_dir = output_root / "manifests"

    raw_root.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    print("ERA5-Land heat download only (month-by-month)", flush=True)
    print(f"Dataset: {DATASET}", flush=True)
    if selected_years == YEARS:
        print(f"Years: {YEARS[0]}-{YEARS[-1]} ({len(YEARS)} years)", flush=True)
    else:
        print(
            f"Selected years: {selected_years[0]}-{selected_years[-1]} ({len(selected_years)} year(s))",
            flush=True,
        )
    if selected_months == MONTHS:
        print(f"Months per year: {len(MONTHS)}", flush=True)
    else:
        print(
            f"Selected months: {', '.join(selected_months)} ({len(selected_months)} month(s))",
            flush=True,
        )
    print(f"Output root: {output_root}", flush=True)

    client = cdsapi.Client(quiet=False, progress=True)

    manifest_rows: list[dict[str, str | bool]] = []
    failed: list[tuple[str, str, str]] = []

    for year in selected_years:
        for month in selected_months:
            out_file = raw_root / year / f"era5land_dailymax_t2m_{year}_{month}.nc"
            out_file.parent.mkdir(parents=True, exist_ok=True)

            if out_file.exists() and out_file.stat().st_size > 0:
                print(f"Skip existing: {out_file}", flush=True)
                manifest_rows.append(
                    {
                        "year": year,
                        "month": month,
                        "dataset": DATASET,
                        "variable": VARIABLE,
                        "daily_statistic": DAILY_STATISTIC,
                        "frequency": FREQUENCY,
                        "time_zone": TIME_ZONE,
                        "output_file": str(out_file),
                        "downloaded": False,
                        "status": "skipped_existing",
                    }
                )
                continue

            request = build_request(year, month)
            print(f"Downloading year={year}, month={month} -> {out_file.name}", flush=True)

            try:
                client.retrieve(DATASET, request, str(out_file))
                manifest_rows.append(
                    {
                        "year": year,
                        "month": month,
                        "dataset": DATASET,
                        "variable": VARIABLE,
                        "daily_statistic": DAILY_STATISTIC,
                        "frequency": FREQUENCY,
                        "time_zone": TIME_ZONE,
                        "output_file": str(out_file),
                        "downloaded": True,
                        "status": "downloaded",
                    }
                )
            except Exception as exc:
                print(f"Failed year={year}, month={month}: {exc}", flush=True)
                failed.append((year, month, str(exc)))
                manifest_rows.append(
                    {
                        "year": year,
                        "month": month,
                        "dataset": DATASET,
                        "variable": VARIABLE,
                        "daily_statistic": DAILY_STATISTIC,
                        "frequency": FREQUENCY,
                        "time_zone": TIME_ZONE,
                        "output_file": str(out_file),
                        "downloaded": False,
                        "status": "failed",
                        "error": str(exc),
                    }
                )

    if selected_years == YEARS:
        manifest_file = manifest_dir / "download_manifest.json"
        failed_file = manifest_dir / "failed_requests.json"
    elif len(selected_years) == 1:
        suffix = selected_years[0]
        manifest_file = manifest_dir / f"download_manifest_{suffix}.json"
        failed_file = manifest_dir / f"failed_requests_{suffix}.json"
    else:
        suffix = f"{selected_years[0]}_{selected_years[-1]}_n{len(selected_years)}"
        manifest_file = manifest_dir / f"download_manifest_{suffix}.json"
        failed_file = manifest_dir / f"failed_requests_{suffix}.json"

    with manifest_file.open("w", encoding="utf-8") as f:
        json.dump(manifest_rows, f, indent=2)

    if failed:
        with failed_file.open("w", encoding="utf-8") as f:
            json.dump(
                [
                    {"year": year, "month": month, "error": err}
                    for year, month, err in failed
                ],
                f,
                indent=2,
            )
        raise SystemExit(
            f"Completed with failures: {len(failed)} month(s). See {failed_file} and {manifest_file}."
        )

    print("Done", flush=True)
    print(f"Manifest: {manifest_file}", flush=True)


# ---------------------------------------------------------------------------
# Write global maps
# ---------------------------------------------------------------------------

def _run_write_global_maps() -> None:
    """
    Compute yearly exceedance-day maps and climatological mean GeoTIFFs.

    Steps
    -----
    0. Convert Kelvin → Celsius  (ERA5-Land stores temperature in Kelvin)
    1. For each year 1995-2024: count days where daily-max T > 30/35/40 °C.
       Save one GeoTIFF per (year, threshold).
    2. For each threshold: compute mean days/year over 1995-2024.
       Save one climatological GeoTIFF per threshold.
    """
    output_root = OUTPUT_ROOT.resolve()
    raw_root = output_root / "raw_nc"
    exceedance_dir = output_root / "global_maps" / "exceedance_days"
    clim_dir = output_root / "global_maps" / "climatology"

    years_int = [int(y) for y in YEARS]

    print("ERA5-Land heat: writing global maps", flush=True)
    print(f"Output root : {output_root}", flush=True)
    print(f"Thresholds  : {THRESHOLDS_C} °C", flush=True)
    print(f"Years       : {years_int[0]}–{years_int[-1]}", flush=True)
    print(flush=True)

    yearly_stacks: dict[int, list[np.ndarray]] = {t: [] for t in THRESHOLDS_C}
    lats_ref: np.ndarray | None = None
    lons_ref: np.ndarray | None = None

    # Step 1 – yearly exceedance-day maps
    for year in years_int:
        print(f"Year {year} ...", flush=True)
        result = compute_exceedance_days(raw_root, year, THRESHOLDS_C)
        if result is None:
            continue

        for thresh, (arr, lats, lons) in result.items():
            if lats_ref is None:
                lats_ref, lons_ref = lats, lons
            out_path = exceedance_dir / f"heat_exceedance_{thresh}C_{year}.tif"
            write_geotiff(arr, lats, lons, out_path)
            print(f"  Saved: {out_path.name}", flush=True)
            yearly_stacks[thresh].append(arr)

    print(flush=True)

    # Step 2 – climatological mean days/year
    print("Computing climatological means ...", flush=True)

    if lats_ref is None or lons_ref is None:
        raise SystemExit("ERROR: no yearly data was processed – cannot compute climatology.")

    for thresh in THRESHOLDS_C:
        arrays = yearly_stacks[thresh]
        if not arrays:
            print(f"  No data for {thresh} °C – skipping climatology.", flush=True)
            continue
        clim_mean = np.stack(arrays, axis=0).mean(axis=0)
        out_path = clim_dir / f"heat_clim_mean_exceedance_{thresh}C_{years_int[0]}_{years_int[-1]}.tif"
        write_geotiff(clim_mean, lats_ref, lons_ref, out_path)
        print(f"  {thresh} °C  ({len(arrays)} years)  →  {out_path.name}", flush=True)

    print(flush=True)
    print("Done.", flush=True)


if __name__ == "__main__":
    main()
