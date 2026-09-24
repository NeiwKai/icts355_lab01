"""Lab 3 — inference service.

Provider-neutral by construction: the model arrives through the adapter, and the same
container image deploys to SageMaker, Azure ML, or Vertex AI. Route paths differ per
platform; that difference belongs in cloudlayer/, never here.

Run locally:  uvicorn service.app:app --port 8080
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Union

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

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

def _load_model():
    """Load once at startup via Cloud Layer abstraction."""
    import joblib
    import os
    from src import config
    from cloudlayer.factory import get_adapter

    raw_path = os.environ.get("MODEL_PATH", "/tmp/reports/model.joblib")
    log.info("Configured MODEL_PATH: '%s'", raw_path)

    # Resolve and download model via cloudlayer adapter
    cfg = config.load()
    adapter = get_adapter(cfg)
    
    local_path = adapter.download_artifact(raw_path, "/tmp/reports/model.joblib")

    log.info("Unpickling model from '%s'...", local_path)
    return joblib.load(local_path)

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        STATE["model"] = _load_model()
        log.info('"model loaded, version=%s"', STATE["version"])
    except Exception as exc:  # readiness stays false; liveness still passes
        STATE["model"] = None
        log.error('"model load failed: %s"', exc)
    yield
    STATE["model"] = None


app = FastAPI(title="ITCS355 inference", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def add_request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    started = time.perf_counter()
    response = await call_next(request)
    latency_ms = (time.perf_counter() - started) * 1000
    response.headers["x-request-id"] = request_id
    response.headers["x-model-version"] = str(STATE["version"])
    log.info(
        '{"request_id":"%s","path":"%s","status":%d,"latency_ms":%.2f,"model_version":"%s"}',
        request_id, request.url.path, response.status_code, latency_ms, STATE["version"],
    )
    return response


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness. The process is up. Says nothing about whether it can serve."""
    return {"status": "alive"}


@app.get("/ready")
def ready():
    """Readiness. The model is loaded and can score.

    These two are genuinely different, and confusing them causes a specific production
    failure: traffic routed to a container whose model has not finished loading. All three
    providers distinguish them, and Quiz 3 asks about it.
    """
    if STATE["model"] is None:
        return JSONResponse(status_code=503, content={"status": "not_ready", "reason": "model not loaded"})
    return {"status": "ready", "model_version": STATE["version"]}


def _score(rows: list[dict]) -> list[float]:
    if STATE["model"] is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    import pandas as pd

    from src.data import FEATURES

    frame = pd.DataFrame(rows)[FEATURES]
    return [float(p) for p in STATE["model"].predict_proba(frame)[:, 1]]


@app.post("/predict")
def predict(payload: Union[BatchRequest, VertexPredictRequest, PredictRequest]) -> dict[str, Any]:
    # 1. Handle BatchRequest: {"rows": [...]}
    if isinstance(payload, BatchRequest):
        scores = _score([row.model_dump() for row in payload.rows])
        return {"probabilities": scores, "model_version": str(STATE["version"])}

    # 2. Handle VertexPredictRequest: {"instances": [...]}
    if isinstance(payload, VertexPredictRequest):
        scores = _score([instance.model_dump() for instance in payload.instances])
        return {"predictions": scores, "model_version": str(STATE["version"])}

    # 3. Handle single PredictRequest: {"temp_c": 78.4, ...}
    score = _score([payload.model_dump()])[0]
    return {"probability": score, "model_version": str(STATE["version"])}



@app.post("/predict/batch", response_model=BatchResponse)
def predict_batch(payload: BatchRequest) -> BatchResponse:
    scores = _score([row.model_dump() for row in payload.rows])
    return BatchResponse(probabilities=scores, model_version=str(STATE["version"]))
