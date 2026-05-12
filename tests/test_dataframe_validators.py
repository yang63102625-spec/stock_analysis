# -*- coding: utf-8 -*-
"""Unit tests for ``data_provider.validators``."""
from __future__ import annotations

import logging
import unittest

import pandas as pd

from data_provider.validators import (
    OHLCV_REQUIRED_COLUMNS,
    coerce_numeric_columns,
    validate_dataframe,
    validate_ohlcv_dataframe,
    validate_required_columns,
)
from src.exceptions import ValidationError


def _ohlcv(rows: int = 3) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "code": ["600000"] * rows,
            "date": pd.date_range("2024-01-02", periods=rows),
            "open": [10.0, 10.5, 10.2],
            "high": [10.6, 10.9, 10.4][:rows],
            "low": [9.8, 10.1, 10.0][:rows],
            "close": [10.4, 10.6, 10.1][:rows],
            "volume": [1_000_000, 1_200_000, 900_000][:rows],
            "amount": [10_400_000, 12_720_000, 9_090_000][:rows],
            "pct_chg": [1.5, 1.9, -4.7][:rows],
        }
    )


class ValidateRequiredColumnsTest(unittest.TestCase):
    def test_passes_when_all_columns_present(self) -> None:
        validate_required_columns(_ohlcv(), OHLCV_REQUIRED_COLUMNS, context="t")

    def test_raises_with_actionable_message(self) -> None:
        df = _ohlcv().drop(columns=["close"])
        with self.assertRaises(ValidationError) as cm:
            validate_required_columns(df, OHLCV_REQUIRED_COLUMNS, context="t")
        self.assertIn("close", str(cm.exception))


class CoerceNumericColumnsTest(unittest.TestCase):
    def test_coerces_string_columns_to_float(self) -> None:
        df = _ohlcv()
        df["close"] = df["close"].astype(str)
        out = coerce_numeric_columns(df, ["close"])
        self.assertTrue(pd.api.types.is_numeric_dtype(out["close"]))
        self.assertFalse(pd.api.types.is_numeric_dtype(df["close"]))  # not in-place


class ValidateOhlcvDataFrameTest(unittest.TestCase):
    def test_returns_df_for_valid_input(self) -> None:
        out = validate_ohlcv_dataframe(_ohlcv(), context="unit")
        self.assertEqual(len(out), 3)

    def test_raises_for_empty(self) -> None:
        with self.assertRaises(ValidationError):
            validate_ohlcv_dataframe(pd.DataFrame(), context="unit")

    def test_raises_for_none(self) -> None:
        with self.assertRaises(ValidationError):
            validate_ohlcv_dataframe(None, context="unit")

    def test_raises_for_negative_volume(self) -> None:
        df = _ohlcv()
        df.loc[0, "volume"] = -100
        with self.assertRaises(ValidationError) as cm:
            validate_ohlcv_dataframe(df, context="unit")
        self.assertIn("volume", str(cm.exception))

    def test_raises_for_negative_close(self) -> None:
        df = _ohlcv()
        df.loc[1, "close"] = -1.0
        with self.assertRaises(ValidationError):
            validate_ohlcv_dataframe(df, context="unit")

    def test_warns_for_zero_close_during_session(self) -> None:
        df = _ohlcv()
        df.loc[0, "close"] = 0.0
        with self.assertLogs("data_provider.validators", level="WARNING") as cm:
            validate_ohlcv_dataframe(
                df, context="unit", is_trading_session=True
            )
        self.assertTrue(any("close == 0" in m for m in cm.output))

    def test_warns_for_extreme_pct_chg(self) -> None:
        df = _ohlcv()
        df.loc[0, "pct_chg"] = 35.0
        with self.assertLogs("data_provider.validators", level="WARNING") as cm:
            validate_ohlcv_dataframe(df, context="unit")
        self.assertTrue(any("pct_chg" in m for m in cm.output))


class ValidateDataFrameTest(unittest.TestCase):
    def test_dtype_map_coerces(self) -> None:
        df = pd.DataFrame({"ts": ["2024-01-02", "2024-01-03"], "pe": ["12.5", "13"]})
        out = validate_dataframe(
            df,
            context="fund",
            required_columns=["ts", "pe"],
            dtype_map={"ts": "datetime", "pe": "numeric"},
        )
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(out["ts"]))
        self.assertTrue(pd.api.types.is_numeric_dtype(out["pe"]))


if __name__ == "__main__":
    unittest.main()
