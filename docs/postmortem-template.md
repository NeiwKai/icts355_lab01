# Post-mortem — Injected Sensor Temperature Drift (`temp_c`)

**What fired:**
Scheduled PSI drift alert on `temp_c` (PSI: `3.3005` vs threshold: `0.25`, KS: `0.6788`) fired at 2026-10-06 14:30:00 UTC.

**True cause:**
Broken upstream data pipeline / hardware sensor re-calibration bug (+20°C raw value offset introduced by firmware update).

**Retrain, roll back, or no action — and why:**
NO ACTION / DO NOT RETRAIN. Retraining on corrupted sensor data destroys a working baseline model; instead, fix the upstream data producer pipeline, roll back the firmware patch, and backfill clean telemetry data.

**What this would have cost if unnoticed for a week:**
Approximately $42,000 in unnecessary plant maintenance shutdowns and false emergency machinery flags caused by artificial probability spikes (>0.95) across healthy equipment.

**How to prevent or detect it faster:**
Add physical range data contract assertions (`temp_c <= 120°C`) at the ingestion layer (`tests/test_data.py`) and increase scheduled drift check frequency from 6 hours to 15 minutes.
