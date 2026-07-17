#!/usr/bin/env python3
"""Extract IRIS vmax return-value maps to GeoTIFF files.

This writes one GeoTIFF per requested return period from the PRESENT
scenario NetCDF file, preserving the global 0.1 degree grid.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import netCDF4 as nc
import numpy as np
import rasterio
from rasterio.transform import from_origin


def build_profile(lat: np.ndarray, lon: np.ndarray) -> dict:
    if lat.size < 2 or lon.size < 2:
        raise ValueError("latitude and longitude coordinates must each have at least 2 values")

    yres = float(abs(lat[1] - lat[0]))
    xres = float(abs(lon[1] - lon[0]))
    west = float(lon.min() - xres / 2.0)
    north = float(lat.max() + yres / 2.0)

    return {
        "driver": "GTiff",
        "height": int(lat.size),
        "width": int(lon.size),
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": from_origin(west, north, xres, yres),
        "compress": "LZW",
        "tiled": True,
        "bigtiff": "IF_SAFER",
        "nodata": np.nan,
    }


def extract(input_nc: Path, output_dir: Path, return_periods: list[int], lat_chunk: int) -> None:
    with nc.Dataset(input_nc, "r") as ds:
        lat = np.asarray(ds.variables["latitude"][:], dtype=np.float64)
        lon = np.asarray(ds.variables["longitude"][:], dtype=np.float64)
        rp_values = np.asarray(ds.variables["rp"][:], dtype=np.int64)
        vmax = ds.variables["vmax"]

        rp_to_index = {int(rp): idx for idx, rp in enumerate(rp_values)}
        missing = [rp for rp in return_periods if rp not in rp_to_index]
        if missing:
            raise SystemExit(f"Missing return periods in file: {', '.join(map(str, missing))}")

        profile = build_profile(lat, lon)
        nlat = int(lat.size)
        nlon = int(lon.size)
        lat_increasing = bool(lat[0] < lat[-1])

        output_dir.mkdir(parents=True, exist_ok=True)

        for rp in return_periods:
            rp_index = rp_to_index[rp]
            out_tif = output_dir / f"IRIS_vmax_maps_PRESENT_RP{rp}.tif"

            with rasterio.open(out_tif, "w", **profile) as dst:
                for i0 in range(0, nlat, lat_chunk):
                    i1 = min(i0 + lat_chunk, nlat)
                    chunk = np.asarray(vmax[rp_index, i0:i1, :], dtype=np.float32)

                    if lat_increasing:
                        row_off = nlat - i1
                        data = chunk[::-1, :]
                    else:
                        row_off = i0
                        data = chunk

                    dst.write(data, 1, window=((row_off, row_off + (i1 - i0)), (0, nlon)))

            print(f"Wrote {out_tif}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract IRIS vmax maps to GeoTIFF.")
    parser.add_argument(
        "input_nc",
        type=Path,
        help="Input NetCDF file, for example IRIS_vmax_maps_PRESENT_tenthdeg.nc",
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        help="Directory to write GeoTIFF files into",
    )
    parser.add_argument(
        "--return-periods",
        type=int,
        nargs="+",
        default=[10, 100, 500],
        help="Return periods to extract",
    )
    parser.add_argument(
        "--lat-chunk",
        type=int,
        default=120,
        help="Latitude rows per chunk",
    )
    args = parser.parse_args()

    extract(args.input_nc, args.output_dir, args.return_periods, args.lat_chunk)


if __name__ == "__main__":
    main()