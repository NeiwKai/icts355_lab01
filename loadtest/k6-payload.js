// ITCS355 Lab 3 — payload size variable.
//
//   k6 run -e TARGET=https://<endpoint>/predict -e PAD_BYTES=0    loadtest/k6-payload.js
//   k6 run -e TARGET=https://<endpoint>/predict -e PAD_BYTES=1000 loadtest/k6-payload.js
//   k6 run -e TARGET=https://<endpoint>/predict -e PAD_BYTES=10000 loadtest/k6-payload.js
//   k6 run -e TARGET=https://<endpoint>/predict -e PAD_BYTES=100000 loadtest/k6-payload.js
//
// PAD_BYTES adds an inert string field to the request body to grow it without
// changing the real feature values, so any latency change is attributable to
// serialization/transport, not model compute. Sweep PAD_BYTES and plot latency
// vs body size; the point where the line stops being flat is where
// serialization starts to dominate. Note: your server must accept and ignore
// an unknown "_pad" field — confirm it doesn't 422 before trusting these numbers.

import http from 'k6/http';
import { check } from 'k6';
import { Trend } from 'k6/metrics';

const latency = new Trend('predict_latency_ms');
const padBytes = Number(__ENV.PAD_BYTES || 0);

export const options = {
  vus: Number(__ENV.VUS || 10),
  duration: __ENV.DURATION || '30s',
};

function buildPayload(pad) {
  return JSON.stringify({
    temp_c: 78.4,
    vibration_mm_s: 3.1,
    pressure_kpa: 315.2,
    hours_since_service: 4200,
    load_pct: 68.0,
    ambient_humidity: 55.0,
    _pad: pad > 0 ? 'x'.repeat(pad) : undefined,
  });
}

const payload = buildPayload(padBytes);

const headers = { 'Content-Type': 'application/json' };
if (__ENV.TOKEN) {
  headers['Authorization'] = `Bearer ${__ENV.TOKEN}`;
}

export default function () {
  const res = http.post(__ENV.TARGET, payload, { headers });
  latency.add(res.timings.duration);
  check(res, { 'status is 200': (r) => r.status === 200 });
}
