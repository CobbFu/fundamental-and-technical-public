"""Shared DataFrame extraction helpers used by Analyst modules."""

import pandas as pd


def extract_value(
    df: pd.DataFrame | None, row_label: str, col: object = None
) -> float | None:
    """Safely extract a float from a DataFrame cell.

    Args:
        df: DataFrame to read from (may be None or empty).
        row_label: Row index label (financial line item).
        col: Column to read. If None, uses last column (latest period).

    Returns:
        float value or None if extraction fails.
    """
    if df is None or df.empty:
        return None
    if row_label not in df.index:
        return None
    if col is None:
        if len(df.columns) == 0:
            return None
        col = df.columns[-1]
    if col not in df.columns:
        return None
    raw = df.loc[row_label, col]  # type: ignore[index]
    if pd.isna(raw):
        return None
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def extract_value_multi(
    df: pd.DataFrame | None, labels: list[str], col: object = None
) -> float | None:
    """Try multiple row labels, return the first that resolves to a float."""
    for label in labels:
        val = extract_value(df, label, col)
        if val is not None:
            return val
    return None


def extract_series(
    df: pd.DataFrame | None, row_label: str
) -> pd.Series | None:
    """Extract an entire row as a numeric Series, dropping NaN values."""
    if df is None or df.empty:
        return None
    if row_label not in df.index:
        return None
    row = df.loc[row_label]
    if isinstance(row, pd.DataFrame):
        series = row.iloc[0]
    else:
        series = row
    series = pd.to_numeric(series, errors="coerce").dropna()
    if series.empty:
        return None
    return series


def extract_series_multi(
    df: pd.DataFrame | None, labels: list[str]
) -> pd.Series | None:
    """Try multiple row labels, return the first that resolves to a Series."""
    for label in labels:
        s = extract_series(df, label)
        if s is not None:
            return s
    return None


def tagged_float(tagged: object) -> float | None:
    """Safely get float value from a TaggedValue-like object."""
    if tagged is None:
        return None
    val = getattr(tagged, "value", None)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
