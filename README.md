# EquityLens — Institutional DCF Research Terminal

**A self-hosted equity research tool that builds a full institutional-style DCF valuation — model, diagnostics, and a magazine-quality PDF tear sheet — from nothing but public `yfinance` data.**

> Not investment advice. Not a registered investment adviser. Educational and research use only — see [Disclaimer](#disclaimer).

---

## What this is

Most free DCF calculators do one thing: pull a trailing free cash flow number, apply a growth rate, and spit out a target price. EquityLens goes several steps further — it routes the valuation methodology by company type (a bank isn't valued like a manufacturer), runs a small forensic-accounting suite on the underlying financial statements, triangulates the DCF output against peer and market-based valuation ranges, and packages the whole thing into a two-column PDF tear sheet that reads like something a sell-side desk would publish.

It runs entirely on public data via `yfinance` — no paid data feeds, no API keys.

---

## Table of Contents

- [Key Features](#key-features)
- [How It Works](#how-it-works)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
- [Deployment](#deployment)
- [Project Structure](#project-structure)
- [Data Reliability Engineering](#data-reliability-engineering)
- [Known Limitations](#known-limitations)
- [Disclaimer](#disclaimer)

---

## Key Features

### Valuation Engine
- **Automatic model routing** — Free Cash Flow to Firm (FCFF) for standard corporates, Free Cash Flow to Equity (FCFE) for banks and NBFCs, and Dividend Discount Model (DDM) for REITs and insurers — detected from sector/industry, since a bank's debt is a raw material, not a financing choice, and valuing it like an industrial company is a common beginner mistake.
- **10-year, two-stage DCF** with an explicit terminal value, correctly discounted at WACC (FCFF) or Cost of Equity (FCFE/DDM) — never a blended rate applied to the wrong cash flow.
- **Reverse DCF solver** — instead of assumptions → price, it solves backwards: *"to justify the current price, the market is pricing in X% annual growth."*
- **Bear / Base / Bull scenario analysis** and a full **WACC × Terminal Growth sensitivity heatmap**.
- **Triangulated "football field" chart** — DCF range, peer-multiple-implied range, and 52-week trading range on one axis, so you can see at a glance whether independent methods agree.
- Hard guards against the two most common DCF failure modes: terminal growth rate accidentally exceeding the discount rate (mathematically undefined — this used to crash the app or silently return a nonsensical negative value), and widget-level crashes from extreme or negative beta values.

### Forensic Diagnostics
A small, auditable credit/earnings-quality suite computed directly from the fetched financial statements:

| Metric | What it flags |
|---|---|
| **Sloan Accruals Ratio** | Reported earnings running ahead of actual cash collection |
| **Altman Z-Score** | Bankruptcy / credit-distress risk |
| **3-Stage DuPont** | Whether ROE is driven by margin, capital efficiency, or leverage |
| **ROIC vs. Cost of Capital Spread** | Whether the business is actually creating economic value |
| **Normalized FCF Margin** | Smooths one-off CapEx spikes out of the DCF's starting cash flow |

### Institutional PDF Report
- Two-column **executive tear sheet** (built with ReportLab's `BaseDocTemplate`/`PageTemplate`/`Frame`, not a simple linear document) — header, 3-year financial summary, football field chart, and an automated investment thesis, side by side.
- **Automated investment thesis** — three paragraphs, deterministically generated from the computed metrics (not an LLM call — same inputs always produce the same text, which matters for audit trails).
- Full backing detail across nine sections: company snapshot, DCF assumptions with every input's provenance disclosed, the 10-year projection table, sensitivity analysis, scenario analysis, peer comps, risk flags, and the model-implied conviction verdict.
- Compliance footer and watermark on every page, version-stamped for traceability.

### Compliance-First Output
Every model-derived verdict is labeled **High / Moderate / Low Conviction** — never "Buy/Sell/Hold." This isn't cosmetic: the tool is not a registered investment adviser, and conviction labels describe only how the current price compares to the model's own intrinsic value estimate, not a recommendation.

---

## How It Works

```
 Ticker + Market
        │
        ▼
 ┌──────────────────┐     retries, backoff, HTTP cache,
 │  Data Fetch Layer │ ──  fuzzy field matching, multi-tier
 └──────────────────┘     fallbacks (see below)
        │
        ▼
 ┌──────────────────┐     bank/NBFC → FCFE · REIT/insurer → DDM
 │   Model Router    │ ──  everyone else → FCFF
 └──────────────────┘
        │
        ├──────────────► DCF Engine (10yr projection, terminal value,
        │                 sensitivity grid, Bear/Base/Bull scenarios)
        │
        ├──────────────► Forensic Accounting Suite (5 diagnostics)
        │
        ├──────────────► Reverse DCF Solver + Football Field ranges
        │
        └──────────────► Automated Thesis Generator
                                  │
                                  ▼
                   Streamlit Dashboard  +  PDF Tear Sheet
```

---

## Tech Stack

| Layer | Tool |
|---|---|
| UI | [Streamlit](https://streamlit.io) |
| Data | [`yfinance`](https://github.com/ranaroussi/yfinance) |
| Interactive charts | Plotly |
| PDF charts | Matplotlib |
| PDF generation | ReportLab (`BaseDocTemplate` for the two-column layout) |
| Data wrangling | Pandas / NumPy |
| HTTP caching | `requests_cache` |

---

## Getting Started

### Local setup

```bash
git clone <your-repo-url>
cd equitylens
pip install -r requirements.txt
streamlit run app.py
```

`requirements.txt`:
```
streamlit>=1.35.0
yfinance>=0.2.40
pandas>=2.0.0
numpy>=1.24.0
plotly>=5.18.0
matplotlib>=3.7.0
reportlab>=4.0.0
requests-cache>=1.1.0
```

### Usage

1. Pick a market in the sidebar (India, USA, UK, France, Germany, Europe).
2. Enter a ticker in that market's format (e.g. `TCS.NS`, `AAPL`, `AIR.PA`).
3. Click **Fetch Company Data**, review any data-quality notices, then adjust the DCF assumptions if you want to override the auto-fetched figures.
4. Click **Run DCF Analysis** to see the full dashboard — charts, forensics, football field, reverse DCF, risk flags.
5. Download the **institutional PDF report** from the bottom of the page.

---

## Deployment

This is a stateful Streamlit app — it needs a real Python process, not a serverless function, so **Vercel-style platforms will not work.**

**Recommended: [Railway](https://railway.app)**
A dedicated outbound IP meaningfully reduces `yfinance` rate-limiting versus a shared free-tier IP — worth the small cost if you're demoing this to anyone.

```
web: streamlit run app.py --server.port=$PORT --server.address=0.0.0.0
```
(save as `Procfile`, then connect the repo on Railway — it auto-detects the rest)

**Free alternative: [Streamlit Community Cloud](https://share.streamlit.io)**
Same repo, zero config, shared IP pool (fine for light/personal use, less reliable under sustained traffic).

---

## Project Structure

The app currently ships as a single file by design — everything from data fetching through PDF generation lives in `app.py`, organized into clearly delimited sections (data layer → model routing → DCF engine → forensics → charts → PDF builder → Streamlit UI). This keeps the whole request lifecycle traceable end to end, which matters more than file-splitting for a tool this size.

```
equitylens/
├── app.py              # the whole application
└── requirements.txt
```

---

## Data Reliability Engineering

This is where most of the actual engineering effort went, not the DCF math itself (that's a known formula). `yfinance` is an unofficial, undocumented API wrapper, and it fails in specific, recurring ways:

- **Net Debt** — balance sheet field names vary across tickers and library versions. Resolved with exact-match → fuzzy-match → info-dict fallback, and every figure carries a disclosed provenance string (which row, which fiscal period, which tier) so a wrong number is diagnosable, never a black box.
- **Market Cap** — falls back to `Price × Shares Outstanding` when the API's own `marketCap` field is empty, which happens more often than you'd expect.
- **Dividend Yield** — the API's `dividendYield` field has a documented history of returning something that isn't a yield at all for certain tickers. `dividendRate ÷ Price` is now the primary source; the field is used only as a cross-check.
- **Return on Equity** — computed via DuPont decomposition from the raw statements rather than trusted from the API's `returnOnEquity` field, which has been observed returning `0` for profitable companies.
- **Missing peer data** — genuinely absent metrics are preserved as `None` through the whole pipeline and rendered as `N/A`, instead of being silently conflated with a real value of zero.
- **Terminal Growth ≥ Discount Rate** — mathematically undefined in the Gordon Growth Model; clamped with a safety buffer at the one shared function every calculation path routes through, so it can never divide by zero or return a negative "intrinsic value."

---

## Known Limitations

- **Consensus analyst estimates and the live 10-Year Treasury yield fetch** are the two lowest-confidence data paths — they reach `yfinance` endpoints with a documented history of inconsistent shapes across versions. Both are wrapped defensively and fall back to static values rather than risk a bad number silently entering the model.
- **Dynamic WACC fade** (linearly fading the discount rate toward a mature-market average over the projection period) is implemented and tested but not yet exposed as a UI toggle — the app currently runs the static-WACC DCF as its primary output.
- **Historical-multiples valuation range** (the third leg of the football field, alongside DCF and peer-relative) needs 3 years of trailing multiple history that isn't reliably available post-fetch for every ticker, so it's currently disabled in the live UI path even though the underlying function exists and is tested.

---

## Disclaimer

EquityLens is produced for educational and research purposes only. It does not constitute investment advice, and neither the tool nor its author is a registered investment adviser, broker-dealer, or research analyst in any jurisdiction. The High / Moderate / Low Conviction labels describe only how the current market price compares to this model's own intrinsic value estimate — they are not buy, sell, or hold recommendations. All data is sourced from `yfinance`; verify anything material against the company's own published financials before relying on it. Past performance is not indicative of future results.

---
