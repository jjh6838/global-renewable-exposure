#!/bin/bash --login
#SBATCH --job-name=analyze_centroids_exposure
#SBATCH --output=/soge-home/users/lina4376/dphil_p2/p2_test/logs/slurm_analyze_centroids_exposure_%j.out
#SBATCH --error=/soge-home/users/lina4376/dphil_p2/p2_test/logs/slurm_analyze_centroids_exposure_%j.err
#SBATCH --partition=Long
#SBATCH --time=24:00:00
#SBATCH --ntasks=1
#SBATCH --nodes=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --export=NONE
#SBATCH --chdir=/soge-home/users/lina4376/dphil_p2/p2_test
#SBATCH --mail-type=END,FAIL

set -euo pipefail

MICROMAMBA_BIN="$(command -v micromamba || true)"
if [[ -z "$MICROMAMBA_BIN" && -x "$HOME/.local/bin/micromamba" ]]; then
	MICROMAMBA_BIN="$HOME/.local/bin/micromamba"
fi

if [[ -z "$MICROMAMBA_BIN" ]]; then
	echo "micromamba not found in PATH and not at $HOME/.local/bin/micromamba" >&2
	exit 127
fi

eval "$($MICROMAMBA_BIN shell hook --shell bash)"
micromamba activate p2_etl

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

SCRIPT_DIR=/soge-home/users/lina4376/dphil_p2/p2_test
PY_SCRIPT=${SCRIPT_DIR}/p2_k_analyze_centroids_exposure.py
FINAL_OUTPUT_DIR=${SCRIPT_DIR}/output_per_country/parquet_centroids_exposure
GLOBAL_OUTPUT=${SCRIPT_DIR}/output_global/centroids_global_exposure.gpkg
CENTROIDS_DIR=/soge-home/projects/mistral/ji/bigdata_global_renewable_dataset_p1/2050_supply_100%_add_v2
RPS=(10 100 500)
HEAT_DIR=/soge-home/projects/mistral/ji/bigdata_heat_era5land/global_maps/climatology
HEAT_THRESHOLDS_C=(30 35 40)
HEAT_THRESHOLD_DAYS=30

mkdir -p "$FINAL_OUTPUT_DIR"

TIER1=(CHN USA IND BRA DEU FRA RUS)
TIER2=(CAN MEX AUS ARG KAZ SAU IDN IRN ZAF EGY)

ISO3_ARG=""
TIER_ARG=""
COUNTRY_LIST_FILE=""
SUBMIT_TIERED=0
WRITE_GLOBAL=""
BUILD_GLOBAL_FROM_PER_COUNTRY=0

usage() {
	cat <<'USAGE'
Usage:
	Default (no --iso3): submit tiered Slurm arrays:
	bash p2_l_process_analyze_centroids_exposure.sh

	Global-only build from existing per-country outputs:
	bash p2_l_process_analyze_centroids_exposure.sh --write-global

	Explicit tiered submit:
	bash p2_l_process_analyze_centroids_exposure.sh --submit-tiered

  Worker mode (used by Slurm arrays):
	sbatch --array=0-(N-1) p2_l_process_analyze_centroids_exposure.sh --tier <1|2|3> --country-list-file <file>

  One-country test:
	bash p2_l_process_analyze_centroids_exposure.sh --iso3 ABW

Options:
  --submit-tiered           Build tier lists and submit 3 Slurm arrays (tier 1/2/3)
  --tier <1|2|3>            Tier label (for worker metadata/logging)
  --country-list-file PATH  One ISO3 per line, used with SLURM_ARRAY_TASK_ID
  --iso3 ISO3               Run a single country immediately
	--heat-dir PATH           Override heat climatology raster directory
	--heat-thresholds-c ...   Override heat raster thresholds (default: 30 35 40)
	--heat-threshold-days N   Override exposure cutoff in climatological days/year
	--write-global            Build global GPKG from existing per-country outputs only
										(optional; default is OFF)
	--no-write-global         Disable global output (same as default)
	--build-global-from-per-country  Internal mode to combine per-country parquet outputs
  -h, --help                Show this help message
USAGE
}

