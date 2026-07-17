# p2_test Pipeline (p2_a to p2_l)

This README documents only the production scripts in this workspace:

- p2_a_download_cyclonetides_isimip.py
- p2_b_process_download_cyclonetides_isimip.sh
- p2_c_download_riverflood_jrc.py
- p2_d_process_download_riverflood_jrc.sh
- p2_g_extract_cyclone_iris_nc_to_tif.py
- p2_h_process_extract_cyclone_iris_nc_to_tif.sh
- p2_i_analyze_facilities_exposure.py
- p2_m_analyze_polylines_exposure.py
- p2_n_process_analyze_polylines_exposure.sh

## Environment setup

eval "$($HOME/.local/bin/micromamba shell hook --shell bash)"
micromamba create -n p2_etl -f environment_p2_etl.yml -y || true
micromamba install -n p2_etl --file environment_p2_etl.yml -y
- p2_a_download_cyclonetides_isimip.py (Python)
- p2_b_process_download_cyclonetides_isimip.sh (Slurm wrapper)

Purpose:

- Download yearly ISIMIP cyclone-tide NetCDF files (global, no crop)
- Optionally build global climatology GeoTIFF maps

Key options for p2_a:

- --skip-download
- --start-year YYYY
- --end-year YYYY
 output_per_country/parquet_facilities_exposure/facilities_<ISO3>_exposure.parquet
- --tide-stat tidesmean|tidesmax|tidesmin (repeatable)

Examples:
python p2_a_download_cyclonetides_isimip.py --start-year 2000 --end-year 2005 --tide-stat tidesmax

sbatch p2_b_process_download_cyclonetides_isimip.sh
Main output root:

- /soge-home/projects/mistral/ji/bigdata_cyclonetide_isimip
Script pair:

- p2_c_download_riverflood_jrc.py
- p2_d_process_download_riverflood_jrc.sh

Purpose:

- Download JRC flood depth TIFFs for RP10/RP100/RP500
- Optionally create VRT and global GeoTIFF mosaics if GDAL tools are available

Examples:

```bash
```

Main output root:
## p2_e and p2_f: ERA5-Land heat download

Script pair:

Purpose:


- --year YYYY (repeatable)
- --month MM (repeatable)

Prompt/CLI behavior in p2_f:

- Accepts positional arguments: <YEAR> [MONTH]
- If no month and Slurm array ID exists, uses SLURM_ARRAY_TASK_ID as month
- If YEAR is missing in an interactive shell, prompts: Enter year (YYYY)

python p2_e_download_heat_era5land.py
python p2_e_download_heat_era5land.py --year 2024 --month 07
python p2_e_download_heat_era5land.py --year 2023 --year 2024 --month 06 --month 07

sbatch p2_f_process_download_heat_era5land.sh 2024 07
sbatch p2_f_process_download_heat_era5land.sh 2024
sbatch --array=1-12%5 p2_f_process_download_heat_era5land.sh 2024
```

 Per-country output dir: output_per_country/parquet_centroids_exposure

- /soge-home/projects/mistral/ji/bigdata_heat_era5land

## p2_g and p2_h: IRIS cyclone RP map extraction

Script pair:

- p2_g_extract_cyclone_iris_nc_to_tif.py
- p2_h_process_extract_cyclone_iris_nc_to_tif.sh

Purpose:

- Extract IRIS PRESENT return-period layers from NetCDF to global GeoTIFF

Current default return periods:

- 10, 100, 500

Key options for p2_g:

- positional: input_nc output_dir
- --return-periods 10 100 500
- --lat-chunk N

Prompt/CLI behavior in p2_h:

- Uses environment variable RETURN_PERIODS
- Default: RETURN_PERIODS="10 100 500"

Examples:

```bash
python p2_g_extract_cyclone_iris_nc_to_tif.py \
  /soge-home/projects/mistral/ji/bigdata_cyclone_iris/return_value_maps/IRIS_vmax_maps_PRESENT_tenthdeg.nc \
  /soge-home/projects/mistral/ji/bigdata_cyclone_iris/global_maps \
  --return-periods 10 100 500

