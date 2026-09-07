#!/bin/bash
set -euo pipefail

LOG_FILE="reports/task5_runs.txt"

mkdir -p reports

# Start a fresh log
{
    echo "ITCS355 Lab 1 - Task 5 MLflow Runs"
    echo "=================================="
    echo "Date: $(date)"
    echo
} > "$LOG_FILE"


run_experiment() {
    local name="$1"
    local n_estimators="$2"
    local max_depth="$3"
    local min_samples_leaf="$4"
    local seed="$5"

    {
        echo "=================================="
        echo "RUN: $name"
        echo "=================================="
        echo "Hyperparameters:"
        echo "  n_estimators     = $n_estimators"
        echo "  max_depth        = $max_depth"
        echo "  min_samples_leaf = $min_samples_leaf"
        echo "  seed             = $seed"
        echo
        echo "MLflow output:"
    } | tee -a "$LOG_FILE"

    python -m src.train \
        --n-estimators "$n_estimators" \
        --max-depth "$max_depth" \
        --min-samples-leaf "$min_samples_leaf" \
        --seed "$seed" \
        --run-name "$name" \
        2>&1 | tee -a "$LOG_FILE"

    echo >> "$LOG_FILE"
}


# --------------------------------------------------
# Run 1
# --------------------------------------------------
run_experiment \
    "rf-100-depth4" \
    100 \
    4 \
    5 \
    42


# --------------------------------------------------
# Run 2
# --------------------------------------------------
run_experiment \
    "rf-200-depth4" \
    200 \
    4 \
    5 \
    42


# --------------------------------------------------
# Run 3
# --------------------------------------------------
run_experiment \
    "rf-300-depth4" \
    300 \
    4 \
    5 \
    42


# --------------------------------------------------
# Run 4
# --------------------------------------------------
run_experiment \
    "rf-200-depth8" \
    200 \
    8 \
    5 \
    42


# --------------------------------------------------
# Run 5
# --------------------------------------------------
run_experiment \
    "rf-200-depth12" \
    200 \
    12 \
    5 \
    42


{
    echo "=================================="
    echo "All 5 runs completed."
    echo "Log saved to: $LOG_FILE"
    echo "=================================="
} | tee -a "$LOG_FILE"

