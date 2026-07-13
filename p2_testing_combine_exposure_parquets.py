from __future__ import annotations

import argparse
from pathlib import Path
import re

import geopandas as gpd
import pandas as pd


ISO3_FILENAME_RE = re.compile(r"^polylines_([A-Za-z0-9]{3})_.*$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Combine country-level exposure parquet files into a single global GeoPackage."
        )
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("output_per_country/parquet_exposure"),
        help="Directory containing per-country exposure parquet files.",
    )
    parser.add_argument(
        "--output-gpkg",
        type=Path,
        default=Path("output_global/polylines_global_exposure.gpkg"),
        help="Path to output GeoPackage.",
    )
    parser.add_argument(
        "--layer",
        type=str,
        default="polylines",
        help="GeoPackage layer name.",
    )
    parser.add_argument(
        "--pattern",
        type=str,
        default="polylines_*_add_v2_exposure.parquet",
        help="Glob pattern for parquet files inside --input-dir.",
    )
    parser.add_argument(
        "--countries",
        nargs="+",
        default=None,
        help="Optional ISO3 country codes to include (space-separated), e.g. --countries KOR JPN GBR.",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Fail if the output GeoPackage already exists.",
    )
    return parser.parse_args()


def iso3_from_path(file_path: Path) -> str | None:
    match = ISO3_FILENAME_RE.match(file_path.stem)
    if not match:
        return None
    return match.group(1).upper()


def ensure_iso3_column(gdf: gpd.GeoDataFrame, file_path: Path) -> gpd.GeoDataFrame:
    if "iso3" in gdf.columns:
        return gdf

    parts = file_path.stem.split("_")
    # Expected names like polylines_KOR_add_v2_exposure
    if len(parts) >= 2 and parts[0] == "polylines":
        gdf = gdf.copy()
        gdf["iso3"] = parts[1]
    return gdf


def main() -> None:
    args = parse_args()

    script_dir = Path(__file__).resolve().parent
    input_dir = (script_dir / args.input_dir).resolve() if not args.input_dir.is_absolute() else args.input_dir.resolve()
    output_gpkg = (
        (script_dir / args.output_gpkg).resolve()
        if not args.output_gpkg.is_absolute()
        else args.output_gpkg.resolve()
    )

    parquet_files = sorted(input_dir.glob(args.pattern))
    if not parquet_files:
        raise FileNotFoundError(
            f"No parquet files found in {input_dir} matching pattern '{args.pattern}'."
        )

    if args.countries:
        selected_iso3 = {c.upper() for c in args.countries}
        filtered_files: list[Path] = []
        unknown_files = 0
        for fp in parquet_files:
            iso3 = iso3_from_path(fp)
            if iso3 is None:
                unknown_files += 1
                continue
            if iso3 in selected_iso3:
                filtered_files.append(fp)

        parquet_files = filtered_files
        if not parquet_files:
            raise FileNotFoundError(
                f"No parquet files found for selected countries {sorted(selected_iso3)} in {input_dir}."
            )

        print(f"Country filter active: {sorted(selected_iso3)}")
        if unknown_files:
            print(f"Skipped {unknown_files} file(s) with unrecognized filename format.")

    print(f"Found {len(parquet_files)} parquet file(s).")

    gdfs: list[gpd.GeoDataFrame] = []
    for fp in parquet_files:
        gdf = gpd.read_parquet(fp)
        gdf = ensure_iso3_column(gdf, fp)

        if gdf.crs is None:
            # Fall back to WGS84 if CRS metadata is missing.
            gdf = gdf.set_crs("EPSG:4326", allow_override=True)

        # Standardize to WGS84 for one consistent global output.
        gdf = gdf.to_crs("EPSG:4326")
        gdfs.append(gdf)

    combined = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True), geometry="geometry", crs="EPSG:4326")

    output_gpkg.parent.mkdir(parents=True, exist_ok=True)
    if output_gpkg.exists():
        if args.no_overwrite:
            raise FileExistsError(
                f"Output file already exists and --no-overwrite was set: {output_gpkg}"
            )
        output_gpkg.unlink()

    combined.to_file(output_gpkg, layer=args.layer, driver="GPKG", mode="w")

    print("Done")
    print(f"Input dir: {input_dir}")
    print(f"Output GPKG: {output_gpkg}")
    print(f"Layer: {args.layer}")
    print(f"Total features: {len(combined)}")


if __name__ == "__main__":
    main()