RETURN_PERIODS="500" sbatch p2_h_process_extract_cyclone_iris_nc_to_tif.sh
sbatch p2_h_process_extract_cyclone_iris_nc_to_tif.sh
```

Main output path:

- /soge-home/projects/mistral/ji/bigdata_cyclone_iris/global_maps

## p2_i and p2_j: Cyclone exposure analysis (facilities)

Script pair:

- p2_i_analyze_facilities_exposure.py
- p2_j_process_analyze_facilities_exposure.sh

Purpose:

- Overlay IRIS cyclone RP rasters with facilities parquet files
- Write per-country exposure parquet outputs as facilities_<ISO3>_exposure.parquet
- Exposure threshold: wind speed >= 33 m/s

Output exposure columns in p2_i:

- exposed_cyclone_rp10
- exposed_cyclone_rp100
- exposed_cyclone_rp500

Key options for p2_i:

- --hazard-dir PATH
- --facilities-dir PATH
- --output-dir PATH
- --global-output PATH (default: output_global/facilities_global_exposure.gpkg)
- --rps 10 100 500
- --iso3 ISO3 [ISO3 ...]
- --write-global / --no-write-global

Examples for p2_i:

```bash
python p2_i_analyze_facilities_exposure.py --iso3 ABW --rps 10 100 500
python p2_i_analyze_facilities_exposure.py --rps 10 100 500
python p2_i_analyze_facilities_exposure.py --rps 10 100 500 --write-global
```

Global output when `--write-global` is enabled:

- output_global/facilities_global_exposure.gpkg (layer: facilities_global_exposure)

Per-country output naming:

- output_per_country/parquet_facilities_exposure/facilities_<ISO3>_exposure.parquet

Tiered Slurm behavior in p2_j:

- Default with no `--iso3`: submits tiered global arrays.
- --submit-tiered: build tier country lists and submit 3 Slurm arrays
- --iso3 ISO3: one-country direct run
- --write-global / --no-write-global are available (`--write-global` is optional).
- Array worker mode uses --tier and --country-list-file

Global output behavior in p2_j:

- In tiered submit mode, global build is OFF by default.
- --write-global runs global-only mode: it builds from existing per-country outputs and does not submit/re-run per-country jobs.
- Global file written:
  - output_global/facilities_global_exposure.gpkg (layer: facilities_global_exposure)

Current tier setup in p2_j:

- Tier 1: CHN, USA, IND, BRA, DEU, FRA, RUS
- Tier 2: CAN, MEX, AUS, ARG, KAZ, SAU, IDN, IRN, ZAF, EGY
- Tier 3: all remaining countries from facilities files

Current tier resource submission:

- Tier 1: Long, 40 CPU, 95G, 168:00:00, array concurrency 7
- Tier 2: Medium, 40 CPU, 95G, 48:00:00, array concurrency 6
- Tier 3: Short, 40 CPU, 25G, 12:00:00, array concurrency 24

Slurm prompt for p2_j (run from login shell):

```bash
# Submit all countries as tiered Slurm arrays (default mode)
bash p2_j_process_analyze_facilities_exposure.sh

# Submit one country as a Slurm job (test purpose)
sbatch p2_j_process_analyze_facilities_exposure.sh --iso3 BGD

# Submit global combine as a Slurm job (from existing per-country outputs)
sbatch p2_j_process_analyze_facilities_exposure.sh --write-global
```

Notes for p2_j Slurm behavior:

- `bash p2_j_process_analyze_facilities_exposure.sh` is a submit command. It does not process all countries in the current shell; it internally issues `sbatch` submissions for tiered Slurm array jobs.
- You can verify submitted jobs with `squeue -u lina4376`.

About `output_global/slurm_country_lists_facilities/`:

- This folder is temporary orchestration metadata created automatically by `p2_j_process_analyze_facilities_exposure.sh`.
- It stores tier country list files (`tier1.txt`, `tier2.txt`, `tier3.txt`) used by facilities Slurm array tasks.
- You do not need to create it manually.
- If deleted, it will be recreated on the next p2_j tiered submission.

## p2_k and p2_l: Cyclone exposure analysis (centroids)

Script pair:

- p2_k_analyze_centroids_exposure.py
- p2_l_process_analyze_centroids_exposure.sh

Purpose:

- Overlay IRIS cyclone RP rasters with centroids parquet files
- Write per-country centroid exposure parquet outputs
- Exposure threshold: wind speed >= 33 m/s

Output exposure columns in p2_k:

- exposed_cyclone_rp10
- exposed_cyclone_rp100
- exposed_cyclone_rp500

Default paths in p2_k:

- Input centroids dir: /soge-home/projects/mistral/ji/bigdata_global_renewable_dataset_p1/2050_supply_100%_add_v2
- Per-country output dir: output_per_country/parquet_centroids_exposure
- Global output: output_global/centroids_global_exposure.gpkg (layer: centroids_global_exposure)

Examples for p2_k:

```bash
python p2_k_analyze_centroids_exposure.py --iso3 BGD --rps 10 100 500
python p2_k_analyze_centroids_exposure.py --rps 10 100 500 --write-global
```

Tiered Slurm behavior in p2_l:

- Default with no `--iso3`: submits tiered global arrays.
- `--iso3 ISO3`: runs a single country (RPs 10/100/500 together by default).
- `--write-global` / `--no-write-global` are available (`--write-global` is optional).

Global output behavior in p2_l:

- In tiered submit mode, global build is OFF by default.
- `--write-global` runs global-only mode: it builds from existing per-country outputs and does not submit/re-run per-country jobs.
- Global file written:
  - output_global/centroids_global_exposure.gpkg (layer: centroids_global_exposure)

Slurm prompt for p2_l (run from login shell):

```bash
# Submit all countries as tiered Slurm arrays (default mode)
bash p2_l_process_analyze_centroids_exposure.sh

