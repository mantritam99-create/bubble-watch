#!/usr/bin/env python3
"""
fetch_risk.py — pull current readings, score them, write risk_data.json.

Reliably-free sources only:
  • FRED (one free API key)  -> credit spreads, 2s10s, VIX, Fed balance sheet
  • yfinance (no key)        -> KOSPI level/chg, RSP/SPY/IWM relative strength

Fields that have no clean free machine-readable feed can be read from a dated
overrides.json. Missing fields remain visible as baseline/missing coverage but
do not enter the live score or verdict.

Env:  FRED_API_KEY  (required for the FRED block; the rest still runs without it)
Out:  risk_data.json  (same keys the dashboard reads, plus computed scores)
"""

import os, sys, json, datetime as dt
import requests
from risk_model import model_config, score_all

try:
    sys.stdout.reconfigure(encoding="utf-8")  # print non-ASCII on Windows consoles
except Exception:
    pass

FRED = "https://api.stlouisfed.org/fred/series/observations"
FRED_KEY = os.environ.get("FRED_API_KEY", "")

# metric key -> (FRED series id, scale).  scale converts to the dashboard's unit.
# NOTE: baa (Moody's Baa-10Y, full history) backs the deter-layer credit signal.
# To make it backtest-only and leave the live verdict unchanged, delete the "baa"
# line below — risk_model will then drop it and renormalise.
FRED_SERIES = {
    "baa":    ("BAA10Y",       100.0),  # percent -> basis points (credit spread)
    "hy_oas": ("BAMLH0A0HYM2", 100.0),  # percent -> basis points
    "ig_oas": ("BAMLC0A0CM",   100.0),  # percent -> basis points
    "curve":  ("T10Y2Y",       100.0),  # percent -> basis points
    "vix":    ("VIXCLS",       1.0),
    "fed_bs": ("WALCL",        1e-6),    # millions -> $ trillions
}

OVERRIDE_KEYS = [
    "cape", "fwd_pe", "pb", "margin_yoy", "spx_200", "nhnl",
    "kr_margin", "kr_forced_liq", "ipo", "flows", "retail", "aicapex", "cds",
]


def load_overrides(path="overrides.json"):
    """Load dated manual values; reject unversioned or future-dated input."""
    with open(path) as f:
        payload = json.load(f)
    asof, values = payload.get("asof"), payload.get("values")
    if not asof or not isinstance(values, dict):
        raise ValueError("expected {'asof': 'YYYY-MM-DD', 'values': {...}}")
    date = dt.date.fromisoformat(asof)
    if date > dt.date.today():
        raise ValueError("manual asof cannot be in the future")
    return asof, {k: values[k] for k in OVERRIDE_KEYS
                  if k in values and values[k] is not None}


def fred_latest(series_id):
    """Most recent non-missing observation for a FRED series, or None."""
    if not FRED_KEY:
        return None
    try:
        r = requests.get(FRED, params={
            "series_id": series_id, "api_key": FRED_KEY, "file_type": "json",
            "sort_order": "desc", "limit": 10,
        }, timeout=30)
        r.raise_for_status()
        for obs in r.json().get("observations", []):
            if obs["value"] not in (".", "", None):
                return float(obs["value"])
    except Exception as e:
        print(f"  ! FRED {series_id}: {e}")
    return None


def _close(df):
    """Return a clean Close Series regardless of yfinance column shape."""
    c = df["Close"]
    if hasattr(c, "columns"):       # MultiIndex -> single column
        c = c.iloc[:, 0]
    return c.dropna()


def ytd_pct(ticker):
    import yfinance as yf
    y0 = dt.date(dt.date.today().year, 1, 1).isoformat()
    df = yf.download(ticker, start=y0, progress=False, auto_adjust=True)
    if df is None or df.empty:
        return None
    c = _close(df)
    return round(float(c.iloc[-1] / c.iloc[0] - 1) * 100, 2) if len(c) else None


def fetch_yf(data):
    """KOSPI level/chg + RSP/SPY/IWM relative YTD. Best-effort."""
    try:
        import yfinance as yf
        df = yf.download("^KS11", period="7d", progress=False, auto_adjust=True)
        c = _close(df)
        if len(c) >= 2:
            data["kospi"] = round(float(c.iloc[-1]), 2)
            data["kospi_chg"] = round(float(c.iloc[-1] / c.iloc[-2] - 1) * 100, 2)
    except Exception as e:
        print(f"  ! yfinance KOSPI: {e}")
    try:
        spy = ytd_pct("SPY")
        if spy is not None:
            rsp, iwm = ytd_pct("RSP"), ytd_pct("IWM")
            if rsp is not None:
                data["rsp_spy"] = round(rsp - spy, 2)
            if iwm is not None:
                data["iwm_spy"] = round(iwm - spy, 2)
    except Exception as e:
        print(f"  ! yfinance relative strength: {e}")


def main():
    data = {"asof": dt.date.today().isoformat()}
    sources = {}

    print("FRED…")
    for key, (sid, scale) in FRED_SERIES.items():
        v = fred_latest(sid)
        data[key] = round(v * scale, 2) if v is not None else None
        if data[key] is not None:
            sources[key] = "live"
        print(f"  {key:8} {data[key]}")

    print("yfinance…")
    fetch_yf(data)
    for k in ("kospi", "kospi_chg", "rsp_spy", "iwm_spy"):
        if data.get(k) is not None:
            sources[k] = "live"
        print(f"  {k:8} {data.get(k)}")

    # manual / hard-to-fetch fields
    try:
        manual_asof, overrides = load_overrides()
        data["manual_asof"] = manual_asof
        for k, value in overrides.items():
            data[k] = value
            sources[k] = "manual"
        print(f"overrides ({manual_asof}): applied {list(overrides)}")
    except FileNotFoundError:
        print("overrides.json not found — manual fields left null")
    except (ValueError, TypeError, json.JSONDecodeError) as e:
        print(f"overrides.json ignored — {e}")

    for k in OVERRIDE_KEYS:
        data.setdefault(k, None)

    data["sources"] = sources
    data["model"] = model_config()
    data["scores"] = score_all(data, sources=sources)
    print("scores:", data["scores"])

    with open("risk_data.json", "w") as f:
        json.dump(data, f, indent=2)
    print("wrote risk_data.json")


if __name__ == "__main__":
    main()
