# ITCS355 Lab 1
# `make reproduce` is the one command a grader runs. Keep it working.

SHELL := /bin/bash
IMAGE ?= itcs355-lab1
TAG   ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo dev)
PLATFORM ?= linux/amd64
SEED ?= 20260101

.PHONY: help setup cloud-check data test portability-audit train image image-push reproduce verify clean teardown \
        tune compare reload-check serve serve-image loadtest drift inject-drift pipeline cost swap-check llm-eval llm-gate \
				train-remote \ # For lab2
				serve-image-push deploy loadtest-payload loadtest-coldstart loadtest-batch # For lab3

help:
	@grep -E "^[a-zA-Z_-]+:.*?## .*$$" $(MAKEFILE_LIST) | awk -F":.*?## " "{printf \"  %-20s %s\\n\", \$$1, \$$2}"

setup: ## Install dependencies and print environment status
	python -m pip install --upgrade pip
	pip install -r requirements.txt
	@echo "environment ok"

cloud-check: ## Resolve the eight capability slots
	python scripts/cloud_check.py

data: ## Generate the default dataset (deterministic)
	# Use docker instead of host machine python
	docker run --rm \
		--user "$$(id -u):$$(id -g)" \
		-v "$$PWD:/app" \
		-w /app \
		python:3.11-slim \
		bash -c "pip install --quiet --target /tmp/packages numpy pandas && PYTHONPATH=/tmp/packages python scripts/make_dataset.py --seed $(SEED)"

test: ## Run data contract and split property tests
	# Use docker instead of host machine python
	docker run --rm \
		--user "$$(id -u):$$(id -g)" \
		-v "$$PWD:/app" \
		-w /app \
		python:3.11-slim \
		bash -c "pip install --quiet --target /tmp/packages -r requirements.txt && PYTHONPATH=/tmp/packages python -m pytest -q tests/"

portability-audit: ## Fail if provider strings leak into src/
	python scripts/portability_audit.py

train: ## Train locally, outside the container
	python -m src.train --seed $(SEED) --metrics-out reports/metrics.json

image: ## Build the training image for linux/amd64
	docker buildx build --platform $(PLATFORM) -t $(IMAGE):$(TAG) --load .

image-push: image ## Push to CONTAINER_REGISTRY via your adapter
	python -c "from src import config; from cloudlayer.factory import get_adapter; \
	print(get_adapter(config.load()).push_image(\"$(IMAGE):$(TAG)\"))"

reproduce: data image ## THE ONE COMMAND. Grader runs this.
	mkdir -p reports
	chmod 777 reports # Fix permission issue
	docker run --rm \
	  -v "$$PWD/data:/app/data:ro" \
	  -v "$$PWD/reports:/app/reports" \
	  -e MLFLOW_TRACKING_URI=sqlite:////app/reports/mlflow.db \
	  $(IMAGE):$(TAG) --seed $(SEED) --metrics-out /app/reports/metrics.json

verify: ## Check the produced metric against the README claim
	python scripts/verify_metric.py

teardown: ## Delete every resource tagged course=itcs355 for this lab
	# cfg.tags indicate the lab. e.g., cfg.tags(1) -> lab1
	python -c "from src import config; from cloudlayer.factory import get_adapter; \
	cfg=config.load(); print(get_adapter(cfg).teardown(cfg.tags($(LAB))))"

clean: ## Remove local artifacts
	rm -rf mlruns mlartifacts mlflow.db reports/metrics.json .pytest_cache

# --- Lab 2 -------------------------------------------------------------------
tune: ## Budgeted hyperparameter study (>=12 trials)
	python -m src.tune --trials 12 --budget-thb 150 --instance n4-highcpu-2

compare: ## Rank runs by metric and by cost per point
	python scripts/compare_runs.py --experiment itcs355-lab2

reload-check: ## Load the registered model by version and score rows
	python scripts/reload_check.py --name $(MODEL_REGISTRY_NAME) --version $(VERSION)

