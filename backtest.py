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
    df["r1"]  = px.shift(-1)  / px - 1
    df["r3"]  = px.shift(-3)  / px - 1
    df["r6"]  = px.shift(-6)  / px - 1
    df["r12"] = px.shift(-12) / px - 1
    df["mdd12"] = [
        (window / window.cummax() - 1).min() if len(window) == 13 else float("nan")
        for i in range(len(px)) for window in [px.iloc[i:i + 13]]
    ]
    return df


def stats(sub, label):
    if sub["r12"].dropna().empty:
        return None
    outcomes = {}
    for months in (1, 3, 6, 12):
        s = sub[f"r{months}"].dropna()
        outcomes[f"{months}m"] = {
            "n": int(len(s)),
            "mean_pct": round(s.mean() * 100, 1),
            "median_pct": round(s.median() * 100, 1),
            "pct_negative": round((s < 0).mean() * 100, 1),
            "worst_pct": round(s.min() * 100, 1),
        }
    mdd = sub["mdd12"].dropna()
    return {
        "condition": label,
        "n_months": outcomes["12m"]["n"],
        "outcomes": outcomes,
        "mean_max_drawdown_12m_pct": round(mdd.mean() * 100, 1),
        "worst_max_drawdown_12m_pct": round(mdd.min() * 100, 1),
    }


def main():
    print("Building monthly panel since", START, "…")
    df = build_panel()
    df = pd.concat([df, df.apply(score_row, axis=1)], axis=1)
    df = forward(df)
    print(f"Panel: {df.index.min():%Y-%m} → {df.index.max():%Y-%m}  ({len(df)} months)\n")

    baseline = stats(df, "ALL months (baseline)")
    results = [baseline]

    print("Reporting ACTUAL forward 1/3/6/12-month S&P returns and 12-month maximum drawdown.")
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

    def row(st):
        outcomes = st["outcomes"]
        return (f"{st['condition']:22} {st['n_months']:>4} "
                f"{outcomes['1m']['mean_pct']:>6}% {outcomes['3m']['mean_pct']:>6}% "
                f"{outcomes['6m']['mean_pct']:>6}% {outcomes['12m']['mean_pct']:>7}% "
                f"{st['mean_max_drawdown_12m_pct']:>7}% {st['worst_max_drawdown_12m_pct']:>8}%")

    hdr = f"{'condition':22} {'n':>4} {'mean1':>7} {'mean3':>7} {'mean6':>7} {'mean12':>8} {'avgMDD':>8} {'worstMDD':>9}"
    print(hdr); print("-" * len(hdr))
    print(row(baseline))
    for label, sub in conditions:
        st = stats(sub, label)
        if not st:
            print(f"{label:22}   no qualifying months")
            continue
        results.append(st)
        print(row(st))

    out = {
        "generated": dt.date.today().isoformat(),
        "window": f"{df.index.min():%Y-%m} to {df.index.max():%Y-%m}",
        "credit_start": f"{df['baa'].first_valid_index():%Y-%m}",
        "hy_oas_start": f"{df['hy_oas'].first_valid_index():%Y-%m}",
        "note": ("Real forward 1/3/6/12m S&P returns and forward 12m maximum drawdown "
                 "conditioned on signals. Post-trigger rebounds are outcomes, not evidence "
                 "that the signal predicted a breakdown. Credit conditioning uses Baa-10Y "
                 "(1986+); ICE HY/IG OAS are API-truncated to ~3yr and shown for context only."),
        "results": results,
    }
    with open("backtest_results.json", "w") as f:
        json.dump(out, f, indent=2)
    print("\nwrote backtest_results.json")


if __name__ == "__main__":
    main()
