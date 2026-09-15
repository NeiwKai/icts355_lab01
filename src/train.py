"""Training entry point.

Run locally:      python -m src.train --n-estimators 200 --max-depth 8
Run in Docker:    make reproduce

Every run logs: all hyperparameters, the seed, validation AND test metrics separately,
the data fingerprint, and the Git commit. A metric that cannot be traced to code and
data is not evidence of anything.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import mlflow
import mlflow.sklearn
from google.cloud import storage
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import average_precision_score, roc_auc_score

from src import config, data, seeds


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, cwd=config.REPO_ROOT,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def ensure_raw_data(cfg) -> None:
    """Download raw dataset from GCS if missing locally inside container."""
    local_path = Path(cfg.raw_path)
    if local_path.exists():
        print(f"Using existing local raw data at {local_path}")
        return

    print(f"Dataset missing at {local_path}. Fetching from GCS...")
    local_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Fallback / Sanity Check on BLOB_URI
    raw_uri = getattr(cfg, "blob_uri", "") or "gs://itcs355-6688132"
    if not raw_uri.startswith("gs://"):
        raw_uri = f"gs://{raw_uri.lstrip('/')}"

    # 2. Extract bucket name and prefix robustly
    clean_parts = raw_uri.replace("gs://", "").strip("/").split("/", 1)
    bucket_name = clean_parts[0]
    sub_path = clean_parts[1] if len(clean_parts) > 1 else ""

    if not bucket_name:
        raise ValueError(f"Invalid GCS bucket extracted from URI: '{raw_uri}'")

    # 3. Construct blob path
    blob_path = f"{sub_path}/data/raw/sensors.csv".lstrip("/") if sub_path else "data/raw/sensors.csv"

    print(f"Connecting to GCS Bucket: '{bucket_name}', target blob: '{blob_path}'")
    client = storage.Client(project=cfg.project_id)
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)

    # Fallback to root path if blob doesn't exist under sub_path
    if not blob.exists():
        blob = bucket.blob("data/raw/sensors.csv")

    blob.download_to_filename(str(local_path))
    print(f"Successfully downloaded raw dataset to {local_path}")

def upload_gcs_file(local_path: str, gcs_uri: str) -> None:
    """Upload a local file to a GCS destination URI (gs://bucket/path/file.json)."""
    if not gcs_uri.startswith("gs://"):
        return
    path_parts = gcs_uri.replace("gs://", "").split("/", 1)
    bucket_name = path_parts[0]
    blob_path = path_parts[1] if len(path_parts) > 1 else Path(local_path).name

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    bucket.blob(blob_path).upload_from_filename(local_path)
    print(f"Uploaded {local_path} to {gcs_uri}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ITCS355 Lab 1 — reproducible training")
    p.add_argument("--n-estimators", type=int, default=200)
    p.add_argument("--max-depth", type=int, default=8)
    p.add_argument("--min-samples-leaf", type=int, default=5)
    p.add_argument("--seed", type=int, default=seeds.DEFAULT_SEED)
    p.add_argument("--experiment", default="itcs355-lab1")
    p.add_argument("--run-name", default=None)
    p.add_argument("--metrics-out", type=Path, default=None,
                   help="Write final metrics as JSON. Used by `make verify`.")
    p.add_argument("--output-gcs-path", type=str, default=None,
                   help="Remote GCS destination for final metrics.json")
    p.add_argument("--checkpoint-dir", type=str, default=None,
                   help="GCS path for Spot VM resumable checkpoints")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cfg = config.load(strict=False)

    # 1. Download raw data from GCS if container disk is empty
    ensure_raw_data(cfg)

    seed = seeds.set_all(args.seed)

    df = data.load_data(cfg)
    fingerprint = data.data_fingerprint(cfg.raw_path)
    train_df, val_df, test_df = data.split(df, seed=seed)

    mlflow.set_tracking_uri(cfg.mlflow_tracking_uri)
    mlflow.set_experiment(args.experiment)

    # FIX: Added 'as run' here so run.info.run_id can be accessed below
    with mlflow.start_run(run_name=args.run_name) as run:
        mlflow.log_params({
            "n_estimators": args.n_estimators,
            "max_depth": args.max_depth,
            "min_samples_leaf": args.min_samples_leaf,
            "seed": seed,
            "n_features": len(data.FEATURES),
        })
        # Provenance. This is what makes the metric traceable.
        mlflow.set_tags({
            "git_commit": git_commit(),
            "data_fingerprint": fingerprint,
            "split_strategy": "group_by_machine_id",
            "n_train_rows": len(train_df),
            "n_val_rows": len(val_df),
            "n_test_rows": len(test_df),
        })

        model = RandomForestClassifier(
            n_estimators=args.n_estimators,
            max_depth=args.max_depth,
            min_samples_leaf=args.min_samples_leaf,
            random_state=seed,
            n_jobs=-1,
        )
        model.fit(train_df[data.FEATURES], train_df[data.TARGET])

        metrics: dict[str, float] = {}
        for name, part in (("val", val_df), ("test", test_df)):
            proba = model.predict_proba(part[data.FEATURES])[:, 1]
            metrics[f"{name}_roc_auc"] = float(roc_auc_score(part[data.TARGET], proba))
            metrics[f"{name}_pr_auc"] = float(average_precision_score(part[data.TARGET], proba))
        mlflow.log_metrics(metrics)
        mlflow.sklearn.log_model(model, name="model")

        output_payload = {
            "seed": seed,
            "data_fingerprint": fingerprint,
            "mlflow_run_id": run.info.run_id,
            **metrics,
        }

        print(json.dumps(output_payload, indent=2))

        # Save local metrics output if requested
        if args.metrics_out:
            try:
                args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
                args.metrics_out.write_text(json.dumps(output_payload, indent=2))
            except PermissionError:
                # Fallback to container-writable /tmp directory
                fallback_path = Path("/tmp") / args.metrics_out.name
                fallback_path.write_text(json.dumps(output_payload, indent=2))
                print(f"Warning: Could not write to {args.metrics_out}, saved to {fallback_path} instead.")

        # Upload metrics.json directly to GCS for orchestrator tracking
        if args.output_gcs_path:
            local_tmp = "/tmp/metrics.json"
            Path(local_tmp).write_text(json.dumps(output_payload, indent=2))
            upload_gcs_file(local_tmp, args.output_gcs_path)


if __name__ == "__main__":
    main()