train-remote: data image-push ## Task 1: Train docker on cloud
	@echo "Submitting remote training job..."
	python -c "from src import config; from cloudlayer.factory import get_adapter; \
	cfg = config.load(); adapter = get_adapter(cfg); \
	adapter.upload('data/raw/sensors.csv', 'data/raw/sensors.csv'); \
	img = adapter.push_image('$(IMAGE):$(TAG)'); \
	args = ['--seed', '$(SEED)', '--metrics-out', '/tmp/reports/metrics.json', '--output-gcs-path', f'{cfg.blob_uri}/reports/metrics.json']; \
	job_id = adapter.submit_training(img, args=args); \
	print(f'Submitted training job: {job_id}'); \
	res = adapter.wait_training(job_id); \
	print('Job result:', res)"


register: ## Task 4: Register candidate model to Vertex AI Registry (e.g. make register RUN_ID=a62c6df0)
	@if [ -z "$(RUN_ID)" ]; then echo "Error: RUN_ID is required. Usage: make register RUN_ID=<id>"; exit 1; fi
	python -c "\
	from src import config; \
	from cloudlayer.factory import get_adapter; \
	cfg = config.load(strict=False); \
	adapter = get_adapter(cfg); \
	model_uri = f'runs:/$(RUN_ID)/model'; \
	version = adapter.register_model(model_uri=model_uri, name=cfg.model_registry_name); \
	print(f'Successfully registered model version {version} with lineage tags.')"

# --- Lab 3 -------------------------------------------------------------------
serve: ## Run the inference service locally on :8080
	python scripts/export_model.py --out reports/model.joblib
	MODEL_PATH=reports/model.joblib MODEL_VERSION=local uvicorn service.app:app --port 8080

serve-image: ## Build the serving image
	docker buildx build --platform $(PLATFORM) -f service/Dockerfile.serve -t itcs355-serve:$(TAG) --load .


serve-image-push: serve-image ## Push app service image to CONTAINER_REGISTRY via your adapter
	python -c "from src import config; from cloudlayer.factory import get_adapter; \
	print(get_adapter(config.load()).push_image(\"itcs355-serve:$(TAG)\"))"


GCP_REGION ?= asia-south1
PROJECT_ID ?= $(shell gcloud config get-value project 2>/dev/null)
ENDPOINT_NAME ?= itcs355-endpoint
ENDPOINT_ID ?= $(shell gcloud ai endpoints list --region=$(GCP_REGION) --filter="displayName:$(ENDPOINT_NAME)" --format="value(name)" 2>/dev/null | awk -F'/' '{print $$NF}' | head -n 1)


loadtest: ## Load test at three concurrency levels (1, 10, 50 VUs)
	@TOKEN=$$(gcloud auth print-access-token) ; \
	TARGET="https://$(GCP_REGION)-aiplatform.googleapis.com/v1/projects/$(PROJECT_ID)/locations/$(GCP_REGION)/endpoints/$(ENDPOINT_ID):rawPredict" ; \
	for vus in 1 10 50; do \
		echo "=== $$vus VUs ===" ; \
		k6 run -e TARGET="$$TARGET" -e TOKEN="$$TOKEN" -e VUS=$$vus loadtest/k6.js || true ; \
	done

loadtest-batch: ## Task 3 Variable 1: Compare 100x single vs 1x batch call
	@TOKEN=$$(gcloud auth print-access-token) ; \
	BASE="https://$(GCP_REGION)-aiplatform.googleapis.com/v1/projects/$(PROJECT_ID)/locations/$(GCP_REGION)/endpoints/$(ENDPOINT_ID)" ; \
	echo "=== Running Single Mode (100x /predict per iter) ===" ; \
	k6 run -e BASE="$$BASE" -e TOKEN="$$TOKEN" -e MODE=single -e VUS=1 loadtest/k6-batch.js || true ; \
	echo "=== Running Batch Mode (1x /predict/batch per iter) ===" ; \
	k6 run -e BASE="$$BASE" -e TOKEN="$$TOKEN" -e MODE=batch -e VUS=1 loadtest/k6-batch.js || true

loadtest-payload: ## Task 3 Variable 2: Sweep payload size padding (0, 1KB, 10KB, 100KB, 1MB)
	@TOKEN=$$(gcloud auth print-access-token) ; \
	TARGET="https://$(GCP_REGION)-aiplatform.googleapis.com/v1/projects/$(PROJECT_ID)/locations/$(GCP_REGION)/endpoints/$(ENDPOINT_ID):rawPredict" ; \
	for pad in 0 1000 10000 100000 1000000; do \
		echo "=== Testing PAD_BYTES=$$pad ===" ; \
		k6 run -e TARGET="$$TARGET" -e TOKEN="$$TOKEN" -e PAD_BYTES=$$pad -e VUS=10 loadtest/k6-payload.js || true ; \
	done

