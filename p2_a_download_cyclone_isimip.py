from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import requests


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

YEAR_START = 1995
YEAR_END = 2024
TIMEOUT_SECONDS = 120

# Requested save location.
OUTPUT_ROOT = Path("/soge-home/projects/mistral/ji/bigdata_cyclonetide_isimip")

# Full globe coverage requested: no clipping/cropping.
COVERAGE_NOTE = "global extent (-180..180, -90..90), no crop"


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


def main() -> None:
    output_root = OUTPUT_ROOT.resolve()
    raw_dir = output_root / "raw_nc"

    years = list(range(YEAR_START, YEAR_END + 1))
    tasks: list[dict[str, Any]] = []
    for tide_stat, dataset_base_path in DATASETS.items():
        for year in years:
            tasks.append(
                {
                    "tide_stat": tide_stat,
                    "year": year,
                    "dataset_base_path": dataset_base_path,
                }
            )

    total = len(tasks)
    print(f"Total files targeted: {total}", flush=True)
    print(f"Years: {YEAR_START}-{YEAR_END}", flush=True)
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
    output_root.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest_rows, f, indent=2)

    print("Done", flush=True)
    print(f"Output root: {output_root}", flush=True)
    print(f"Manifest: {manifest_path}", flush=True)


if __name__ == "__main__":
    main()
