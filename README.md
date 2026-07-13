# p2_test Workflows

## 1) Country Exposure (existing workflow)

### Submit jobs
```bash
sbatch /soge-home/users/lina4376/dphil_p2/p2_test/process_country_exposure.sh
sbatch /soge-home/users/lina4376/dphil_p2/p2_test/process_country_hazard_extract.sh
```

### If sbatch reports DOS line breaks
```bash
sed -i 's/\r$//' /soge-home/users/lina4376/dphil_p2/p2_test/process_country_exposure.sh
sed -i 's/\r$//' /soge-home/users/lina4376/dphil_p2/p2_test/process_country_hazard_extract.sh
```

### Monitor
```bash
squeue -j <JOB_ID>
scontrol show job <JOB_ID>
tail -f /soge-home/users/lina4376/dphil_p2/p2_test/output_global/slurm_country_exposure_<JOB_ID>.out
sacct -j <JOB_ID> --format=JobID,State,Elapsed,MaxRSS,ExitCode
```

### Main outputs
- Country parquet outputs: /soge-home/users/lina4376/dphil_p2/p2_test/output_per_country/parquet_exposure
- Global GPKG: /soge-home/users/lina4376/dphil_p2/p2_test/output_global/polylines_global_exposure.gpkg
- Excel summary: /soge-home/users/lina4376/dphil_p2/p2_test/output_global/polylines_global_exposure_summary.xlsx

## 2) Cyclone ISIMIP Download (no crop)

Script: /soge-home/users/lina4376/dphil_p2/p2_test/p2_a_download_cyclone_isimip.py

Current behavior:
- Downloads only (no crop, no combine)
- Years: 1995-2024
- Datasets: tidesmean, tidesmax, tidesmin
- Total files: 90
- Coverage: global extent (no clipping)

Output root:
- /soge-home/projects/mistral/ji/bigdata_cyclonetide_isimip

### Create/update environment
```bash
source /soge-home/users/lina4376/miniconda3/etc/profile.d/conda.sh
conda env create -f /soge-home/users/lina4376/dphil_p2/p2_test/environment_p2_etl.yml || \
conda env update -f /soge-home/users/lina4376/dphil_p2/p2_test/environment_p2_etl.yml --prune
```

### Run directly
```bash
cd /soge-home/users/lina4376/dphil_p2/p2_test
python /soge-home/users/lina4376/dphil_p2/p2_test/p2_a_download_cyclone_isimip.py
```

### Run on Slurm
```bash
sbatch /soge-home/users/lina4376/dphil_p2/p2_test/p2_b_process_download_cyclone_isimip.sh
```

### If DOS line endings appear
```bash
sed -i 's/\r$//' /soge-home/users/lina4376/dphil_p2/p2_test/p2_b_process_download_cyclone_isimip.sh
```

### Monitor
```bash
squeue -j <JOB_ID>
scontrol show job <JOB_ID>
tail -f /soge-home/users/lina4376/dphil_p2/p2_test/logs/slurm_cyclone_isimip_<JOB_ID>.out
sacct -j <JOB_ID> --format=JobID,State,Elapsed,MaxRSS,ExitCode
```

### Outputs
- Raw NetCDF: /soge-home/projects/mistral/ji/bigdata_cyclonetide_isimip/raw_nc
- Manifest: /soge-home/projects/mistral/ji/bigdata_cyclonetide_isimip/download_manifest.json

## 3) JRC Flood Download (no crop)

Script: /soge-home/users/lina4376/dphil_p2/p2_test/p2_c_download_flood_jrc.py

Current behavior:
- Downloads only (no clip/crop)
- Return periods: RP10, RP100, RP500
- Coverage: all available source tiles
- Optional mosaics if GDAL tools are available:
  - VRT via gdalbuildvrt
  - Global GeoTIFF via gdal_translate

Output root:
- /soge-home/projects/mistral/ji/bigdata_riverflood_jrc

### Run directly
```bash
cd /soge-home/users/lina4376/dphil_p2/p2_test
python /soge-home/users/lina4376/dphil_p2/p2_test/p2_c_download_flood_jrc.py
```

### Run on Slurm
```bash
sbatch /soge-home/users/lina4376/dphil_p2/p2_test/p2_d_process_download_flood_jrc.sh
```

### If DOS line endings appear
```bash
sed -i 's/\r$//' /soge-home/users/lina4376/dphil_p2/p2_test/p2_d_process_download_flood_jrc.sh
```

### Monitor
```bash
squeue -j <JOB_ID>
scontrol show job <JOB_ID>
tail -f /soge-home/users/lina4376/dphil_p2/p2_test/logs/slurm_flood_jrc_download_<JOB_ID>.out
sacct -j <JOB_ID> --format=JobID,State,Elapsed,MaxRSS,ExitCode
```

### Outputs
- Raw TIFF tiles: /soge-home/projects/mistral/ji/bigdata_riverflood_jrc/raw/<RP>
- VRT mosaic: /soge-home/projects/mistral/ji/bigdata_riverflood_jrc/vrt/<RP>_depth.vrt
- Global GeoTIFF map: /soge-home/projects/mistral/ji/bigdata_riverflood_jrc/global_maps/<RP>_depth_global.tif
- Manifest: /soge-home/projects/mistral/ji/bigdata_riverflood_jrc/manifests/download_manifest.json

## 4) Common queue commands

```bash
squeue -u lina4376
scancel <JOB_ID>
```
