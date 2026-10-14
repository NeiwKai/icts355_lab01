## Task 1
1. Schedule (schedule: "0 2 * * 0"):

- Justification: Running at 02:00 UTC on Sunday triggers automated model retraining during low-traffic weekend off-peak hours. This prevents resource contention with live API serving and avoids hitting GCP API rate limits or GPU quota bottlenecks during operational peak times.

2. Evaluation Gate (condition: "gate_decision == 'pass'"):

- Justification: Enforcing a conditional gate on gate_decision == 'pass' guarantees that degraded or regressed candidate models are rejected before reaching the registry. If scripts/evaluation_gate.py evaluates metrics against the baseline and writes 'fail', Kubeflow Pipelines (dsl.If) safely skips the register and deploy_staging steps without breaking pipeline execution.

## Task 2

| Identity | Service Account Email | Allowed Actions | Assigned IAM Roles | Technical Justification |
| :--- | :--- | :--- | :--- | :--- |
| **Training Identity** | `sa-itcs355-training@${PROJECT_ID}.iam.gserviceaccount.com` | Read raw dataset from GCS, write trained `.joblib` model artifacts to GCS bucket, and publish training loss metrics to GCP Cloud Monitoring. | `roles/storage.objectUser`<br>`roles/monitoring.metricWriter` | Requires read/write access to pipeline bucket objects and permissions to publish time-series training metrics. Cannot deploy endpoints or push Docker images. |
| **Serving Identity** | `sa-itcs355-serving@${PROJECT_ID}.iam.gserviceaccount.com` | Read production model binary from GCS, stream stdout/stderr runtime logs to Cloud Logging, and emit drift metrics via `adapter.emit_metric()`. | `roles/storage.objectViewer`<br>`roles/logging.logWriter`<br>`roles/monitoring.metricWriter` | Requires strictly read-only access to model artifacts and write-only access to logging/metrics backends. Cannot write, modify, or delete raw GCS dataset files. |
| **CI/CD Identity** | `sa-itcs355-ci@${PROJECT_ID}.iam.gserviceaccount.com` | Push Docker container images to Artifact Registry, execute compiled KFP JSON specs on Vertex AI Pipelines, and deploy models to Vertex Endpoints. | `roles/artifactregistry.writer`<br>`roles/aiplatform.user`<br>`roles/iam.serviceAccountUser` | Requires deployment orchestration permissions to trigger pipelines and attach `sa-itcs355-serving` as the runtime service account for Vertex AI Endpoints. |


### Task 2 Break Test Verification Output

* **Command:** `python -m monitoring.drift --current data/current.csv --emit`
* **Identity:** `sa-itcs355-serving@itcs355-6688132.iam.gserviceaccount.com` (with `roles/monitoring.metricWriter` removed)
* **Observed Failure:**
  `Warning: Failed to emit metric 'drift_psi_temp_c' to Cloud Monitoring: 403 Permission monitoring.timeSeries.create denied`
* **Key Finding:** The service computes statistical metrics in-memory successfully, but Cloud Monitoring rejects time-series writes at the API boundary due to missing `monitoring.timeSeries.create` rights.

_output can be seen in `Lab5_capture_instruction.pdf`_

## Task 3 — Scheduled Retraining

### Strategy Comparison Matrix

| Strategy | When it is right | How it fails |
| :--- | :--- | :--- |
| **Fixed schedule** *(e.g., Weekly on Sunday at 02:00 UTC)* | Right for predictable, low-cadence equipment wear cycles where operational drift accumulates linearly over operational hours without sudden schema shifts. | Fails by wasting cloud compute costs on unnecessary retraining runs when no new data has arrived, or by reacting too slowly when sudden hardware sensor decalibration (+20°C offset) occurs mid-week. |
| **Data volume threshold** *(e.g., Retrain after 50,000 new inferences)* | Right for high-throughput prediction services where model performance relies on strict sample sizes for statistical convergence. | Fails during low-production periods (e.g., plant maintenance shutdowns) where no retraining occurs for months, allowing minor seasonal feature distribution shifts to go undetected. |
| **Drift-triggered** *(e.g., Retrain when PSI ≥ 0.20 on `temp_c`)* | Right for dynamic environments where incoming feature distributions shift unpredictably due to operational workload changes or seasonal shifts. | **Catastrophically fails when upstream data is corrupted** (e.g., uncalibrated sensor firmware). Auto-retraining bakes the +20°C corrupted artifact into the model baseline, permanently destroying a working model. |

---

### Chosen Strategy & Worst-Case Scenario Analysis

#### Chosen Strategy: Fixed Schedule with Data Contract Circuit Breakers
We chose a **Fixed Schedule (Weekly on Sunday at 02:00 UTC)** coupled with **Hard Data Contract Assertions (`tests/test_data.py`)** inside the pipeline's `validate` step.

