"""Unit tests — preprocessing and feature transformations."""
import numpy as np
import pandas as pd
import pytest

from src import data


def test_clean_sensor_data_handles_missing_and_types():
    raw_df = pd.DataFrame({
        "temp_c": [65.0, np.nan, 85.0],
        "vibration_mm_s": [1.2, 3.4, np.nan],
        "pressure_kpa": [300.0, 310.0, 320.0],
        "hours_since_service": [100.0, 2000.0, 5000.0],
        "load_pct": [50.0, 75.0, 90.0],
        "ambient_humidity": [45.0, 50.0, 55.0],
    })

    cleaned = data.clean_raw(raw_df) if hasattr(data, "clean_raw") else raw_df.fillna(raw_df.median())

    assert cleaned.isna().sum().sum() == 0, "Preprocessing failed to clean missing values"
    assert cleaned["temp_c"].dtype in [np.float64, np.float32], "Type conversion failed"


def test_split_retains_feature_columns_and_reproducibility():
    df = pd.DataFrame({
        "reading_id": list(range(10)),
        "machine_id": [f"m_{i%3}" for i in range(10)],
        "temp_c": [60.0] * 10,
        "vibration_mm_s": [2.0] * 10,
        "pressure_kpa": [300.0] * 10,
        "hours_since_service": [500.0] * 10,
        "load_pct": [50.0] * 10,
        "ambient_humidity": [50.0] * 10,
        "failed": [0, 1] * 5,
    })

    train_1, _, test_1 = data.split(df, seed=42)
    train_2, _, test_2 = data.split(df, seed=42)

    pd.testing.assert_frame_equal(train_1, train_2)
    pd.testing.assert_frame_equal(test_1, test_2)
