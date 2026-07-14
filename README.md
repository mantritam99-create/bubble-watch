# Market Risk Dashboard — `bubble-watch`

A three-layer market-risk monitor for US equities. It pulls free macro/market data,
scores it 0–100 across three layers, synthesises a verdict, and renders a static
dashboard. Every signal is **backtested against actual 1-, 3-, 6-, and 12-month
S&P 500 returns plus forward maximum drawdown (1990–2026)**.

**Live:** https://mantritam99-create.github.io/bubble-watch/

## The three layers

| Layer | Meaning | Examples |
|-------|---------|----------|
| **Fuel** | vulnerability — can stay elevated for years | valuation (CAPE, P/E, P/B), margin debt, AI capex, yield-curve inversion |
| **Deterioration** | something actually breaking | credit spreads (Baa-10Y, HY/IG OAS), breadth (RSP/IWM vs SPY), net highs−lows |
| **Triggers** | act-now confirmations | price breaks, VIX spike, credit blowout |

Verdict escalates: `NEUTRAL → HIGH_RISK (F≥60) → DISTRIBUTION (D≥50) → BREAKDOWN (T≥40)`
only when weighted live Fuel coverage is at least 50%. Otherwise it is
`INSUFFICIENT_DATA` and the available scores are explicitly provisional.

## Files

- `risk_model.py` — scoring config + functions. **Single source of truth**; its config is exported in `risk_data.json` for the frontend.
- `fetch_risk.py` — pulls current readings (FRED + yfinance) → `risk_data.json`.
- `backtest.py` — conditions real 1/3/6/12m returns and maximum drawdown on the signals → `backtest_results.json`.
- `index.html` — static dashboard; fetches the two JSON files (relative paths, no hardcoded URL).
- `.github/workflows/risk.yml` — daily refresh + commit.

## Data honesty

- ICE BofA HY/IG OAS are served by the FRED **API** for only ~3 years, so long-history credit
  conditioning uses **Moody's Baa-10Y** (1986+). HY/IG are shown for current context only.
- Missing values and model baselines are displayed but **excluded from the observed score and verdict**.
  Every layer reports weighted `live`, `manual`, `baseline`, and `missing` coverage.
- Optional manual inputs require a dated `overrides.json` (`asof` plus `values`; copy
  `overrides.example.json`). Manual weight is shown separately and never counts toward
  the 50% live-Fuel gate. Qualitative IPO/flows/retail/AI-capex values are 0–100 scores.
- KOSPI / Korea fields are displayed but **not scored** (the backtest validates against the S&P).
- Backtest = real past behaviour, **not a forecast**. A rebound after a trigger is shown
  alongside the path's maximum drawdown; it is not treated as proof of breakdown timing.

## Setup

1. Add repo secret **`FRED_API_KEY`** (free key: https://fred.stlouisfed.org/docs/api/api_key.html).
2. GitHub Pages is served from the default branch root.
3. Local run: `pip install -r requirements.txt`, set `FRED_API_KEY`, then `python fetch_risk.py` (and optionally `python backtest.py`).
4. Tests: `python -m unittest discover -s tests -v`.