loadtest-coldstart: ## Task 3: Measure cold-start latency vs warm steady-state latency
	@TOKEN=$$(gcloud auth print-access-token) ; \
	TARGET="https://$(GCP_REGION)-aiplatform.googleapis.com/v1/projects/$(PROJECT_ID)/locations/$(GCP_REGION)/endpoints/$(ENDPOINT_ID):rawPredict" ; \
	PAYLOAD='{"temp_c": 78.4, "vibration_mm_s": 3.1, "pressure_kpa": 315.2, "hours_since_service": 4200, "load_pct": 68.0, "ambient_humidity": 55.0}' ; \
	echo "=== 1. First Request (Cold Start Overhead) ===" ; \
	curl -o /dev/null -s -w "Cold Start Latency: %{time_total}s\n" -X POST "$$TARGET" \
		-H "Authorization: Bearer $$TOKEN" \
		-H "Content-Type: application/json" \
		-d "$$PAYLOAD" ; \
	echo "=== 2. Second Request (Warm / Steady State) ===" ; \
	curl -o /dev/null -s -w "Warm Request Latency: %{time_total}s\n" -X POST "$$TARGET" \
		-H "Authorization: Bearer $$TOKEN" \
		-H "Content-Type: application/json" \
		-d "$$PAYLOAD"


deploy: ## Deploy model image to Vertex AI Endpoint (e.g. make deploy MACHINE_TYPE=n1-standard-4 MODEL_REGISTRY_NAME=dev ENDPOINT_NAME=itcs355-endpoint-large)
	@MODEL_REF="$(or $(MODEL_REGISTRY_NAME),dev)"; \
	ENDPOINT="$(or $(ENDPOINT_NAME),itcs355-endpoint)"; \
	MACHINE_TYPE="$(or $(MACHINE_TYPE),n1-standard-2)"; \
	python -c "\
	from src import config; \
	from cloudlayer.factory import get_adapter; \
	cfg = config.load(); \
	adapter = get_adapter(cfg); \
	ep = adapter.deploy('$${MODEL_REF}', '$${ENDPOINT}', '$${MACHINE_TYPE}'); \
	print('Deployed to Endpoint:', ep)"
	


smoke: ## Smoke test deployed endpoint with a sample payload
	@ENDPOINT="$(or $(ENDPOINT_NAME),itcs355-endpoint)"; \
	python -c "\
	from src import config; \
	from cloudlayer.factory import get_adapter; \
	cfg = config.load(strict=False); \
	adapter = get_adapter(cfg); \
	payload = {'temp_c': 82.478, 'vibration_mm_s': 4.888, 'pressure_kpa': 308.557, 'hours_since_service': 1508.063, 'load_pct': 95.792, 'ambient_humidity': 63.407}; \
	preds = adapter.invoke('$${ENDPOINT}', payload); \
	print('Smoke Test Response:', preds)"

# --- Lab 4 -------------------------------------------------------------------
inject-drift: ## Shift a feature's distribution on purpose
	python scripts/inject_drift.py --feature temp_c --mode shift --magnitude 6

drift: ## Score drift against the reference window
	python -m monitoring.drift --current data/current.csv

# --- Lab 5 -------------------------------------------------------------------
pipeline: ## Compile pipeline/pipeline.yaml for your provider
	python -c "from cloudlayer.pipelines import compile_for; from src import config; \
	compile_for(config.load().provider)"

llm-eval: ## Run the LLM golden set against recorded responses (offline, free)
	python scripts/llm_eval.py --out reports/llm_eval-baseline.json

llm-gate: ## Prove the gate fails on a degraded set — expected to exit non-zero
	python scripts/llm_eval.py --out reports/llm_eval-baseline.json >/dev/null
	python scripts/llm_eval.py --responses evals/fixtures/triage-regressed.jsonl \
	  --out reports/llm_eval.json --baseline reports/llm_eval-baseline.json

cost: ## Build the cost report
	python scripts/cost_report.py --estimate $(EST) --actual $(ACT) --rps $(RPS) --instance $(INSTANCE)

swap-check: ## Prove the portability seam against a second provider
	python scripts/portability_swap_check.py --second-provider $(SECOND)
