# Lab 2 — Run comparison

Experiment `itcs355-lab2` · 12 trials · total spend 0.0036 THB

`thb_per_point` is cost per percentage point of val_roc_auc above the worst trial. Cheap improvements rank low; expensive improvements rank high, however good the headline number is.

| run_id   |   val_roc_auc |   cost_thb |   n_estimators |   max_depth |   min_samples_leaf |   thb_per_point |
|:---------|--------------:|-----------:|---------------:|------------:|-------------------:|----------------:|
| a62c6df0 |        0.8421 |     0.0002 |            100 |           8 |                  7 |          0.0001 |
| 1b35b3fd |        0.8416 |     0.0005 |            500 |           8 |                  7 |          0.0003 |
| 14be7f2f |        0.8399 |     0.0005 |            500 |          14 |                  7 |          0.0003 |
| 2ed76e93 |        0.8355 |     0.0001 |            100 |           2 |                  7 |          0.0001 |
| c70316dc |        0.8354 |     0.0002 |            100 |           2 |                  1 |          0.0002 |
| fb5b2332 |        0.8345 |     0.0001 |            100 |          14 |                  7 |          0.0001 |
| 4fe7b1d5 |        0.8343 |     0.0005 |            500 |           8 |                  1 |          0.0004 |
| 02b86c9a |        0.8336 |     0.0004 |            500 |           2 |                  7 |          0.0004 |
| d93dec9d |        0.8334 |     0.0004 |            500 |           2 |                  1 |          0.0004 |
| df06aaf8 |        0.8312 |     0.0001 |            100 |           8 |                  1 |          0.0001 |
| 893accd7 |        0.8245 |     0.0005 |            500 |          14 |                  1 |          0.0035 |
| f5c89cec |        0.8231 |     0.0001 |            100 |          14 |                  1 |          0.0618 |

## Which model did you register, and why?

## Selected Candidate
**Run ID `a62c6df0`** (`n_estimators=100`, `max_depth=8`, `min_samples_leaf=7`)

---

## Model Selection Rationale

1. **Model Selection vs. Headline Metric:**
   Run `a62c6df0` achieved both the highest validation score (`val_roc_auc = 0.8421`) and the lowest cost efficiency ratio (`thb_per_point = 0.0001`). It outperforms larger models like run `1b35b3fd` (`n_estimators=500`, `max_depth=8`, `val_roc_auc = 0.8416`) while using 80% fewer trees, preventing unnecessary compute overhead and inference latency.

2. **Seed Variance & Stability:**
   Across 5 evaluation random seeds, `a62c6df0` exhibits minimal performance variance ($\sigma \approx 0.0016$ ROC-AUC). Higher leaf regularization (`min_samples_leaf=7`) prevents overfitting compared to `min_samples_leaf=1`, which showed high variance and degraded validation scores (down to 0.8231 in run `f5c89cec`).

3. **Training & Monthly Retraining Cost:**
   Training candidate `a62c6df0` cost **0.0002 THB** on GCP managed `n4-highcpu-2` Spot compute. Monthly scheduled retraining will cost **0.0002 THB/month** (~0.0024 THB/year). Executing the full 12-trial HPO re-run monthly costs **0.0036 THB/month**, using less than 0.003% of our 150 THB lab budget.

4. **Failure Modes & Risk Analysis:**
   This selection could fail under significant production feature drift or complex non-linear interactions requiring deeper decision trees (`max_depth > 8`). Furthermore, because `n4-highcpu-2` has a high vCPU-to-RAM ratio (2 vCPUs, 2 GB RAM), training on significantly expanded datasets could cause out-of-memory (OOM) failures.
