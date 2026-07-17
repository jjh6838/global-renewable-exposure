from __future__ import annotations

import argparse
import json
from pathlib import Path

import cdsapi


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download ERA5-Land daily maximum 2m temperature month-by-month. "
            "Use --year/--month multiple times to run selected periods only."
        )
    )
    parser.add_argument(
        "--year",
        action="append",
        metavar="YYYY",
        help="Year to download (repeatable), e.g. --year 2024 --year 2023",
    )
    parser.add_argument(
        "--month",
        action="append",
        metavar="MM",
        help="Month to download (repeatable), e.g. --month 01 --month 12",
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


if __name__ == "__main__":
    main()
