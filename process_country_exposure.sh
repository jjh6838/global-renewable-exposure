#!/bin/bash --login
#SBATCH --job-name=country_exposure
#SBATCH --output=/soge-home/users/lina4376/dphil_p2/p2_test/output_global/slurm_country_exposure_%j.out
#SBATCH --error=/soge-home/users/lina4376/dphil_p2/p2_test/output_global/slurm_country_exposure_%j.err
#SBATCH --partition=Long
#SBATCH --time=168:00:00
#SBATCH --ntasks=1
#SBATCH --nodes=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --export=NONE
#SBATCH --chdir=/soge-home/users/lina4376/dphil_p2/p2_test
#SBATCH --mail-type=END,FAIL

set -euo pipefail

# Adjust these to your cluster environment
# module load python/3.10
source /soge-home/users/lina4376/miniconda3/etc/profile.d/conda.sh
conda activate p1_etl

python /soge-home/users/lina4376/dphil_p2/p2_test/p2_a_hazard_data.py
