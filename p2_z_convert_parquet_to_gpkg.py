#!/usr/bin/env python3
"""Convert a GeoParquet file to a GeoPackage (.gpkg)."""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert GeoParquet to GeoPackage.")
    parser.add_argument("input_parquet", type=Path, help="Input GeoParquet path")
    parser.add_argument("output_gpkg", type=Path, help="Output GeoPackage path")
    parser.add_argument(
        "--layer",
        default=None,
        help="GeoPackage layer name (default: output file stem)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_parquet = args.input_parquet.resolve()
    output_gpkg = args.output_gpkg.resolve()
    layer = args.layer or output_gpkg.stem

    if not input_parquet.exists():
        raise FileNotFoundError(f"Input file not found: {input_parquet}")

    gdf = gpd.read_parquet(input_parquet)

    output_gpkg.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(output_gpkg, layer=layer, driver="GPKG", mode="w")

    print(f"Done: {input_parquet} -> {output_gpkg} (layer={layer})", flush=True)


if __name__ == "__main__":
    main()
