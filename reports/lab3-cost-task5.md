# Task 5 — Cost per Thousand Predictions Report

## 1. Methodology & Step-by-Step Calculation

### Inputs & Parameters
* **GCP Region:** `asia-south1` (Mumbai)
* **Machine Type:** `n1-standard-2` (2 vCPUs, 7.5 GB RAM)
* **Instance Hourly Cost ($C_{hourly}$):** **$0.1141 / hour**
* **Measured Throughput ($T$):** **11.85 requests/second** (derived from the 10 VU baseline load test result)
* **Assumed Utilization ($U$):** **80%**

> **Explicit Utilization Assumption:** The utilization rate is set to **80% ($U = 0.80$)**. This reflects realistic production conditions where an endpoint experiences natural traffic dips, idle off-peak hours, and headroom buffers. This parameter is the most fragile part of the estimation—at 100% steady load, cost per thousand drops to **$0.00267**, whereas at 10% average utilization during low-traffic periods, cost per thousand spikes to **$0.02674**.

---

### Step-by-Step Calculation Method

1. **Calculate Effective Hourly Capacity at Assumed Utilization:**
   $$\text{Effective Throughput (req/hr)} = T \times 3,600 \text{ sec/hr} \times U$$
   $$\text{Effective Throughput} = 11.85 \times 3,600 \times 0.80 = 34,128 \text{ predictions/hour}$$

2. **Calculate Cost per Single Prediction:**
   $$\text{Cost per Request} = \frac{C_{hourly}}{\text{Effective Throughput}} = \frac{\$0.1141}{34,128} = \$0.0000033432 \text{ per request}$$

3. **Calculate Cost per 1,000 Predictions (CPM):**
   $$\text{Cost per 1,000 Predictions} = \text{Cost per Request} \times 1,000 = \mathbf{\$0.00334} \text{ (or } \approx \mathbf{\text{฿}0.115 \text{ per 1,000 predictions)}}$$

---

## 2. Batch Inference Breakeven Analysis

1. Batch inference becomes cheaper than keeping a warm endpoint when daily request volume drops below **~34,000 to 50,000 predictions per day**, where the fixed cost of running a 24/7 endpoint ($2.738/day) exceeds the transient compute cost of spinning up an on-demand batch job.
2. However, if predictions require real-time response times (SLA < 1 second), keeping the online endpoint warm remains necessary regardless of low volume due to the 3–5 minute startup latency of batch jobs.
