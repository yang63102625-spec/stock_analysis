# -*- coding: utf-8 -*-
"""DataFrame validators for fetcher outputs.

Implements rule §7 from ``code-quality.mdc``:

1. Non-empty check (``df is not None and not df.empty``).
2. Required columns are present.
3. Numeric / datetime columns have the expected dtypes (best-effort
   coercion when the upstream source returns strings).
4. Financial integrity checks: reject negative prices / volumes, zero
   prices during a trading session, and ``> ±20%`` single-day moves
   (flagged but not rejected — A-shares have ±10% / ±20% limit-up
   bands, so we only ``logger.warning`` rather than raise).

The module-level :func:`validate_ohlcv_dataframe` is the canonical entry
point used by every historical-data fetcher; smaller helpers
(:func:`validate_required_columns`, :func:`coerce_numeric_columns`)
are exposed for fetchers that produce non-OHLCV frames (fundamentals,
moneyflow, etc.).
"""
from __future__ import annotations

import logging
from typing import Iterable, Mapping, Optional

import pandas as pd

from src.exceptions import ValidationError

logger = logging.getLogger(__name__)


# Columns produced by ``BaseFetcher`` historical-data outputs (mirrors
# ``data_provider.base.codes.STANDARD_COLUMNS``). Kept as a local
# constant so callers don't need a second import.
OHLCV_REQUIRED_COLUMNS: tuple[str, ...] = (
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
)

OHLCV_NUMERIC_COLUMNS: tuple[str, ...] = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "pct_chg",
)


def validate_required_columns(
    df: pd.DataFrame,
    required: Iterable[str],
    *,
    context: str = "DataFrame",
) -> None:
    """Raise :class:`ValidationError` if any required column is missing.

    ``context`` is included in the error message to make logs actionable
    (e.g. ``"tushare historical (600000)"``).
    """
    required_list = list(required)
    missing = [c for c in required_list if c not in df.columns]
    if missing:
        raise ValidationError(
            f"{context}: missing required columns {missing}; "
            f"got {list(df.columns)}"
        )


def coerce_numeric_columns(
    df: pd.DataFrame,
    columns: Iterable[str],
    *,
    inplace: bool = False,
) -> pd.DataFrame:
    """Coerce *columns* in *df* to numeric dtype (NaN on failure).

    Returns the (possibly mutated) frame. When ``inplace=False`` the
    caller-provided frame is left untouched and a copy is returned.
    """
    target = df if inplace else df.copy()
    for col in columns:
        if col in target.columns and not pd.api.types.is_numeric_dtype(target[col]):
            target[col] = pd.to_numeric(target[col], errors="coerce")
    return target


def _check_non_negative(
    df: pd.DataFrame,
    columns: Iterable[str],
    *,
    context: str,
) -> None:
    """Raise if any of *columns* contains negative values (NaN allowed)."""
    for col in columns:
        if col not in df.columns:
            continue
        series = df[col]
        if not pd.api.types.is_numeric_dtype(series):
            continue
        negative_mask = series.lt(0).fillna(False)
        if negative_mask.any():
            sample = df.loc[negative_mask, col].head(3).tolist()
            raise ValidationError(
                f"{context}: column '{col}' contains negative values "
                f"(sample: {sample})"
            )


def _flag_zero_prices(
    df: pd.DataFrame,
    *,
    context: str,
    is_trading_session: bool,
) -> None:
    """Warn when ``close == 0`` while the market is open.

    A zero close is almost always a bad upstream payload (suspended
    stocks usually emit the prior close). We only flag — fetchers may
    legitimately return historical bars where pre-IPO rows have zero
    prices.
    """
    if "close" not in df.columns:
        return
    if not pd.api.types.is_numeric_dtype(df["close"]):
        return
    zero_mask = df["close"].eq(0).fillna(False)
    if zero_mask.any():
        level = logger.warning if is_trading_session else logger.debug
        sample = df.index[zero_mask].tolist()[:3]
        level(
            "%s: close == 0 detected in %d row(s) (sample index: %s)",
            context,
            int(zero_mask.sum()),
            sample,
        )


