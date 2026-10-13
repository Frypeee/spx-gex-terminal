"""TPO-профіль RTH-сесії: POC, Value Area (68%), VAH, VAL. Алгоритм із T·09 методички."""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
import pandas as pd


def tpo_counts(rth: pd.DataFrame, bin_size: float) -> pd.Series:
    """Кількість TPO на кожному ціновому рівні. Період = 30 хв від 09:30 ET (A, B, C ...).

    Очікує колонки High, Low та tod (хвилини від півночі ET) для 5m-свічок RTH.
    """
    if rth.empty:
        return pd.Series(dtype=float)
    block = (rth["tod"] - 570) // 30
    counts: dict[float, int] = defaultdict(int)
    for _, g in rth.groupby(block):
        lo, hi = float(g["Low"].min()), float(g["High"].max())
        start = math.floor(lo / bin_size) * bin_size
        for p in np.arange(start, hi + bin_size * 0.5, bin_size):
            counts[round(float(p), 6)] += 1
    return pd.Series(counts).sort_index()


def value_area(counts: pd.Series, pct: float = 0.68):
    """(POC, VAH, VAL). Від POC розширюємося вгору/вниз, додаючи сусідній рівень з більшою кількістю TPO."""
    if counts.empty:
        return None, None, None
    prices = counts.index.to_numpy(float)
    vals = counts.to_numpy(float)
    mid = (prices[0] + prices[-1]) / 2
    cand = np.flatnonzero(vals == vals.max())
    i_poc = int(cand[np.argmin(np.abs(prices[cand] - mid))])
    lo = hi = i_poc
    total, acc = vals.sum(), vals[i_poc]
    while acc < pct * total and (lo > 0 or hi < len(vals) - 1):
        up = vals[hi + 1] if hi < len(vals) - 1 else -1
        dn = vals[lo - 1] if lo > 0 else -1
        if up >= dn:
            hi += 1; acc += vals[hi]
        else:
            lo -= 1; acc += vals[lo]
    return float(prices[i_poc]), float(prices[hi]), float(prices[lo])