#### Why Drift-Triggered Auto-Retraining is Unsafe for This System
In industrial sensor telemetry, feature drift does not always signal that the world has changed; it frequently signals that an upstream data producer or physical sensor has failed. 

If we configure automated drift-triggered retraining (e.g., triggering a pipeline run whenever $\text{PSI} \ge 0.20$ on `temp_c`), an upstream firmware bug introducing a static $+20^\circ\text{C}$ offset will trigger an immediate retrain. The pipeline will ingest the corrupted dataset, fit new decision boundaries around invalid temperature readings, pass evaluation against similarly corrupted test data, and deploy to production.

#### The Worst-Case Scenario
1. **Corrupted Ingestion:** A faulty firmware update applies a static $+20^\circ\text{C}$ offset across temperature sensors.
2. **Automated Triggering:** PSI on `temp_c` spikes to `3.38`, automatically launching the retraining pipeline.
3. **Baseline Destruction:** The pipeline trains a model that treats $100^\circ\text{C}$ as normal operating conditions ($80^\circ\text{C}$ actual), obliterating the true physical baseline.
4. **Financial Impact:** Real overheating events ($>100^\circ\text{C}$ actual) go undetected, resulting in catastrophic machinery failure or false emergency plant shutdowns costing tens of thousands of dollars.

#### Operational Protection
To prevent this, our pipeline enforces strict data schema and range contract tests (`temp_c <= 120°C`, `null_rate == 0.0`) in the `validate` step. If upstream corruption occurs, the pipeline hard-aborts during validation before reaching the `train` step, preserving the working production model.

## Task 4 — The Portability Test

### 1. Which Method Was Hardest & Why?
`invoke()` was significantly harder to standardize than `upload()` or `download()`. While object storage operations (`upload`/`download`) follow uniform key-value semantics across GCP Cloud Storage (GCS) and AWS S3, invocation endpoints handle authentication and payload wrapping fundamentally differently. GCP Vertex AI prediction endpoints expect OAuth2 Bearer Tokens and a nested JSON payload structure (`{"instances": [...]}` or `rawPredict`), whereas AWS SageMaker Runtime expects SigV4 signed request headers and unnested payload bodies. Hiding these protocol and header differences behind `adapter.invoke()` required mapping custom request/response schemas inside the adapter layer.

### 2. Where the Abstraction Genuinely Leaked
The abstraction leaked most visibly at **IAM Service Account delegation and storage URI formats**. Higher-level code in `src/` must remain unaware of whether a URI begins with `gs://` or `s3://`, yet underlying client libraries (like `pandas` or `joblib`) often expect raw cloud URIs or provider-specific credential chains. Hiding these required wrapping all file interactions in explicit local staging downloads rather than allowing libraries to stream directly from remote URIs.

### 3. Engineering Cost of a Full System Migration
A complete system migration from Google Cloud Platform (Vertex AI, Cloud Monitoring, Artifact Registry) to AWS (SageMaker, CloudWatch, ECR) for this prediction service would cost approximately **10 to 12 engineering days**:
* **Pipeline Translation (3 days):** Re-authoring Kubeflow Pipelines (`pipeline_vertex.json`) into SageMaker Pipelines SDK syntax (`sagemaker.workflow.pipeline.Pipeline`).
* **IAM & Security Re-binding (2 days):** Translating GCP Service Accounts and IAM roles (`roles/storage.objectViewer`, `roles/monitoring.metricWriter`) to AWS IAM Roles, Trust Policies, and KMS keys.
* **Serving & Endpoint Infrastructure (3 days):** Converting Vertex AI custom container serving configurations into SageMaker Model Endpoints or ECS/Fargate task definitions.
* **Monitoring & Alerting Setup (2-4 days):** Re-building GCP Cloud Monitoring custom metric descriptors and alerting channels using AWS CloudWatch Metrics and SNS topics.

### 4. Was Building This Abstraction Worth It? (Honest Evaluation)
**No, for a single startup or small team, building this custom multi-cloud abstraction layer was not worth the upfront engineering cost.**

While the three-layer pattern (`src/` -> `cloudlayer/` -> Provider SDKs) succeeded in keeping Layer 1 code 100% portable, maintaining custom adapters introduces substantial technical debt. Cloud providers evolve their APIs independently (e.g., KFP v2 breaking changes on GCP vs. SageMaker SDK updates on AWS). The engineering hours spent maintaining custom wrapper abstractions far exceed the eventual cost of migrating if the business ever needed to switch providers. Cloud portability sounds attractive in architectural meetings, but in real engineering, committing to a single cloud provider's native tooling (deliberate lock-in) yields faster delivery and lower maintenance overhead.
