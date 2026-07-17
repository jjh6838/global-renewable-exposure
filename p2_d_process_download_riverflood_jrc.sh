#!/bin/bash --login
#SBATCH --job-name=flood_jrc_download
#SBATCH --output=/soge-home/users/lina4376/dphil_p2/p2_test/logs/slurm_flood_jrc_download_%j.out
#SBATCH --error=/soge-home/users/lina4376/dphil_p2/p2_test/logs/slurm_flood_jrc_download_%j.err
#SBATCH --partition=Long
#SBATCH --time=168:00:00
#SBATCH --ntasks=1
#SBATCH --nodes=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --export=NONE
#SBATCH --chdir=/soge-home/users/lina4376/dphil_p2/p2_test
#SBATCH --mail-type=END,FAIL

set -euo pipefail

eval "$(micromamba shell hook --shell bash)"
micromamba activate p2_etl

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

python -u /soge-home/users/lina4376/dphil_p2/p2_test/p2_c_download_riverflood_jrc.py
