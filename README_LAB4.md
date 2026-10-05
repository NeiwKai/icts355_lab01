### Task 1

## Production Incidents Prevented by Data Contract Tests

1. **Schema Contract (`test_schema_contract`):**
   * **Incident Prevented:** Upstream telemetry schema mutations (e.g., sensor pipeline renaming `vibration_mm_s` to `vib_rate` or dropping `ambient_humidity`). Catches missing features before they hit the container and trigger HTTP 422 validation errors or unhandled NaNs during serving.

2. **Range & Null Rate Contract (`test_range_and_null_rate_contract`):**
   * **Incident Prevented:** Upstream sensor hardware failures or stream corruptions (e.g., pressure sensor returning negative values or stream outages causing a 10%+ null rate spike). Prevents silent garbage-in, garbage-out predictions in production.

3. **Data Leakage Contract (`test_no_data_leakage_contract`):**
   * **Incident Prevented:** Inadvertently passing post-failure indicators or maintenance log timestamps (`failure_timestamp`, `repair_action`) into online serving payloads. Ensures offline model evaluation accurately mirrors live production conditions.
