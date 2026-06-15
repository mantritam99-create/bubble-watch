#!/usr/bin/env python3
"""
backtest.py — score every month and report ACTUAL forward returns.

No borrowed win-rates. Everything below is computed from real history:
  FRED   : Baa-10Y credit spread (BAA10Y, 1986+) for long-history credit,
           2s10s (T10Y2Y, 1990+), VIX (VIXCLS, 1990+),
           ICE BofA HY/IG OAS (BAMLH0A0HYM2, BAMLC0A0CM) — context only, see below
  yfinance: ^GSPC monthly close (forward returns)

Honesty notes printed at the top of the run:
  • ICE BofA HY/IG OAS are now API-truncated to a rolling ~3yr window (data
    begins ~2023-06), so they CANNOT condition history. Long-history credit
    conditioning therefore uses Moody's Baa-10Y spread (BAA10Y, daily since
    1986) — a true credit spread covering every recession back to the late '80s.
    HY/IG are still fetched and reported for context.
  • Curve / VIX / price stats run from 1990.
  • Valuation (CAPE) is optional: drop shiller_cape.csv (cols: date,cape) next to
    this file to include it; otherwise the historical fuel score omits it.
  • Missing signals are dropped and weights renormalised — historical scores
    rest only on data that actually existed at the time.

Env:  FRED_API_KEY
Out:  backtest_results.json  + a printed report
"""

import os, sys, json, datetime as dt
import requests
import pandas as pd
from risk_model import SIGNALS, score_from, layer_score, verdict

try:
    sys.stdout.reconfigure(encoding="utf-8")  # print → and • on Windows consoles
except Exception:
    pass

FRED = "https://api.stlouisfed.org/fred/series/observations"
FRED_KEY = os.environ.get("FRED_API_KEY", "")
START = "1986-01-01"   # Baa-10Y begins 1986; captures the 1987 crash + 1990-91 recession

FRED_MONTHLY = {                       # metric -> (series id, scale)
    "baa":    ("BAA10Y",       100.0),  # Moody's Baa-10Y spread, bps (1986+)
    "hy_oas": ("BAMLH0A0HYM2", 100.0),  # ICE HY OAS — API-truncated to ~3yr, context only
    "ig_oas": ("BAMLC0A0CM",   100.0),  # ICE IG OAS — API-truncated to ~3yr, context only
    "curve":  ("T10Y2Y",       100.0),
    "vix":    ("VIXCLS",       1.0),
}


def fred_series(series_id, scale):
    """Full history as a month-end pandas Series (last obs of each month)."""
    if not FRED_KEY:
        raise RuntimeError("FRED_API_KEY not set")
    r = requests.get(FRED, params={
        "series_id": series_id, "api_key": FRED_KEY, "file_type": "json",
        "observation_start": START,
    }, timeout=60)
    r.raise_for_status()
    rows = [(o["date"], o["value"]) for o in r.json()["observations"] if o["value"] not in (".", "", None)]
    s = pd.Series({pd.Timestamp(d): float(v) * scale for d, v in rows}).sort_index()
    return s.resample("ME").last()


def sp500_monthly():
    import yfinance as yf
    df = yf.download("^GSPC", start=START, interval="1mo", progress=False, auto_adjust=True)
    c = df["Close"]
    if hasattr(c, "columns"):
        c = c.iloc[:, 0]
    return c.dropna().resample("ME").last()


def build_panel():
    cols = {}
    for key, (sid, scale) in FRED_MONTHLY.items():
        print(f"  FRED {key}…")
        cols[key] = fred_series(sid, scale)
    print("  yfinance ^GSPC…")
    cols["spx"] = sp500_monthly()

    cape_path = "shiller_cape.csv"
    if os.path.exists(cape_path):
        cape = pd.read_csv(cape_path, parse_dates=["date"]).set_index("date")["cape"]
        cols["cape"] = cape.resample("ME").last()
        print("  CAPE: shiller_cape.csv loaded")
    else:
        print("  CAPE: not provided — valuation omitted from historical fuel")

    df = pd.DataFrame(cols).sort_index()
    df = df.dropna(subset=["spx"])
    return df


def score_row(row):
    """Three layer scores from whatever data existed that month (renormalised)."""
    vals = {k: (None if pd.isna(row.get(k)) else float(row[k]))
            for k in ("baa", "hy_oas", "ig_oas", "curve", "vix", "cape")}
    F = layer_score(vals, "fuel",  use_base=False)
    D = layer_score(vals, "deter", use_base=False)
    T = layer_score(vals, "trig",  use_base=False)
    v, _ = verdict(F, D, T)
    return pd.Series({"F": F, "D": D, "T": T, "verdict": v})


