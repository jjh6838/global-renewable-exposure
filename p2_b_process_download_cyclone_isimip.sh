#!/bin/bash --login
#SBATCH --job-name=cyclone_isimip_download
#SBATCH --output=/soge-home/users/lina4376/dphil_p2/p2_test/logs/slurm_cyclone_isimip_%j.out
#SBATCH --error=/soge-home/users/lina4376/dphil_p2/p2_test/logs/slurm_cyclone_isimip_%j.err
#SBATCH --partition=Long
#SBATCH --time=168:00:00
#SBATCH --ntasks=1
#SBATCH --nodes=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=128G
#SBATCH --export=NONE
#SBATCH --chdir=/soge-home/users/lina4376/dphil_p2/p2_test
#SBATCH --mail-type=END,FAIL

set -euo pipefail

source /soge-home/users/lina4376/miniconda3/etc/profile.d/conda.sh
conda activate p2_etl

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

python -u /soge-home/users/lina4376/dphil_p2/p2_test/p2_a_download_cyclone_isimip.py
