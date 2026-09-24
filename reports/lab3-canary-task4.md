# Task 4 — Canary Deployment & Emergency Rollback Report

**Target Endpoint:** `itcs355-endpoint` (`projects/203185016197/locations/asia-south1/endpoints/4774855743012601856`)  
**Primary Model ID:** `247779343365832704` (`itcs355-endpoint-deployed`)  
**Canary Model ID:** `2891955274585735168` (`v2-canary`)

---

## 1. Initial 90/10 Traffic Split Evidence

A canary deployment was executed by deploying `v2-canary` to the existing active Vertex AI endpoint alongside the primary model. Traffic was split with **90% routed to primary** and **10% routed to canary**.

Timestamped confirmation was recorded in `reports/canary-traffic-90-10.json`:

```json
{
  "trafficSplit": {
    "247779343365832704": 90,
    "2891955274585735168": 10
  }
}



## 2. Load Test & Degradation Detection

Synthetic traffic was executed against the active 90/10 endpoint using `k6`. Degradation caused by `v2-canary` was immediately detected via standard HTTP assertion checks and custom failure metrics across multiple concurrency levels:

- 1 VU Test: predict_failures rate reached 10.82% (29 failed requests out of 268 total requests).

- 10 VU Test: predict_failures rate stabilized at 10.04% (72 failed requests out of 717 total requests).

- 50 VU Test: predict_failures reached 12.37% with server queue saturation causing request timeouts at p95 = 9,263 ms.

The observed error rate of ~10% directly matches the 10% traffic weight assigned to `v2-canary`, proving that the model degradation was successfully isolated and detected using endpoint-level metrics alone.



## 3. Five-Line Task 4 Analysis

1. Revealing Metric: The HTTP prediction failure metric (`predict_failures` / `http_req_failed`) jumped from 0.00% to 10.04%–10.82%, precisely reflecting the 10% traffic share allocated to `v2-canary`.

2. Detection Time: Detection took 60 seconds (the duration of the 1 VU load test scenario), during which 29 out of 268 requests failed status checks and probability payload assertions.

3. Faster Detection: Real-time Cloud Monitoring log metric alerts tracking non-200 responses or automated payload output distribution checks (e.g., KS-test statistical drift alerts on prediction scores) would have brought detection time under 10 seconds.

4. 50/50 vs 90/10 Impact: A 50/50 split would have exposed 50% of production traffic to degraded model responses (a 5x increase in failed user requests) and caused earlier queue collapse, whereas 90/10 limited failure exposure to 10% of total traffic.

5. Rollback Execution: Rollback was executed via `ep.update(traffic_split={'247779343365832704': 100})`, restoring 100% traffic to the primary model in under 10 seconds and the out is below.

```json
{
  "trafficSplit": {
    "247779343365832704": 90,
    "2891955274585735168": 10
  }
}
```



## 4. Emergency Rollback Verification Evidence

Timestamped evidence confirming that 100% of incoming traffic was shifted back to the primary model (`247779343365832704`) and 0% to `v2-canary` give output below:

```json
{
  "trafficSplit": {
    "247779343365832704": 100
  }
}
```

## 5. The five lines answer

1. **Revealing Metric:** The HTTP prediction failure rate (`predict_failures` / `http_req_failed`) spiked from 0.00% to **10.04%–10.82%**, matching the 10% traffic weight assigned to `v2-canary`.
2. **Detection Time:** Detection took **60 seconds** during the 1 VU load test scenario, across 268 total requests (29 failed checks).
3. **Faster Detection:** Real-time Cloud Monitoring log metric alerts or automated output distribution drift assertions (e.g., KS-test drift on prediction probabilities) would have triggered a rollback alert in **under 10 seconds**.
4. **50/50 vs 90/10 Impact:** A 50/50 split would have exposed 5x more production traffic to degraded responses (driving overall failure rate to ~50%), accelerating statistical detection but severely impacting half of active users instead of isolating risk to 10%.
5. **Rollback Execution:** Emergency rollback was executed via `ep.update(traffic_split={'247779343365832704': 100})`, restoring 100% traffic back to primary model `247779343365832704` in under 10 seconds.
