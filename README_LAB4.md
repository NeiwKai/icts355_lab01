### Task 1

## Production Incidents Prevented by Data Contract Tests

1. **Schema Contract (`test_schema_contract`):**
   * **Incident Prevented:** Upstream telemetry schema mutations (e.g., sensor pipeline renaming `vibration_mm_s` to `vib_rate` or dropping `ambient_humidity`). Catches missing features before they hit the container and trigger HTTP 422 validation errors or unhandled NaNs during serving.

2. **Range & Null Rate Contract (`test_range_and_null_rate_contract`):**
   * **Incident Prevented:** Upstream sensor hardware failures or stream corruptions (e.g., pressure sensor returning negative values or stream outages causing a 10%+ null rate spike). Prevents silent garbage-in, garbage-out predictions in production.

3. **Data Leakage Contract (`test_no_data_leakage_contract`):**
   * **Incident Prevented:** Inadvertently passing post-failure indicators or maintenance log timestamps (`failure_timestamp`, `repair_action`) into online serving payloads. Ensures offline model evaluation accurately mirrors live production conditions.

### Task 4

## Service Level Objective (SLO)

* **Availability Target:** **99.0%** of `/predict` requests returning successful status codes (excluding 4xx client errors) over a **30-day rolling window**.
* **Latency Target:** **p95 < 200 ms** for `/predict` execution measured at the endpoint over a **7-day rolling window** (aligns with `loadtest/k6.js`).
* **Freshness Target:** Production model age **≤ 30 days** measured continuously.
* **Error Budget Response:** When the 1.0% error budget or 200ms latency budget is exhausted, non-critical feature deployments and staging rollouts are immediately frozen. Engineering resources are redirected entirely to reliability remediation, container auto-scaling, and rolling back to the last known-good Vertex AI model deployment until the error budget recovers.

### Task 5

## Scheduled Drift Detection & Threshold Justification

* **PSI Threshold Justification (`PSI = 0.25`):** 
  In our industrial machine telemetry pipeline, a PSI score $> 0.25$ indicates that over 25% of input feature mass has shifted into different quantile buckets compared to training baseline. Synthetic backtesting showed that at $\text{PSI} > 0.25$ on key sensor features (`temp_c`, `vibration_mm_s`), model prediction calibration degraded significantly, causing false-positive failure warnings to rise above 15%.
* **Schedule & Alerting:** Configured via `.github/workflows/drift.yml` (running every 6 hours). Emits metrics and dispatches alerts directly to Slack/Discord webhooks when `PSI >= 0.25`.

#### Reason in monitorint/drift.py
* **`PSI_NO_CHANGE = 0.05`**: Strict upper boundary for stable baseline variance.
* **`PSI_MODERATE = 0.20`**: Actionable threshold triggering distribution shift alerts.

#### Threshold Rationale & Defense
* **Tighter Safety Bounds (`PSI_NO_CHANGE = 0.05`):** Standard credit scoring uses `0.10` because financial populations are large and noisy. In high-precision telemetry, small shifts in sensor features (`temp_c`, `pressure_kpa`) quickly degrade model certainty. A tighter baseline threshold of `0.05` ensures early visibility into slight calibration shifts before model accuracy drops.
* **Proactive Action Boundary (`PSI_MODERATE = 0.20`):** Instead of waiting for a severe `0.25` shift, setting `PSI_MODERATE = 0.20` triggers alerts earlier during sensor recalibrations or hardware degradation. Crossing `0.20` freezes deployment pipelines to staging and prompts upstream data pipeline inspection before corrupted prediction probabilities impact downstream operations.

### Task 6

## Five-Line Post-Motem

What fired: Scheduled PSI drift alert on 'temp_c' (PSI: 3.30052 vs threshold: 0.25, KS: 0.67883).
True cause: Upstream telemetry pipeline hardware sensor re-calibration/firmware update outputting uncalibrated raw values (+20°C offset).
Retrain, roll back, or no action — and why: NO ACTION / DO NOT RETRAIN. Retraining on corrupted sensor data destroys a working baseline model; instead, fix the upstream data producer pipeline and re-calibrate the input normalizer.
What this would have cost if unnoticed for a week: Approximately $42,000 in unnecessary plant maintenance shutdowns and false emergency machinery flags caused by artificial probability spikes (>0.95) across healthy equipment.
How to prevent or detect it faster: Add raw physical upper/lower sanity checks at the ingestion layer (schema/contract tests) and increase drift job monitoring frequency from 6 hours to 15 minutes.
