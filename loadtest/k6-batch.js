// ITCS355 Lab 3 — batch size variable comparison.

import http from 'k6/http';
import { check } from 'k6';
import { Trend } from 'k6/metrics';

const rowLatency = new Trend('per_row_latency_ms');
const batchLatency = new Trend('batch_call_latency_ms');

export const options = {
  vus: Number(__ENV.VUS || 10),
  duration: __ENV.DURATION || '30s',
};

const row = {
  temp_c: 78.4,
  vibration_mm_s: 3.1,
  pressure_kpa: 315.2,
  hours_since_service: 4200,
  load_pct: 68.0,
  ambient_humidity: 55.0,
};

const rows100 = new Array(100).fill(row);
const mode = __ENV.MODE || 'single';

const headers = { 'Content-Type': 'application/json' };
if (__ENV.TOKEN) {
  headers['Authorization'] = `Bearer ${__ENV.TOKEN}`;
}

export default function () {
  const base = __ENV.BASE; // Vertex AI endpoint base URL

  if (mode === 'batch') {
    const res = http.post(`${base}:rawPredict`, JSON.stringify({ rows: rows100 }), { headers });
    batchLatency.add(res.timings.duration);
    check(res, {
      'batch status 200': (r) => r.status === 200,
      'probabilities array present': (r) => r.status === 200 && Array.isArray(r.json('probabilities')),
    });
  } else {
    for (let i = 0; i < 100; i++) {
      const res = http.post(`${base}:rawPredict`, JSON.stringify(row), { headers });
      rowLatency.add(res.timings.duration);
      check(res, { 'single status 200': (r) => r.status === 200 });
    }
  }
}