def _flag_extreme_moves(
    df: pd.DataFrame,
    *,
    context: str,
    threshold: float = 0.20,
) -> None:
    """Warn when ``pct_chg`` exceeds ±*threshold* (default ±20%).

    A-shares have ±10% / ±20% (ChiNext / STAR) daily limits, so a single
    bar above 20% almost certainly indicates a bad price tick or a
    forward/backward-adjustment artefact. We don't raise — historical
    data with ex-dividend gaps is allowed to be loud.
    """
    if "pct_chg" not in df.columns:
        return
    if not pd.api.types.is_numeric_dtype(df["pct_chg"]):
        return
    pct = df["pct_chg"].abs()
    # ``pct_chg`` is conventionally in percent (i.e. 5.0 == 5%) in this
    # project. Treat values > 100 as obviously percent-scaled.
    extreme_mask = pct.gt(threshold * 100).fillna(False)
    if extreme_mask.any():
        sample = df.loc[extreme_mask, "pct_chg"].head(3).tolist()
        logger.warning(
            "%s: |pct_chg| > %.0f%% in %d row(s) (sample: %s)",
            context,
            threshold * 100,
            int(extreme_mask.sum()),
            sample,
        )


def validate_ohlcv_dataframe(
    df: Optional[pd.DataFrame],
    *,
    context: str,
    required_columns: Iterable[str] = OHLCV_REQUIRED_COLUMNS,
    numeric_columns: Iterable[str] = OHLCV_NUMERIC_COLUMNS,
    coerce: bool = True,
    is_trading_session: bool = False,
) -> pd.DataFrame:
    """Validate (and optionally normalise) a fetcher OHLCV DataFrame.

    Parameters
    ----------
    df:
        The frame returned by a fetcher. ``None`` / empty frames cause
        :class:`ValidationError`.
    context:
        Free-form label included in error/warning messages — typically
        ``f"{source} historical ({stock_code})"``.
    required_columns / numeric_columns:
        Override defaults for non-standard fetchers (e.g. baostock has
        no ``amount`` column).
    coerce:
        When ``True`` (default), non-numeric numeric-typed columns are
        coerced via :func:`pd.to_numeric` before integrity checks.
    is_trading_session:
        Used to escalate ``close == 0`` flags from DEBUG to WARNING.

    Returns
    -------
    pd.DataFrame
        The validated (and possibly coerced) frame. Caller should treat
        the return value as the canonical reference.

    Raises
    ------
    ValidationError
        On empty frames, missing columns or negative prices/volumes.
    """
    if df is None or df.empty:
        raise ValidationError(f"{context}: empty DataFrame")

    validate_required_columns(df, required_columns, context=context)

    if coerce:
        df = coerce_numeric_columns(df, numeric_columns)

    _check_non_negative(
        df,
        columns=("open", "high", "low", "close", "volume", "amount"),
        context=context,
    )
    _flag_zero_prices(df, context=context, is_trading_session=is_trading_session)
    _flag_extreme_moves(df, context=context)

    return df


def validate_dataframe(
    df: Optional[pd.DataFrame],
    *,
    context: str,
    required_columns: Iterable[str],
    dtype_map: Optional[Mapping[str, str]] = None,
) -> pd.DataFrame:
    """Generic non-OHLCV validator for fundamentals / moneyflow frames.

    ``dtype_map`` maps column names to one of ``"numeric"`` or
    ``"datetime"``; columns not listed are left as-is.
    """
    if df is None or df.empty:
        raise ValidationError(f"{context}: empty DataFrame")

    validate_required_columns(df, required_columns, context=context)

    if not dtype_map:
        return df

    out = df.copy()
    for col, kind in dtype_map.items():
        if col not in out.columns:
            continue
        if kind == "numeric" and not pd.api.types.is_numeric_dtype(out[col]):
            out[col] = pd.to_numeric(out[col], errors="coerce")
        elif kind == "datetime" and not pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = pd.to_datetime(out[col], errors="coerce")
    return out


__all__ = [
    "OHLCV_NUMERIC_COLUMNS",
    "OHLCV_REQUIRED_COLUMNS",
    "coerce_numeric_columns",
    "validate_dataframe",
    "validate_ohlcv_dataframe",
    "validate_required_columns",
]
