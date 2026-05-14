"""Expected Threat (xT) calculation.

Divides the StatsBomb pitch (120×80) into a 16×12 grid and assigns each cell
a pre-computed xT value derived from the Karun Singh xT model.  For each pass
or carry in the DataFrame the module calculates the *xT gain* (destination
value minus origin value).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 16 × 12 xT grid (columns × rows) — Karun Singh public values, row-major
# Rows run from goal-line (y=0) to goal-line (y=80), columns from own half.
# ---------------------------------------------------------------------------
_XT_GRID_RAW = np.array([
    [0.000, 0.000, 0.001, 0.001, 0.001, 0.001, 0.002, 0.002, 0.002, 0.003, 0.004, 0.005, 0.007, 0.010, 0.019, 0.040],
    [0.000, 0.001, 0.001, 0.001, 0.001, 0.002, 0.002, 0.003, 0.003, 0.004, 0.006, 0.008, 0.012, 0.018, 0.031, 0.068],
    [0.000, 0.001, 0.001, 0.001, 0.002, 0.002, 0.003, 0.004, 0.005, 0.007, 0.010, 0.013, 0.020, 0.030, 0.054, 0.120],
    [0.001, 0.001, 0.001, 0.002, 0.002, 0.003, 0.004, 0.005, 0.007, 0.010, 0.014, 0.020, 0.030, 0.046, 0.080, 0.176],
    [0.001, 0.001, 0.002, 0.002, 0.003, 0.004, 0.005, 0.007, 0.010, 0.013, 0.019, 0.026, 0.040, 0.060, 0.103, 0.210],
    [0.001, 0.001, 0.002, 0.002, 0.003, 0.004, 0.005, 0.007, 0.010, 0.013, 0.019, 0.026, 0.040, 0.060, 0.103, 0.210],
    [0.001, 0.001, 0.001, 0.002, 0.002, 0.003, 0.004, 0.005, 0.007, 0.010, 0.014, 0.020, 0.030, 0.046, 0.080, 0.176],
    [0.000, 0.001, 0.001, 0.001, 0.002, 0.002, 0.003, 0.004, 0.005, 0.007, 0.010, 0.013, 0.020, 0.030, 0.054, 0.120],
    [0.000, 0.001, 0.001, 0.001, 0.001, 0.002, 0.002, 0.003, 0.003, 0.004, 0.006, 0.008, 0.012, 0.018, 0.031, 0.068],
    [0.000, 0.000, 0.001, 0.001, 0.001, 0.001, 0.002, 0.002, 0.002, 0.003, 0.004, 0.005, 0.007, 0.010, 0.019, 0.040],
    [0.000, 0.000, 0.000, 0.001, 0.001, 0.001, 0.001, 0.001, 0.002, 0.002, 0.003, 0.004, 0.005, 0.007, 0.013, 0.025],
    [0.000, 0.000, 0.000, 0.000, 0.001, 0.001, 0.001, 0.001, 0.001, 0.001, 0.002, 0.003, 0.004, 0.005, 0.009, 0.018],
], dtype=float)

# Grid dimensions
_N_COLS = 16
_N_ROWS = 12
_PITCH_LENGTH = 120.0
_PITCH_WIDTH = 80.0


def _coords_to_cell(x: float, y: float) -> tuple[int, int]:
    """Convert pitch coordinates to (row, col) grid indices."""
    col = int(np.clip(x / _PITCH_LENGTH * _N_COLS, 0, _N_COLS - 1))
    row = int(np.clip(y / _PITCH_WIDTH * _N_ROWS, 0, _N_ROWS - 1))
    return row, col


def xT_value(x: float, y: float) -> float:
    """Return the xT value for a location on the pitch."""
    row, col = _coords_to_cell(x, y)
    return float(_XT_GRID_RAW[row, col])


def calculate_xT(df: pd.DataFrame) -> pd.DataFrame:
    """Add *xT_start*, *xT_end*, and *xT_gain* columns to *df*.

    Works on Pass and Carry events.  All other event types get NaN.
    """
    df = df.copy()

    mask_pass = df["type"] == "Pass"
    mask_carry = df["type"] == "Carry"
    mask = mask_pass | mask_carry

    # Vectorised xT start (origin location)
    def _xT_vec(x_series: pd.Series, y_series: pd.Series) -> pd.Series:
        vals = np.full(len(x_series), np.nan)
        valid = x_series.notna() & y_series.notna()
        if valid.any():
            xs = x_series[valid].to_numpy()
            ys = y_series[valid].to_numpy()
            cols = np.clip((xs / _PITCH_LENGTH * _N_COLS).astype(int), 0, _N_COLS - 1)
            rows = np.clip((ys / _PITCH_WIDTH * _N_ROWS).astype(int), 0, _N_ROWS - 1)
            vals[valid.to_numpy()] = _XT_GRID_RAW[rows, cols]
        return pd.Series(vals, index=x_series.index)

    df["xT_start"] = np.nan
    df["xT_end"] = np.nan

    df.loc[mask, "xT_start"] = _xT_vec(df.loc[mask, "location_x"], df.loc[mask, "location_y"])

    # End location differs by event type
    end_x = df["location_x"].copy()
    end_y = df["location_y"].copy()

    if "pass_end_x" in df.columns:
        end_x.loc[mask_pass] = df.loc[mask_pass, "pass_end_x"]
        end_y.loc[mask_pass] = df.loc[mask_pass, "pass_end_y"]
    if "carry_end_x" in df.columns:
        end_x.loc[mask_carry] = df.loc[mask_carry, "carry_end_x"]
        end_y.loc[mask_carry] = df.loc[mask_carry, "carry_end_y"]

    df.loc[mask, "xT_end"] = _xT_vec(end_x.loc[mask], end_y.loc[mask])

    df["xT_gain"] = df["xT_end"] - df["xT_start"]
    # Negative xT gain (backward passes) is valid information — keep as-is.

    return df