# Submit one country as a Slurm job (test purpose)
sbatch p2_l_process_analyze_centroids_exposure.sh --iso3 BGD

# Submit global combine as a Slurm job (from existing per-country outputs)
sbatch p2_l_process_analyze_centroids_exposure.sh --write-global
```

Notes for p2_l Slurm behavior:

- `bash p2_l_process_analyze_centroids_exposure.sh` is a submit command. It does not process all countries in the current shell; it internally issues `sbatch` submissions for tiered Slurm array jobs.
- You can verify submitted jobs with `squeue -u lina4376`.

About `output_global/slurm_country_lists_centroids/`:

- This folder is temporary orchestration metadata created automatically by `p2_l_process_analyze_centroids_exposure.sh`.
- It stores tier country list files (`tier1.txt`, `tier2.txt`, `tier3.txt`) that Slurm array tasks use to map `SLURM_ARRAY_TASK_ID` to ISO3.
- You do not need to create it manually.
- If deleted, it will be recreated on the next tiered submission.

## p2_m and p2_n: Cyclone exposure analysis (polylines)

Script pair:

- p2_m_analyze_polylines_exposure.py
- p2_n_process_analyze_polylines_exposure.sh

Purpose:

- Overlay IRIS cyclone RP rasters with polyline parquet files
- Write per-country polyline exposure parquet outputs
- Exposure threshold: wind speed >= 33 m/s

Output exposure columns in p2_m:

- exposed_cyclone_rp10
- exposed_cyclone_rp100
- exposed_cyclone_rp500

Default paths in p2_m:

- Input polylines dir: /soge-home/projects/mistral/ji/bigdata_global_renewable_dataset_p1/2050_supply_100%_add_v2
- Per-country output dir: output_per_country/parquet_polylines_exposure
- Global output: output_global/polylines_global_exposure.gpkg (layer: polylines_global_exposure)

Tiered Slurm behavior in p2_n:

- Default with no `--iso3`: submits tiered global arrays.
- `--iso3 ISO3`: runs a single country (RPs 10/100/500 together by default).
- `--write-global` / `--no-write-global` are available (`--write-global` is optional).

Global output behavior in p2_n:

- In tiered submit mode, global build is OFF by default.
- `--write-global` runs global-only mode: it builds from existing per-country outputs and does not submit/re-run per-country jobs.
- Global file written:
  - output_global/polylines_global_exposure.gpkg (layer: polylines_global_exposure)

Slurm prompt for p2_n (run from login shell):

```bash
# Submit all countries as tiered Slurm arrays (default mode)
bash p2_n_process_analyze_polylines_exposure.sh

# Submit one country as a Slurm job (test purpose)
sbatch p2_n_process_analyze_polylines_exposure.sh --iso3 BGD

# Submit global combine as a Slurm job (from existing per-country outputs)
sbatch p2_n_process_analyze_polylines_exposure.sh --write-global
```

About `output_global/slurm_country_lists_polylines/`:

- This folder is temporary orchestration metadata created automatically by `p2_n_process_analyze_polylines_exposure.sh`.
- It stores tier country list files (`tier1.txt`, `tier2.txt`, `tier3.txt`) that Slurm array tasks use to map `SLURM_ARRAY_TASK_ID` to ISO3.
- You do not need to create it manually.
- If deleted, it will be recreated on the next tiered submission.

## Slurm monitoring

```bash
squeue -u lina4376
scontrol show job <JOB_ID>
sacct -j <JOB_ID> --format=JobID,State,Elapsed,MaxRSS,ExitCode
scancel <JOB_ID>
```

## Logs

- Cyclonetide ISIMIP: logs/slurm_cyclone_isimip_<JOB_ID>.out and logs/slurm_cyclone_isimip_<JOB_ID>.err
- JRC flood: logs/slurm_flood_jrc_download_<JOB_ID>.out and logs/slurm_flood_jrc_download_<JOB_ID>.err
- ERA5-Land heat: logs/slurm_heat_era5land_download_<JOB_ID>.out and logs/slurm_heat_era5land_download_<JOB_ID>.err
- IRIS extract: logs/slurm_iris_vmax_to_tif_<JOB_ID>.out and logs/slurm_iris_vmax_to_tif_<JOB_ID>.err
- Facilities exposure tier arrays: logs/slurm_analyze_exposure_<JOB_ID>.out and logs/slurm_analyze_exposure_<JOB_ID>.err
- Centroids exposure tier arrays: logs/slurm_analyze_centroids_exposure_<JOB_ID>.out and logs/slurm_analyze_centroids_exposure_<JOB_ID>.err
- Polylines exposure tier arrays: logs/slurm_analyze_polylines_exposure_<JOB_ID>.out and logs/slurm_analyze_polylines_exposure_<JOB_ID>.err