def forward(df):
    px = df["spx"]
    df["r3"]  = px.shift(-3)  / px - 1
    df["r6"]  = px.shift(-6)  / px - 1
    df["r12"] = px.shift(-12) / px - 1
    # worst close over the next 12 months (drawdown proxy)
    fwd_min = px[::-1].rolling(12, min_periods=1).min()[::-1].shift(-1)
    df["dd12"] = fwd_min / px - 1
    return df


def stats(sub, label):
    s = sub["r12"].dropna()
    if len(s) == 0:
        return None
    return {
        "condition": label,
        "n_months": int(len(s)),
        "mean_fwd12_pct": round(s.mean() * 100, 1),
        "median_fwd12_pct": round(s.median() * 100, 1),
        "pct_negative": round((s < 0).mean() * 100, 1),
        "worst_fwd12_pct": round(s.min() * 100, 1),
        "mean_dd12_pct": round(sub["dd12"].dropna().mean() * 100, 1),
    }


def main():
    print("Building monthly panel since", START, "…")
    df = build_panel()
    df = pd.concat([df, df.apply(score_row, axis=1)], axis=1)
    df = forward(df)
    print(f"Panel: {df.index.min():%Y-%m} → {df.index.max():%Y-%m}  ({len(df)} months)\n")

    baseline = stats(df, "ALL months (baseline)")
    results = [baseline]

    print("Reporting ACTUAL forward 12-month S&P returns, conditioned on real signals.")
    print(f"(Credit conditioning uses Baa-10Y from {df['baa'].first_valid_index():%Y-%m}; "
          f"ICE HY OAS only exists from {df['hy_oas'].first_valid_index():%Y-%m} — see HY rows)\n")

    conditions = [
        ("Baa spread > 250",    df[df["baa"] > 250]),
        ("Baa spread > 350",    df[df["baa"] > 350]),
        ("HY OAS > 325 (3yr)",  df[df["hy_oas"] > 325]),
        ("HY OAS > 475 (3yr)",  df[df["hy_oas"] > 475]),
        ("2s10s inverted (<0)", df[df["curve"] < 0]),
        ("VIX > 25",            df[df["vix"] > 25]),
        ("Fuel >= 60",          df[df["F"] >= 60]),
        ("Deterioration >= 50", df[df["D"] >= 50]),
        ("Triggers >= 40",      df[df["T"] >= 40]),
        ("Verdict HIGH_RISK",   df[df["verdict"] == "HIGH_RISK"]),
        ("Verdict DISTRIBUTION", df[df["verdict"] == "DISTRIBUTION"]),
        ("Verdict BREAKDOWN",   df[df["verdict"] == "BREAKDOWN"]),
    ]

    hdr = f"{'condition':22} {'n':>4} {'meanF12':>8} {'medF12':>7} {'%neg':>6} {'worst':>7} {'avgDD':>7}"
    print(hdr); print("-" * len(hdr))
    base = baseline
    print(f"{base['condition']:22} {base['n_months']:>4} {base['mean_fwd12_pct']:>7}% "
          f"{base['median_fwd12_pct']:>6}% {base['pct_negative']:>5}% {base['worst_fwd12_pct']:>6}% {base['mean_dd12_pct']:>6}%")
    for label, sub in conditions:
        st = stats(sub, label)
        if not st:
            print(f"{label:22}   no qualifying months")
            continue
        results.append(st)
        print(f"{st['condition']:22} {st['n_months']:>4} {st['mean_fwd12_pct']:>7}% "
              f"{st['median_fwd12_pct']:>6}% {st['pct_negative']:>5}% {st['worst_fwd12_pct']:>6}% {st['mean_dd12_pct']:>6}%")

    out = {
        "generated": dt.date.today().isoformat(),
        "window": f"{df.index.min():%Y-%m} to {df.index.max():%Y-%m}",
        "credit_start": f"{df['baa'].first_valid_index():%Y-%m}",
        "hy_oas_start": f"{df['hy_oas'].first_valid_index():%Y-%m}",
        "note": ("Real forward 12m S&P returns conditioned on signals. Past behaviour, "
                 "not a forecast. Credit conditioning uses Baa-10Y (1986+); ICE HY/IG OAS "
                 "are API-truncated to ~3yr and shown for context only."),
        "results": results,
    }
    with open("backtest_results.json", "w") as f:
        json.dump(out, f, indent=2)
    print("\nwrote backtest_results.json")


if __name__ == "__main__":
    main()
