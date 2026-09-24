# Lab 3: Load Testing & Performance Benchmark Report

**Pre-Stated Latency Target:** p95 < 200 ms at 0.00% error rate.

---

## 1. Concurrency Load Test Results (`n1-standard-2`)

Load tests were executed against the FastAPI deployment on Vertex AI (`asia-south1`) across 1, 10, and 50 Virtual Users (VUs) using `loadtest/k6.js`.

| Concurrency (VUs) | Throughput (RPS) | p50 Latency | p90 Latency | p95 Latency | p99 / Max Latency | Error Rate |
|---|---|---|---|---|---|---|
| **1 VU** | **4.77 RPS** | **184.17 ms** | 255.28 ms | **282.23 ms** | 2,382.41 ms (Max) | **0.00%** |
| **10 VUs** | **13.95 RPS** | **698.73 ms** | 925.61 ms | **999.34 ms** | 1,283.50 ms (Max) | **0.00%** |
| **50 VUs** | **12.17 RPS** | **4,004.64 ms** | 4,799.54 ms | **4,992.87 ms** | 5,663.99 ms (Max) | **0.00%** |

### Breaking Point Analysis
* **Breaking Point:** **1 VU** (Immediate breach).
* **Observed vs. Target:** Even at a single virtual user, the p95 latency reached **282.23 ms**, crossing the pre-stated 200 ms target.
* **Root Cause:** Network propagation delay between the local client and Vertex AI in `asia-south1` imposes a baseline transport overhead of ~100–150 ms. Combined with single-threaded Uvicorn processing, the overall service capacity saturates early, with throughput peaking at **13.95 RPS** at 10 VUs before queueing delays degrade performance to ~5.0 seconds per request at 50 VUs.

---

## 2. Cold-Start Latency Analysis

Cold-start latency was measured independently via `make loadtest-coldstart` after container initialization and scale-from-zero:

* **Cold-Start Latency (First Request):** **1,086.03 ms** (1.086 s)
* **Warm / Steady-State Latency (Second Request):** **605.59 ms** (0.606 s)

### Metric Impact
During cold start, model instantiation, pandas imports, and container runtime lifespans create an initial initialization overhead of ~1.08 seconds. In the 1 VU load test, this initial request caused the maximum observed request latency to spike to **2,382.41 ms** (2.38 s), severely inflating the overall p99 and maximum latency metrics while steady-state calls remained ~184 ms.

---

## 3. Variable 1: Batch Size Comparison (100 Rows)

Evaluated via `loadtest/k6-batch.js` by comparing 100 sequential requests to `/predict` against 1 request containing 100 rows sent to `/predict/batch`:

| Execution Mode | Iterations Completed | Total Time per 100 Rows | Per-Call Median Latency (p50) | Effective Throughput |
|---|---|---|---|---|
| **Single Mode (100x `/predict`)** | 1 iteration | **40.22 seconds** | 258.33 ms | 2.49 rows/sec |
| **Batch Mode (1x `/predict/batch`)** | 107 iterations | **0.24 seconds** | 240.98 ms | 443.98 rows/sec |

### Key Finding
Processing 100 rows in a single batch request dropped wall-clock execution time from **40.22 seconds down to 0.24 seconds** (a **~167x throughput speedup**). Batching eliminates 99 unnecessary network round-trips and leverages vectorized NumPy/pandas array scoring inside the model container.

---

## 4. Variable 2: Payload Size Inflation (`_pad` Sweep)

Evaluated via `loadtest/k6-payload.js` at 10 VUs by appending an inert string (`_pad`) to the JSON request body:

| `PAD_BYTES` | Total Payload Size | Throughput | Median Latency (p50) | p95 Latency | Error Rate |
|---|---|---|---|---|---|
| **0 B** | ~120 B | 9.74 RPS | 959.99 ms | 1,570.13 ms | 0.00% |
| **1,000 B** | ~1.1 KB | 10.57 RPS | 899.06 ms | 1,292.06 ms | 0.00% |
| **10,000 B** | ~10.1 KB | 10.37 RPS | 932.53 ms | 1,258.38 ms | 0.00% |
| **100,000 B** | ~100.1 KB | 10.09 RPS | 983.90 ms | 1,316.68 ms | 0.00% |
| **1,000,000 B** | ~1.0 MB | 9.19 RPS | 1,014.09 ms | 1,568.82 ms | 0.00% |

### Key Finding
Latency remained flat from 0 B to 100 KB (~900–980 ms median), indicating that network ingress processing and single-worker compute queueing dominate small-to-medium requests. At **1.0 MB**, network payload transfer (285 MB total sent) and JSON string deserialization begin to dominate, reducing throughput to **9.19 RPS** and pushing median latency over **1.01 seconds**.

---

## 5. Variable 3: Instance Size Scaling (`n1-standard-2` vs `n1-standard-4`)

Evaluated by deploying the service to `n1-standard-4` (4 vCPUs, 15 GB RAM) and re-running `k6.js`:

| Concurrency Level | Base Instance (`n1-standard-2`) | Scaled Instance (`n1-standard-4`) | Performance Delta / Impact |
|---|---|---|---|
| **1 VU Throughput / p50** | 4.77 RPS / 184.17 ms | 4.99 RPS / 168.88 ms | +4.6% RPS, -8.3% p50 latency |
| **10 VUs Throughput / p50** | 13.95 RPS / 698.73 ms | 17.01 RPS / 576.86 ms | **+21.9% RPS**, -17.4% p50 latency |
| **50 VUs Throughput / p50** | 12.17 RPS / 4,004.64 ms | 10.69 RPS / 3,028.01 ms | -12.2% RPS, **-24.4% p50 latency** |
| **50 VUs p95 Latency** | 4,992.87 ms | 3,650.38 ms | **-26.9% p95 latency** |
| **On-Demand Hourly Cost** | **$0.1141 / hr (฿3.94)** | **$0.2282 / hr (฿7.87)** | **+100.0% Cost Increase** |

### Cost/Performance Tradeoff Analysis
* **Exact Cost Impact:** Upgrading from `n1-standard-2` ($0.1141/hr or ~฿3.94/hr) to `n1-standard-4` ($0.2282/hr or ~฿7.87/hr) doubles compute expenditure (+100%).
* **Performance Gain:** Under 10 VUs, throughput improved by **+21.9%** (13.95 -> 17.01 RPS). Under 50 VUs, p95 latency decreased by **26.9%** (4,992.87 ms -> 3,650.38 ms).
* **Diminishing Returns:** Because Uvicorn runs as a single process (`--workers 1`), additional CPU cores cannot be fully saturated by a single Python thread. Doubling the machine tier provided diminishing returns (~25–27% latency improvement for 100% higher cost) until multi-worker process configurations (`--workers 4`) or horizontal endpoint autoscaling are enabled.
