from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import rasterio
from pyproj import Transformer
from rasterio.windows import from_bounds
from tqdm.auto import tqdm


FLOOD_PATH = Path("/soge-home/projects/mistral/JBA_flood_datasets/processed/hazard/flrf_ud_Q100.tif")
INPUT_PARQUET_DIR = Path("output_per_country/parquet_exposure")
OUTPUT_DIR = Path("output_global")

# Sample selection requested by user.
DEFAULT_COUNTRIES = ["ABW", "AFG", "AGO", "ALB", "ARE", "ARG", "ARM", "ASM", "ATG"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract flood hazard TIFF windows for selected countries (by country bbox)."
    )
    parser.add_argument(
        "--countries",
        nargs="+",
        default=DEFAULT_COUNTRIES,
        help="ISO3 country codes to process (space-separated).",
    )
    parser.add_argument(
        "--flood-path",
        type=Path,
        default=FLOOD_PATH,
        help="Path to source flood hazard TIFF.",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=INPUT_PARQUET_DIR,
        help="Directory containing per-country parquet exposure files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Output directory for extracted country hazard TIFFs.",
    )
    return parser.parse_args()


def get_country_bounds_wgs84(country_file: Path) -> tuple[float, float, float, float]:
    gdf = gpd.read_parquet(country_file)
    if gdf.empty:
        raise ValueError(f"No features found in {country_file}")
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326", allow_override=True)
    gdf_wgs84 = gdf.to_crs("EPSG:4326")
    min_x, min_y, max_x, max_y = gdf_wgs84.total_bounds
    return float(min_x), float(min_y), float(max_x), float(max_y)


def extract_country_raster(
    src: rasterio.io.DatasetReader,
    transformer: Transformer,
    bbox_wgs84: tuple[float, float, float, float],
    output_path: Path,
) -> None:
    min_x, min_y = transformer.transform(bbox_wgs84[0], bbox_wgs84[1])
    max_x, max_y = transformer.transform(bbox_wgs84[2], bbox_wgs84[3])

    left = min(min_x, max_x)
    right = max(min_x, max_x)
    bottom = min(min_y, max_y)
    top = max(min_y, max_y)

    window = from_bounds(left, bottom, right, top, src.transform)
    data = src.read(window=window)
    transform = src.window_transform(window)

    profile = src.profile.copy()
    profile.update(height=data.shape[1], width=data.shape[2], transform=transform)

    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(data)


def main() -> None:
    args = parse_args()
    script_dir = Path(__file__).resolve().parent

    flood_path = (
        (script_dir / args.flood_path).resolve()
        if not args.flood_path.is_absolute()
        else args.flood_path.resolve()
    )
    input_dir = (
        (script_dir / args.input_dir).resolve()
        if not args.input_dir.is_absolute()
        else args.input_dir.resolve()
    )
    output_dir = (
        (script_dir / args.output_dir).resolve()
        if not args.output_dir.is_absolute()
        else args.output_dir.resolve()
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    countries = [c.upper() for c in args.countries]

    with rasterio.open(flood_path) as src:
        transformer = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
        for iso3 in tqdm(countries, desc="Processing countries", unit="country"):
            country_file = input_dir / f"polylines_{iso3}_add_v2_exposure.parquet"
            if not country_file.exists():
                print(f"Skipping {iso3}: missing {country_file.name}")
                continue

            bbox_wgs84 = get_country_bounds_wgs84(country_file)
            output_path = output_dir / f"flood_q100_{iso3}_bbox.tif"
            extract_country_raster(src, transformer, bbox_wgs84, output_path)
            print(f"Created {iso3}: {output_path}")


if __name__ == "__main__":
    main()
