from pathlib import Path

import geopandas as gpd
import pandas as pd
import rasterio
from rasterio.mask import mask
from tqdm.auto import tqdm

flood_path = Path("/soge-home/projects/mistral/JBA_flood_datasets/processed/hazard/flrf_ud_Q100.tif")
data_dir = Path("/soge-home/users/lina4376/dphil_p2/p2_test/global_renewable_dataset_v1.0.0/2050_supply_100%_add_v2")
output_dir = Path("/soge-home/users/lina4376/dphil_p2/p2_test/output_global")
output_gpkg = output_dir / "polylines_global_exposure.gpkg"
output_excel = output_dir / "polylines_global_exposure_summary.xlsx"
output_parquet_dir = Path("/soge-home/users/lina4376/dphil_p2/p2_test/output_per_country/parquet_exposure")

THRESHOLDS = (
    (3.0, "exposed_3m_above"),
    (2.0, "exposed_2m_above"),
    (1.0, "exposed_1m_above"),
)
STATUS_ORDER = [
    "exposed_3m_above",
    "exposed_2m_above",
    "exposed_1m_above",
    "not_exposed",
]

# Set to None for full run. For quick tests, use e.g. {"KOR"}.
test_iso3_filter: set[str] | None = None


def classify_exposure(depth_value: float) -> str:
    for threshold, status in THRESHOLDS:
        if depth_value >= threshold:
            return status
    return "not_exposed"


def max_depth_for_geometry(src: rasterio.io.DatasetReader, geometry) -> float:
    if geometry is None or geometry.is_empty:
        return 0.0

    try:
        clipped, _ = mask(src, [geometry], crop=True, filled=False)
    except ValueError:
        # Geometry does not overlap raster extent.
        return 0.0

    band = clipped[0]
    if band.mask.all():
        return 0.0
    return float(band.max())


files = sorted(data_dir.glob("polylines_*_add_v2.parquet"))
if not files:
    raise FileNotFoundError(f"No polylines files found in {data_dir}")

if test_iso3_filter:
    files = [f for f in files if f.stem.replace("polylines_", "").replace("_add_v2", "") in test_iso3_filter]
    if not files:
        raise FileNotFoundError(f"No files matched test_iso3_filter={sorted(test_iso3_filter)}")
    print(f"Test mode active. Processing ISO3={sorted(test_iso3_filter)}")

output_dir.mkdir(parents=True, exist_ok=True)
output_parquet_dir.mkdir(parents=True, exist_ok=True)
if output_gpkg.exists():
    output_gpkg.unlink()

processed_countries: list[gpd.GeoDataFrame] = []
polygon_rows_for_excel: list[pd.DataFrame] = []

with rasterio.open(flood_path) as src:
    print("Raster CRS:", src.crs)
    for fp in tqdm(files, desc="Processing countries", unit="file"):
        iso3 = fp.stem.replace("polylines_", "").replace("_add_v2", "")
        country_gdf = gpd.read_parquet(fp)
        country_gdf["iso3"] = iso3
        country_in_raster_crs = country_gdf.to_crs(src.crs)
        max_depths = [
            max_depth_for_geometry(src, geom)
            for geom in country_in_raster_crs.geometry
        ]
        country_gdf["flood_depth_q100_max"] = max_depths
        country_gdf["flood_exposed"] = country_gdf["flood_depth_q100_max"].map(classify_exposure)

        country_output_parquet = output_parquet_dir / f"polylines_{iso3}_add_v2_exposure.parquet"
        country_gdf.to_parquet(country_output_parquet, index=False)

        polygon_rows_for_excel.append(pd.DataFrame(country_gdf.drop(columns="geometry")))
        processed_countries.append(country_gdf.to_crs("EPSG:4326"))

all_assets = gpd.GeoDataFrame(
    pd.concat(processed_countries, ignore_index=True),
    geometry="geometry",
    crs="EPSG:4326",
)
all_assets.to_file(output_gpkg, layer="polylines", driver="GPKG", mode="w")

polygon_level_df = pd.concat(polygon_rows_for_excel, ignore_index=True)
country_summary = (
    polygon_level_df.groupby(["iso3", "flood_exposed"]).size().unstack(fill_value=0).reset_index()
)
for status in STATUS_ORDER:
    if status not in country_summary.columns:
        country_summary[status] = 0
country_summary["total_assets"] = country_summary[STATUS_ORDER].sum(axis=1)
country_summary = country_summary[["iso3", *STATUS_ORDER, "total_assets"]]

global_summary = polygon_level_df["flood_exposed"].value_counts().to_dict()
global_summary_row = {status: int(global_summary.get(status, 0)) for status in STATUS_ORDER}
global_summary_row["total_assets"] = int(sum(global_summary_row.values()))
global_summary_df = pd.DataFrame([global_summary_row])

with pd.ExcelWriter(output_excel) as writer:
    polygon_level_df.to_excel(writer, sheet_name="polygon_status", index=False)
    country_summary.to_excel(writer, sheet_name="country_summary", index=False)
    global_summary_df.to_excel(writer, sheet_name="global_summary", index=False)

print("Done")
print("Parquet folder:", output_parquet_dir)
print("Global GPKG:", output_gpkg)
print("Excel:", output_excel)
print("Total assets:", len(polygon_level_df))