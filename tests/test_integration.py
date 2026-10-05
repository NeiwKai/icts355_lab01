"""Integration test — validates container endpoint response and metadata."""
import os
import requests
import pytest

ENDPOINT_URL = os.getenv("TEST_ENDPOINT_URL", "http://localhost:8080")


@pytest.mark.integration
def test_container_predict_shape_and_version():
    """Hits /predict and asserts response schema and version reporting."""
    payload = {
        "instances": [{
            "temp_c": 82.478,
            "vibration_mm_s": 4.888,
            "pressure_kpa": 308.557,
            "hours_since_service": 1508.063,
            "load_pct": 95.792,
            "ambient_humidity": 63.407,
        }]
    }

    try:
        response = requests.post(f"{ENDPOINT_URL}/predict", json=payload, timeout=5)
    except requests.exceptions.ConnectionError:
        pytest.skip(f"Endpoint not running at {ENDPOINT_URL}; run container locally first")

    assert response.status_code == 200, f"HTTP {response.status_code}: {response.text}"
    data = response.json()

    assert "predictions" in data, "Response missing 'predictions' array"
    assert len(data["predictions"]) == len(payload["instances"])
    assert "version" in data or "model_version" in data, "Response missing version metadata"
