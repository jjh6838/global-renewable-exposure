from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import requests


BASE_URL = "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/CEMS-GLOFAS/flood_hazard"
RP_LIST = ("RP10", "RP100", "RP500")
TIMEOUT_SECONDS = 180

# Requested save location.
OUTPUT_ROOT = Path("/soge-home/projects/mistral/ji/bigdata_riverflood_jrc")

# Keep raw depth tiles; reclass can be enabled if needed later.
INCLUDE_RECLASS = False


TILE_FILE_RE = re.compile(
    r"^(ID(?P<id>\d+)_(?P<name>[NS]\d+_[EW]\d+)_RP(?P<rp>\d+)_depth(?:_reclass)?\.tif)$"
)


def fetch_text(url: str) -> str:
    response = requests.get(url, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.text


def list_remote_tifs(rp: str, include_reclass: bool) -> list[str]:
    html = fetch_text(f"{BASE_URL}/{rp}/")
    hrefs = re.findall(r'href="([^"]+\.tif)"', html)
    files = sorted(set(Path(h).name for h in hrefs))

    if include_reclass:
        return [f for f in files if f.endswith("_depth.tif") or f.endswith("_depth_reclass.tif")]
    return [f for f in files if f.endswith("_depth.tif")]


def parse_tile_meta(file_name: str) -> tuple[str, str] | None:
    match = TILE_FILE_RE.match(file_name)
    if not match:
        return None
    return match.group("name"), match.group("rp")


def download_file(url: str, out_file: Path) -> None:
    if out_file.exists() and out_file.stat().st_size > 0:
        print(f"Skip download: {out_file.name}", flush=True)
        return

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=TIMEOUT_SECONDS) as response:
        response.raise_for_status()
        with out_file.open("wb") as f:
            for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                if chunk:
                    f.write(chunk)

    print(f"Downloaded: {out_file.name}", flush=True)


def build_vrt_if_available(vrt_path: Path, tif_files: list[Path]) -> bool:
    gdalbuildvrt = shutil.which("gdalbuildvrt")
    if gdalbuildvrt is None or not tif_files:
        return False

    vrt_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as tf:
        tf.write("\n".join(str(p) for p in tif_files))
        list_path = tf.name

    try:
        cmd = [gdalbuildvrt, "-input_file_list", list_path, str(vrt_path)]
        subprocess.run(cmd, check=True)
    finally:
        Path(list_path).unlink(missing_ok=True)

    return True


def build_global_geotiff_from_vrt_if_available(vrt_path: Path, out_tif: Path) -> bool:
    gdal_translate = shutil.which("gdal_translate")
    if gdal_translate is None or not vrt_path.exists():
        return False

    out_tif.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        gdal_translate,
        "-of",
        "GTiff",
        "-co",
        "TILED=YES",
        "-co",
        "COMPRESS=LZW",
        "-co",
        "BIGTIFF=IF_SAFER",
        str(vrt_path),
        str(out_tif),
    ]
    subprocess.run(cmd, check=True)
    return True


def main() -> None:
    output_root = OUTPUT_ROOT.resolve()
    raw_root = output_root / "raw"
    manifest_dir = output_root / "manifests"

    print("JRC flood download only (no crop)", flush=True)
    print(f"Return periods: {', '.join(RP_LIST)}", flush=True)
    print("Coverage: full available global tiles from source", flush=True)
    print(f"Output root: {output_root}", flush=True)

    manifest_rows: list[dict[str, str | bool]] = []

    for rp in RP_LIST:
        print(f"Processing {rp}...", flush=True)
        file_names = list_remote_tifs(rp, include_reclass=INCLUDE_RECLASS)

        downloaded_for_rp: list[Path] = []
        for file_name in file_names:
            parsed = parse_tile_meta(file_name)
            if parsed is None:
                continue

            tile_name, rp_in_name = parsed
            if f"RP{rp_in_name}" != rp:
                continue

            remote_url = f"{BASE_URL}/{rp}/{file_name}"
            raw_file = raw_root / rp / file_name

            download_file(remote_url, raw_file)
            downloaded_for_rp.append(raw_file)

            manifest_rows.append(
                {
                    "rp": rp,
                    "file_name": file_name,
                    "tile_name": tile_name,
                    "remote_url": remote_url,
                    "raw_file": str(raw_file),
                    "crop_applied": False,
                }
            )

        # Build an optional virtual mosaic per RP if GDAL is available.
        vrt_file = output_root / "vrt" / f"{rp}_depth.vrt"
        if build_vrt_if_available(vrt_file, downloaded_for_rp):
            print(f"Built VRT: {vrt_file}", flush=True)

            # Build a concrete global GeoTIFF map per RP from the VRT mosaic.
            global_tif_file = output_root / "global_maps" / f"{rp}_depth_global.tif"
            if build_global_geotiff_from_vrt_if_available(vrt_file, global_tif_file):
                print(f"Built global map: {global_tif_file}", flush=True)
            else:
                print(f"Skipped global map for {rp} (gdal_translate not available)", flush=True)
        else:
            print(f"Skipped VRT for {rp} (gdalbuildvrt not available)", flush=True)

    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = manifest_dir / "download_manifest.json"
    with manifest_file.open("w", encoding="utf-8") as f:
        json.dump(manifest_rows, f, indent=2)

    print("Done", flush=True)
    print(f"Manifest: {manifest_file}", flush=True)


if __name__ == "__main__":
    main()
