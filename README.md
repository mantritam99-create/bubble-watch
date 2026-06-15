# Market Risk Dashboard — `bubble-watch`

A three-layer market-risk monitor for US equities. It pulls free macro/market data,
scores it 0–100 across three layers, synthesises a verdict, and renders a static
dashboard. Every signal is **backtested against actual forward S&P 500 returns (1990–2026)**.

**Live:** https://mantritam99-create.github.io/bubble-watch/

## The three layers

| Layer | Meaning | Examples |
|-------|---------|----------|
| **Fuel** | vulnerability — can stay elevated for years | valuation (CAPE, P/E, P/B), margin debt, AI capex, yield-curve inversion |
| **Deterioration** | something actually breaking | credit spreads (Baa-10Y, HY/IG OAS), breadth (RSP/IWM vs SPY), net highs−lows |
| **Triggers** | act-now confirmations | price breaks, VIX spike, credit blowout |

Verdict escalates: `NEUTRAL → HIGH_RISK (F≥60) → DISTRIBUTION (D≥50) → BREAKDOWN (T≥40)`.

## Files

- `risk_model.py` — scoring config + functions. **Single source of truth**; `index.html` mirrors these thresholds exactly.
- `fetch_risk.py` — pulls current readings (FRED + yfinance) → `risk_data.json`.
- `backtest.py` — conditions real forward 12m returns on the signals → `backtest_results.json`.
- `index.html` — static dashboard; fetches the two JSON files (relative paths, no hardcoded URL).
- `.github/workflows/risk.yml` — daily refresh + commit.

## Data honesty

- ICE BofA HY/IG OAS are served by the FRED **API** for only ~3 years, so long-history credit
  conditioning uses **Moody's Baa-10Y** (1986+). HY/IG are shown for current context only.
- The Fuel layer falls back to **baselines** until you supply `overrides.json` (real CAPE/fwd-P/E/P/B/margin) —
  copy `overrides.example.json`. Until then the verdict reads HIGH_RISK by construction (a stretched-valuation prior), not a live read.
- KOSPI / Korea fields are displayed but **not scored** (the backtest validates against the S&P).
- Backtest = real past behaviour, **not a forecast**.

## Setup

1. Add repo secret **`FRED_API_KEY`** (free key: https://fred.stlouisfed.org/docs/api/api_key.html).
2. GitHub Pages is served from the default branch root.
3. Local run: `pip install -r requirements.txt`, set `FRED_API_KEY`, then `python fetch_risk.py` (and optionally `python backtest.py`).
