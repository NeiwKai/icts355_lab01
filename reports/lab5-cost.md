# Lab 5 — Cost report

Provider `gcp` · instance `n1-standard-2` · 3.83 THB/hour

## 1. Estimate, made before running
100.00 THB

## 2. Actual, from billing filtered by tag
93.36 THB

## 3. The gap
-6.64 THB (-6.6%)

Our actual weekly spend was -6.64 THB (-6.6%) lower than our pre-run estimate, remaining well within the required 20% tolerance threshold. The favorable variance was driven by two key factors:
1. **Prompt Teardown After Testing:** We shut down the Vertex AI Endpoint immediately following our Lab 3 load testing, avoiding unbudgeted overnight idle charges for the `n1-standard-2` instance.
2. **Spot Instance Discounts:** Running our training pipeline on `n1-standard-4` Spot Instances reduced compute execution costs compared to standard on-demand pricing. The remaining spend consists of baseline endpoint uptime during test execution, GCS artifact storage, and Cloud Logging ingestion.

## 4. Breakdown by component
| Component | THB | Notes |
|---|---|---|
| Training | 3.55 | Vertex AI Training Pipeline execution (`n1-standard-4` Spot instance) |
| Storage | 5.13 | GCS Buckets (`gs://itcs355-6688132-bucket`) + Artifact Registry image layers |
| Serving | 76.84 | Vertex AI Online Prediction Endpoint (`n1-standard-2` runtime during testing) |
| Pipeline | 0.75 | Vertex AI Pipelines execution fees ($0.03/run across pipeline iterations) |
| Monitoring | 7.09 | Cloud Logging ingestion + Cloud Monitoring custom metric time-series points |

## 5. Cost per 1,000 predictions
Measured throughput: 42.0 req/s

| Utilisation | THB per 1,000 |
|---|---|
| 5% | 0.5066 |
| 25% | 0.1013 |
| 80% | 0.0317 |

We believe the **25% utilisation scenario (0.1013 THB per 1,000 predictions)** represents the realistic steady-state baseline for this industrial system. Industrial equipment telemetry exhibits strong diurnal cycles—peaking during active plant operation hours and dropping significantly during shift changes and nighttime maintenance windows. Evaluating unit economics at 25% reflects realistic operational capacity without assuming unrealistically constant peak load (80%).

Below roughly **0.0010 req/s**, scheduled batch inference is cheaper than keeping this endpoint warm. Our measured load-test throughput of **42.0 req/s** easily exceeds the **0.0010 req/s** breakeven threshold. Because our real-time prediction traffic requires sub-150ms latency for immediate safety alerts, keeping a warm real-time endpoint is both financially justified and operationally necessary.

## 6. One optimisation you applied
| | Before | After |
|---|---|---|
| Configuration | `n1-standard-4` On-Demand Training + `n1-standard-4` Serving | `n1-standard-4` Spot Training + `n1-standard-2` Serving |
| THB per 1,000 | 0.1962 | 0.1013 |
| Latency p95 | 88 ms | 112 ms |

We optimized system cost by transitioning training pipeline steps to **Spot Instances** (`spot: true` in `pipeline/pipeline.yaml`) and right-sizing the serving endpoint machine class from `n1-standard-4` (4 vCPUs, 15 GB RAM) to `n1-standard-2` (2 vCPUs, 7.5 GB RAM).

* **Financial Impact:** Reduced cost per 1,000 predictions at 25% utilization from 0.1962 THB to 0.1013 THB (**48.4% cost reduction**).
* **Performance Impact:** Downsizing the serving node increased p95 prediction latency from 88 ms to 112 ms (+24 ms overhead). Because our service SLA permits p95 latency up to 200 ms, trading 24 ms of compute headroom for a ~50% reduction in infrastructure spend represents a clear engineering win.
