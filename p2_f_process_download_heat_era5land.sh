#!/bin/bash --login
#SBATCH --job-name=heat_era5land_download
#SBATCH --output=/soge-home/users/lina4376/dphil_p2/p2_test/logs/slurm_heat_era5land_download_%j.out
#SBATCH --error=/soge-home/users/lina4376/dphil_p2/p2_test/logs/slurm_heat_era5land_download_%j.err
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

YEAR_ARG="${1:-}"
MONTH_ARG="${2:-}"

if [[ -n "${SLURM_ARRAY_TASK_ID:-}" && -z "$MONTH_ARG" ]]; then
	MONTH_ARG="$SLURM_ARRAY_TASK_ID"
fi

if [[ -z "$YEAR_ARG" ]]; then
	if [[ -t 0 ]]; then
		read -r -p "Enter year (YYYY): " YEAR_ARG
	else
		echo "Usage:" >&2
		echo "  sbatch p2_f_process_download_heat_era5land.sh <YEAR> [MONTH]" >&2
		echo "  sbatch --array=1-12%5 p2_f_process_download_heat_era5land.sh <YEAR>" >&2
		echo "Examples:" >&2
		echo "  sbatch p2_f_process_download_heat_era5land.sh 2024 07" >&2
		echo "  sbatch p2_f_process_download_heat_era5land.sh 2024" >&2
		echo "  sbatch --array=1-12%5 p2_f_process_download_heat_era5land.sh 2024" >&2
		exit 2
	fi
fi

if [[ ! "$YEAR_ARG" =~ ^[0-9]{4}$ ]]; then
	echo "Invalid year: $YEAR_ARG (expected YYYY)" >&2
	exit 2
fi

if [[ -n "$MONTH_ARG" ]]; then
	if [[ ! "$MONTH_ARG" =~ ^[0-9]{1,2}$ ]]; then
		echo "Invalid month: $MONTH_ARG (expected 1-12 or MM)" >&2
		exit 2
	fi

	if ((10#$MONTH_ARG < 1 || 10#$MONTH_ARG > 12)); then
		echo "Invalid month: $MONTH_ARG (expected 1-12)" >&2
		exit 2
	fi

	MONTH_ARG=$(printf "%02d" "$((10#$MONTH_ARG))")
fi

eval "$(micromamba shell hook --shell bash)"
micromamba activate p2_etl

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

PY_ARGS=(--year "$YEAR_ARG")
if [[ -n "$MONTH_ARG" ]]; then
	PY_ARGS+=(--month "$MONTH_ARG")
fi

python -u /soge-home/users/lina4376/dphil_p2/p2_test/p2_e_download_heat_era5land.py "${PY_ARGS[@]}"
