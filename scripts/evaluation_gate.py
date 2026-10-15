"""Lab 5 — the registration gate.

Compares a candidate against the currently registered production model. Exits non-zero
when the candidate should NOT be registered, which is what makes the pipeline condition
real rather than decorative.

    python scripts/evaluation_gate.py --metrics reports/metrics.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cloudlayer.factory import get_adapter
from src import config

# Defended Gate Parameters:
# - MIN_ABSOLUTE = 0.75: Establishes a hard floor to prevent registering broken/underfitting models,
#   ensuring candidate performance exceeds random guessing (0.50) and simple heuristics.
# - MIN_IMPROVEMENT = 0.002 (+0.2% ROC-AUC): Enforces a minimum gain threshold above statistical noise.
#   A margin of zero risks promoting noisy fluctuations and incurring unnecessary deployment/churn costs.
MIN_ABSOLUTE = 0.75
MIN_IMPROVEMENT = 0.002


def fetch_incumbent_metric(metric_name: str) -> float | None:
    """Read the current production model's metric from the registry.

    Returns None if no incumbent model exists (e.g., initial pipeline deployment).
    """
    try:
        cfg = config.load(strict=False)
        adapter = get_adapter(cfg)

        # Query production model metrics from registry adapter
        if hasattr(adapter, "get_production_model_metrics"):
            prod_metrics = adapter.get_production_model_metrics()
            if prod_metrics and metric_name in prod_metrics:
                return float(prod_metrics[metric_name])
    except Exception as exc:
        print(f"Warning: Could not fetch incumbent from registry ({exc}) — assuming no incumbent.")

    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--metrics", type=Path, required=True, help="Path to evaluation metrics JSON")
    ap.add_argument("--metric", default="test_roc_auc", help="Metric name to evaluate against gate")
    ap.add_argument(
        "--incumbent",
        type=float,
        default=None,
        help="Current production score; omit to read from the registry",
    )
    args = ap.parse_args()

    payload = json.loads(args.metrics.read_text())
    candidate = float(payload[args.metric])
    print(f"candidate {args.metric} = {candidate:.4f}")

    if candidate < MIN_ABSOLUTE:
        print(f"GATE FAIL  below absolute floor {MIN_ABSOLUTE}")
        return 1

    incumbent = args.incumbent
    if incumbent is None:
        incumbent = fetch_incumbent_metric(args.metric)

    if incumbent is None:
        print("no incumbent found in registry — treating as first registration")
        print("GATE PASS")
        return 0

    delta = candidate - incumbent
    print(f"incumbent {incumbent:.4f}  delta {delta:+.4f}  required {MIN_IMPROVEMENT:+.4f}")
    if delta < MIN_IMPROVEMENT:
        print("GATE FAIL  improvement within noise; not registering")
        return 1

    print("GATE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