while [[ $# -gt 0 ]]; do
	case "$1" in
		--submit-tiered)
			SUBMIT_TIERED=1
			shift
			;;
		--tier)
			if [[ $# -lt 2 ]]; then
				echo "Missing value for --tier" >&2
				exit 2
			fi
			TIER_ARG="$2"
			shift 2
			;;
		--country-list-file)
			if [[ $# -lt 2 ]]; then
				echo "Missing value for --country-list-file" >&2
				exit 2
			fi
			COUNTRY_LIST_FILE="$2"
			shift 2
			;;
		--iso3)
			if [[ $# -lt 2 ]]; then
				echo "Missing value for --iso3" >&2
				exit 2
			fi
			ISO3_ARG="${2^^}"
			shift 2
			;;
		--heat-dir)
			if [[ $# -lt 2 ]]; then
				echo "Missing value for --heat-dir" >&2
				exit 2
			fi
			HEAT_DIR="$2"
			shift 2
			;;
		--heat-thresholds-c)
			shift
			HEAT_THRESHOLDS_C=()
			while [[ $# -gt 0 ]] && [[ ! "$1" =~ ^-- ]]; do
				HEAT_THRESHOLDS_C+=("$1")
				shift
			done
			if [[ ${#HEAT_THRESHOLDS_C[@]} -eq 0 ]]; then
				echo "Missing value(s) for --heat-thresholds-c" >&2
				exit 2
			fi
			;;
		--heat-threshold-days)
			if [[ $# -lt 2 ]]; then
				echo "Missing value for --heat-threshold-days" >&2
				exit 2
			fi
			HEAT_THRESHOLD_DAYS="$2"
			shift 2
			;;
		--write-global)
			WRITE_GLOBAL=1
			shift
			;;
		--no-write-global)
			WRITE_GLOBAL=0
			shift
			;;
		--build-global-from-per-country)
			BUILD_GLOBAL_FROM_PER_COUNTRY=1
			shift
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			echo "Unknown argument: $1" >&2
			usage >&2
			exit 2
			;;
	esac
done

if [[ -n "$TIER_ARG" ]] && [[ ! "$TIER_ARG" =~ ^[123]$ ]]; then
	echo "Invalid --tier value: $TIER_ARG (expected 1, 2, or 3)" >&2
	exit 2
fi

if (( WRITE_GLOBAL == 1 )) && [[ -n "$ISO3_ARG" ]]; then
	echo "--write-global cannot be combined with --iso3." >&2
	exit 2
fi

# If no mode is selected and not running as an array task, default to tiered submit.
if (( SUBMIT_TIERED == 0 )) && [[ -z "$ISO3_ARG" ]] && [[ -z "${SLURM_ARRAY_TASK_ID:-}" ]] && (( BUILD_GLOBAL_FROM_PER_COUNTRY == 0 )); then
	SUBMIT_TIERED=1
fi

# Default: do not write global unless explicitly requested.
if [[ -z "$WRITE_GLOBAL" ]]; then
	WRITE_GLOBAL=0
fi

if [[ ! -d "$CENTROIDS_DIR" ]]; then
	echo "Centroids directory not found: $CENTROIDS_DIR" >&2
	exit 1
fi

collect_all_iso3s() {
	find "$CENTROIDS_DIR" -maxdepth 1 -type f -name 'centroids_*_add_v2.parquet' \
		-printf '%f\n' \
		| sed -E 's/^centroids_([A-Za-z0-9]{3})_add_v2\.parquet$/\1/' \
		| tr '[:lower:]' '[:upper:]' \
		| sort -u
}

run_one_country() {
	local iso3="$1"
	local allow_global="${2:-1}"
	local cmd=(python -u "$PY_SCRIPT" --iso3 "$iso3" --rps "${RPS[@]}" --heat-dir "$HEAT_DIR" --heat-thresholds-c "${HEAT_THRESHOLDS_C[@]}" --heat-threshold-days "$HEAT_THRESHOLD_DAYS" --output-dir "$FINAL_OUTPUT_DIR")
	if (( allow_global == 1 )) && (( WRITE_GLOBAL == 1 )); then
		cmd+=(--write-global)
	else
		cmd+=(--no-write-global)
	fi
	echo "Running ISO3=${iso3}, tier=${TIER_ARG:-manual}: ${cmd[*]}"
	"${cmd[@]}"
}

build_global_from_per_country() {
	export FINAL_OUTPUT_DIR
	export GLOBAL_OUTPUT
	python - <<'PY'
import os
from pathlib import Path

import geopandas as gpd
import pandas as pd

input_dir = Path(os.environ["FINAL_OUTPUT_DIR"])
global_output = Path(os.environ["GLOBAL_OUTPUT"])

files = sorted(input_dir.glob("centroids_*_exposure.parquet"))
if not files:
    raise SystemExit(f"No per-country centroid exposure files found in {input_dir}")

parts = [gpd.read_parquet(f) for f in files]
combined = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), geometry="geometry", crs=parts[0].crs)

global_output.parent.mkdir(parents=True, exist_ok=True)
combined.to_file(global_output, layer="centroids_global_exposure", driver="GPKG", mode="w")
print(f"Wrote global GeoPackage: {global_output} (rows={len(combined)})", flush=True)
PY
}

if (( BUILD_GLOBAL_FROM_PER_COUNTRY == 1 )); then
	build_global_from_per_country
	exit 0
fi

# Global build mode: do not rerun per-country jobs.
if (( WRITE_GLOBAL == 1 )) && [[ -z "$ISO3_ARG" ]] && [[ -z "${SLURM_ARRAY_TASK_ID:-}" ]]; then
	build_global_from_per_country
	exit 0
fi

if (( SUBMIT_TIERED == 1 )); then
	RUN_TAG="tier_submit_${USER}_$(date +%Y%m%d_%H%M%S)"
	LIST_DIR="${SCRIPT_DIR}/output_global/slurm_country_lists_centroids/${RUN_TAG}"
	mkdir -p "$LIST_DIR"

	TIER1_FILE="${LIST_DIR}/tier1.txt"
	TIER2_FILE="${LIST_DIR}/tier2.txt"
	TIER3_FILE="${LIST_DIR}/tier3.txt"

	printf '%s\n' "${TIER1[@]}" | sort -u > "$TIER1_FILE"
	printf '%s\n' "${TIER2[@]}" | sort -u > "$TIER2_FILE"

	mapfile -t ALL_ISO3 < <(collect_all_iso3s)
	if [[ "${#ALL_ISO3[@]}" -eq 0 ]]; then
		echo "No country centroid files found under $CENTROIDS_DIR" >&2
		exit 1
	fi

	cat "$TIER1_FILE" "$TIER2_FILE" | sort -u > "${LIST_DIR}/tier12_union.txt"
	printf '%s\n' "${ALL_ISO3[@]}" | sort -u | grep -vxFf "${LIST_DIR}/tier12_union.txt" > "$TIER3_FILE"

	n1=$(wc -l < "$TIER1_FILE")
	n2=$(wc -l < "$TIER2_FILE")
	n3=$(wc -l < "$TIER3_FILE")

	echo "Tier lists written to: $LIST_DIR"
	echo "Tier 1 countries: $n1"
	echo "Tier 2 countries: $n2"
	echo "Tier 3 countries: $n3"

	SCRIPT_PATH="${SCRIPT_DIR}/p2_l_process_analyze_centroids_exposure.sh"

	submit_array() {
		local tier="$1"
		local list_file="$2"
		local count="$3"
		local limit="$4"
		local cpus="$5"
		local mem="$6"
		local time="$7"
		local partition="$8"

		if (( count == 0 )); then
			echo "Skipping tier ${tier}: no countries"
			return
		fi

		local array_spec
		array_spec="0-$((count - 1))%${limit}"

		local cmd=(
			sbatch
			--job-name "analyze_cent_t${tier}"
			--array "$array_spec"
			--partition "$partition"
			--cpus-per-task "$cpus"
			--mem "$mem"
			--time "$time"
			"$SCRIPT_PATH"
			--tier "$tier"
			--country-list-file "$list_file"
		)

		echo "Submit: ${cmd[*]}"
		"${cmd[@]}"
	}

	submit_array 1 "$TIER1_FILE" "$n1" 7 40 95G 168:00:00 Long
	submit_array 2 "$TIER2_FILE" "$n2" 6 40 95G 48:00:00 Medium
	submit_array 3 "$TIER3_FILE" "$n3" 24 40 25G 12:00:00 Short

	exit 0
fi

if [[ -n "$ISO3_ARG" ]]; then
	run_one_country "$ISO3_ARG"
	echo "Done. Final outputs in: ${FINAL_OUTPUT_DIR}"
	exit 0
fi

if [[ -n "${SLURM_ARRAY_TASK_ID:-}" ]]; then
	if [[ -z "$COUNTRY_LIST_FILE" ]]; then
		echo "SLURM_ARRAY_TASK_ID is set but --country-list-file was not provided." >&2
		exit 2
	fi
	if [[ ! -f "$COUNTRY_LIST_FILE" ]]; then
		echo "Country list file not found: $COUNTRY_LIST_FILE" >&2
		exit 1
	fi

	line_num=$((SLURM_ARRAY_TASK_ID + 1))
	iso3=$(sed -n "${line_num}p" "$COUNTRY_LIST_FILE" | tr '[:lower:]' '[:upper:]' | tr -d '[:space:]')

	if [[ -z "$iso3" ]]; then
		echo "No ISO3 found for SLURM_ARRAY_TASK_ID=${SLURM_ARRAY_TASK_ID} in $COUNTRY_LIST_FILE" >&2
		exit 1
	fi

	run_one_country "$iso3" 0
	echo "Done. Final outputs in: ${FINAL_OUTPUT_DIR}"
	exit 0
fi

echo "No action selected. Use --submit-tiered, --iso3 ISO3, or Slurm array mode." >&2
usage >&2
exit 2
