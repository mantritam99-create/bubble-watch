"""
risk_model.py — shared scoring config + functions.

This is the single source of truth for the three-layer model. The JS dashboard
mirrors these exact thresholds; if you change one, change the other.

Each signal maps a raw value to a 0–100 sub-score via linear interpolation
between `lo` (benign) and `hi` (extreme). Layer score = weighted mean of its
signals. `base` = the sub-score used in LIVE mode when a value is missing
(qualitative signals that have no machine-readable series). In BACKTEST mode
missing signals are dropped and weights renormalised, so historical scores rest
only on real data.
"""

def score_from(v, lo, hi):
    """Linear 0–100. Works in both directions (set lo=benign, hi=extreme)."""
    if v is None:
        return None
    x = (v - lo) / (hi - lo)
    return round(max(0.0, min(1.0, x)) * 100)


# signal -> config.  layer in {fuel, deter, trig}.
# `series` lets a signal read another metric's value (e.g. hy_break reads hy_oas).
# `manual` = no live series, base only.  `toggle` = event flag set in the UI.
SIGNALS = {
    # ── Layer 1: Fuel (vulnerability) ───────────────────────────────
    "cape":       {"layer": "fuel", "lo": 25, "hi": 45,  "w": 3, "base": 80},
    "fwd_pe":     {"layer": "fuel", "lo": 16, "hi": 24,  "w": 2, "base": 75},
    "pb":         {"layer": "fuel", "lo": 3,  "hi": 5.5, "w": 2, "base": 75},
    "margin_yoy": {"layer": "fuel", "lo": 0,  "hi": 45,  "w": 2, "base": 90},
    # 2s10s in bps: +100 = steep/benign, -50 = deeply inverted/extreme. A slow
    # macro vulnerability that can persist for years (hence fuel, not deter).
    "curve":      {"layer": "fuel", "lo": 100, "hi": -50, "w": 2, "base": 30},
    "ipo":        {"layer": "fuel", "w": 1.5, "base": 85, "manual": True},
    "flows":      {"layer": "fuel", "w": 1,   "base": 65, "manual": True},
    "retail":     {"layer": "fuel", "w": 1,   "base": 78, "manual": True},
    "aicapex":    {"layer": "fuel", "w": 1.5, "base": 90, "manual": True},
    # ── Layer 2: Deterioration (something breaking) ─────────────────
    "hy_oas":     {"layer": "deter", "lo": 275, "hi": 600,  "w": 4, "base": 0},
    "ig_oas":     {"layer": "deter", "lo": 80,  "hi": 220,  "w": 2, "base": 0},
    # Moody's Baa-10Y spread (bps). Non-ICE, full history since 1986 — carries the
    # credit dimension when ICE HY/IG OAS are API-truncated (~3yr; see backtest note).
    # lo=170 (long-run calm) → hi=450 (≈2020 peak; 2008 saturates at 100).
    "baa":        {"layer": "deter", "lo": 170, "hi": 450,  "w": 2, "base": 0},
    "spx_200":    {"layer": "deter", "lo": 80,  "hi": 25,   "w": 3, "base": 40},
    "rsp_spy":    {"layer": "deter", "lo": 2,   "hi": -15,  "w": 2, "base": 55},
    "iwm_spy":    {"layer": "deter", "lo": 2,   "hi": -18,  "w": 1.5, "base": 55},
    "nhnl":       {"layer": "deter", "lo": 50,  "hi": -200, "w": 1.5, "base": 45},
    "cds":        {"layer": "deter", "w": 1.5, "base": 20, "manual": True},
    # ── Layer 3: Triggers (act now) ─────────────────────────────────
    "lh":         {"layer": "trig", "w": 3, "toggle": True},
    "b50":        {"layer": "trig", "w": 2, "toggle": True},
    "b200":       {"layer": "trig", "w": 3, "toggle": True},
    "hy_break":   {"layer": "trig", "series": "hy_oas", "lo": 325, "hi": 600, "w": 4, "base": 0},
    "vol":        {"layer": "trig", "series": "vix",    "lo": 18,  "hi": 45,  "w": 2, "base": 0},
    "eps":        {"layer": "trig", "w": 2, "toggle": True},
}

LAYERS = ("fuel", "deter", "trig")


def layer_score(values, layer, use_base=True):
    """Weighted-mean sub-score for one layer.

    values: dict of raw metric values (and optional toggle booleans).
    use_base=True  -> LIVE: missing signals fall back to their baseline.
    use_base=False -> BACKTEST: missing signals are dropped, weights renormalised.
    Returns int 0–100, or None if nothing scoreable.
    """
    num = den = 0.0
    for key, cfg in SIGNALS.items():
        if cfg["layer"] != layer:
            continue
        if cfg.get("toggle"):
            if key in values and values[key] is not None:
                s = 100.0 if values[key] else 0.0
            else:
                continue  # event flags only set in the UI
        else:
            v = values.get(cfg.get("series", key))
            if v is None:
                if use_base and "base" in cfg:
                    s = cfg["base"]
                else:
                    continue
            else:
                s = score_from(v, cfg["lo"], cfg["hi"])
        num += s * cfg["w"]
        den += cfg["w"]
    return round(num / den) if den else None


def verdict(F, D, T):
    """Synthesised verdict from the three layer scores (mirrors the dashboard)."""
    F, D, T = (x or 0 for x in (F, D, T))
    if T >= 40:
        return "BREAKDOWN", "Triggers firing — execute per rules."
    if D >= 50:
        return "DISTRIBUTION", "Internals deteriorating under a stretched tape — reduce, arm hedges."
    if F >= 60:
        return "HIGH_RISK", "Fuel maxed, nothing broken yet — defend in composition, not exposure."
    return "NEUTRAL", "No edge for defense — stay invested."


def score_all(values, use_base=True):
    F = layer_score(values, "fuel", use_base)
    D = layer_score(values, "deter", use_base)
    T = layer_score(values, "trig", use_base)
    v, note = verdict(F, D, T)
    return {"fuel": F, "deter": D, "trig": T, "verdict": v, "note": note}
