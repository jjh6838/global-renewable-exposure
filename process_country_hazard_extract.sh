#!/bin/bash --login
#SBATCH --job-name=country_hazard_extract
#SBATCH --partition=Short
#SBATCH --time=12:00:00
#SBATCH --ntasks=1
#SBATCH --nodes=1
#SBATCH --output=/soge-home/users/lina4376/dphil_p2/p2_test/output_global/slurm_country_hazard_extract_%j.out
#SBATCH --error=/soge-home/users/lina4376/dphil_p2/p2_test/output_global/slurm_country_hazard_extract_%j.err
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --export=NONE
#SBATCH --chdir=/soge-home/users/lina4376/dphil_p2/p2_test
#SBATCH --mail-type=END,FAIL

set -euo pipefail

source /soge-home/users/lina4376/miniconda3/etc/profile.d/conda.sh
conda activate p1_etl

python /soge-home/users/lina4376/dphil_p2/p2_test/p2_testing_extract_flood_tif.py \
  --countries ABW AFG AGO ALB ARE ARG ARM ASM ATG
