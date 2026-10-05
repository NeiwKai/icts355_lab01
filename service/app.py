"""Lab 3 & 4 — inference service with Prometheus monitoring instrumentation."""
from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Union

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from service.schemas import (
    BatchRequest,
    BatchResponse,
    PredictRequest,
    VertexPredictRequest,
)

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":%(message)s}',
)
log = logging.getLogger("service")

STATE: dict[str, Any] = {"model": None, "version": os.environ.get("MODEL_VERSION", "unknown")}

# -----------------------------------------------------------------------------
# Prometheus Metrics Configuration (Matches monitoring/dashboard.json)
# -----------------------------------------------------------------------------
HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total count of HTTP requests served",
    ["method", "path", "status_code", "status_class"],
)

REQUEST_LATENCY_MS = Histogram(
    "request_latency_ms",
    "Execution latency of HTTP requests in milliseconds",
    ["path"],
    buckets=[5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000],
)

MODEL_VERSION_INFO = Gauge(
    "model_version_info",
    "Currently deployed model version info",
    ["model_version"],
)

FEATURE_TEMP_C_MEAN = Gauge(
    "feature_temp_c_rolling_mean",
    "Rolling temperature input feature mean",
)


def _load_model():
    """Load once at startup via Cloud Layer abstraction."""
    from pathlib import Path
    import joblib

    raw_path = os.environ.get("MODEL_PATH", "/tmp/reports/model.joblib")
    log.info("Configured MODEL_PATH: '%s'", raw_path)

    local_path = Path(raw_path)

    # 1. Direct local file loading
    if local_path.exists():
        log.info("Loading local model file from '%s'...", local_path)
        return joblib.load(local_path)

    # 2. Delegate remote GCS downloads to cloudlayer adapter
    try:
        from src import config
        from cloudlayer.factory import get_adapter

        cfg = config.load()
        adapter = get_adapter(cfg)
        local_path = adapter.download_artifact(raw_path, "/tmp/reports/model.joblib")
    except Exception as err:
        log.error("Failed to load model via cloudlayer adapter: %s", err)
        raise RuntimeError(f"Model initialization failed: {err}") from err

    log.info("Unpickling model from '%s'...", local_path)
    return joblib.load(local_path)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        STATE["model"] = _load_model()
        log.info('"model loaded, version=%s"', STATE["version"])
        MODEL_VERSION_INFO.labels(model_version=str(STATE["version"])).set(1)
    except Exception as exc:  # readiness stays false; liveness still passes
        STATE["model"] = None
        log.error('"model load failed: %s"', exc)
    yield
    STATE["model"] = None


app = FastAPI(title="ITCS355 inference", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def add_request_context_and_metrics(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    started = time.perf_counter()

    response = await call_next(request)

    latency_ms = (time.perf_counter() - started) * 1000
    status_code = response.status_code
    status_class = f"{status_code // 100}xx"
    path = request.url.path

    # Update Prometheus metrics
    HTTP_REQUESTS_TOTAL.labels(
        method=request.method,
        path=path,
        status_code=str(status_code),
        status_class=status_class,
    ).inc()

    REQUEST_LATENCY_MS.labels(path=path).observe(latency_ms)

    # Set response headers
    response.headers["x-request-id"] = request_id
    response.headers["x-model-version"] = str(STATE["version"])

    log.info(
        '{"request_id":"%s","path":"%s","status":%d,"latency_ms":%.2f,"model_version":"%s"}',
        request_id, path, status_code, latency_ms, STATE["version"],
    )
    return response


@app.get("/metrics")
def metrics():
    """Prometheus metrics scraping endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "alive"}


@app.get("/ready")
def ready():
    """Readiness probe."""
    if STATE["model"] is None:
        return JSONResponse(status_code=503, content={"status": "not_ready", "reason": "model not loaded"})
    return {"status": "ready", "model_version": STATE["version"]}


def _score(rows: list[dict]) -> list[float]:
    if STATE["model"] is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    import pandas as pd
    from src.data import FEATURES

    # Record feature distribution stats for monitoring
    if rows and "temp_c" in rows[0]:
        temps = [r["temp_c"] for r in rows if "temp_c" in r]
        if temps:
            FEATURE_TEMP_C_MEAN.set(sum(temps) / len(temps))

    frame = pd.DataFrame(rows)[FEATURES]
    return [float(p) for p in STATE["model"].predict_proba(frame)[:, 1]]


@app.post("/predict")
def predict(payload: Union[BatchRequest, VertexPredictRequest, PredictRequest]) -> dict[str, Any]:
    if isinstance(payload, BatchRequest):
        scores = _score([row.model_dump() for row in payload.rows])
        return {"probabilities": scores, "model_version": str(STATE["version"])}

    if isinstance(payload, VertexPredictRequest):
        scores = _score([instance.model_dump() for instance in payload.instances])
        return {"predictions": scores, "model_version": str(STATE["version"])}

    score = _score([payload.model_dump()])[0]
    return {"probability": score, "model_version": str(STATE["version"])}


@app.post("/predict/batch", response_model=BatchResponse)
def predict_batch(payload: BatchRequest) -> BatchResponse:
    scores = _score([row.model_dump() for row in payload.rows])
    return BatchResponse(probabilities=scores, model_version=str(STATE["version"]))


@app.get("/v1/endpoints/{endpoint_id}/deployedModels/{deployed_model_id}")
async def vertex_internal_health(endpoint_id: str, deployed_model_id: str):
    return {"status": "HEALTHY", "model_version": STATE.get("version", "unknown")}
