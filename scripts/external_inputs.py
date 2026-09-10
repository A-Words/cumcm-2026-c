"""Validate a genuinely subsequent data file without changing the frozen model.

The file supplies hourly release values, never interpolated forecasts or their
observation anchors. Those derived arrays are rebuilt from information available
at each release. Temporal placement alone does not establish that a dataset was
unseen during model development; that provenance must be documented separately.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

import numpy as np

from model import DT, ForecastCache, point_forecast

REQUIRED_FIELDS = ("dates", "load", "pv", "dynamic_price", "forecast_hourly")


def _dates(values, label: str) -> np.ndarray:
    original = np.asarray(values)
    if original.ndim != 1 or not len(original):
        raise ValueError(f"{label}: dates must be a nonempty one-dimensional array")
    if original.dtype.kind == "M":
        result = original.astype("datetime64[D]")
        if np.any(original != result):
            raise ValueError(f"{label}: dates cannot contain a time of day")
    elif original.dtype.kind in "US":
        strings = original.astype(str)
        if any(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None for value in strings):
            raise ValueError(f"{label}: dates must use YYYY-MM-DD")
        try:
            result = strings.astype("datetime64[D]")
        except ValueError as error:
            raise ValueError(f"{label}: invalid calendar date") from error
    else:
        raise ValueError(f"{label}: dates must be ISO strings or datetime64 values")
    if np.any(np.isnat(result)):
        raise ValueError(f"{label}: dates cannot contain NaT")
    if np.any(np.diff(result) != np.timedelta64(1, "D")):
        raise ValueError(f"{label}: dates must be consecutive daily observations")
    return result


def _numbers(values, shape: tuple, label: str, positive=False) -> np.ndarray:
    try:
        result = np.asarray(values, dtype=float)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label}: values must be numeric") from error
    if result.shape != shape:
        raise ValueError(f"{label}: expected shape {shape}, received {result.shape}")
    if not np.all(np.isfinite(result)):
        raise ValueError(f"{label}: all values must be finite")
    if np.any(result <= 0 if positive else result < 0):
        qualifier = "positive" if positive else "nonnegative"
        raise ValueError(f"{label}: all values must be {qualifier}")
    return result.copy()


def load_future_data(history: dict, path: str | Path) -> tuple[dict, dict]:
    """Append consecutive external days and rebuild all derived daily arrays.

    Extra keys are ignored and listed in metadata. In particular, a caller
    cannot inject ``forecast``, ``forecast_anchor`` or a new fixed tariff.
    The returned mapping owns its arrays and never mutates the history mapping.
    """
    source = Path(path).resolve()
    history_dates = _dates(history["dates"], "history")
    with np.load(source, allow_pickle=False) as archive:
        missing = sorted(set(REQUIRED_FIELDS) - set(archive.files))
        if missing:
            raise ValueError("future file is missing required fields: " + ", ".join(missing))
        future_dates = _dates(archive["dates"], "future")
        if future_dates[0] != history_dates[-1] + np.timedelta64(1, "D"):
            raise ValueError("future dates must start immediately after the last history date")
        count = len(future_dates)
        future = {"dates": future_dates}
        for key in ("load", "pv", "dynamic_price"):
            future[key] = _numbers(archive[key], (count, 144), key,
                                   positive=key == "dynamic_price")
        future["forecast_hourly"] = _numbers(
            archive["forecast_hourly"], (count, 4, 24), "forecast_hourly")
        ignored = sorted(set(archive.files) - set(REQUIRED_FIELDS))

    merged = {key: np.asarray(value).copy() for key, value in history.items()}
    merged["dates"] = np.concatenate((history_dates, future_dates))
    for key in ("load", "pv", "dynamic_price", "forecast_hourly"):
        tail_shape = (4, 24) if key == "forecast_hourly" else (144,)
        previous = _numbers(history[key], (len(history_dates), *tail_shape),
                            "history " + key, positive=key == "dynamic_price")
        merged[key] = np.concatenate((previous, future[key]), axis=0)
    merged["fixed_price"] = _numbers(history["fixed_price"], (144,),
                                       "history fixed_price", positive=True)

    anchors = np.empty((count, 4), dtype=float)
    anchors[:, 0] = np.concatenate(([merged["pv"][len(history_dates)-1, -1]],
                                    future["pv"][:-1, -1]))
    for issue in range(1, 4):
        anchors[:, issue] = future["pv"][:, issue * 36 - 1]
    knots = np.concatenate((anchors[..., None], future["forecast_hourly"]), axis=2)
    fine = np.empty((count, 4, 145), dtype=float)
    for day in range(count):
        for issue in range(4):
            fine[day, issue] = np.interp(np.arange(145) / 6, np.arange(25),
                                          knots[day, issue])
    derived = {"forecast_anchor": anchors, "forecast": fine[:, :, 1:],
               "forecast_trapezoid": (fine[:, :, :-1] + fine[:, :, 1:]) / 2}
    for key, values in derived.items():
        if key in history:
            merged[key] = np.concatenate((history[key], values), axis=0)
        else:
            raise ValueError(f"history is missing preprocessed field {key}")
    # Preserve coherent optional integration diagnostics across the year boundary.
    for key in ("load", "pv"):
        diagnostic = key + "_trapezoid"
        if diagnostic in history:
            values = merged[key]
            previous = np.concatenate(([values[len(history_dates)-1, -1]],
                                        values[len(history_dates):].reshape(-1)[:-1]))
            trapezoid = (previous.reshape(count, 144) + future[key]) / 2
            merged[diagnostic] = np.concatenate((history[diagnostic], trapezoid), axis=0)
    metadata = dict(source_path=str(source), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                    history_days=len(history_dates), future_days=count,
                    history_last_date=str(history_dates[-1]),
                    future_first_date=str(future_dates[0]), future_last_date=str(future_dates[-1]),
                    required_fields=list(REQUIRED_FIELDS), ignored_fields=ignored,
                    anchors_rebuilt=True, fixed_tariff_source="history")
    return merged, metadata


def build_causal_cache(data: dict, pv_weight: float, dynamic: bool) -> ForecastCache:
    """Use the frozen predictor for any number of consecutive days, including leap years."""
    count = len(data["dates"])
    shape = (count, 4, 144)
    net, price, errors, load, pv = [np.full(shape, np.nan) for _ in range(5)]
    actual = (data["load"] - data["pv"]) * DT
    for day in range(count):
        for issue in range(4):
            start = issue * 36
            prediction, tariff, demand, solar = point_forecast(
                data, day, issue, True, dynamic=dynamic, pv_weight=pv_weight)
            net[day, issue, start:] = prediction
            price[day, issue, start:] = tariff
            load[day, issue, start:] = demand
            pv[day, issue, start:] = solar
            # The frozen risk_forecast helper only reads errors from earlier days.
            errors[day, issue, start:] = actual[day, start:] - prediction
    return ForecastCache(net, price, errors, load, pv)
