#!/bin/bash --login
#SBATCH --job-name=iris_vmax_to_tif
#SBATCH --output=/soge-home/users/lina4376/dphil_p2/p2_test/logs/slurm_iris_vmax_to_tif_%j.out
#SBATCH --error=/soge-home/users/lina4376/dphil_p2/p2_test/logs/slurm_iris_vmax_to_tif_%j.err
#SBATCH --partition=Long
#SBATCH --time=24:00:00
#SBATCH --ntasks=1
#SBATCH --nodes=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --export=NONE
#SBATCH --chdir=/soge-home/users/lina4376/dphil_p2/p2_test

set -euo pipefail

eval "$(micromamba shell hook --shell bash)"
micromamba activate p2_etl

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

INPUT_NC=/soge-home/projects/mistral/ji/bigdata_cyclone_iris/return_value_maps/IRIS_vmax_maps_PRESENT_tenthdeg.nc
OUTPUT_DIR=/soge-home/projects/mistral/ji/bigdata_cyclone_iris/global_maps
RETURN_PERIODS=${RETURN_PERIODS:-"10 100 500"}

python -u /soge-home/users/lina4376/dphil_p2/p2_test/p2_g_extract_cyclone_iris_nc_to_tif.py \
  "$INPUT_NC" \
  "$OUTPUT_DIR" \
  --return-periods ${RETURN_PERIODS} \
  --lat-chunk 120