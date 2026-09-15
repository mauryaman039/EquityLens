"""
EquityLens — Institutional DCF Equity Research Terminal  |  v9.0
Changes in this version:
  1. NET DEBT FIX — balance sheet columns are now explicitly sorted by date
     (newest first) before any value extraction. Each field uses dropna().iloc[0]
     so missing values in one period never cause a cross-period mismatch.
     Multiple field-name fallbacks tried in order of preference.
     Final safety net: cross-check against info-dict totalDebt / totalCash.
  2. LIGHT PROFESSIONAL THEME — clean white/navy palette readable on any
     display, designed to look institutional-grade in LinkedIn screenshots.
  3. All v8.0 features retained (retries, backoff, HTTP cache, model routing,
     Ke vs WACC labeling, conviction levels, model-aware value bridge chart).
"""

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import io, datetime, time, warnings, random, re
warnings.filterwarnings("ignore")

try:
    import requests_cache
    requests_cache.install_cache(
        cache_name="yf_cache", backend="sqlite", expire_after=1800,
        allowable_methods=["GET"], allowable_codes=[200], stale_if_error=True)
    _CACHE_ACTIVE = True
except ImportError:
    _CACHE_ACTIVE = False

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, BaseDocTemplate, PageTemplate, Frame, FrameBreak,
    NextPageTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, Image as RLImage, KeepTogether)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Candidate (regular, bold) font path pairs, tried in order. DejaVu Sans is
# checked first because — unlike Liberation Sans — it actually contains the
# Indian Rupee glyph (U+20B9), which this report renders on every page for
# Indian-market companies. All candidates below are confirmed to cover
# ₹ £ € $ — — · → β × ≤, the full set of special characters this PDF uses.
_FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf",
     "/usr/share/fonts/truetype/crosextra/Carlito-Bold.ttf"),
    ("/usr/share/fonts/truetype/freefont/FreeSans.ttf",
     "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"),
]
PDF_F, PDF_FB = "Helvetica", "Helvetica-Bold"   # last-resort fallback
for _reg_path, _bold_path in _FONT_CANDIDATES:
    try:
        pdfmetrics.registerFont(TTFont("PDFSans",      _reg_path))
        pdfmetrics.registerFont(TTFont("PDFSans-Bold", _bold_path))
        PDF_F, PDF_FB = "PDFSans", "PDFSans-Bold"
        break
    except Exception:
        continue

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG & CSS  — Clean Light Professional Theme
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="EquityLens — DCF Terminal",
                   page_icon="📊", layout="wide",
                   initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Playfair+Display:wght@700&display=swap');

/* ── Base ── */
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.main, .stApp { background-color: #F0F4F8; }
section[data-testid="stSidebar"] {
    background-color: #1E3A5F;
    border-right: none;
}

/* ── Sidebar text overrides ── */
section[data-testid="stSidebar"] .section-header-sb {
    font-size: .65rem; color: #93C5FD; text-transform: uppercase;
    letter-spacing: 2px; font-weight: 700; margin-bottom: 8px;
    padding-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,.15);
}
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] .stSelectbox label,
section[data-testid="stSidebar"] p { color: #E2E8F0 !important; }
section[data-testid="stSidebar"] .stButton>button {
    background: linear-gradient(135deg, #2563EB, #1D4ED8);
    color: white; border: none; font-weight: 700;
    border-radius: 8px; padding: 0.6rem 1rem;
    font-size: .9rem; width: 100%;
    box-shadow: 0 4px 12px rgba(37,99,235,.4);
    transition: all .2s;
}
section[data-testid="stSidebar"] .stButton>button:hover {
    background: linear-gradient(135deg, #1D4ED8, #1E40AF);
    box-shadow: 0 6px 16px rgba(37,99,235,.5);
    transform: translateY(-1px);
}

/* ── Hero banner ── */
.hero-banner {
    background: linear-gradient(135deg, #1E3A5F 0%, #1E40AF 50%, #1E3A5F 100%);
    border-radius: 16px; padding: 36px 44px; margin-bottom: 28px;
    position: relative; overflow: hidden;
    box-shadow: 0 8px 32px rgba(30,58,95,.25);
}
.hero-banner::before {
    content: ''; position: absolute; top: 0; left: 0; right: 0; height: 4px;
    background: linear-gradient(90deg, #60A5FA, #34D399, #FBBF24);
}
.hero-banner::after {
    content: ''; position: absolute; top: -60px; right: -60px;
    width: 200px; height: 200px; border-radius: 50%;
    background: rgba(255,255,255,.04); pointer-events: none;
}
.hero-title {
    font-family: 'Playfair Display', serif; font-size: 2.4rem;
    font-weight: 700; color: #FFFFFF; margin: 0; letter-spacing: -.5px;
}
.hero-subtitle { color: #93C5FD; font-size: .95rem; margin-top: 8px; font-weight: 400; }
.hero-badge {
    display: inline-block;
    background: rgba(255,255,255,.12);
    border: 1px solid rgba(255,255,255,.25);
    color: #E0F2FE; font-size: .72rem; font-weight: 700;
    padding: 4px 12px; border-radius: 20px;
    letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 14px;
}

/* ── Cards ── */
.metric-card {
    background: #FFFFFF; border: 1px solid #E2E8F0;
    border-radius: 12px; padding: 20px 22px;
    box-shadow: 0 1px 4px rgba(0,0,0,.06);
    transition: box-shadow .2s;
}
.metric-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,.1); }
.metric-label {
    font-size: .7rem; color: #64748B; text-transform: uppercase;
    letter-spacing: 1.2px; font-weight: 600; margin-bottom: 8px;
}
.metric-value { font-size: 1.5rem; font-weight: 800; color: #0F172A; letter-spacing: -.5px; }
.metric-delta-up  { color: #059669; font-size: .82rem; font-weight: 600; }
.metric-delta-down{ color: #DC2626; font-size: .82rem; font-weight: 600; }

/* ── Section headers ── */
.section-header {
    font-size: .68rem; color: #64748B; text-transform: uppercase;
    letter-spacing: 2px; font-weight: 700; margin-bottom: 14px;
    padding-bottom: 10px; border-bottom: 2px solid #E2E8F0;
}

/* ── Company header card ── */
.company-card {
    background: #FFFFFF; border: 1px solid #E2E8F0;
    border-radius: 14px; padding: 24px 30px; margin-bottom: 20px;
    box-shadow: 0 2px 8px rgba(0,0,0,.06);
    border-left: 4px solid #2563EB;
}

/* ── Conviction badges ── */
.conviction-high {
    background: #ECFDF5; border: 2px solid #059669; color: #065F46;
    font-size: .9rem; font-weight: 800; padding: 16px 10px;
    border-radius: 12px; text-align: center; line-height: 1.4;
    box-shadow: 0 2px 8px rgba(5,150,105,.15);
}
.conviction-moderate {
    background: #FFFBEB; border: 2px solid #D97706; color: #92400E;
    font-size: .9rem; font-weight: 800; padding: 16px 10px;
    border-radius: 12px; text-align: center; line-height: 1.4;
    box-shadow: 0 2px 8px rgba(217,119,6,.15);
}
.conviction-low {
    background: #FEF2F2; border: 2px solid #DC2626; color: #991B1B;
    font-size: .9rem; font-weight: 800; padding: 16px 10px;
    border-radius: 12px; text-align: center; line-height: 1.4;
    box-shadow: 0 2px 8px rgba(220,38,38,.15);
}

/* ── Risk flags ── */
.risk-flag {
    background: #FEF2F2; border-left: 4px solid #DC2626;
    padding: 12px 16px; border-radius: 0 8px 8px 0;
    margin-bottom: 8px; font-size: .87rem; color: #7F1D1D;
}
.risk-moderate {
    background: #FFFBEB; border-left: 4px solid #D97706;
    padding: 12px 16px; border-radius: 0 8px 8px 0;
    margin-bottom: 8px; font-size: .87rem; color: #78350F;
}
.risk-low {
    background: #ECFDF5; border-left: 4px solid #059669;
    padding: 12px 16px; border-radius: 0 8px 8px 0;
    margin-bottom: 8px; font-size: .87rem; color: #064E3B;
}

/* ── Info / warning boxes ── */
.info-box {
    background: #EFF6FF; border: 1px solid #BFDBFE;
    border-radius: 10px; padding: 14px 18px;
    font-size: .85rem; color: #1E40AF; line-height: 1.6;
}
.warn-box {
    background: #FFFBEB; border: 1px solid #FDE68A;
    border-radius: 10px; padding: 14px 18px;
    font-size: .85rem; color: #92400E;
}
.sidebar-info {
    background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.15);
    border-radius: 10px; padding: 14px 16px;
    font-size: .83rem; color: #CBD5E1; line-height: 1.7;
}
.divider { border-top: 1px solid rgba(255,255,255,.12); margin: 20px 0; }

/* ── Model tag ── */
.model-tag-fcff { background:#EFF6FF;border:1.5px solid #2563EB;color:#1D4ED8;
    font-size:.68rem;font-weight:800;padding:3px 10px;border-radius:20px;
    letter-spacing:1px;text-transform:uppercase; }
.model-tag-fcfe { background:#FFFBEB;border:1.5px solid #D97706;color:#B45309;
    font-size:.68rem;font-weight:800;padding:3px 10px;border-radius:20px;
    letter-spacing:1px;text-transform:uppercase; }
.model-tag-ddm  { background:#ECFDF5;border:1.5px solid #059669;color:#047857;
    font-size:.68rem;font-weight:800;padding:3px 10px;border-radius:20px;
    letter-spacing:1px;text-transform:uppercase; }

/* ── Streamlit overrides ── */
.stExpander { background: #FFFFFF; border: 1px solid #E2E8F0 !important; border-radius: 12px !important; }
.stNumberInput input, .stTextInput input {
    background: #F8FAFC; border: 1.5px solid #CBD5E1;
    border-radius: 8px; color: #0F172A; font-weight: 500;
}
.stNumberInput input:focus, .stTextInput input:focus {
    border-color: #2563EB; box-shadow: 0 0 0 3px rgba(37,99,235,.1);
}
.stButton>button[data-testid="baseButton-primary"] {
    background: linear-gradient(135deg, #2563EB, #1D4ED8);
    color: white; border: none; font-weight: 700;
    border-radius: 10px; font-size: 1rem;
    box-shadow: 0 4px 14px rgba(37,99,235,.35);
    transition: all .2s;
}
.stButton>button[data-testid="baseButton-primary"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(37,99,235,.45);
}
div[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }
#MainMenu, footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# RETRY WRAPPER
# ─────────────────────────────────────────────────────────────────────────────
MAX_RETRIES  = 4
BASE_DELAY   = 2.0
MAX_DELAY    = 30.0
INTER_TICKER = 1.5

def _backoff(attempt):
    return min(BASE_DELAY * (2 ** attempt), MAX_DELAY) + random.uniform(0, 0.8)

def _looks_like_real_info(info):
    """
    yfinance returns a near-empty stub dict (sometimes {} or a single
    all-None key) when a request is silently rate-limited or partially
    fails upstream, rather than raising an exception. This distinguishes
    that stub from a genuine — even if partial — response, so a real dict
    that's simply missing regularMarketPrice/currentPrice/marketCap isn't
    discarded and retried away for no benefit, sending fetch_company_data
    into its total-failure path (which hardcodes Market Cap to 0).
    """
    if not info or not isinstance(info, dict):
        return False
    has_identity = bool(info.get("longName") or info.get("shortName") or info.get("symbol"))
    has_any_price = any(info.get(k) for k in [
        "regularMarketPrice", "currentPrice", "previousClose",
        "regularMarketPreviousClose", "open", "regularMarketOpen", "marketCap"])
    has_shares = bool(info.get("sharesOutstanding"))
    substantial = sum(1 for v in info.values() if v is not None) >= 5
    return (has_identity or has_any_price or has_shares) and substantial

def _safe_info(ticker):
    for attempt in range(MAX_RETRIES):
        try:
            info = yf.Ticker(ticker).info
            if _looks_like_real_info(info):
                return info
            if attempt < MAX_RETRIES - 1:
                time.sleep(_backoff(attempt))
        except Exception as exc:
            is_rate = any(k in str(exc).lower() for k in ["429","too many","rate limit","timeout","connection"])
            if attempt < MAX_RETRIES - 1:
                time.sleep(_backoff(attempt) * (3 if is_rate else 1))
    return {}

def _safe_fetch(attr, ticker):
    """Generic safe fetch for cashflow / balance_sheet / financials."""
    for attempt in range(MAX_RETRIES):
        try:
            df = getattr(yf.Ticker(ticker), attr)
            if df is not None and not df.empty:
                return df
            if attempt < MAX_RETRIES - 1:
                time.sleep(_backoff(attempt))
        except Exception:
            if attempt < MAX_RETRIES - 1:
                time.sleep(_backoff(attempt))
    return None

def _safe_history(ticker, period="5y"):
    for attempt in range(MAX_RETRIES):
        try:
            hist = yf.Ticker(ticker).history(period=period)
            if hist is not None and not hist.empty:
                return hist["Close"].reset_index()
            if attempt < MAX_RETRIES - 1:
                time.sleep(_backoff(attempt))
        except Exception:
            if attempt < MAX_RETRIES - 1:
                time.sleep(_backoff(attempt))
    return None

def _f(v, fallback=0.0):
    try:
        return float(v) if v is not None else fallback
    except (TypeError, ValueError):
        return fallback

def _latest(df, *row_names):
    """
    From a DataFrame where columns = fiscal period dates,
    return the most recent non-null value for the first matching row name.
    Sorts columns newest-first before searching.
    """
    if df is None or df.empty:
        return None
    try:
        df_sorted = df.sort_index(axis=1, ascending=False)
        for name in row_names:
            if name in df_sorted.index:
                series = df_sorted.loc[name].dropna()
                if not series.empty:
                    return float(series.iloc[0])
    except Exception:
        pass
    return None

# ═══════════════════════════════════════════════════════════════════════════
# FORENSIC ACCOUNTING ENGINE
# ═══════════════════════════════════════════════════════════════════════════
# Five institutional diagnostics computed purely from multi-period yfinance
# statements. Every metric degrades gracefully (returns None + a reason)
# rather than guessing when a required line item is unavailable — consistent
# with how Net Debt / Market Cap already handle missing data in this app.

def _multi_period(df, *row_names, n=3):
    """
    Like _find_bs_value but returns up to n most-recent non-null values
    (newest first) for the first matching row name, plus the field used.
    Returns (list_of_values, field_name) or ([], None).
    """
    if df is None or df.empty:
        return [], None
    try:
        df_sorted = df.sort_index(axis=1, ascending=False)
    except Exception:
        df_sorted = df
    for name in row_names:
        if name in df_sorted.index:
            series = df_sorted.loc[name]
            if isinstance(series, pd.DataFrame):
                series = series.iloc[0]
            series = series.dropna()
            if not series.empty:
                return [float(v) for v in series.iloc[:n]], name
    return [], None


def compute_sloan_accruals(inc, cf, bs, div):
    """
    Sloan Accruals Ratio = (Net Income - Operating Cash Flow) / Total Assets
    Flags earnings quality: large positive accruals mean reported profit is
    running well ahead of actual cash collection (aggressive accounting risk).
    Returns dict with value, verdict, and a diagnosability note.
    """
    ni_list, ni_f = _multi_period(inc, "Net Income", "Net Income Common Stockholders", n=1)
    ocf_list, ocf_f = _multi_period(cf, "Operating Cash Flow",
                                     "Total Cash From Operating Activities", n=1)
    ta_list, ta_f = _multi_period(bs, "Total Assets", n=1)

    if not (ni_list and ocf_list and ta_list) or ta_list[0] == 0:
        return {"value": None, "verdict": "N/A",
                "note": f"Missing inputs (NI:{bool(ni_list)}, OCF:{bool(ocf_list)}, "
                        f"Total Assets:{bool(ta_list)}) — cannot compute."}

    ratio = (ni_list[0] - ocf_list[0]) / ta_list[0]
    if ratio > 0.10:
        verdict = "HIGH RISK — earnings significantly outpace cash collection"
    elif ratio > 0.05:
        verdict = "MODERATE — some earnings quality concern"
    elif ratio > -0.05:
        verdict = "HEALTHY — earnings well-matched to cash generation"
    else:
        verdict = "CONSERVATIVE — cash generation exceeds reported earnings"
    return {"value": round(ratio, 4), "verdict": verdict,
            "note": f"NI {ni_list[0]/div:,.0f} − OCF {ocf_list[0]/div:,.0f}, "
                    f"÷ Total Assets {ta_list[0]/div:,.0f}"}


def compute_altman_z(bs, inc, mkt_cap_raw, div):
    """
    Altman Z-Score (original 1968 model, for public manufacturing/industrial
    firms — the standard formulation computable from yfinance alone):
      Z = 1.2*A + 1.4*B + 3.3*C + 0.6*D + 1.0*E
      A = Working Capital / Total Assets
      B = Retained Earnings / Total Assets
      C = EBIT / Total Assets
      D = Market Value of Equity / Total Liabilities
      E = Sales / Total Assets
    Zones: Z > 2.99 Safe | 1.81-2.99 Grey | < 1.81 Distress
    mkt_cap_raw must be in RAW currency units (not div-scaled) to match the
    raw-unit balance sheet figures used in this formula.
    """
    ca, _ = _multi_period(bs, "Current Assets", n=1)
    cl, _ = _multi_period(bs, "Current Liabilities", n=1)
    ta, _ = _multi_period(bs, "Total Assets", n=1)
    re_, _ = _multi_period(bs, "Retained Earnings", n=1)
    tl, _ = _multi_period(bs, "Total Liabilities Net Minority Interest",
                           "Total Liabilities", n=1)
    ebit, _ = _multi_period(inc, "EBIT", "Operating Income", n=1)
    sales, _ = _multi_period(inc, "Total Revenue", "Revenue", n=1)

    missing = [name for name, v in [
        ("Current Assets", ca), ("Current Liabilities", cl), ("Total Assets", ta),
        ("Retained Earnings", re_), ("Total Liabilities", tl),
        ("EBIT", ebit), ("Sales", sales)] if not v]
    if missing or ta[0] == 0 or tl[0] == 0:
        return {"value": None, "zone": "N/A",
                "note": f"Missing inputs: {', '.join(missing) if missing else 'zero denominator'}"}

    wc = ca[0] - cl[0]
    A = wc / ta[0]
    B = re_[0] / ta[0]
    C = ebit[0] / ta[0]
    D = (mkt_cap_raw or 0) / tl[0] if mkt_cap_raw else 0
    E = sales[0] / ta[0]
    z = 1.2*A + 1.4*B + 3.3*C + 0.6*D + 1.0*E

    if z > 2.99:   zone = "SAFE — low bankruptcy risk"
    elif z > 1.81: zone = "GREY ZONE — monitor credit metrics"
    else:          zone = "DISTRESS ZONE — elevated bankruptcy risk"
    return {"value": round(z, 2), "zone": zone,
            "note": f"WC/TA {A:.2f} · RE/TA {B:.2f} · EBIT/TA {C:.2f} · "
                    f"MVE/TL {D:.2f} · Sales/TA {E:.2f}"}


def compute_dupont(info, inc, bs, div):
    """
    3-Stage DuPont: ROE = Net Margin x Asset Turnover x Equity Multiplier
    Reveals whether ROE is driven by pricing power (margin), capital
    efficiency (turnover), or leverage (multiplier) — each has very
    different quality/durability implications for a valuation.
    """
    ni, _ = _multi_period(inc, "Net Income", "Net Income Common Stockholders", n=1)
    sales, _ = _multi_period(inc, "Total Revenue", "Revenue", n=1)
    ta, _ = _multi_period(bs, "Total Assets", n=1)
    eq, _ = _multi_period(bs, "Stockholders Equity", "Total Equity Gross Minority Interest",
                           "Common Stock Equity", n=1)

    if not (ni and sales and ta and eq) or sales[0] == 0 or ta[0] == 0 or eq[0] == 0:
        return {"net_margin": None, "asset_turnover": None, "equity_multiplier": None,
                "roe_check": None, "driver": "N/A",
                "note": "Missing one or more of Net Income / Revenue / Total Assets / Equity."}

    net_margin = ni[0] / sales[0]
    asset_turnover = sales[0] / ta[0]
    equity_multiplier = ta[0] / eq[0]
    roe_check = net_margin * asset_turnover * equity_multiplier

    components = {"Margin": net_margin, "Turnover": asset_turnover / 3,  # rough normalization for comparison
                  "Leverage": (equity_multiplier - 1) / 2}
    driver = max(components, key=components.get)
    driver_note = {
        "Margin": "Pricing power / cost control is the primary ROE driver",
        "Turnover": "Capital efficiency (asset utilization) is the primary ROE driver",
        "Leverage": "Financial leverage is doing much of the work — check sustainability",
    }[driver]

    return {"net_margin": round(net_margin*100, 2), "asset_turnover": round(asset_turnover, 2),
            "equity_multiplier": round(equity_multiplier, 2), "roe_check": round(roe_check*100, 2),
            "driver": driver, "note": driver_note}


def compute_roic_wacc_spread(inc, bs, wacc, tax_rate=0.25):
    """
    ROIC = NOPAT / Invested Capital ; Spread = ROIC - WACC
    Positive spread = economic value creation (EVA > 0, i.e. a real moat).
    Negative spread = the firm is destroying capital even if "profitable"
    on a simple net-income basis.
    """
    ebit, _ = _multi_period(inc, "EBIT", "Operating Income", n=1)
    debt, _ = _multi_period(bs, "Total Debt", n=1)
    eq, _ = _multi_period(bs, "Stockholders Equity", "Total Equity Gross Minority Interest",
                           "Common Stock Equity", n=1)
    cash, _ = _multi_period(bs, "Cash And Cash Equivalents",
                             "Cash Cash Equivalents And Short Term Investments", n=1)

    if not (ebit and debt and eq) or (debt[0] + eq[0] - (cash[0] if cash else 0)) <= 0:
        return {"roic": None, "spread": None,
                "note": "Missing EBIT / Debt / Equity, or non-positive invested capital."}

    nopat = ebit[0] * (1 - tax_rate)
    invested_capital = debt[0] + eq[0] - (cash[0] if cash else 0)
    roic = nopat / invested_capital
    spread = (roic * 100) - wacc

    if spread > 3:      verdict = "STRONG ECONOMIC MOAT — value creation well above cost of capital"
    elif spread > 0:    verdict = "MODEST VALUE CREATION — ROIC exceeds WACC"
    elif spread > -3:   verdict = "ROUGHLY VALUE-NEUTRAL — ROIC near WACC"
    else:                verdict = "VALUE DESTRUCTIVE — ROIC below cost of capital"
    return {"roic": round(roic*100, 2), "spread": round(spread, 2), "verdict": verdict,
            "note": f"NOPAT {nopat:,.0f} / Invested Capital {invested_capital:,.0f} "
                    f"(tax rate assumption: {tax_rate*100:.0f}%)"}


def compute_normalized_fcf(cf, inc, revenue_ttm, div, ttm_fcf):
    """
    Normalized FCF Margin = median(FCF_t, FCF_t-1, FCF_t-2) / Revenue_TTM
    Smooths one-off CapEx spikes / working-capital swings. If TTM FCF
    deviates >40% from this normalized base (or is negative while the
    normalized base is healthy), the normalized figure is recommended as
    the safer DCF starting point, with an audit flag raised.
    """
    ocf_hist, _ = _multi_period(cf, "Operating Cash Flow",
                                 "Total Cash From Operating Activities", n=3)
    capex_hist, _ = _multi_period(cf, "Capital Expenditure", "capitalExpenditures", n=3)
    sales_hist, _ = _multi_period(inc, "Total Revenue", "Revenue", n=3)

    if len(ocf_hist) < 2 or len(sales_hist) < 2:
        return {"normalized_fcf": None, "normalized_margin": None,
                "flag": False, "note": "Fewer than 2 historical periods available — cannot normalize."}

    n = min(len(ocf_hist), len(capex_hist) if capex_hist else len(ocf_hist), len(sales_hist))
    fcf_hist = []
    for i in range(n):
        capex = abs(capex_hist[i]) if capex_hist and i < len(capex_hist) else 0
        fcf_hist.append(ocf_hist[i] - capex)
    margin_hist = [fcf_hist[i] / sales_hist[i] for i in range(n) if sales_hist[i] != 0]

    if not margin_hist:
        return {"normalized_fcf": None, "normalized_margin": None,
                "flag": False, "note": "Revenue history unusable (zero values)."}

    median_margin = sorted(margin_hist)[len(margin_hist)//2]
    normalized_fcf = median_margin * revenue_ttm

    flag = False
    note = f"3-yr median FCF margin {median_margin*100:.1f}% applied to TTM Revenue."
    if ttm_fcf and normalized_fcf != 0:
        deviation = abs(ttm_fcf - normalized_fcf) / abs(normalized_fcf)
        if deviation > 0.40 or (ttm_fcf < 0 and normalized_fcf > 0):
            flag = True
            note += (f" ⚠ TTM FCF ({ttm_fcf/div:,.0f}) deviates {deviation*100:.0f}% from "
                     f"the normalized base ({normalized_fcf/div:,.0f}) — normalized figure "
                     "recommended as the DCF starting point instead of raw TTM.")
    return {"normalized_fcf": round(normalized_fcf, 2), "normalized_margin": round(median_margin*100, 2),
            "flag": flag, "note": note}

# ═══════════════════════════════════════════════════════════════════════════
# REVERSE DCF SOLVER + DYNAMIC WACC FADE + BLUME BETA
# ═══════════════════════════════════════════════════════════════════════════

def blume_adjusted_beta(raw_beta):
    """
    Blume (1975) adjustment toward the market mean (1.0):
        beta_adj = 2/3 * beta_raw + 1/3 * 1.0
    NOTE: this is computed and DISPLAYED as a secondary/reference metric only.
    The app's actual WACC/DCF math continues to use raw, unadjusted beta —
    per an explicit standing instruction earlier in this project not to
    smooth or clamp beta for the primary calculation. Both numbers are shown
    side by side so nothing is decided silently.
    """
    if raw_beta is None:
        return None
    return round((2/3) * raw_beta + (1/3) * 1.0, 3)


def fade_wacc_schedule(wacc_stage1, terminal_wacc=8.25, years=10):
    """
    Linearly fades the discount rate from the company's Stage-1 WACC/Ke down
    (or up) to a mature-market long-run average by Year `years`. Real
    high-growth/high-risk companies don't retain elevated risk forever as
    they mature — using a single static WACC across 10 years overstates the
    discount applied to later, more mature-looking cash flows.
    Returns a list of `years` discount rates, one per projection year.
    """
    if years <= 1:
        return [wacc_stage1] * max(years, 1)
    step = (terminal_wacc - wacc_stage1) / (years - 1)
    return [round(wacc_stage1 + step * i, 4) for i in range(years)]


def run_dcf_dynamic_wacc(fcf, wacc_schedule, g1, g2, tr, nd, so, market_div, model="FCFF"):
    """
    Same cash-flow projection logic as the core run_dcf(), but discounts each
    year's cash flow at ITS OWN rate from `wacc_schedule` (a fading WACC) via
    compounding period-by-period discount factors, rather than one constant
    rate applied uniformly across all 10 years.
    """
    terminal_wacc = wacc_schedule[-1]
    if tr >= terminal_wacc:
        tr = max(terminal_wacc - 0.5, 0.1)

    proj = []; pv_fs = []; cf = fcf; cum_disc = 1.0
    for yr in range(1, 11):
        r = g1/100 if yr <= 5 else g2/100
        cf = cf * (1 + r)
        yr_wacc = wacc_schedule[yr-1]
        cum_disc *= (1 + yr_wacc/100)
        pv = cf / cum_disc
        proj.append({"Year": f"Y{yr}", "FCF": round(cf, 2), "WACC": f"{yr_wacc:.2f}%",
                     "Growth Rate": f"{r*100:.1f}%", "PV Factor": round(1/cum_disc, 4),
                     "PV of FCF": round(pv, 2)})
        pv_fs.append(pv)

    tv_fcf = proj[-1]["FCF"] * (1 + tr/100)
    tv = tv_fcf / (terminal_wacc/100 - tr/100)
    pv_tv = tv / cum_disc
    sum_pv = sum(pv_fs); ev = sum_pv + pv_tv
    eq = ev if model in ("FCFE", "DDM") else ev - nd
    ip = (eq * market_div) / so if so > 0 else 0
    return {"projections": proj, "pv_fcfs": pv_fs, "pv_terminal": pv_tv,
            "sum_pv_fcf": sum_pv, "enterprise_val": ev, "equity_val": eq,
            "intrinsic_price": ip, "model": model, "wacc_schedule": wacc_schedule}


def reverse_dcf_solve(current_price, fcf, nd, so, market, model="FCFF",
                       wacc=9.0, g2=3.0, tr=2.5, max_iter=100, tol=1e-4):
    """
    Solves for the single Stage-1 growth rate g1 (Years 1-5, held constant,
    with Years 6-10 fading to g2, matching the forward model's shape) that
    makes the DCF's intrinsic price exactly equal the current market price.
    Uses bisection — monotonic and numerically stable for this kind of
    problem, unlike Newton's method which can diverge on a flat objective.
    `market` is the real market key (e.g. "USA \U0001F1FA\U0001F1F8") so this
    reuses the existing, already-verified run_dcf() unmodified.
    Returns (implied_growth_rate_pct, iterations_used, converged_bool).
    """
    def price_at_growth(g1):
        res = run_dcf(fcf, wacc, g1, g2, tr, nd, so, current_price, market, model)
        return res["intrinsic_price"]

    lo, hi = -20.0, 60.0
    price_lo = price_at_growth(lo)
    price_hi = price_at_growth(hi)

    # If the target price isn't bracketed by this range, the company's
    # current price already implies an extreme (near limitless or negative)
    # growth expectation -- report the boundary rather than a false solve.
    if current_price <= price_lo:
        return lo, 0, False
    if current_price >= price_hi:
        return hi, 0, False

    for i in range(max_iter):
        mid = (lo + hi) / 2
        price_mid = price_at_growth(mid)
        if abs(price_mid - current_price) < tol * max(current_price, 1):
            return round(mid, 2), i+1, True
        if price_mid < current_price:
            lo = mid
        else:
            hi = mid
    return round((lo+hi)/2, 2), max_iter, False

# ═══════════════════════════════════════════════════════════════════════════
# MULTI-YEAR FINANCIALS, CONSENSUS ESTIMATES, LIVE TREASURY YIELD, THESIS GEN
# ═══════════════════════════════════════════════════════════════════════════

def fetch_multi_year_financials(inc, cf, div, n=3):
    """
    Extracts up to `n` most-recent historical years of Revenue, EBITDA (proxied
    by EBIT if EBITDA itself isn't a line item), EPS-equivalent (Net Income),
    and FCF (Operating CF - CapEx) from the ALREADY-FETCHED income statement
    and cash flow DataFrames -- no new network call. Returns a list of dicts,
    newest year first, each possibly with None for any line that genuinely
    isn't available that year (never fabricated).
    """
    rev_vals, _ = _multi_period(inc, "Total Revenue", "Revenue", n=n)
    ebit_vals, _ = _multi_period(inc, "EBIT", "Operating Income", n=n)
    ni_vals, _ = _multi_period(inc, "Net Income", "Net Income Common Stockholders", n=n)
    ocf_vals, _ = _multi_period(cf, "Operating Cash Flow",
                                 "Total Cash From Operating Activities", n=n)
    capex_vals, _ = _multi_period(cf, "Capital Expenditure", "capitalExpenditures", n=n)

    years = max(len(rev_vals), len(ebit_vals), len(ni_vals), len(ocf_vals))
    out = []
    for i in range(min(years, n)):
        fcf = None
        if i < len(ocf_vals):
            capex = abs(capex_vals[i]) if i < len(capex_vals) else 0
            fcf = ocf_vals[i] - capex
        out.append({
            "revenue": round(rev_vals[i]/div, 1) if i < len(rev_vals) else None,
            "ebitda":  round(ebit_vals[i]/div, 1) if i < len(ebit_vals) else None,
            "net_income": round(ni_vals[i]/div, 1) if i < len(ni_vals) else None,
            "fcf": round(fcf/div, 1) if fcf is not None else None,
        })
    return out


def fetch_consensus_estimates(ticker):
    """
    Best-effort fetch of forward analyst consensus (revenue/earnings growth)
    via yfinance's earnings_estimate / revenue_estimate properties.
    CAVEAT: this specific yfinance endpoint has NOT been verified against
    live data -- it has a documented history of inconsistent field names and
    availability across yfinance versions and tickers, unlike every other
    data path in this app. This function is maximally defensive: any
    unexpected shape, missing attribute, or empty result degrades cleanly to
    "unavailable" rather than raising or fabricating a number, and nothing
    else in the app depends on this succeeding.
    """
    try:
        t = yf.Ticker(ticker)
        est = getattr(t, "earnings_estimate", None)
        if est is None or not hasattr(est, "empty") or est.empty:
            return {"available": False, "note": "Consensus estimate data not available for this ticker."}
        row = None
        for candidate_idx in ["+1y", "0y", "+1q"]:
            if candidate_idx in est.index:
                row = est.loc[candidate_idx]
                break
        if row is None:
            return {"available": False, "note": "Expected consensus period rows not found in response."}
        growth = row.get("growth") if hasattr(row, "get") else None
        avg_eps = row.get("avg") if hasattr(row, "get") else None
        n_analysts = row.get("numberOfAnalysts") if hasattr(row, "get") else None
        if growth is None and avg_eps is None:
            return {"available": False, "note": "Consensus row found but contained no usable figures."}
        return {"available": True,
                "eps_growth_pct": round(float(growth)*100, 1) if growth is not None else None,
                "avg_eps_estimate": round(float(avg_eps), 2) if avg_eps is not None else None,
                "num_analysts": int(n_analysts) if n_analysts else None,
                "note": "Source: yfinance consensus estimate (best-effort; verify against a primary source)."}
    except Exception as e:
        return {"available": False, "note": f"Consensus fetch failed ({type(e).__name__}) — not available."}


def fetch_live_treasury_yield(fallback_rate):
    """
    Attempts to fetch the live 10Y US Treasury yield via yfinance's ^TNX
    index. CAVEAT: like fetch_consensus_estimates, this has NOT been
    verified against live data in this app's build environment. ^TNX's
    quoting convention has also historically been a source of confusion
    (some feeds show the yield directly, e.g. 4.25 for 4.25%; legacy
    CBOE-index-style feeds show it x10, e.g. 42.5) -- this checks both
    interpretations for plausibility and falls back to the existing static
    rate if neither is plausible, so a live-fetch mistake can never
    silently corrupt the WACC calculation with a nonsensical rate.
    Returns (rate_percent, was_live: bool).
    """
    try:
        info = _safe_info("^TNX")
        if not info:
            return fallback_rate, False
        raw = info.get("regularMarketPrice") or info.get("previousClose") or info.get("currentPrice")
        if raw is None:
            return fallback_rate, False
        raw = float(raw)
        if 0.1 <= raw <= 20.0:
            return round(raw, 2), True
        if 1.0 <= raw/10 <= 20.0:
            return round(raw/10, 2), True
        return fallback_rate, False
    except Exception:
        return fallback_rate, False


def generate_investment_thesis(data, dcf_res, intrinsic, upside, verdict, forensics,
                                model_label, rate_label, wacc, currency, unit):
    """
    Deterministic 3-paragraph thesis synthesized from computed metrics —
    template-based, not a language model, so it is exactly reproducible and
    audit-safe. Uses this app's existing CONVICTION framing throughout
    (not formal Overweight/Underweight ratings) to stay consistent with its
    compliance posture: EquityLens is not a registered investment adviser
    and does not issue formal ratings, only a description of how price
    compares to modeled intrinsic value.
    """
    ticker = data["ticker"]; name = data["long_name"]
    # Unambiguous "above/below" phrasing instead of "premium/discount to X" --
    # that wording is genuinely ambiguous depending on which value (intrinsic
    # or market) is treated as the grammatical subject, and got the direction
    # backwards in an earlier version as a result. "Market price sits X%
    # above/below intrinsic value" cannot be misread the same way, and it
    # matches the "Upside / Downside" terminology already used on the
    # dashboard's metric cards, so the whole report is now internally
    # consistent about what a positive vs negative number means.
    rel_word = "below" if upside > 0 else "above"
    conviction_phrase = {"HIGH CONVICTION": "a high-conviction", "MODERATE CONVICTION": "a moderate-conviction",
                          "LOW CONVICTION": "a low-conviction"}.get(verdict, "a")

    # Paragraph 1 — thesis statement
    p1 = (f"Our {model_label} discounted cash flow model estimates an intrinsic value for "
          f"{name} ({ticker}) of {currency}{intrinsic:,.2f} per share. The current market price of "
          f"{currency}{data['price']:,.2f} sits {abs(upside):.1f}% {rel_word} that estimate. This "
          f"supports {conviction_phrase} model read on the name at today's price.")
    roic = forensics.get("roic_spread", {})
    if roic.get("spread") is not None:
        moat_phrase = roic["verdict"].split("—")[-1].strip().lower() if "—" in roic.get("verdict","") else ""
        p1 += (f" The valuation is underpinned by an estimated {roic['spread']:+.1f} percentage-point "
               f"ROIC-{rate_label} spread ({roic['roic']:.1f}% ROIC vs {wacc:.1f}% {rate_label})"
               f"{', indicating ' + moat_phrase if moat_phrase else ''}.")

    # Paragraph 2 — operational driver
    dupont = forensics.get("dupont", {})
    if dupont.get("roe_check") is not None:
        p2 = (f"Return on equity of {dupont['roe_check']:.1f}% decomposes into a "
              f"{dupont['net_margin']:.1f}% net margin, {dupont['asset_turnover']:.2f}x asset "
              f"turnover, and a {dupont['equity_multiplier']:.2f}x equity multiplier. "
              f"{dupont['note']}.")
    else:
        p2 = "Insufficient multi-period balance sheet and income statement data were available to decompose ROE via DuPont analysis for this name."
    norm_fcf = forensics.get("normalized_fcf", {})
    if norm_fcf.get("flag"):
        p2 += f" Note: {norm_fcf['note']}"

    # Paragraph 3 — balance sheet health
    nd = data.get("net_debt", 0)
    nd_desc = f"a net cash position of {currency}{abs(nd):,.0f}{unit}" if nd < 0 else f"net debt of {currency}{nd:,.0f}{unit}"
    p3 = f"The balance sheet carries {nd_desc}."
    altman = forensics.get("altman", {})
    if altman.get("value") is not None:
        # Use the ZONE NAME (before the em-dash), not its description, so
        # this reads as "...in the grey zone" not "...in the monitor credit
        # metrics" (which was the earlier, grammatically broken version).
        zone_phrase = altman["zone"].split("—")[0].strip().lower() if "—" in altman.get("zone","") else altman.get("zone","").lower()
        p3 += f" An Altman Z-Score of {altman['value']:.2f} places the company's credit profile in the {zone_phrase}."
    sloan = forensics.get("sloan", {})
    if sloan.get("value") is not None:
        p3 += f" A Sloan Accruals Ratio of {sloan['value']*100:.1f}% suggests {sloan['verdict'].split('—')[-1].strip().lower() if '—' in sloan.get('verdict','') else sloan.get('verdict','').lower()}."
    p3 += (" This is model output synthesized from public financial statement data — not a recommendation "
           "to buy, sell, or hold this security.")

    return p1, p2, p3

# ─────────────────────────────────────────────────────────────────────────────
# RATIO SCALING
# ─────────────────────────────────────────────────────────────────────────────
def fix_ratio(val, field):
    if val is None: return 0.0
    try:
        v = float(val)
    except (TypeError, ValueError):
        return 0.0
    if v == 0: return 0.0
    if field == "dividendYield":
        return round(v * 100, 4) if v <= 1.0 else (round(v, 4) if v <= 100 else round(v / 100, 4))
    if field in ("ps_ratio", "ev_ebitda", "ev_revenue", "pb_ratio"):
        thresholds = {"ps_ratio": 80, "ev_ebitda": 150, "ev_revenue": 40, "pb_ratio": 40}
        return round(v / 100, 4) if v > thresholds.get(field, 150) else round(v, 4)
    if field == "roe":
        return round(v * 100, 2) if abs(v) <= 5.0 else round(v, 2)
    if field == "net_margin":
        return round(v * 100, 2) if abs(v) <= 5.0 else round(v, 2)
    return round(v, 4)

# ─────────────────────────────────────────────────────────────────────────────
# MODEL ROUTING
# ─────────────────────────────────────────────────────────────────────────────
FINANCIAL_SECTORS = {"Financial Services","Banks","Insurance","Diversified Financials","Finance"}
REIT_KEYWORDS     = ["reit","real estate investment","property trust"]
BANK_KEYWORDS     = ["bank","banking","savings","credit","mortgage","nbfc","microfinance"]

def detect_model(sector, industry):
    s = (sector or "").lower(); i = (industry or "").lower()
    if any(k in i for k in REIT_KEYWORDS):              return "DDM"
    if any(k in s+i for k in BANK_KEYWORDS):            return "FCFE"
    if sector in FINANCIAL_SECTORS:                      return "FCFE"
    if any(k in s+i for k in ["insurance","asset management","brokerage"]): return "DDM"
    return "FCFF"

def discount_rate_label(model):
    return "Cost of Equity (Ke)" if model in ("FCFE","DDM") else "WACC"

# ─────────────────────────────────────────────────────────────────────────────
# NET DEBT — date-sorted, multi-field, fuzzy-fallback, self-diagnosing
# ─────────────────────────────────────────────────────────────────────────────
CASH_FIELDS = [
    "Cash And Cash Equivalents",
    "Cash Cash Equivalents And Short Term Investments",
    "Cash And Short Term Investments",
    "Cash",
    "cashAndCashEquivalents",
    "CashAndCashEquivalentsAtCarryingValue",
]
DEBT_FIELDS = [
    "Total Debt",
    "Total Debt And Capital Lease Obligation",
    "Long Term Debt And Capital Lease Obligation",
    "Long Term Debt",
    "Short Long Term Debt",
    "LongTermDebt",
    "CurrentDebt",
    "ShortLongTermDebt",
]

def _find_bs_value(df, exact_names, fuzzy_tokens):
    """
    Search a balance-sheet-shaped DataFrame (columns = fiscal period dates)
    for a value, in two passes:
      1. Exact row-label match against `exact_names`, tried in priority order.
      2. Case-insensitive substring match: the first row whose label contains
         every token in `fuzzy_tokens` (catches yfinance row-name variants
         that don't match any exact candidate, which otherwise silently fall
         through to a less reliable fallback with no visible explanation).
    Columns are sorted newest-first before searching, so whichever field
    matches, the most recent non-null figure for it is used.
    Returns (value, field_name_actually_used, fiscal_period_label) or
    (None, None, None) if nothing matched.
    """
    if df is None or df.empty:
        return None, None, None
    try:
        df_sorted = df.sort_index(axis=1, ascending=False)
    except Exception:
        df_sorted = df

    def _extract(row_label):
        try:
            series = df_sorted.loc[row_label]
            if isinstance(series, pd.DataFrame):   # duplicate-labeled rows
                series = series.iloc[0]
            series = series.dropna()
            if not series.empty:
                return float(series.iloc[0]), str(series.index[0])
        except Exception:
            pass
        return None, None

    for name in exact_names:
        if name in df_sorted.index:
            val, period = _extract(name)
            if val is not None:
                return val, name, period

    if fuzzy_tokens:
        for idx_name in df_sorted.index:
            low = str(idx_name).lower()
            if all(tok in low for tok in fuzzy_tokens):
                val, period = _extract(idx_name)
                if val is not None:
                    return val, str(idx_name), period

    return None, None, None

def compute_net_debt(bs, info, div, data_warnings, missing_fields):
    """
    Three-tier strategy, most-reliable first:
      1. Balance sheet, exact field-name match, date-sorted.
      2. Balance sheet, fuzzy (substring) field-name match — catches
         yfinance row-label variants an exact whitelist would miss.
      3. info-dict totalDebt / totalCash — a DIFFERENT, less reliable Yahoo
         endpoint used only when the balance sheet itself is unusable.
      4. 0.0, logged as missing — last resort.
    Returns (net_debt_value_in_div_scaled_units, basis_description_string).
    The basis string always states exactly which field(s), period(s), and
    tier produced the number, so a wrong figure is diagnosable at a glance
    instead of a black box.
    """
    if bs is not None and not bs.empty:
        cash_v, cash_f, cash_p = _find_bs_value(bs, CASH_FIELDS, ["cash"])
        debt_v, debt_f, debt_p = _find_bs_value(bs, DEBT_FIELDS, ["debt"])
        if cash_v is not None and debt_v is not None:
            basis = (f"Balance sheet: Total Debt {debt_v/div:,.0f} (row '{debt_f}', "
                     f"period {debt_p[:10]}) − Cash {cash_v/div:,.0f} (row '{cash_f}', "
                     f"period {cash_p[:10]})")
            if cash_p != debt_p:
                data_warnings.append(
                    f"Net Debt combines Cash from {cash_p[:10]} with Total Debt from "
                    f"{debt_p[:10]} — the two most-recent fiscal periods for these rows "
                    "didn't align exactly. Verify against published financials if this matters.")
            return round((debt_v - cash_v) / div, 2), basis
        if debt_v is not None:
            data_warnings.append(
                f"No cash row matched on the balance sheet (checked {len(CASH_FIELDS)} exact names "
                "plus a fuzzy 'cash' search) — Net Debt equals Total Debt only and is likely overstated.")
            return round(debt_v / div, 2), f"Balance sheet: Total Debt only, {debt_v/div:,.0f} (row '{debt_f}')"

    # Tier 2: info dict — a different, less reliable endpoint than the
    # annual balance sheet; only reached if the statement itself failed.
    total_debt = _f(info.get("totalDebt"))
    total_cash = _f(info.get("totalCash") or info.get("cashAndCashEquivalentsAtCarryingValue"))
    if total_debt > 0 or total_cash > 0:
        data_warnings.append(
            f"Balance-sheet statement had no recognizable Cash/Debt rows (checked "
            f"{len(CASH_FIELDS)+len(DEBT_FIELDS)} exact names plus fuzzy matching) — Net Debt "
            f"computed instead from Yahoo's summary fields (totalDebt={total_debt/div:,.0f}, "
            f"totalCash={total_cash/div:,.0f}). This endpoint can lag the annual balance sheet — "
            "verify against the company's published financials if this figure looks off.")
        return round((total_debt - total_cash) / div, 2), (
            f"Info-dict fallback: totalDebt {total_debt/div:,.0f} − totalCash {total_cash/div:,.0f} "
            "(balance sheet unavailable)")

    missing_fields.append("Net Debt")
    return 0.0, "Not available — no balance sheet or info-dict figures found."

# ─────────────────────────────────────────────────────────────────────────────
# MACROS & CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
MACROS = {
    "India 🇮🇳":  {"risk_free_rate":7.1,  "market_premium":6.5, "currency":"₹","unit":"Cr","div":1e7},
    "USA 🇺🇸":    {"risk_free_rate":4.3,  "market_premium":4.6, "currency":"$","unit":"M", "div":1e6},
    "UK 🇬🇧":     {"risk_free_rate":4.15, "market_premium":5.0, "currency":"£","unit":"M", "div":1e6},
    "France 🇫🇷": {"risk_free_rate":3.0,  "market_premium":5.5, "currency":"€","unit":"M", "div":1e6},
    "Germany 🇩🇪":{"risk_free_rate":2.8,  "market_premium":5.2, "currency":"€","unit":"M", "div":1e6},
    "Europe 🇪🇺": {"risk_free_rate":3.2,  "market_premium":5.3, "currency":"€","unit":"M", "div":1e6},
}
TICKER_HINTS = {
    "India 🇮🇳":  "NSE tickers: TCS.NS · RELIANCE.NS · INFY.NS",
    "USA 🇺🇸":    "US tickers: AAPL · MSFT · GOOGL",
    "UK 🇬🇧":     "LSE tickers: SHEL.L · BP.L · HSBA.L",
    "France 🇫🇷": "Euronext: AIR.PA · TTE.PA · BNP.PA",
    "Germany 🇩🇪": "XETRA: SAP.DE · BMW.DE · SIE.DE",
    "Europe 🇪🇺": "Exchange suffix: .PA .DE .AS .MI  e.g. ASML.AS",
}
CF_LABEL_LONG  = {"FCFF":"Free Cash Flow (FCFF)","FCFE":"Net Income — FCFE proxy","DDM":"Dividends Paid — DDM base"}
CF_LABEL_SHORT = {"FCFF":"Free Cash Flow","FCFE":"Net Income","DDM":"Dividends Paid"}

PEERS = {
    "India 🇮🇳": {
        "Large-cap IT":         ["TCS.NS","INFY.NS","WIPRO.NS","HCLTECH.NS","TECHM.NS"],
        "Mid-cap IT":           ["MPHASIS.NS","COFORGE.NS","LTIM.NS","PERSISTENT.NS"],
        "Private Banks":        ["HDFCBANK.NS","ICICIBANK.NS","KOTAKBANK.NS","AXISBANK.NS","INDUSINDBK.NS"],
        "PSU Banks":            ["SBIN.NS","BANKBARODA.NS","PNB.NS","CANBK.NS"],
        "NBFC":                 ["BAJFINANCE.NS","BAJAJFINSV.NS","CHOLAFIN.NS","M&MFIN.NS"],
        "FMCG — Staples":       ["HINDUNILVR.NS","ITC.NS","NESTLEIND.NS","DABUR.NS","MARICO.NS"],
        "FMCG — Discretionary": ["TITAN.NS","TRENT.NS","ABFRL.NS"],
        "Paints & Adhesives":   ["ASIANPAINT.NS","BERGEPAINT.NS","PIDILITIND.NS","KANSAINER.NS"],
        "Auto OEM":             ["MARUTI.NS","TATAMOTORS.NS","M&M.NS","BAJAJ-AUTO.NS","HEROMOTOCO.NS"],
        "Auto Ancillary":       ["BOSCHLTD.NS","MOTHERSON.NS","APOLLOTYRE.NS","MRF.NS"],
        "Pharma — Domestic":    ["SUNPHARMA.NS","CIPLA.NS","TORNTPHARM.NS","ALKEM.NS"],
        "Pharma — Export":      ["DRREDDY.NS","DIVISLAB.NS","AUROBINDO.NS","LUPIN.NS"],
        "Refiners & OMC":       ["RELIANCE.NS","BPCL.NS","IOC.NS"],
        "E&P":                  ["ONGC.NS","OIL.NS"],
        "Metals — Steel":       ["TATASTEEL.NS","JSWSTEEL.NS","SAIL.NS","WELCORP.NS","JSPL.NS"],
        "Metals — Non-Ferrous": ["HINDALCO.NS","NALCO.NS","VEDL.NS","NMDC.NS"],
        "Telecom":              ["BHARTIARTL.NS","INDUSTOWER.NS"],
        "Hospitals":            ["APOLLOHOSP.NS","MAXHEALTH.NS","FORTIS.NS"],
        "Diagnostics":          ["METROPOLIS.NS","LALPATHLAB.NS"],
        "Specialty Chemicals":  ["PIIND.NS","ALKYLAMINE.NS","NAVINFLUOR.NS"],
        "Infra & Construction": ["LT.NS","NTPC.NS","POWERGRID.NS","IRFC.NS"],
    },
    "USA 🇺🇸": {
        "Mega-cap Tech":      ["AAPL","MSFT","GOOGL","META","NVDA"],
        "Software — Cloud":   ["CRM","NOW","SNOW","WDAY","HUBS"],
        "Semiconductors":     ["NVDA","AMD","INTC","QCOM","AVGO"],
        "Large-cap Banks":    ["JPM","BAC","WFC","C","USB"],
        "Investment Banks":   ["GS","MS","BLK","SCHW","AXP"],
        "Insurance":          ["MET","PRU","ALL","TRV","PGR"],
        "Large Pharma":       ["JNJ","PFE","ABBV","MRK","BMY"],
        "Biotech":            ["AMGN","GILD","REGN","BIIB","VRTX"],
        "Consumer Staples":   ["PG","KO","PEP","CL","KMB"],
        "E-commerce":         ["AMZN","EBAY","ETSY","CHWY"],
        "Discount Retail":    ["WMT","COST","TGT","DG","DLTR"],
        "Energy — Majors":    ["XOM","CVX","COP","OXY","EOG"],
        "Utilities":          ["NEE","DUK","SO","AEP"],
        "Telecom":            ["T","VZ","TMUS"],
        "Industrials — Aero": ["BA","LMT","RTX","NOC","GD"],
        "EV & Auto":          ["TSLA","F","GM"],
    },
    "UK 🇬🇧": {
        "Integrated Energy":    ["SHEL.L","BP.L"],
        "Large Banks":          ["HSBA.L","LLOY.L","BARC.L","NWG.L"],
        "Insurance":            ["AV.L","LGEN.L","PRU.L"],
        "Pharma — Major":       ["AZN.L","GSK.L"],
        "Consumer Staples":     ["ULVR.L","DGE.L","ABF.L"],
        "Mining — Diversified": ["RIO.L","BHP.L","AAL.L","GLEN.L"],
        "Telecom":              ["BT-A.L","VOD.L"],
        "Aerospace & Defence":  ["BA.L","RR.L"],
    },
    "France 🇫🇷": {
        "Luxury — Major":       ["MC.PA","RMS.PA","CFR.PA"],
        "Luxury — Other":       ["KER.PA","OR.PA"],
        "Consumer Staples":     ["BN.PA","RI.PA","CA.PA"],
        "Aerospace":            ["AIR.PA","SAF.PA","HO.PA"],
        "Energy":               ["TTE.PA","ENGI.PA"],
        "Utilities":            ["VIE.PA","ENGI.PA"],
        "Large Banks":          ["BNP.PA","ACA.PA","GLE.PA"],
        "Insurance":            ["CS.PA"],
        "Tech / IT Services":   ["CAP.PA","ATO.PA"],
        "Pharma & Healthcare":  ["SAN.PA","EL.PA"],
        "Industrials":          ["SU.PA","LR.PA","ALO.PA","DG.PA"],
        "Materials":            ["SGO.PA","AI.PA"],
        "Telecom":              ["ORA.PA"],
    },
    "Germany 🇩🇪": {
        "Auto — Premium":      ["BMW.DE","MBG.DE","PAH3.DE"],
        "Auto — Volume":       ["VOW3.DE","MAN.DE"],
        "Software":            ["SAP.DE"],
        "Industrials":         ["SIE.DE","AIXA.DE"],
        "Chemicals":           ["BAYN.DE","BASF.DE","LIN.DE"],
        "Finance / Insurance": ["DBK.DE","ALV.DE","MUV2.DE"],
        "Consumer":            ["ADS.DE","BEI.DE"],
        "Utilities":           ["EOAN.DE","RWE.DE"],
        "Telecom":             ["DTE.DE"],
    },
    "Europe 🇪🇺": {
        "Semiconductors":      ["ASML.AS","STM.MI","IFX.DE"],
        "Luxury":              ["MC.PA","OR.PA","RMS.PA","CFR.PA"],
        "Energy — Integrated": ["TTE.PA","SHEL.L","ENI.MI"],
        "Large Banks":         ["BNP.PA","HSBA.L","SAN.MC","UCG.MI"],
        "Pharma — Major":      ["NVS","ROG.SW","AZN.L","NVO"],
        "Software / Tech":     ["SAP.DE","CAP.PA","ASML.AS"],
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# DATA FETCHING
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def fetch_company_data(ticker, market):
    macro = MACROS[market]; div = macro["div"]
    data_warnings = []; missing_fields = []

    info = _safe_info(ticker)
    if not info:
        try:
            dl = yf.download(ticker, period="1d", progress=False, auto_adjust=True)
            if dl is not None and not dl.empty:
                price_fb = float(dl["Close"].iloc[-1])
                return {"error":None,"ticker":ticker,"long_name":ticker,
                        "sector":"","industry":"","summary":"","exchange":"",
                        "country_hq":"","employees":0,"valuation_model":"FCFF",
                        "cf_basis":"fallback","net_debt_basis":"Full data fetch failed",
                        "beta":1.0,"fcf":0.0,"net_debt":0.0,
                        "mkt_cap":0.0,"price":price_fb,"revenue":0.0,"ebitda":0.0,
                        "shares_out":1,"div_yield":0.0,"pe_ratio":0.0,"pb_ratio":0.0,
                        "ps_ratio":0.0,"ev_ebitda":0.0,"roe":0.0,"debt_equity":0.0,
                        "curr_ratio":0.0,"net_margin":0.0,"eps":0.0,
                        "data_warnings":["⚠️ Full data fetch failed — only price recovered. "
                                         "Wait 60 s and retry, or switch network/VPN."],
                        "missing_fields":["All financial data"]}
        except Exception:
            pass
        return {"error": "Yahoo Finance returned no data. The ticker may be wrong, "
                         "markets may be closed, or you are temporarily rate-limited. "
                         "Wait 60 seconds and try again."}

    time.sleep(0.4)
    cf  = _safe_fetch("cashflow",      ticker)
    time.sleep(0.4)
    bs  = _safe_fetch("balance_sheet", ticker)
    time.sleep(0.4)
    inc = _safe_fetch("financials",    ticker)

    price    = _f(info.get("currentPrice") or info.get("regularMarketPrice")
                  or info.get("previousClose") or info.get("regularMarketPreviousClose")
                  or info.get("open") or info.get("regularMarketOpen"))
    shares   = info.get("sharesOutstanding") or 1
    raw_mkt_cap = info.get("marketCap")
    if raw_mkt_cap:
        mkt_cap = _f(raw_mkt_cap) / div
    elif price > 0 and shares > 1:
        mkt_cap = (price * shares) / div
        data_warnings.append(
            "Market Cap not returned by the API — derived from Price × Shares "
            "Outstanding instead (mathematically equivalent, not an approximation).")
    else:
        mkt_cap = 0.0
        missing_fields.append("Market Cap")
    ebitda   = _f(info.get("ebitda")) / div
    sector   = info.get("sector","") or ""
    industry = info.get("industry","") or ""
    val_model= detect_model(sector, industry)

    # ── Starting cash flow — model-aware ─────────────────────────────────────
    fcf = None; cf_basis = ""

    if val_model == "FCFF":
        cf_basis = "Operating Cash Flow − CapEx (standard unlevered FCFF)"
        ocf = _latest(cf,
            "Operating Cash Flow",
            "Total Cash From Operating Activities",
            "Cash From Operations")
        cap = _latest(cf, "Capital Expenditure", "capitalExpenditures",
                      "Purchase Of Property Plant And Equipment")
        if ocf is not None and cap is not None:
            fcf = (ocf - abs(cap)) / div
        elif ocf is not None:
            fcf = ocf / div
            data_warnings.append("CapEx not found — FCF approximated from Operating CF only.")
        if fcf is None:
            raw = info.get("freeCashflow")
            fcf = _f(raw) / div if raw else None
        if fcf is None:
            fcf = 0.0; missing_fields.append("Free Cash Flow")

    elif val_model == "FCFE":
        cf_basis = ("Net Income — standard bank/NBFC FCFE proxy "
                    "(capex negligible; regulatory-capital cost embedded in NI)")
        ni = _latest(inc,
            "Net Income", "Net Income Common Stockholders",
            "Net Income Applicable To Common Shares",
            "NetIncome", "NetIncomeLoss")
        if ni is not None:
            fcf = ni / div
        else:
            raw = info.get("netIncomeToCommon")
            fcf = _f(raw) / div if raw else None
        if fcf is None:
            fcf = 0.0; missing_fields.append("Net Income (FCFE basis)")

    else:  # DDM
        cf_basis = "Total Dividends Paid (true DDM cash-flow base)"
        dv = _latest(cf,
            "Cash Dividends Paid", "Common Stock Dividend Paid",
            "Payment Of Dividends", "Dividends Paid")
        if dv is not None:
            fcf = abs(dv) / div
        else:
            div_rate = _f(info.get("dividendRate"))
            if div_rate > 0:
                fcf = (div_rate * _f(shares)) / div
                data_warnings.append("Dividends Paid not on cash flow — estimated from dividendRate × shares.")
            else:
                fcf = 0.0; missing_fields.append("Dividends Paid (DDM basis)")

    # ── Net Debt — self-diagnosing: always know exactly how this was computed ──
    net_debt, net_debt_basis = compute_net_debt(bs, info, div, data_warnings, missing_fields)

    # ── v10: Forensic accounting suite (reuses bs/inc/cf already fetched
    # above — no new network calls). Computed here, before mkt_cap/beta are
    # finalized below, since Altman Z needs raw (un-div-scaled) market cap.
    # mkt_cap is already computed above (div-scaled, with its own price x
    # shares fallback already applied) -- just convert back to raw units
    # for the Altman Z-Score formula, instead of duplicating that logic.
    _mkt_cap_raw = mkt_cap * div
    forensics = {
        "sloan":         compute_sloan_accruals(inc, cf, bs, div),
        "altman":        compute_altman_z(bs, inc, _mkt_cap_raw, div),
        "dupont":        compute_dupont(info, inc, bs, div),
        "roic_spread":   None,   # filled in later once WACC is known (UI/report-time, not fetch-time)
        "normalized_fcf": None,  # filled in below once TTM fcf and revenue are known
    }

    # ── v10: 52-week trading range (direct from info dict) ──────────────────
    week52_low  = info.get("fiftyTwoWeekLow")
    week52_high = info.get("fiftyTwoWeekHigh")

    # ── v10: Blume-adjusted beta — SECONDARY/reference metric only. The
    # actual WACC/DCF math below still uses raw beta, per this project's
    # standing "don't smooth beta" instruction; both are exposed so nothing
    # about this choice is hidden. ───────────────────────────────────────────
    _blume_beta = blume_adjusted_beta(info.get("beta"))

    # ── Revenue ───────────────────────────────────────────────────────────────
    revenue = _latest(inc, "Total Revenue", "Revenue") or 0.0
    if revenue:
        revenue /= div
    else:
        revenue = _f(info.get("totalRevenue")) / div

    # ── Beta ──────────────────────────────────────────────────────────────────
    raw_beta = info.get("beta")
    try:
        beta = round(_f(raw_beta, 1.0), 3) or 1.0
    except Exception:
        beta = 1.0
    if raw_beta is None:
        data_warnings.append("Beta not available from API — defaulted to 1.0.")

    # ── Dividend yield — computed value now PREFERRED over the raw API field.
    # info.get("dividendYield") has twice now (in this project) been observed
    # returning a value that isn't actually a yield at all for certain
    # tickers -- e.g. Welspun returned 19.0 here, which fix_ratio's normal
    # scaling logic reasonably read as "already a percentage" (1 < 19 <= 100),
    # but the company's real dividend yield is ~1.5-2.5%. dividendRate/price
    # is unambiguous (two absolute currency figures in the same unit, no
    # scaling guesswork needed) and is now the primary source whenever
    # dividendRate is available; the API field is used only as a secondary
    # cross-check, with a warning if the two disagree by more than 2pp.
    div_rate = _f(info.get("dividendRate"))
    _dy_field = info.get("dividendYield")
    if div_rate > 0 and price > 0:
        div_yield = round((div_rate / price) * 100, 4)
        div_yield_basis = f"Computed: dividendRate ({div_rate:.2f}) ÷ price ({price:.2f}) × 100"
        if _dy_field is not None:
            _dy_field_pct = fix_ratio(_dy_field, "dividendYield")
            if abs(_dy_field_pct - div_yield) > 2.0:
                data_warnings.append(
                    f"API dividendYield field ({_dy_field_pct:.2f}%) disagreed with the computed "
                    f"yield from dividendRate/price ({div_yield:.2f}%) by more than 2pp — using the "
                    "computed value. This field has a documented history of returning something "
                    "other than a true yield for certain tickers.")
    elif _dy_field is not None:
        div_yield = fix_ratio(_dy_field, "dividendYield")
        div_yield_basis = "API dividendYield field (dividendRate unavailable for cross-check — verify manually)"
        data_warnings.append(
            f"Dividend yield ({div_yield:.2f}%) came only from the API's dividendYield field, with no "
            "dividendRate available to cross-check it against. This field has a documented history of "
            "returning something other than a true yield for certain tickers — verify manually.")
    else:
        div_yield = 0.0
        div_yield_basis = "Not available"

    # ── ROE — prefer the DuPont-decomposed figure (computed from the same
    # raw statements we already trust for Net Debt/forensics) over the API's
    # returnOnEquity field, which returned 0 for Welspun despite the company
    # being clearly profitable -- this eliminates the possibility of the
    # dashboard and the auto-generated thesis ever showing two different
    # ROE numbers, since both now read from this single value. ─────────────
    _roe_api = fix_ratio(info.get("returnOnEquity"), "roe")
    _roe_dupont = forensics.get("dupont", {}).get("roe_check")
    if _roe_dupont is not None:
        roe = _roe_dupont
        roe_basis = "DuPont decomposition (Net Margin × Asset Turnover × Equity Multiplier, from statements)"
        if _roe_api and abs(_roe_api - _roe_dupont) > 3.0:
            data_warnings.append(
                f"API returnOnEquity field ({_roe_api:.1f}%) disagreed with the statement-based DuPont "
                f"ROE ({_roe_dupont:.1f}%) by more than 3pp — using the DuPont figure since it's computed "
                "from the same raw financials as the rest of this report.")
    elif _roe_api:
        roe = _roe_api
        roe_basis = "API returnOnEquity field (insufficient statement data for DuPont cross-check)"
    else:
        roe = 0.0
        roe_basis = "Not available"
        missing_fields.append("Return on Equity")

    # ── Current Ratio — fallback to Current Assets / Current Liabilities
    # from the balance sheet (already pulled for the Altman Z-Score above)
    # when the API's own currentRatio field is missing or zero. ────────────
    _cr_api = _f(info.get("currentRatio"))
    if _cr_api > 0:
        curr_ratio = round(_cr_api, 2)
    else:
        _ca, _ = _multi_period(bs, "Current Assets", n=1)
        _cl, _ = _multi_period(bs, "Current Liabilities", n=1)
        if _ca and _cl and _cl[0] != 0:
            curr_ratio = round(_ca[0] / _cl[0], 2)
            data_warnings.append(
                f"API currentRatio field unavailable — computed instead from balance sheet "
                f"(Current Assets ÷ Current Liabilities = {curr_ratio:.2f}x).")
        else:
            curr_ratio = 0.0
            missing_fields.append("Current Ratio")

    forensics["normalized_fcf"] = compute_normalized_fcf(
        cf, inc, revenue_ttm=revenue*div, div=div, ttm_fcf=fcf*div if fcf else 0.0)

    return {
        "error": None,
        "ticker": ticker,
        "long_name":  info.get("longName") or info.get("shortName") or ticker,
        "sector": sector, "industry": industry,
        "summary": (info.get("longBusinessSummary","") or "").strip(),
        "exchange": info.get("exchange",""), "country_hq": info.get("country",""),
        "employees": info.get("fullTimeEmployees",0),
        "valuation_model": val_model, "cf_basis": cf_basis,
        "beta":        beta,
        "fcf":         round(_f(fcf), 2),
        "net_debt":    net_debt,
        "net_debt_basis": net_debt_basis,
        "forensics":   forensics,
        "week52_low":  round(_f(week52_low), 2) if week52_low else None,
        "week52_high": round(_f(week52_high), 2) if week52_high else None,
        "beta_blume":  _blume_beta,
        "multi_year":  fetch_multi_year_financials(inc, cf, div, n=3),
        "mkt_cap":     round(_f(mkt_cap), 2),
        "price":       round(_f(price), 2),
        "revenue":     round(_f(revenue), 2),
        "ebitda":      round(_f(ebitda), 2),
        "shares_out":  shares,
        "div_yield":   div_yield,
        "div_yield_basis": div_yield_basis,
        "pe_ratio":    round(_f(info.get("trailingPE") or info.get("forwardPE")), 2),
        "pb_ratio":    fix_ratio(info.get("priceToBook"), "pb_ratio"),
        "ps_ratio":    fix_ratio(info.get("priceToSalesTrailing12Months"), "ps_ratio"),
        "ev_ebitda":   fix_ratio(info.get("enterpriseToEbitda"), "ev_ebitda"),
        "roe":         roe,
        "roe_basis":   roe_basis,
        "debt_equity": round(_f(info.get("debtToEquity")), 2),
        "curr_ratio":  curr_ratio,
        "net_margin":  fix_ratio(info.get("profitMargins"), "net_margin"),
        "eps":         round(_f(info.get("trailingEps")), 2),
        "data_warnings":  data_warnings,
        "missing_fields": missing_fields,
    }


@st.cache_data(ttl=300, show_spinner=False)
def fetch_peers(tickers, market):
    """
    Returns one row dict per peer with a successful fetch. Each metric is
    either a real number (including legitimately negative or zero values,
    e.g. a peer with negative ROE) or Python None when the underlying API
    field itself was missing for that ticker — these two cases are now kept
    distinct all the way through to display, instead of both collapsing to
    0.0 and becoming indistinguishable from "the real value happens to be
    zero." Downstream rendering (PDF Section 07 and the Streamlit peer
    table) shows "N/A" only for genuine None, never for a real number.
    """
    div = MACROS[market]["div"]; rows = []

    def _peer_num(val, ndigits=1):
        if val is None: return None
        try: return round(float(val), ndigits)
        except (TypeError, ValueError): return None

    def _peer_ratio(val, field, ndigits=1):
        if val is None: return None
        v = fix_ratio(val, field)
        return round(v, ndigits) if v is not None else None

    for i, t in enumerate(tickers):
        if i > 0: time.sleep(INTER_TICKER)
        try:
            info = _safe_info(t)
            if not info: continue
            pe_raw = info.get("trailingPE")
            if pe_raw is None:
                pe_raw = info.get("forwardPE")
            mktcap_raw = info.get("marketCap")
            rows.append({
                "Ticker":    t.split(".")[0],
                "P/E":       _peer_num(pe_raw, 1),
                "P/B":       _peer_ratio(info.get("priceToBook"), "pb_ratio", 2),
                "EV/EBITDA": _peer_ratio(info.get("enterpriseToEbitda"), "ev_ebitda", 1),
                "P/S":       _peer_ratio(info.get("priceToSalesTrailing12Months"), "ps_ratio", 2),
                "ROE %":     _peer_ratio(info.get("returnOnEquity"), "roe", 1),
                "Mkt Cap":   _peer_num((_f(mktcap_raw) / div) if mktcap_raw is not None else None, 0),
            })
        except Exception:
            continue
    return rows

@st.cache_data(ttl=300, show_spinner=False)
def fetch_price_history(ticker):
    return _safe_history(ticker, "5y")

# ─────────────────────────────────────────────────────────────────────────────
# DCF ENGINE
# ─────────────────────────────────────────────────────────────────────────────
def run_dcf(fcf, wacc, g1, g2, tr, nd, so, price, market, model="FCFF"):
    # Gordon Growth Model requires tr < wacc (a perpetuity growing faster
    # than, or as fast as, its own discount rate is mathematically
    # undefined). Clamp with a 50bps safety buffer so this can never divide
    # by zero or produce a negative "intrinsic value" — this guards the
    # main calculation, every sensitivity-grid cell, and all three
    # Bear/Base/Bull scenarios, since they all route through this function.
    if tr >= wacc:
        tr = max(wacc - 0.5, 0.1)
    div = MACROS[market]["div"]; disc = 1 + wacc/100
    proj=[]; pv_fs=[]; cf=fcf
    for yr in range(1,11):
        r  = g1/100 if yr<=5 else g2/100
        cf = cf*(1+r); pv = cf/disc**yr
        proj.append({"Year":f"Y{yr}","FCF":round(cf,2),
                     "Growth Rate":f"{r*100:.1f}%","PV Factor":round(1/disc**yr,4),"PV of FCF":round(pv,2)})
        pv_fs.append(pv)
    tv_fcf=proj[-1]["FCF"]*(1+tr/100)
    tv=tv_fcf/(wacc/100-tr/100); pv_tv=tv/disc**10
    sum_pv=sum(pv_fs); ev=sum_pv+pv_tv
    eq = ev if model in ("FCFE","DDM") else ev-nd
    ip = (eq*div)/so if so>0 else 0
    return {"projections":proj,"pv_fcfs":pv_fs,"pv_terminal":pv_tv,
            "sum_pv_fcf":sum_pv,"enterprise_val":ev,"equity_val":eq,
            "intrinsic_price":ip,"model":model}

def build_sensitivity(fcf,g1,g2,tr,nd,so,p,market,model):
    mat={}
    for w in [x/10 for x in range(60,160,10)]:
        row={}
        for tg in [x/10 for x in range(15,55,5)]:
            row[f"{tg:.1f}%"]=round(run_dcf(fcf,w,g1,g2,tg,nd,so,p,market,model)["intrinsic_price"],1)
        mat[f"{w:.1f}%"]=row
    return mat

def get_scenarios(fcf,wacc,g1,g2,tr,nd,so,p,market,model):
    return {
        "Bear": run_dcf(fcf,wacc+2,       max(g1-5,1), max(g2-3,1), max(tr-.5,1.),nd*1.1,so,p,market,model),
        "Base": run_dcf(fcf,wacc,          g1,          g2,          tr,           nd,    so,p,market,model),
        "Bull": run_dcf(fcf,max(wacc-2,5), min(g1+5,30),min(g2+3,20),min(tr+.5,5.),nd*.9, so,p,market,model),
    }

def get_conviction_level(intrinsic, current, mos_pct):
    upside    = ((intrinsic-current)/current*100) if current>0 else 0
    mos_price = intrinsic*(1-mos_pct/100)
    if current<=mos_price:   return "HIGH CONVICTION",     upside, mos_price
    elif current<=intrinsic: return "MODERATE CONVICTION", upside, mos_price
    else:                    return "LOW CONVICTION",      upside, mos_price

def generate_risks(data, wacc, g1, g2, tr, model):
    risks=[]; rl=discount_rate_label(model)
    de=data.get("debt_equity",0); cr=data.get("curr_ratio",0)
    roe=data.get("roe",0);        nm=data.get("net_margin",0)
    beta=data.get("beta",1);      pe=data.get("pe_ratio",0)
    fcf=data.get("fcf",0)
    if model in ("FCFE","DDM"):
        risks.append(("LOW",f"Model: {model}. CF basis: {data.get('cf_basis','')}. "
                      "Net Debt excluded from equity bridge (correct for banks/REITs/insurers)."))
    if de>150:     risks.append(("HIGH",    f"High leverage: D/E {de:.0f}% — elevated risk in rising rate environment."))
    elif de>80:    risks.append(("MODERATE",f"Moderate leverage: D/E {de:.0f}% — monitor debt servicing capacity."))
    if 0<cr<1.0:   risks.append(("HIGH",    f"Liquidity risk: Current ratio {cr:.2f}x — liabilities exceed current assets."))
    elif 0<cr<1.5: risks.append(("MODERATE",f"Tight liquidity: Current ratio {cr:.2f}x — limited short-term buffer."))
    if 0<roe<10:   risks.append(("MODERATE",f"Low capital efficiency: ROE {roe:.1f}% below typical cost-of-equity."))
    elif roe>40:   risks.append(("LOW",     f"Exceptional ROE {roe:.1f}% — verify sustainability across the cycle."))
    if 0<nm<5:     risks.append(("HIGH",    f"Thin net margins {nm:.1f}% — small cost shocks could erase profitability."))
    if beta>1.5:   risks.append(("HIGH",    f"High market sensitivity: Beta {beta:.3f} — amplifies market drawdowns."))
    elif beta>1.2: risks.append(("MODERATE",f"Above-average volatility: Beta {beta:.3f} — size position accordingly."))
    if fcf<0:      risks.append(("HIGH",    f"Negative {CF_LABEL_SHORT.get(model,'FCF')} — DCF assumptions may be optimistic."))
    if pe>60 and pe>0: risks.append(("MODERATE",f"Rich valuation: P/E {pe:.1f}x — high growth priced in."))
    if g1>20:      risks.append(("MODERATE",f"Aggressive Stage-1 growth {g1:.1f}% — validate against sector benchmarks."))
    if tr>4.5:     risks.append(("HIGH",    f"Terminal rate {tr:.1f}% approaching {rl} ({wacc:.1f}%) — highly sensitive."))
    for w in data.get("data_warnings",[]): risks.append(("MODERATE",f"Data quality: {w}"))
    for f in data.get("missing_fields",[]): risks.append(("HIGH",f"Missing: '{f}' defaulted to 0 — verify manually."))
    if not risks: risks.append(("LOW","No critical risk flags identified from available financial data."))
    return risks

# ─────────────────────────────────────────────────────────────────────────────
# PLOTLY CHARTS — Light professional theme
# ─────────────────────────────────────────────────────────────────────────────
C_BG   = "#FFFFFF"
C_PLOT = "#F8FAFC"
C_GRID = "#E2E8F0"
C_TX   = "#374151"
C_BL   = "#2563EB"
C_GN   = "#059669"
C_AM   = "#D97706"
C_RD   = "#DC2626"
C_NV   = "#1E3A5F"

def _base(title, h=380):
    return dict(
        title=dict(text=title, font=dict(color=C_NV, size=14, family="Inter"), x=0),
        paper_bgcolor=C_BG, plot_bgcolor=C_PLOT, font=dict(color=C_TX, family="Inter"),
        xaxis=dict(gridcolor=C_GRID, linecolor=C_GRID, showgrid=True),
        yaxis=dict(gridcolor=C_GRID, linecolor=C_GRID, showgrid=True),
        margin=dict(t=55, b=35, l=15, r=15), height=h)

def chart_waterfall(proj, pv_tv, sum_pv, cf_label="FCF"):
    yrs  = [p["Year"] for p in proj] + ["Terminal PV"]
    vals = [p["PV of FCF"] for p in proj] + [pv_tv]
    fig  = go.Figure(go.Bar(x=yrs, y=vals,
        marker_color=[C_BL]*10+[C_GN],
        text=[f"{v:,.0f}" for v in vals], textposition="outside",
        textfont=dict(color=C_TX, size=10)))
    fig.update_layout(**_base(f"PV of {cf_label} Projections"))
    fig.update_yaxes(title="Present Value"); return fig

def chart_fcf_growth(proj, unit, cf_label="FCF"):
    yrs = [p["Year"] for p in proj]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=yrs, y=[p["FCF"] for p in proj],
        name=f"Projected {cf_label}", line=dict(color=C_BL, width=2.5),
        mode="lines+markers", marker=dict(size=7, color=C_BL)))
    fig.add_trace(go.Scatter(x=yrs, y=[p["PV of FCF"] for p in proj],
        name=f"PV of {cf_label}", line=dict(color=C_AM, width=2, dash="dot"),
        mode="lines+markers", marker=dict(size=7, color=C_AM)))
    fig.update_layout(**_base(f"{cf_label} Projection ({unit})"))
    fig.update_layout(legend=dict(bgcolor="rgba(255,255,255,.9)",
        bordercolor=C_GRID, borderwidth=1, font=dict(color=C_TX)))
    fig.update_yaxes(title=unit); return fig

def chart_sensitivity(mat, cur_price, rate_label="WACC"):
    wk=list(mat.keys()); tgk=list(next(iter(mat.values())).keys())
    z=[[mat[w][t] for t in tgk] for w in wk]
    fig=go.Figure(go.Heatmap(z=z, x=tgk, y=wk,
        colorscale=[[0,C_RD],[0.35,C_AM],[0.6,"#166534"],[1.0,C_GN]],
        text=[[f"{v:.0f}" for v in row] for row in z],
        texttemplate="%{text}", textfont=dict(size=9, color="white"),
        showscale=True,
        colorbar=dict(tickfont=dict(color=C_TX),
                      title=dict(text="Price", font=dict(color=C_TX)))))
    fig.update_layout(**_base(f"Sensitivity: {rate_label} (Y) vs Terminal Growth (X)", 420))
    fig.update_xaxes(title=dict(text="Terminal Growth Rate", font=dict(color=C_TX)))
    fig.update_yaxes(title=dict(text=rate_label, font=dict(color=C_TX))); return fig

def chart_scenarios(sc, cur_price, curr):
    names=list(sc.keys()); prices=[s["intrinsic_price"] for s in sc.values()]
    fig=go.Figure()
    fig.add_trace(go.Bar(x=names, y=prices,
        marker_color=[C_RD, C_BL, C_GN],
        text=[f"{curr}{p:,.1f}" for p in prices],
        textposition="outside", textfont=dict(color=C_NV, size=11, family="Inter")))
    fig.add_hline(y=cur_price, line_dash="dot", line_color=C_AM,
        annotation_text=f"Current {curr}{cur_price:,.1f}",
        annotation_font_color=C_AM)
    fig.update_layout(**_base("Bear / Base / Bull — Intrinsic Value"))
    fig.update_yaxes(title="Intrinsic Value"); return fig

def chart_price_history(hist_df, ticker):
    if hist_df is None or hist_df.empty: return None
    fig=go.Figure()
    fig.add_trace(go.Scatter(x=hist_df["Date"], y=hist_df["Close"],
        fill="tozeroy", fillcolor="rgba(37,99,235,0.08)",
        line=dict(color=C_BL, width=1.8), name="Close Price"))
    fig.update_layout(**_base(f"{ticker} — 5-Year Price History", 310))
    fig.update_yaxes(title="Price"); return fig

def chart_value_bridge(sum_pv, pv_tv, nd, eq_val, unit, model="FCFF"):
    if model in ("FCFE","DDM"):
        fig=go.Figure(go.Waterfall(orientation="v",
            measure=["relative","relative","total"],
            x=["PV of Cash Flows","+ Terminal PV","Equity Value"],
            y=[sum_pv, pv_tv, 0],
            connector=dict(line=dict(color=C_GRID, dash="dot")),
            increasing=dict(marker_color=C_GN),
            totals=dict(marker_color=C_BL),
            text=[f"{v:,.0f}" for v in [sum_pv, pv_tv, sum_pv+pv_tv]],
            textposition="outside", textfont=dict(color=C_NV, size=10)))
    else:
        fig=go.Figure(go.Waterfall(orientation="v",
            measure=["relative","relative","total","relative","total"],
            x=["PV of FCFs","+ Terminal PV","Enterprise Value","− Net Debt","Equity Value"],
            y=[sum_pv, pv_tv, 0, -nd, 0],
            connector=dict(line=dict(color=C_GRID, dash="dot")),
            increasing=dict(marker_color=C_GN),
            decreasing=dict(marker_color=C_RD),
            totals=dict(marker_color=C_BL),
            text=[f"{v:,.0f}" for v in [sum_pv, pv_tv, sum_pv+pv_tv, nd, eq_val]],
            textposition="outside", textfont=dict(color=C_NV, size=10)))
    fig.update_layout(**_base(f"Value Bridge ({unit})"))
    fig.update_yaxes(title=unit); return fig


def chart_football_field(ticker, current_price, currency,
                          dcf_bear, dcf_base, dcf_bull,
                          pe_low, pe_high, ev_ebitda_low, ev_ebitda_high,
                          peer_low, peer_high,
                          week52_low, week52_high):
    """
    Horizontal floating-bar 'football field' comparing four independent
    valuation methodologies on one axis:
      1. Intrinsic DCF Range (Bear -> Bull)
      2. Historical Multiples Range (3-yr trailing P/E & EV/EBITDA bands
         applied to TTM earnings — pass pe_low/high and ev_ebitda_low/high
         as already-converted PRICE levels, not raw multiples)
      3. Peer Relative Range (sector median multiple applied to fundamentals
         — also passed as price levels)
      4. 52-Week Trading Range (fiftyTwoWeekLow/High directly from the API)
    Any row with a None bound is skipped rather than drawn as a fake zero-
    width bar, since a missing methodology should be invisible, not
    misleadingly precise.
    """
    rows = [
        ("52-Week Trading Range", week52_low, week52_high, "#94A3B8"),
        ("Peer Relative Range",   peer_low,   peer_high,   "#F59E0B"),
        ("Historical Multiples",  min(x for x in [pe_low, ev_ebitda_low] if x is not None) if (pe_low or ev_ebitda_low) else None,
                                   max(x for x in [pe_high, ev_ebitda_high] if x is not None) if (pe_high or ev_ebitda_high) else None,
                                   "#8B5CF6"),
        ("Intrinsic DCF Range",   dcf_bear,   dcf_bull,    "#2563EB"),
    ]
    rows = [r for r in rows if r[1] is not None and r[2] is not None and r[2] >= r[1]]
    if not rows:
        return None

    fig = go.Figure()
    for i, (label, lo, hi, color) in enumerate(rows):
        fig.add_trace(go.Bar(
            y=[label], x=[hi - lo], base=[lo], orientation="h",
            marker=dict(color=color, line=dict(color="white", width=1)),
            text=f"{currency}{lo:,.0f} — {currency}{hi:,.0f}",
            textposition="inside", insidetextanchor="middle",
            textfont=dict(color="white", size=11, family="Inter"),
            showlegend=False, hoverinfo="skip"))
        # DCF Base case gets its own marker within the DCF range row
        if label == "Intrinsic DCF Range" and dcf_base is not None:
            fig.add_trace(go.Scatter(
                y=[label], x=[dcf_base], mode="markers",
                marker=dict(symbol="diamond", size=14, color="#0F172A",
                            line=dict(color="white", width=2)),
                name="DCF Base Case", showlegend=True, hoverinfo="skip"))

    fig.add_vline(x=current_price, line_dash="dash", line_color="#DC2626", line_width=2,
        annotation_text=f"Current {currency}{current_price:,.1f}",
        annotation_position="top", annotation_font_color="#DC2626")

    fig.update_layout(
        title=dict(text=f"{ticker} — Triangulated Valuation Football Field",
                   font=dict(color="#1E3A5F", size=15, family="Inter"), x=0),
        paper_bgcolor="#FFFFFF", plot_bgcolor="#F8FAFC",
        font=dict(color="#374151", family="Inter"),
        xaxis=dict(title=f"Price ({currency})", gridcolor="#E2E8F0"),
        yaxis=dict(gridcolor="#E2E8F0"),
        margin=dict(t=60, b=40, l=140, r=30), height=320,
        legend=dict(bgcolor="rgba(255,255,255,.9)", bordercolor="#E2E8F0", borderwidth=1))
    return fig


def compute_historical_multiple_range(hist_pe_series, hist_ev_ebitda_series,
                                       trailing_eps, ebitda_absolute, net_debt_absolute, shares_out):
    """
    3-year trailing P/E and EV/EBITDA interquartile bands, applied to the
    subject company's own TTM fundamentals, to produce two implied PRICE
    ranges. hist_*_series should be lists of the metric's value at each of
    the last ~12 quarterly or 3 annual snapshots available; returns None
    bounds if insufficient history exists (never fabricates a band from
    <2 points).

    IMPORTANT: P/E is already a per-share (equity) multiple, so
    Price = P/E x EPS directly. EV/EBITDA is an ENTERPRISE-level multiple,
    NOT a per-share one -- naively multiplying it by EBITDA-per-share and
    calling the result a "price" overstates the implied value by roughly
    Enterprise-Value-to-Equity-Value ratio (found via an end-to-end test:
    it produced a price ~15-20x too high for a real net-cash company).
    The correct bridge is: Implied EV = multiple x EBITDA (absolute) ->
    Implied Equity Value = Implied EV - Net Debt -> Price = Equity / Shares.
    ebitda_absolute and net_debt_absolute must be in the same absolute
    currency units as each other (both raw, or both div-scaled -- caller's
    choice, as long as they match).
    """
    def _pe_price(series, eps):
        vals = sorted(v for v in series if v and v > 0)
        if len(vals) < 2 or not eps or eps <= 0:
            return None, None
        n = len(vals)
        q1, q3 = vals[max(0, n//4)], vals[min(n-1, (3*n)//4)]
        return round(q1 * eps, 2), round(q3 * eps, 2)

    def _ev_ebitda_price(series, ebitda_abs, net_debt_abs, shares):
        vals = sorted(v for v in series if v and v > 0)
        if len(vals) < 2 or not ebitda_abs or ebitda_abs <= 0 or not shares or shares <= 0:
            return None, None
        n = len(vals)
        q1, q3 = vals[max(0, n//4)], vals[min(n-1, (3*n)//4)]
        lo_equity = q1 * ebitda_abs - net_debt_abs
        hi_equity = q3 * ebitda_abs - net_debt_abs
        return round(lo_equity / shares, 2), round(hi_equity / shares, 2)

    pe_lo, pe_hi = _pe_price(hist_pe_series, trailing_eps)
    ev_lo, ev_hi = _ev_ebitda_price(hist_ev_ebitda_series, ebitda_absolute, net_debt_absolute, shares_out)
    return pe_lo, pe_hi, ev_lo, ev_hi


def compute_peer_relative_range(peer_pe_list, peer_ev_ebitda_list,
                                 trailing_eps, ebitda_absolute, net_debt_absolute, shares_out):
    """
    Sector median EV/EBITDA and P/E (from the already-fetched peer comps
    table) applied to the subject company's own TTM fundamentals, bounded
    by the 25th/75th percentile of the peer set to form a range rather
    than a single point estimate. Same EV/EBITDA -> equity-value bridge as
    compute_historical_multiple_range() above (see its docstring for why
    this matters) -- ebitda_absolute and net_debt_absolute must be in the
    same absolute currency units as each other.
    """
    def _pe_price(vals, eps):
        vals = sorted(v for v in vals if v and v > 0)
        if len(vals) < 2 or not eps or eps <= 0:
            return None, None
        n = len(vals)
        q1, q3 = vals[max(0, n//4)], vals[min(n-1, (3*n)//4)]
        return round(q1 * eps, 2), round(q3 * eps, 2)

    def _ev_ebitda_price(vals, ebitda_abs, net_debt_abs, shares):
        vals = sorted(v for v in vals if v and v > 0)
        if len(vals) < 2 or not ebitda_abs or ebitda_abs <= 0 or not shares or shares <= 0:
            return None, None
        n = len(vals)
        q1, q3 = vals[max(0, n//4)], vals[min(n-1, (3*n)//4)]
        lo_equity = q1 * ebitda_abs - net_debt_abs
        hi_equity = q3 * ebitda_abs - net_debt_abs
        return round(lo_equity / shares, 2), round(hi_equity / shares, 2)

    pe_lo, pe_hi = _pe_price(peer_pe_list, trailing_eps)
    ev_lo, ev_hi = _ev_ebitda_price(peer_ev_ebitda_list, ebitda_absolute, net_debt_absolute, shares_out)
    los = [x for x in [pe_lo, ev_lo] if x is not None]
    his = [x for x in [pe_hi, ev_hi] if x is not None]
    if not los or not his:
        return None, None
    return min(los), max(his)

# ──────────────────────────────────────────────────────────────────────────
# MATPLOTLIB PDF CHARTS — Light professional
# ─────────────────────────────────────────────────────────────────────────────
MP_BG  = "#FFFFFF"
MP_AX  = "#F8FAFC"
MP_GR  = "#E2E8F0"
MP_TX  = "#374151"
MP_BL  = "#2563EB"
MP_GN  = "#059669"
MP_AM  = "#D97706"
MP_RD  = "#DC2626"
MP_LT  = "#93C5FD"
MP_NV  = "#1E3A5F"

def _mpl_style(fig):
    fig.patch.set_facecolor(MP_BG)
    for ax in fig.get_axes():
        ax.set_facecolor(MP_AX)
        ax.tick_params(colors=MP_TX, labelsize=8)
        ax.xaxis.label.set_color(MP_TX); ax.yaxis.label.set_color(MP_TX)
        ax.title.set_color(MP_NV)
        for sp in ax.spines.values(): sp.set_edgecolor(MP_GR)
        ax.grid(True, color=MP_GR, linewidth=0.6, alpha=0.8, linestyle="--")

def mpl_to_rl(fig, w_cm, h_cm):
    buf=io.BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf.seek(0); plt.close(fig)
    return RLImage(buf, width=w_cm*cm, height=h_cm*cm)

def pdf_fcf_growth(proj, unit, cf_label="FCF"):
    fig, ax = plt.subplots(figsize=(10,4))
    yrs=[p["Year"] for p in proj]
    ax.plot(yrs,[p["FCF"] for p in proj],
            color=MP_BL, marker="o", lw=2, ms=5, label=f"Projected {cf_label}", zorder=3)
    ax.plot(yrs,[p["PV of FCF"] for p in proj],
            color=MP_AM, marker="s", lw=2, ms=5, ls="--", label=f"PV of {cf_label}", zorder=3)
    ax.fill_between(yrs,[p["FCF"] for p in proj], alpha=0.07, color=MP_BL)
    ax.legend(facecolor=MP_BG, edgecolor=MP_GR, labelcolor=MP_TX, fontsize=8)
    ax.set_title(f"{cf_label} Projection ({unit})", fontsize=11, fontweight="bold", pad=10, color=MP_NV)
    ax.set_ylabel(unit, fontsize=9)
    _mpl_style(fig); fig.tight_layout(pad=1.5); return fig

def pdf_value_bridge(sum_pv, pv_tv, nd, eq_val, unit, model="FCFF"):
    if model in ("FCFE","DDM"):
        labels  = ["PV of\nCFs","+Terminal\nPV","Equity\nValue"]
        barvals = [sum_pv, pv_tv, sum_pv+pv_tv]; bottoms=[0,sum_pv,0]
        values  = [sum_pv, pv_tv, sum_pv+pv_tv]; clrs=[MP_BL,MP_GN,MP_AM]
    else:
        ev = sum_pv+pv_tv
        # Net debt >=0 subtracts (bar drops, red). Net CASH (nd<0) instead
        # ADDS to equity value, so the bar must rise (green), matching the
        # true EV -> Equity Value relationship instead of always assuming
        # a subtraction.
        if nd >= 0:
            nd_label, nd_color, nd_bottom = "-Net\nDebt", MP_RD, ev-nd
        else:
            nd_label, nd_color, nd_bottom = "+Net\nCash", MP_GN, ev
        labels  = ["PV of\nFCFs","+Terminal\nPV","Enterprise\nValue",nd_label,"Equity\nValue"]
        barvals = [sum_pv,pv_tv,ev,abs(nd),eq_val]
        bottoms = [0,sum_pv,0,nd_bottom,0]
        values  = [sum_pv,pv_tv,ev,nd,eq_val]
        clrs    = [MP_BL,MP_GN,MP_LT,nd_color,MP_AM]
    fig,ax=plt.subplots(figsize=(10,4))
    bars=ax.bar(labels,barvals,bottom=bottoms,color=clrs,edgecolor=MP_GR,lw=0.5,width=0.55,zorder=3)
    for i,(bar,v) in enumerate(zip(bars,values)):
        ax.text(bar.get_x()+bar.get_width()/2, bottoms[i]+barvals[i]+max(barvals)*0.01,
                f"{abs(v):,.0f}", ha="center", va="bottom", fontsize=8, color=MP_TX)
    ax.set_title(f"Value Bridge ({unit})",fontsize=11,fontweight="bold",pad=10,color=MP_NV)
    ax.set_ylabel(unit,fontsize=9)
    _mpl_style(fig); fig.tight_layout(pad=1.5); return fig

def pdf_football_field(ticker, current_price, currency,
                        dcf_bear, dcf_base, dcf_bull,
                        pe_low, pe_high, ev_ebitda_low, ev_ebitda_high,
                        peer_low, peer_high, week52_low, week52_high):
    """
    Matplotlib counterpart to chart_football_field() (which is Plotly, for
    the interactive UI) -- needed because the PDF embeds matplotlib PNGs via
    mpl_to_rl(), the same pattern already used for every other PDF chart in
    this app (pdf_value_bridge, pdf_sensitivity, etc.). Same graceful-skip
    behavior: a methodology with no data is omitted, never drawn as a fake
    zero-width bar.
    """
    rows = [
        ("52-Week Range",      week52_low, week52_high, MP_TX),
        ("Peer Relative",      peer_low,   peer_high,   MP_AM),
        ("Historical Multiples",
            min(x for x in [pe_low, ev_ebitda_low] if x is not None) if (pe_low or ev_ebitda_low) else None,
            max(x for x in [pe_high, ev_ebitda_high] if x is not None) if (pe_high or ev_ebitda_high) else None,
            "#8B5CF6"),
        ("Intrinsic DCF",      dcf_bear,   dcf_bull,    MP_BL),
    ]
    rows = [r for r in rows if r[1] is not None and r[2] is not None and r[2] >= r[1]]
    if not rows:
        return None

    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    labels = [r[0] for r in rows]
    for i, (label, lo, hi, color) in enumerate(rows):
        ax.barh(i, hi - lo, left=lo, height=0.55, color=color, edgecolor=MP_GR, zorder=3)
        ax.text((lo+hi)/2, i, f"{currency}{lo:,.0f}-{currency}{hi:,.0f}",
                ha="center", va="center", fontsize=7.5, color="white", fontweight="bold", zorder=4)
        if label == "Intrinsic DCF" and dcf_base is not None:
            ax.plot(dcf_base, i, marker="D", color=MP_NV, markersize=9,
                    markeredgecolor="white", markeredgewidth=1.5, zorder=5)

    ax.axvline(current_price, color=MP_RD, linestyle="--", linewidth=1.6, zorder=2)
    ax.text(current_price, len(rows)-0.35, f"Current {currency}{current_price:,.1f}",
            color=MP_RD, fontsize=8, fontweight="bold", ha="left", va="bottom")

    ax.set_yticks(range(len(rows))); ax.set_yticklabels(labels, fontsize=8.5)
    ax.set_xlabel(f"Price ({currency})", fontsize=8.5, color=MP_TX)
    ax.set_title(f"{ticker} — Triangulated Valuation Football Field",
                 fontsize=10.5, fontweight="bold", pad=8, color=MP_NV)
    ax.set_ylim(-0.6, len(rows)-0.1)
    _mpl_style(fig); fig.tight_layout(pad=1.2)
    return fig

def pdf_sensitivity(mat, cur_price, rate_label="WACC"):
    wk=list(mat.keys()); tgk=list(next(iter(mat.values())).keys())
    z=np.array([[mat[w][t] for t in tgk] for w in wk],dtype=float)
    cmap=LinearSegmentedColormap.from_list("rv",[MP_RD,"#FCA5A5","#BBF7D0",MP_GN])
    fig,ax=plt.subplots(figsize=(11,5.5))
    im=ax.imshow(z,cmap=cmap,aspect="auto",vmin=z.min(),vmax=z.max())
    ax.set_xticks(range(len(tgk))); ax.set_xticklabels(tgk,fontsize=7)
    ax.set_yticks(range(len(wk)));  ax.set_yticklabels(wk, fontsize=7)
    ax.set_xlabel("Terminal Growth Rate",fontsize=9,color=MP_TX)
    ax.set_ylabel(rate_label,fontsize=9,color=MP_TX)
    ax.set_title(f"Sensitivity — {rate_label} vs Terminal Growth Rate",
                 fontsize=11,fontweight="bold",pad=10,color=MP_NV)
    for i in range(len(wk)):
        for j in range(len(tgk)):
            v=z[i,j]
            clr=MP_NV if v>=cur_price else "#7F1D1D"
            ax.text(j,i,f"{v:.0f}",ha="center",va="center",fontsize=7,
                    color=clr,fontweight="bold" if v<cur_price else "normal")
    cbar=fig.colorbar(im,ax=ax,fraction=0.03,pad=0.02)
    cbar.ax.tick_params(labelsize=7)
    cbar.set_label("Intrinsic Price",fontsize=8,color=MP_TX)
    _mpl_style(fig); fig.tight_layout(pad=1.5); return fig

def pdf_scenarios(sc, cur_price, curr):
    names=list(sc.keys()); prices=[s["intrinsic_price"] for s in sc.values()]
    fig,ax=plt.subplots(figsize=(7,4))
    bars=ax.bar(names,prices,color=[MP_RD,MP_BL,MP_GN],edgecolor=MP_GR,lw=0.5,width=0.5,zorder=3)
    for bar,val in zip(bars,prices):
        ax.text(bar.get_x()+bar.get_width()/2,bar.get_height()+max(prices)*0.01,
                f"{curr}{val:,.1f}",ha="center",va="bottom",fontsize=9,color=MP_TX,fontweight="bold")
    ax.axhline(y=cur_price,color=MP_AM,ls="--",lw=1.5,zorder=4,label=f"Current {curr}{cur_price:,.1f}")
    ax.legend(facecolor=MP_BG,edgecolor=MP_GR,labelcolor=MP_TX,fontsize=8)
    ax.set_title("Intrinsic Value by Scenario",fontsize=11,fontweight="bold",pad=10,color=MP_NV)
    ax.set_ylabel(f"Intrinsic Value ({curr})",fontsize=9)
    _mpl_style(fig); fig.tight_layout(pad=1.5); return fig

# ─────────────────────────────────────────────────────────────────────────────
# PDF BUILDER
# ─────────────────────────────────────────────────────────────────────────────
def build_pdf(data,dcf_res,scenarios,sens_mat,peers_data,risks,
              verdict,intrinsic,mos_price,upside,
              wacc,g1,g2,tr,mos,market,macro,currency,unit,
              forensics=None, thesis=None, football_data=None,
              multi_year=None, consensus=None, treasury_live=None):
    forensics  = forensics or {}
    thesis     = thesis or (None, None, None)
    football_data = football_data or {}
    multi_year = multi_year or []
    consensus  = consensus or {"available": False, "note": "Not fetched."}

    model_label = data.get("valuation_model","FCFF")
    rate_label  = discount_rate_label(model_label)
    cf_lbl_l    = CF_LABEL_LONG.get(model_label,"Free Cash Flow")
    cf_lbl_s    = CF_LABEL_SHORT.get(model_label,"FCF")
    # Strip flag emoji (Unicode Regional Indicator Symbols) and stray variation
    # selectors from the market label for PDF use only — ReportLab cannot
    # render color emoji and would otherwise print broken glyph boxes.
    market_plain = re.sub(r"[\U0001F1E6-\U0001F1FF\uFE0F]", "", market).strip()

    def _nd_amount(nd_val):
        """Net debt >=0 -> parenthesized subtraction '(X)'. Net CASH (<0) ->
        plain positive add-back 'X' (never both a minus sign AND parens)."""
        return f"({nd_val:,.2f})" if nd_val >= 0 else f"{abs(nd_val):,.2f}"
    def _nd_label(nd_val):
        return "Less: Net Debt" if nd_val >= 0 else "Add: Net Cash"

    buf=io.BytesIO()
    # Tighter margins than the old SimpleDocTemplate version (1.5cm vs
    # 1.8cm) -- matches the brief's "zero unused whitespace / high-density"
    # ask. iw (usable width) is derived from doc.width below, so every
    # existing Section 01-09 table already adapts automatically since they
    # all size their columns as fractions of iw rather than hardcoded cm.
    doc=BaseDocTemplate(buf,pagesize=A4,
        leftMargin=1.5*cm,rightMargin=1.5*cm,topMargin=1.5*cm,bottomMargin=1.6*cm)

    # PDF colour palette
    NV =colors.HexColor("#1E3A5F"); BL =colors.HexColor("#2563EB")
    LBL=colors.HexColor("#DBEAFE"); GC =colors.HexColor("#059669")
    AC =colors.HexColor("#D97706"); RC =colors.HexColor("#DC2626")
    WH =colors.white;               BK =colors.HexColor("#111827")
    LG =colors.HexColor("#F8FAFC"); MG =colors.HexColor("#E2E8F0")
    GR =colors.HexColor("#6B7280"); BD =colors.HexColor("#E5E7EB")

    W,H=A4; iw=doc.width
    ss=getSampleStyleSheet()
    def S(n,**kw):
        if "fontName" not in kw: kw["fontName"]=PDF_F
        return ParagraphStyle(n,parent=ss["Normal"],**kw)

    ct =S("ct",  fontSize=24,leading=30,textColor=WH,  fontName=PDF_FB)
    cs =S("cs",  fontSize=10,leading=15,textColor=colors.HexColor("#CBD5E1"))
    cb =S("cb",  fontSize=8, leading=12,textColor=LBL, fontName=PDF_FB)
    sh =S("sh",  fontSize=8, leading=12,textColor=BL,  fontName=PDF_FB,spaceBefore=8,spaceAfter=4)
    bo =S("bo",  fontSize=10,leading=15,textColor=BK,  alignment=TA_JUSTIFY)
    bb =S("bb",  fontSize=10,leading=15,textColor=NV,  fontName=PDF_FB)
    ml =S("ml",  fontSize=9, leading=13,textColor=GR,  fontName=PDF_FB)
    mv =S("mv",  fontSize=9, leading=13,textColor=BK)
    thl=S("thl", fontSize=8, leading=11,textColor=GR,  fontName=PDF_FB,alignment=TA_LEFT)
    thr=S("thr", fontSize=8, leading=11,textColor=GR,  fontName=PDF_FB,alignment=TA_RIGHT)
    tcl=S("tcl", fontSize=9, leading=12,textColor=BK,  alignment=TA_LEFT)
    tcr=S("tcr", fontSize=9, leading=12,textColor=BK,  alignment=TA_RIGHT)
    tgl=S("tgl", fontSize=9, leading=12,textColor=GC,  fontName=PDF_FB,alignment=TA_LEFT)
    tgr_=S("tgr",fontSize=9, leading=12,textColor=GC,  fontName=PDF_FB,alignment=TA_RIGHT)
    tal=S("tal", fontSize=9, leading=12,textColor=AC,  fontName=PDF_FB,alignment=TA_LEFT)
    tar=S("tar", fontSize=9, leading=12,textColor=AC,  fontName=PDF_FB,alignment=TA_RIGHT)
    tbl=S("tbl", fontSize=9, leading=12,textColor=BL,  fontName=PDF_FB,alignment=TA_LEFT)
    tbr=S("tbr", fontSize=9, leading=12,textColor=BL,  fontName=PDF_FB,alignment=TA_RIGHT)
    sl =S("sl",  fontSize=8, leading=11,textColor=GR,  fontName=PDF_FB)
    sv =S("sv",  fontSize=9, leading=12,textColor=BK)
    al =S("al",  fontSize=9, leading=12,textColor=NV,  fontName=PDF_FB)
    av =S("av",  fontSize=9, leading=12,textColor=BK,  alignment=TA_RIGHT)
    an =S("an",  fontSize=8.5,leading=12,textColor=GR)
    ah =S("ah",  fontSize=8, leading=11,textColor=GR,  fontName=PDF_FB)
    ahr=S("ahr", fontSize=8, leading=11,textColor=GR,  fontName=PDF_FB,alignment=TA_RIGHT)
    ds =S("ds",  fontSize=7, leading=10,textColor=GR,  alignment=TA_JUSTIFY)
    ws =S("ws",  fontSize=8.5,leading=13,textColor=colors.HexColor("#78350F"))

    def lt(extra=None):
        base=[("BACKGROUND",(0,0),(-1,0),NV),
              ("ROWBACKGROUNDS",(0,1),(-1,-1),[WH,LG]),
              ("BOX",(0,0),(-1,-1),0.6,MG),
              ("LINEBELOW",(0,0),(-1,0),1.5,BL),
              ("INNERGRID",(0,0),(-1,-1),0.3,BD),
              ("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7),
              ("LEFTPADDING",(0,0),(-1,-1),8),("RIGHTPADDING",(0,0),(-1,-1),8)]
        if extra: base+=extra
        return TableStyle(base)

    # ── institutional governance / compliance footer, every page ────────────
    def make_footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica-Bold",40); canvas.setFillColorRGB(.85,.88,.92,.12)
        canvas.translate(W/2,H/2); canvas.rotate(45)
        canvas.drawCentredString(0,0,"PROPRIETARY RESEARCH — DO NOT DISTRIBUTE")
        canvas.rotate(-45); canvas.translate(-W/2,-H/2)
        ts=datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        canvas.setFont("Helvetica-Bold",6.5); canvas.setFillColorRGB(.4,.4,.4)
        gen_ts = datetime.datetime.now().strftime("%d %b %Y %H:%M")
        canvas.drawString(doc.leftMargin, 1.05*cm,
            f"EquityLens Terminal v10.1  |  {data['ticker']}  |  {data.get('exchange','')}  |  Generated {gen_ts}")
        canvas.drawString(doc.leftMargin, 0.7*cm,
            "Algorithmic quantitative research from public yfinance data. Not investment advice. "
            "Not a registered investment adviser.")
        canvas.setFont("Helvetica",6.5); canvas.setFillColorRGB(.5,.5,.5)
        canvas.drawRightString(W-doc.rightMargin, 1.05*cm, f"REF: {abs(hash(data['ticker']+ts))%999999:06d}")
        canvas.drawRightString(W-doc.rightMargin, 0.7*cm, f"Page {doc_.page}")
        canvas.restoreState()

    # ── page templates: two-column tear sheet (page 1) + single-column
    # full-width (page 2 onward, exactly the existing verified Section
    # 01-09 layout, untouched) ───────────────────────────────────────────
    col_gap    = 0.6*cm
    header_h   = 4.6*cm   # generous: masthead + 2-row metrics table, empirically verified to fit
    col_width  = (doc.width - col_gap) / 2

    frame_header = Frame(doc.leftMargin, doc.bottomMargin+doc.height-header_h,
        doc.width, header_h, id="hdr", showBoundary=0,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=4)
    frame_left  = Frame(doc.leftMargin, doc.bottomMargin,
        col_width, doc.height-header_h, id="L", showBoundary=0,
        leftPadding=0, rightPadding=8, topPadding=6, bottomPadding=0)
    frame_right = Frame(doc.leftMargin+col_width+col_gap, doc.bottomMargin,
        col_width, doc.height-header_h, id="R", showBoundary=0,
        leftPadding=8, rightPadding=0, topPadding=6, bottomPadding=0)
    frame_full  = Frame(doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height, id="full", showBoundary=0)

    doc.addPageTemplates([
        PageTemplate(id="TearSheet", frames=[frame_header, frame_left, frame_right], onPage=make_footer),
        PageTemplate(id="FullPage",  frames=[frame_full], onPage=make_footer),
    ])

    story=[]; proj=dcf_res["projections"]

    # ═══════════════════════════════════════════════════════════════════════
    # PAGE 1 — TWO-COLUMN EXECUTIVE TEAR SHEET
    # ═══════════════════════════════════════════════════════════════════════
    vc=GC if verdict=="HIGH CONVICTION" else (AC if verdict=="MODERATE CONVICTION" else RC)

    # ── Header frame content (full width, spans both columns below) ────────
    story.append(Paragraph("EQUITY RESEARCH — EXECUTIVE TEAR SHEET", cb))
    story.append(Spacer(1,0.08*cm))
    story.append(Paragraph(
        f"{data['long_name']}  <font color='#6B7280' size=11>({data['ticker']})</font>",
        S("tsname",fontSize=17,leading=21,textColor=NV,fontName=PDF_FB)))
    story.append(Paragraph(
        f"{data.get('exchange','')}  ·  {market_plain}  ·  {data['sector']}  ·  "
        f"Analyst: EquityLens Terminal  ·  {datetime.datetime.now().strftime('%d %b %Y %H:%M')}",
        S("tsmeta",fontSize=7.5,leading=10,textColor=GR)))
    story.append(Spacer(1,0.18*cm))

    cw5=doc.width/5
    hcs=S("hcs",fontSize=7,leading=9,textColor=GR,fontName=PDF_FB,alignment=TA_CENTER)
    def hcb(txt,clr,fs=13):
        return Paragraph(txt,S(f"hcb{abs(hash(txt))%9999}",fontSize=fs,leading=fs+3,
            textColor=clr,fontName=PDF_FB,alignment=TA_CENTER))
    header_tbl=Table([
        [Paragraph("CONVICTION",hcs),Paragraph("TARGET",hcs),Paragraph("CURRENT",hcs),
         Paragraph("UPSIDE",hcs),Paragraph(f"{rate_label}",hcs)],
        [hcb(verdict,vc,10.5), hcb(f"{currency}{intrinsic:,.1f}",BK),
         hcb(f"{currency}{data['price']:,.1f}",BK), hcb(f"{upside:+.1f}%",GC if upside>0 else RC),
         hcb(f"{wacc:.2f}%",BK)]],colWidths=[cw5]*5)
    header_tbl.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),LG),("BOX",(0,0),(-1,-1),1.5,vc),
        ("INNERGRID",(0,0),(-1,-1),0.4,BD),("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
    story.append(header_tbl)
    story.append(FrameBreak())

    # ── Left column: 52-week range, multi-year financials, key metrics ─────
    tsh=S("tsh",fontSize=7.5,leading=10,textColor=BL,fontName=PDF_FB,spaceBefore=4,spaceAfter=3)
    tst=S("tst",fontSize=7,leading=9,textColor=GR,fontName=PDF_FB,alignment=TA_LEFT)
    tstr=S("tstr",fontSize=7,leading=9,textColor=GR,fontName=PDF_FB,alignment=TA_RIGHT)
    tsc=S("tsc",fontSize=7.5,leading=10,textColor=BK,alignment=TA_LEFT)
    tscr=S("tscr",fontSize=7.5,leading=10,textColor=BK,alignment=TA_RIGHT)

    story.append(Paragraph("52-WEEK TRADING RANGE",tsh))
    wk_lo = football_data.get("week52_low"); wk_hi = football_data.get("week52_high")
    if wk_lo is not None and wk_hi is not None:
        wk_tbl=Table([[Paragraph(f"{currency}{wk_lo:,.1f}",tsc),
                        Paragraph("Low", S("wl",fontSize=6.5,leading=8,textColor=GR,alignment=TA_CENTER)),
                        Paragraph(f"{currency}{data['price']:,.1f}", S("wc",fontSize=7.5,leading=10,textColor=BL,fontName=PDF_FB,alignment=TA_CENTER)),
                        Paragraph("Current", S("wl2",fontSize=6.5,leading=8,textColor=GR,alignment=TA_CENTER)),
                        Paragraph(f"{currency}{wk_hi:,.1f}",tscr)]],
            colWidths=[col_width*.20,col_width*.16,col_width*.26,col_width*.18,col_width*.20])
        wk_tbl.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2)]))
        story.append(wk_tbl)
    else:
        story.append(Paragraph("Not available from API for this ticker.", S("na",fontSize=7,textColor=GR)))
    story.append(Spacer(1,0.15*cm))

    story.append(Paragraph("FINANCIAL SUMMARY", tsh))
    fs_hdr = [Paragraph("",tst)] + [Paragraph(f"FY-{i}" if i>0 else "FY (TTM)",tstr) for i in range(len(multi_year)-1,-1,-1)]
    if consensus.get("available"):
        fs_hdr.append(Paragraph("Cons. +1Y", S("cons",fontSize=7,leading=9,textColor=AC,fontName=PDF_FB,alignment=TA_RIGHT)))
    fs_rows=[fs_hdr]
    metric_labels = [("revenue","Revenue"),("ebitda","EBITDA*"),("net_income","Net Income"),("fcf","FCF")]
    for key,label in metric_labels:
        row=[Paragraph(label,tsc)]
        for yr in reversed(multi_year):
            v=yr.get(key)
            row.append(Paragraph(f"{v:,.0f}" if v is not None else "—",tscr))
        if consensus.get("available"):
            row.append(Paragraph("n/a" if key!="net_income" or not consensus.get("avg_eps_estimate")
                                  else f"{consensus['avg_eps_estimate']:,.2f}*", S("cv",fontSize=7,leading=9,textColor=AC,alignment=TA_RIGHT)))
        fs_rows.append(row)
    n_data_cols = len(multi_year) + (1 if consensus.get("available") else 0)
    fs_colw = [col_width*0.32] + [col_width*0.68/max(n_data_cols,1)]*max(n_data_cols,1)
    fs_tbl=Table(fs_rows, colWidths=fs_colw)
    fs_tbl.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),LG),("LINEBELOW",(0,0),(-1,0),0.8,BL),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WH,LG]),("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
    story.append(fs_tbl)
    story.append(Paragraph(f"All figures in {unit}. *EBITDA proxied by EBIT where unavailable; "
                            f"consensus figures are best-effort (yfinance) and unverified.",
                            S("fn",fontSize=5.8,leading=7.5,textColor=GR)))
    story.append(Spacer(1,0.15*cm))

    story.append(Paragraph("KEY METRICS", tsh))
    key_metrics = [
        ("P/E", f"{data['pe_ratio']:.1f}x" if data['pe_ratio']>0 else "N/A"),
        ("EV/EBITDA", f"{data['ev_ebitda']:.1f}x" if data['ev_ebitda']>0 else "N/A"),
        ("ROE", f"{data['roe']:.1f}%"),
        ("Beta (raw)", f"{data['beta']}"),
        ("Net Debt/(Cash)", f"{currency}{data['net_debt']:,.0f} {unit}"),
    ]
    if forensics.get("altman",{}).get("value") is not None:
        key_metrics.append(("Altman Z-Score", f"{forensics['altman']['value']:.2f}"))
    if forensics.get("roic_spread",{}).get("spread") is not None:
        key_metrics.append((f"ROIC-{rate_label} Spread", f"{forensics['roic_spread']['spread']:+.1f}pp"))
    km_rows=[[Paragraph(k,tst),Paragraph(v,tscr)] for k,v in key_metrics]
    km_tbl=Table(km_rows, colWidths=[col_width*0.55, col_width*0.45])
    km_tbl.setStyle(TableStyle([("ROWBACKGROUNDS",(0,0),(-1,-1),[WH,LG]),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
    story.append(km_tbl)
    story.append(FrameBreak())

    # ── Right column: football field chart + automated thesis ──────────────
    story.append(Paragraph("TRIANGULATED VALUATION", tsh))
    ff_fig = pdf_football_field(
        data["ticker"], data["price"], currency,
        football_data.get("dcf_bear"), football_data.get("dcf_base"), football_data.get("dcf_bull"),
        football_data.get("pe_low"), football_data.get("pe_high"),
        football_data.get("ev_low"), football_data.get("ev_high"),
        football_data.get("peer_low"), football_data.get("peer_high"),
        football_data.get("week52_low"), football_data.get("week52_high"))
    if ff_fig is not None:
        story.append(mpl_to_rl(ff_fig, w_cm=(col_width)/cm, h_cm=5.2))
    else:
        story.append(Paragraph("Insufficient data across methodologies to render the football field.",
                                S("na2",fontSize=7,textColor=GR)))
    story.append(Spacer(1,0.2*cm))

    story.append(Paragraph("INVESTMENT THESIS", tsh))
    p1,p2,p3 = thesis
    thesis_style = S("thesis",fontSize=7.3,leading=10,textColor=BK,alignment=TA_JUSTIFY,spaceAfter=5)
    for p in (p1,p2,p3):
        if p:
            story.append(Paragraph(p, thesis_style))

    story.append(NextPageTemplate("FullPage"))
    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════════
    # PAGE 2 — company description + data quality (lead-in to Section 01)
    # ═══════════════════════════════════════════════════════════════════════
    dw=data.get("data_warnings",[]); mf=data.get("missing_fields",[])
    if dw or mf:
        story.append(Paragraph("Data Quality Notices",
            S("dqh",fontSize=9,leading=12,textColor=AC,fontName=PDF_FB)))
        story.append(Spacer(1,.1*cm))
        wrows=[]
        for w in dw: wrows.append([Paragraph(f"⚠  {w}",ws)])
        for f in mf: wrows.append([Paragraph(f"❌  '{f}' not available — defaulted to 0. Verify manually.",ws)])
        wt=Table(wrows,colWidths=[iw])
        wt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#FFFBEB")),
            ("BOX",(0,0),(-1,-1),0.8,colors.HexColor("#FDE68A")),
            ("INNERGRID",(0,0),(-1,-1),0.3,colors.HexColor("#FEF3C7")),
            ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
            ("LEFTPADDING",(0,0),(-1,-1),10),("RIGHTPADDING",(0,0),(-1,-1),8)]))
        story+=[wt,Spacer(1,.35*cm)]

    if data.get("summary","").strip():
        story.append(Paragraph("About the Company",bb))
        story.append(Spacer(1,.12*cm))
        story.append(Paragraph(data["summary"],bo))
    story.append(Spacer(1,.4*cm))

    now_full=datetime.datetime.now().strftime("%d %B %Y,  %H:%M")
    mt_rows=[
        [Paragraph("Report Date",ml),Paragraph(now_full,mv),Paragraph("Analyst",ml),Paragraph("EquityLens Terminal",mv)],
        [Paragraph("Market",ml),Paragraph(market_plain,mv),Paragraph("Industry",ml),Paragraph(data.get("industry","—"),mv)],
        [Paragraph("Valuation Model",ml),Paragraph(model_label,mv),Paragraph("Beta (raw API)",ml),Paragraph(f"{data['beta']}",mv)],
        [Paragraph("Risk-Free Rate",ml),Paragraph(f"{macro['risk_free_rate']}%",mv),Paragraph("Equity Risk Premium",ml),Paragraph(f"{macro['market_premium']}% (Damodaran)",mv)],
        [Paragraph(f"{rate_label} Applied",ml),Paragraph(f"{wacc:.2f}%",mv),Paragraph("Margin of Safety",ml),Paragraph(f"{mos}%  →  High-conviction ≤ {currency}{mos_price:,.1f}",mv)],
        [Paragraph("Stage-1 Growth Y1–5",ml),Paragraph(f"{g1:.1f}%",mv),Paragraph("Stage-2 Growth Y6–10",ml),Paragraph(f"{g2:.1f}%",mv)],
        [Paragraph("Terminal Growth Rate",ml),Paragraph(f"{tr:.1f}%",mv),Paragraph("Shares Outstanding",ml),Paragraph(f"{data['shares_out']:,.0f}",mv)],
    ]
    cw2=iw/4
    mt=Table(mt_rows,colWidths=[cw2*.72,cw2*1.28,cw2*.72,cw2*1.28])
    mt.setStyle(TableStyle([("ROWBACKGROUNDS",(0,0),(-1,-1),[WH,LG]),
        ("BOX",(0,0),(-1,-1),.8,MG),("INNERGRID",(0,0),(-1,-1),.3,BD),
        ("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7),
        ("LEFTPADDING",(0,0),(-1,-1),10),("RIGHTPADDING",(0,0),(-1,-1),10)]))
    story+=[mt,PageBreak()]

    # S01
    s01_block=[Paragraph("SECTION 01 — COMPANY SNAPSHOT",sh),
               HRFlowable(width=iw,thickness=1,color=BL,spaceAfter=10)]
    snap=[
        ("Market Capitalisation",f"{currency}{data['mkt_cap']:,.0f} {unit}"),
        ("Current Share Price",  f"{currency}{data['price']:,.2f}"),
        ("Revenue (TTM)",        f"{currency}{data['revenue']:,.0f} {unit}"),
        ("EBITDA (TTM)",         f"{currency}{data['ebitda']:,.0f} {unit}"),
        (cf_lbl_l,               f"{currency}{data['fcf']:,.0f} {unit}"),
        ("Net Debt / (Cash)",    f"{currency}{data['net_debt']:,.0f} {unit}"),
        ("Beta (raw)",           f"{data['beta']}"),
        ("P/E Ratio",            f"{data['pe_ratio']:.1f}x" if data['pe_ratio']>0 else "N/A"),
        ("P/B Ratio",            f"{data['pb_ratio']:.2f}x" if data['pb_ratio']>0 else "N/A"),
        ("P/S Ratio",            f"{data['ps_ratio']:.2f}x" if data['ps_ratio']>0 else "N/A"),
        ("EV/EBITDA",            f"{data['ev_ebitda']:.1f}x" if data['ev_ebitda']>0 else "N/A"),
        ("Return on Equity",     f"{data['roe']:.1f}%"),
        ("Net Profit Margin",    f"{data['net_margin']:.1f}%"),
        ("Debt / Equity",        f"{data['debt_equity']:.1f}%"),
        ("Current Ratio",        f"{data['curr_ratio']:.2f}x"),
        ("Dividend Yield",       f"{data['div_yield']:.2f}%"),
        ("EPS (Trailing)",       f"{currency}{data['eps']:.2f}"),
        ("Employees",            f"{data.get('employees',0):,}" if data.get("employees") else "N/A"),
    ]
    sr=[]
    for i in range(0,len(snap),3):
        row=[]
        for j in range(3):
            if i+j<len(snap): row+=[Paragraph(snap[i+j][0],sl),Paragraph(snap[i+j][1],sv)]
            else: row+=[Paragraph("",sl),Paragraph("",sv)]
        sr.append(row)
    cw3=iw/6
    snt=Table(sr,colWidths=[cw3*.82,cw3*1.18]*3)
    snt.setStyle(TableStyle([("ROWBACKGROUNDS",(0,0),(-1,-1),[WH,LG]),
        ("BOX",(0,0),(-1,-1),.6,MG),("INNERGRID",(0,0),(-1,-1),.3,BD),
        ("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7),
        ("LEFTPADDING",(0,0),(-1,-1),8),("RIGHTPADDING",(0,0),(-1,-1),8)]))
    s01_block.append(snt)
    story.append(KeepTogether(s01_block))
    story.append(Spacer(1,.45*cm))

    # S02
    s02_block=[Paragraph("SECTION 02 — DCF ASSUMPTIONS",sh),
               HRFlowable(width=iw,thickness=1,color=BL,spaceAfter=10)]
    nd_note=("Net Debt excluded — debt is a regulatory raw material for financials"
             if model_label in ("FCFE","DDM") else (data.get("net_debt_basis") or
             "Total debt less cash & cash equivalents"))
    cf_note=data.get("cf_basis") or "Latest 12-month free cash flow"
    assump=[[Paragraph("Parameter",ah),Paragraph("Value",ahr),Paragraph("Notes",ah)],
            [Paragraph(f"Initial {cf_lbl_s}",al),Paragraph(f"{currency}{data['fcf']:,.2f} {unit}",av),Paragraph(cf_note,an)],
            [Paragraph("Valuation Model",al),Paragraph(model_label,av),Paragraph("Auto-detected from sector/industry",an)],
            [Paragraph(rate_label,al),Paragraph(f"{wacc:.2f}%",av),Paragraph(f"Rf {macro['risk_free_rate']}% + β{data['beta']} × ERP {macro['market_premium']}% (CAPM)",an)],
            [Paragraph("Growth Y1–Y5",al),Paragraph(f"{g1:.1f}%",av),Paragraph("High-growth phase assumption",an)],
            [Paragraph("Growth Y6–Y10",al),Paragraph(f"{g2:.1f}%",av),Paragraph("Transition phase",an)],
            [Paragraph("Terminal Growth",al),Paragraph(f"{tr:.1f}%",av),Paragraph(f"Must be < {rate_label} and ≤ long-run nominal GDP",an)],
            [Paragraph("Net Debt/(Cash)",al),Paragraph(f"{currency}{data['net_debt']:,.2f} {unit}",av),Paragraph(nd_note,an)],
            [Paragraph("Margin of Safety",al),Paragraph(f"{mos}%",av),Paragraph(f"High-conviction threshold: {currency}{mos_price:,.1f}/share",an)]]
    at=Table(assump,colWidths=[iw*.28,iw*.17,iw*.55]); at.setStyle(lt())
    s02_block.append(at)
    story.append(KeepTogether(s02_block))
    story.append(PageBreak())

    # S03
    s03_block=[Paragraph(f"SECTION 03 — {model_label} MODEL: 10-YEAR PROJECTION",sh),
               HRFlowable(width=iw,thickness=1,color=BL,spaceAfter=10)]
    dcf_cw=[iw*x for x in [.09,.17,.12,.15,.19,.19]]; dcf_cw[-1]=iw-sum(dcf_cw[:-1])
    dcf_rows=[[Paragraph("Year",thl),Paragraph(f"{cf_lbl_s} ({unit})",thr),
               Paragraph("Growth",thr),Paragraph("PV Factor",thr),
               Paragraph(f"PV {cf_lbl_s} ({unit})",thr),Paragraph("Cumul. PV",thr)]]
    cum=0.0
    for p in proj:
        cum+=p["PV of FCF"]
        dcf_rows.append([Paragraph(p["Year"],tcl),Paragraph(f"{p['FCF']:,.2f}",tcr),
            Paragraph(p["Growth Rate"],tcr),Paragraph(f"{p['PV Factor']:.4f}",tcr),
            Paragraph(f"{p['PV of FCF']:,.2f}",tcr),Paragraph(f"{cum:,.2f}",tcr)])
    dcf_rows.append([Paragraph("Terminal Value PV",tal)]+[Paragraph("",tar)]*4+[Paragraph(f"{dcf_res['pv_terminal']:,.2f}",tar)])
    dcf_rows.append([Paragraph("Enterprise Value",tgl)]+[Paragraph("",tgr_)]*4+[Paragraph(f"{dcf_res['enterprise_val']:,.2f}",tgr_)])
    if model_label=="FCFF":
        dcf_rows.append([Paragraph(_nd_label(data['net_debt']),tcl)]+[Paragraph("",tcr)]*4+
            [Paragraph(_nd_amount(data['net_debt']),tcr)])
    else:
        dcf_rows.append([Paragraph(f"Net Debt (excl. — {model_label})",S("ndx",fontSize=8,leading=11,textColor=GR,alignment=TA_LEFT))]+
            [Paragraph("—",S("ndr",fontSize=8,leading=11,textColor=GR,alignment=TA_RIGHT))]*5)
    dcf_rows.append([Paragraph("Equity Value",tgl)]+[Paragraph("",tgr_)]*4+[Paragraph(f"{dcf_res['equity_val']:,.2f}",tgr_)])
    dcf_rows.append([Paragraph("Intrinsic Price/Share",tbl)]+[Paragraph("",tbr)]*4+[Paragraph(f"{currency}{dcf_res['intrinsic_price']:,.2f}",tbr)])
    dcf_span_rows=list(range(len(dcf_rows)-5,len(dcf_rows)))   # 5 summary/total rows
    dcf_extra=[("SPAN",(0,r),(4,r)) for r in dcf_span_rows]
    dt=Table(dcf_rows,colWidths=dcf_cw,repeatRows=1); dt.setStyle(lt(dcf_extra))
    s03_block.append(dt)
    story.append(KeepTogether(s03_block))
    story.append(Spacer(1,.4*cm))

    s03b_block=[Paragraph("Value Bridge Summary",sh),
                HRFlowable(width=iw,thickness=1,color=BL,spaceAfter=8)]
    br_rows=[[Paragraph("Component",thl),Paragraph(f"Value ({unit})",thr),Paragraph("% of EV",thr)],
             [Paragraph(f"PV of {cf_lbl_s} (Y1–Y10)",tcl),Paragraph(f"{dcf_res['sum_pv_fcf']:,.2f}",tcr),Paragraph(f"{dcf_res['sum_pv_fcf']/dcf_res['enterprise_val']*100:.1f}%",tcr)],
             [Paragraph("PV of Terminal Value",tcl),Paragraph(f"{dcf_res['pv_terminal']:,.2f}",tcr),Paragraph(f"{dcf_res['pv_terminal']/dcf_res['enterprise_val']*100:.1f}%",tcr)],
             [Paragraph("Enterprise Value",tgl),Paragraph(f"{dcf_res['enterprise_val']:,.2f}",tgr_),Paragraph("100.0%",tgr_)],
             [Paragraph(_nd_label(data['net_debt']) if model_label=="FCFF" else "Net Debt/(Cash)",tcl),
              Paragraph(_nd_amount(data['net_debt']),tcr) if model_label=="FCFF" else Paragraph("N/A — excluded",tcr),
              Paragraph("—",tcr)],
             [Paragraph("Equity Value",tgl),Paragraph(f"{dcf_res['equity_val']:,.2f}",tgr_),Paragraph("—",tgr_)],
             [Paragraph("Intrinsic Price/Share",tbl),Paragraph(f"{currency}{dcf_res['intrinsic_price']:,.2f}",tbr),Paragraph("—",tbr)]]
    bt=Table(br_rows,colWidths=[iw*.46,iw*.30,iw*.24]); bt.setStyle(lt())
    s03b_block.append(bt)
    story.append(KeepTogether(s03b_block))
    story.append(PageBreak())

    # S04
    story.append(Paragraph(f"SECTION 04 — {cf_lbl_s.upper()} PROJECTION & VALUE BRIDGE",sh))
    story.append(HRFlowable(width=iw,thickness=1,color=BL,spaceAfter=10))
    story.append(mpl_to_rl(pdf_fcf_growth(proj,unit,cf_lbl_s),w_cm=iw/cm,h_cm=8.5))
    story.append(Spacer(1,.4*cm))
    story.append(mpl_to_rl(pdf_value_bridge(dcf_res["sum_pv_fcf"],dcf_res["pv_terminal"],
        data["net_debt"],dcf_res["equity_val"],unit,model_label),w_cm=iw/cm,h_cm=8.5))
    story.append(PageBreak())

    # S05
    s05_block=[Paragraph("SECTION 05 — SENSITIVITY ANALYSIS",sh),
               HRFlowable(width=iw,thickness=1,color=BL,spaceAfter=8),
               Paragraph(f"Green = intrinsic > current price. Red = below. Highlighted = base-case {rate_label}.",bo),
               Spacer(1,.25*cm)]
    wk=list(sens_mat.keys()); tgk=list(next(iter(sens_mat.values())).keys())
    shdr_s=S("shdr",fontSize=7.5,leading=10,textColor=GR,fontName=PDF_FB,alignment=TA_LEFT)
    shdrrr=S("shdrr",fontSize=7.5,leading=10,textColor=GR,fontName=PDF_FB,alignment=TA_RIGHT)
    s_rows=[[Paragraph(f"{rate_label} \\ TGR",shdr_s)]+[Paragraph(t,shdrrr) for t in tgk]]
    base_idx=None
    for i,w in enumerate(wk):
        if abs(float(w[:-1])-wacc)<0.15: base_idx=i+1
        row=[Paragraph(w,S(f"wk{i}",fontSize=8.5,leading=11,textColor=BK,fontName=PDF_FB))]
        for t in tgk:
            v=sens_mat[w][t]
            row.append(Paragraph(f"{v:.0f}",S(f"sc{i}{abs(hash(t))%9999}",fontSize=8.5,leading=11,
                textColor=GC if v>data["price"] else RC,fontName=PDF_FB,alignment=TA_RIGHT)))
        s_rows.append(row)
    scw=[iw*.13]+[iw*.87/len(tgk)]*len(tgk)
    scmds=[("BACKGROUND",(0,0),(-1,0),NV),("ROWBACKGROUNDS",(0,1),(-1,-1),[WH,LG]),
           ("BOX",(0,0),(-1,-1),.6,MG),("LINEBELOW",(0,0),(-1,0),1.5,BL),
           ("INNERGRID",(0,0),(-1,-1),.3,BD),
           ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
           ("LEFTPADDING",(0,0),(-1,-1),5),("RIGHTPADDING",(0,0),(-1,-1),5)]
    if base_idx: scmds.append(("BACKGROUND",(0,base_idx),(-1,base_idx),colors.HexColor("#DBEAFE")))
    st2=Table(s_rows,colWidths=scw,repeatRows=1); st2.setStyle(TableStyle(scmds))
    s05_block.append(st2)
    story.append(KeepTogether(s05_block))
    story.append(Spacer(1,.4*cm))
    story.append(mpl_to_rl(pdf_sensitivity(sens_mat,data["price"],rate_label),w_cm=iw/cm,h_cm=9.5))
    story.append(PageBreak())

    # S06
    s06_block=[Paragraph("SECTION 06 — SCENARIO ANALYSIS",sh),
               HRFlowable(width=iw,thickness=1,color=BL,spaceAfter=10)]
    sc_clr={"Bear":RC,"Base":BL,"Bull":GC}
    sc_r=[[Paragraph("Scenario",thl),Paragraph("Intrinsic Price",thr),
           Paragraph("vs Current",thr),Paragraph(f"Enterprise Val ({unit})",thr),
           Paragraph(f"Equity Val ({unit})",thr)]]
    for nm,res in scenarios.items():
        clr=sc_clr.get(nm,BK)
        ps=S(f"scr{nm}",fontSize=9,leading=12,textColor=clr,fontName=PDF_FB,alignment=TA_RIGHT)
        psl=S(f"scl{nm}",fontSize=9,leading=12,textColor=clr,fontName=PDF_FB,alignment=TA_LEFT)
        upc=((res["intrinsic_price"]-data["price"])/data["price"]*100) if data["price"]>0 else 0
        sc_r.append([Paragraph(nm,psl),Paragraph(f"{currency}{res['intrinsic_price']:,.1f}",ps),
                     Paragraph(f"{upc:+.1f}%",ps),Paragraph(f"{res['enterprise_val']:,.1f}",ps),
                     Paragraph(f"{res['equity_val']:,.1f}",ps)])
    sct=Table(sc_r,colWidths=[iw*x for x in [.14,.20,.18,.25,.23]]); sct.setStyle(lt())
    s06_block.append(sct)
    story.append(KeepTogether(s06_block))
    story.append(Spacer(1,.4*cm))
    story.append(mpl_to_rl(pdf_scenarios(scenarios,data["price"],currency),w_cm=(iw/cm)*.65,h_cm=9))
    story.append(PageBreak())

    # S07
    if peers_data:
        s07_block=[Paragraph("SECTION 07 — COMPARABLE COMPANY ANALYSIS",sh),
                   HRFlowable(width=iw,thickness=1,color=BL,spaceAfter=10)]
        subj=data["ticker"].split(".")[0]
        c_hdrs=["Company","P/E","P/B","EV/EBITDA","P/S","ROE %",f"Mkt Cap ({unit})"]
        c_rows=[[Paragraph(h,thl if i==0 else thr) for i,h in enumerate(c_hdrs)]]
        for row in peers_data:
            is_s=row["Ticker"]==subj; clr=BL if is_s else BK; fn=PDF_FB if is_s else PDF_F
            rs=S(f"cr{row['Ticker']}",fontSize=9,leading=12,textColor=clr,fontName=fn,alignment=TA_RIGHT)
            rsl=S(f"crl{row['Ticker']}",fontSize=9,leading=12,textColor=clr,fontName=fn,alignment=TA_LEFT)
            c_rows.append([
                Paragraph(row["Ticker"]+(" ★" if is_s else ""),rsl),
                Paragraph(f"{row['P/E']:.1f}x"       if row["P/E"] is not None       else "N/A",rs),
                Paragraph(f"{row['P/B']:.2f}x"       if row["P/B"] is not None       else "N/A",rs),
                Paragraph(f"{row['EV/EBITDA']:.1f}x" if row["EV/EBITDA"] is not None else "N/A",rs),
                Paragraph(f"{row['P/S']:.2f}x"       if row["P/S"] is not None       else "N/A",rs),
                Paragraph(f"{row['ROE %']:.1f}%"     if row["ROE %"] is not None     else "N/A",rs),
                Paragraph(f"{row['Mkt Cap']:,.0f}"   if row["Mkt Cap"] is not None   else "N/A",rs)])
        ct2=Table(c_rows,colWidths=[iw*x for x in [.22,.11,.11,.14,.11,.11,.20]],repeatRows=1); ct2.setStyle(lt())
        s07_block.append(ct2)
        story.append(KeepTogether(s07_block))
        story.append(Spacer(1,.45*cm))

    # S08
    s08_header=[Paragraph("SECTION 08 — KEY RISK FLAGS",sh),
                HRFlowable(width=iw,thickness=1,color=BL,spaceAfter=10)]
    r_clr={"HIGH":RC,"MODERATE":AC,"LOW":GC}
    r_bg={"HIGH":colors.HexColor("#FEF2F2"),"MODERATE":colors.HexColor("#FFFBEB"),"LOW":colors.HexColor("#ECFDF5")}
    for idx,(sev,txt) in enumerate(risks):
        rc2=r_clr.get(sev,BK); rbg=r_bg.get(sev,WH)
        ls=S(f"rls{sev}{idx}",fontSize=8,leading=11,textColor=rc2,fontName=PDF_FB,alignment=TA_CENTER)
        bs2=S(f"rbs{sev}{idx}",fontSize=9.5,leading=14,textColor=BK,alignment=TA_LEFT)
        rt=Table([[Paragraph(sev,ls),Paragraph(txt,bs2)]],colWidths=[iw*.17,iw*.83])
        rt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),rbg),("LINEAFTER",(0,0),(0,-1),4,rc2),
            ("BOX",(0,0),(-1,-1),.5,BD),("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),
            ("LEFTPADDING",(0,0),(0,-1),10),("LEFTPADDING",(1,0),(1,-1),8),
            ("RIGHTPADDING",(0,0),(-1,-1),10),("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
        if idx==0:
            story.append(KeepTogether(s08_header+[rt]))
        else:
            story.append(KeepTogether([rt]))
        story.append(Spacer(1,.2*cm))
    story.append(Spacer(1,.35*cm))

    # S09
    s09_block=[Paragraph("SECTION 09 — MODEL-IMPLIED CONVICTION LEVEL",sh),
               HRFlowable(width=iw,thickness=1,color=BL,spaceAfter=10)]
    # Same unambiguous "above/below" phrasing as generate_investment_thesis()
    # above, for the same reason -- "a discount/premium to fair value" is
    # genuinely easy to get backwards depending on which value is read as
    # the subject, and did exactly that in an earlier version.
    rel_word_s09 = "below" if upside > 0 else "above"
    s09_block.append(Paragraph(
        f"Based on our {model_label} DCF analysis, <b>{data['long_name']} ({data['ticker']})</b> "
        f"has an estimated intrinsic value of <b>{currency}{intrinsic:,.2f}</b>. The current market price of "
        f"<b>{currency}{data['price']:,.2f}</b> sits <b>{abs(upside):.1f}% {rel_word_s09}</b> that estimate. "
        f"Applying a <b>{mos}% margin of safety</b>, the high-conviction zone begins at "
        f"<b>{currency}{mos_price:,.1f}</b>. Model-implied conviction: <b>{verdict}</b>. "
        "This is model output only — <b>not</b> a buy, sell, or hold recommendation.",
        S("vp",fontSize=10.5,leading=16,textColor=BK,alignment=TA_JUSTIFY)))
    s09_block.append(Spacer(1,.4*cm))
    vcf=GC if verdict=="HIGH CONVICTION" else (AC if verdict=="MODERATE CONVICTION" else RC)
    ft=Table([[Paragraph(verdict,ParagraphStyle("fv",fontSize=20,leading=26,
        textColor=vcf,fontName=PDF_FB,alignment=TA_CENTER))]],colWidths=[iw])
    ft.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),LG),("BOX",(0,0),(-1,-1),2.5,vcf),
        ("TOPPADDING",(0,0),(-1,-1),22),("BOTTOMPADDING",(0,0),(-1,-1),22)]))
    s09_block.append(ft)
    s09_block.append(Spacer(1,.4*cm))
    s09_block.append(Paragraph(
        "DISCLAIMER: This report is produced by EquityLens for educational and research purposes only. "
        "It does not constitute investment advice. EquityLens and its author are not registered investment "
        "advisers, broker-dealers, or research analysts in any jurisdiction. High / Moderate / Low Conviction "
        "labels describe only how the current price compares to this model's intrinsic value estimate — they "
        "are not buy, sell, or hold recommendations. Past performance is not indicative of future results. "
        "Consult a registered financial advisor before making any investment decisions.",ds))
    story.append(KeepTogether(s09_block))

    # Footer/watermark is already wired via each PageTemplate's onPage=
    # make_footer (set up earlier, before the story was built) — BaseDocTemplate
    # uses that mechanism instead of SimpleDocTemplate's onFirstPage/onLaterPages.
    doc.build(story)
    buf.seek(0); return buf.read()

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="padding:16px 4px 24px 4px;">
      <div style="font-size:.62rem;color:#93C5FD;letter-spacing:2.5px;font-weight:700;
           text-transform:uppercase;margin-bottom:6px;">EquityLens</div>
      <div style="font-size:1.2rem;color:#FFFFFF;font-weight:800;letter-spacing:-.3px;">
           DCF Research Terminal</div>
      <div style="height:3px;background:linear-gradient(90deg,#60A5FA,#34D399,#FBBF24);
           border-radius:3px;margin-top:12px;"></div>
    </div>""", unsafe_allow_html=True)

    st.markdown('<div class="section-header-sb">Market</div>', unsafe_allow_html=True)
    market    = st.selectbox("", list(MACROS.keys()), label_visibility="collapsed")
    macro     = MACROS[market]
    peers_map = PEERS.get(market, PEERS["USA 🇺🇸"])

    st.markdown('<div class="section-header-sb" style="margin-top:18px;">Company Ticker</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="sidebar-info">💡 {TICKER_HINTS[market]}</div>', unsafe_allow_html=True)
    ticker_input = st.text_input("tkr","", placeholder="e.g. AIR.PA or TCS.NS",
                                 label_visibility="collapsed")

    st.markdown('<div class="section-header-sb" style="margin-top:18px;">Peer Group</div>', unsafe_allow_html=True)
    sector_sel = st.selectbox("", list(peers_map.keys()), label_visibility="collapsed")

    st.markdown("<div style='margin-top:20px;'></div>", unsafe_allow_html=True)
    fetch_btn = st.button("⚡  Fetch Company Data", use_container_width=True, type="primary")

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
    st.markdown(f"""<div class="sidebar-info">
      <b style="color:#93C5FD;">{market} Macro</b><br>
      Risk-Free Rate: <b style="color:#FFF">{macro['risk_free_rate']}%</b><br>
      Equity Risk Premium: <b style="color:#FFF">{macro['market_premium']}%</b> (Damodaran)<br>
      Currency: <b style="color:#FFF">{macro['currency']} ({macro['unit']})</b>
    </div>""", unsafe_allow_html=True)

    if _CACHE_ACTIVE:
        st.markdown('<div style="font-size:.68rem;color:#64748B;margin-top:12px;padding:0 4px;">'
                    '🗄️ HTTP cache active — repeated fetches hit disk, not Yahoo.</div>',
                    unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""<div class="hero-banner">
  <div class="hero-badge">Institutional Grade · v10.1 · Build 2026-09-11</div>
  <div class="hero-title">EquityLens DCF Terminal</div>
  <div class="hero-subtitle">
    India · USA · UK · France · Germany · Europe &nbsp;·&nbsp;
    FCFF / FCFE / DDM &nbsp;·&nbsp; Forensics + Reverse DCF + Football Field &nbsp;·&nbsp;
    Two-Column Tear Sheet &nbsp;·&nbsp;
    Conviction-based output (not a recommendation)
  </div>
</div>""", unsafe_allow_html=True)

if "company_data" not in st.session_state:
    st.session_state.company_data = None

if fetch_btn and ticker_input:
    tk = ticker_input.strip().upper()
    ph = st.empty()
    ph.info(f"⏳  Fetching **{tk}** — first load takes 15–25 s (3 statement fetches + retries)…")
    d  = fetch_company_data(tk, market)
    ph.empty()
    if d.get("error"):
        st.error(f"❌  {d['error']}")
        st.info("💡  **Tips:** Wait 60 s · Switch to mobile hotspot · Clear cache "
                "(hamburger menu → Clear cache) · Check ticker format (e.g. AIR.PA not AIR)")
    else:
        st.session_state.company_data = d

if st.session_state.company_data is None:
    c1,c2,c3 = st.columns(3)
    for col,(ico,ttl,dsc) in zip([c1,c2,c3],[
        ("🌍","Select Market","India, USA, UK, France, Germany or Europe"),
        ("🔍","Enter Ticker","Paste the exchange ticker and hit Fetch"),
        ("📊","Run DCF","Set assumptions and generate the full analysis")]):
        with col:
            st.markdown(f"""<div class="metric-card" style="text-align:center;padding:32px 20px;">
              <div style="font-size:2rem;margin-bottom:12px;">{ico}</div>
              <div style="color:#1E3A5F;font-weight:700;font-size:1rem;margin-bottom:8px;">{ttl}</div>
              <div style="color:#64748B;font-size:.85rem;">{dsc}</div>
            </div>""", unsafe_allow_html=True)
    st.stop()

data       = st.session_state.company_data
currency   = macro["currency"]
unit       = macro["unit"]
val_model  = data.get("valuation_model","FCFF")
rate_label = discount_rate_label(val_model)
cf_label   = CF_LABEL_LONG.get(val_model,"Free Cash Flow")
cf_short   = CF_LABEL_SHORT.get(val_model,"FCF")
tk         = data["ticker"]

dw = data.get("data_warnings",[]); mf = data.get("missing_fields",[])
if dw or mf:
    with st.expander("⚠️  Data Quality Notices — review before running DCF", expanded=True):
        for w in dw: st.warning(w)
        for f in mf: st.error(f"❌ '{f}' not available from API — defaulted to 0. Override manually.")

if val_model in ("FCFE","DDM"):
    st.info(f"ℹ️  **{tk}** → **{val_model}** model · "
            f"Starting CF: **{cf_label}** · "
            f"Discount rate: **{rate_label}** (not WACC — FCFE/DDM cash flows belong only to shareholders)")

# Company header
mtag = {"FCFF":"model-tag-fcff","FCFE":"model-tag-fcfe","DDM":"model-tag-ddm"}.get(val_model,"model-tag-fcff")
nd_sign = "−" if data['net_debt'] < 0 else ""
nd_abs  = abs(data['net_debt'])
nd_label= f"{currency}−{nd_abs:,.0f} {unit} (net cash)" if data['net_debt']<0 else f"{currency}{data['net_debt']:,.0f} {unit}"

st.markdown(f"""<div class="company-card">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px;">
    <div>
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
        <span style="font-size:.7rem;color:#64748B;letter-spacing:2px;text-transform:uppercase;font-weight:700;">
          {data['ticker']} · {data.get('exchange','')} · {market}
        </span>
        <span class="{mtag}">{val_model}</span>
      </div>
      <div style="font-size:1.75rem;font-weight:800;color:#0F172A;letter-spacing:-.5px;">{data['long_name']}</div>
      <div style="color:#64748B;font-size:.88rem;margin-top:4px;">
        {data['sector']} &nbsp;·&nbsp; {data.get('industry','')} &nbsp;·&nbsp; {data.get('country_hq','')}
      </div>
    </div>
    <div style="text-align:right;">
      <div style="font-size:2.1rem;font-weight:800;color:#1E3A5F;">{currency}{data['price']:,.2f}</div>
      <div style="font-size:.82rem;color:#64748B;margin-top:2px;">Mkt Cap: <b>{currency}{data['mkt_cap']:,.0f} {unit}</b></div>
      <div style="font-size:.78rem;color:#64748B;margin-top:2px;">Net Debt: <b>{nd_label}</b></div>
      <div style="font-size:.78rem;color:#64748B;margin-top:2px;">Beta: <b>{data['beta']}</b></div>
    </div>
  </div>
</div>""", unsafe_allow_html=True)
st.caption(f"🔍 Net Debt basis: {data.get('net_debt_basis', 'n/a')}")

cols6 = st.columns(6)
metrics = [
    (cf_label,    f"{currency}{data['fcf']:,.1f} {unit}"),
    ("Net Debt",  nd_label),
    ("P/E Ratio", f"{data['pe_ratio']:.1f}x" if data['pe_ratio']>0 else "N/A"),
    ("EV/EBITDA", f"{data['ev_ebitda']:.1f}x" if data['ev_ebitda']>0 else "N/A"),
    ("Beta",      f"{data['beta']}"),
    ("ROE",       f"{data['roe']:.1f}%"),
]
for i,(lbl,val) in enumerate(metrics):
    with cols6[i]:
        st.markdown(f'<div class="metric-card"><div class="metric-label">{lbl}</div>'
                    f'<div class="metric-value">{val}</div></div>', unsafe_allow_html=True)

st.markdown("<div style='margin-top:24px;'></div>", unsafe_allow_html=True)

st.markdown('<div class="section-header">Financial Inputs — Auto-Fetched (Override if needed)</div>',
            unsafe_allow_html=True)
with st.expander("📋  Company Financial Data", expanded=True):
    c1,c2,c3,c4 = st.columns(4)
    with c1: fcf_in    = st.number_input(f"Initial {cf_short} ({unit})", value=float(data["fcf"]),      step=10.0,  format="%.2f", key=f"fcf_{tk}")
    with c2: mktcap_in = st.number_input(f"Market Cap ({unit})",         value=float(data["mkt_cap"]),  step=100.0, format="%.2f", key=f"mc_{tk}")
    with c3: price_in  = st.number_input(f"Current Price ({currency})",  value=float(data["price"]),    step=1.0,   format="%.2f", key=f"px_{tk}")
    with c4: debt_in   = st.number_input(f"Net Debt ({unit})",           value=float(data["net_debt"]), step=10.0,  format="%.2f", key=f"nd_{tk}",
                                          help="+ve = net debt  /  −ve = net cash position. Ignored for FCFE/DDM models.")

st.markdown('<div class="section-header" style="margin-top:8px;">Valuation Assumptions</div>',
            unsafe_allow_html=True)
with st.expander("⚙️  DCF Assumptions", expanded=True):
    ca,cb,cc = st.columns(3)
    suggested_rate = round(macro["risk_free_rate"] + data["beta"] * macro["market_premium"], 2)
    # Clamp only the widget's starting value into its allowed [1.0, 30.0]
    # range — an extreme/negative raw beta can otherwise push the CAPM
    # result outside that range and crash st.number_input on page load.
    suggested_rate_safe = min(max(suggested_rate, 1.0), 30.0)
    with ca:
        wacc_in = st.number_input(f"{rate_label} (%)", value=float(suggested_rate_safe),
            min_value=1.0, max_value=30.0, step=0.1, format="%.2f", key=f"wacc_{tk}",
            help=f"CAPM: Rf {macro['risk_free_rate']}% + β{data['beta']} × ERP {macro['market_premium']}%")
        if suggested_rate != suggested_rate_safe:
            st.caption(f"⚠️ Raw CAPM output ({suggested_rate:+.2f}%) is outside a usable range — "
                       f"defaulted to {suggested_rate_safe:.2f}%. Beta ({data['beta']}) is shown "
                       "unadjusted; override the rate above if you disagree with this default.")
        if val_model in ("FCFE","DDM"):
            st.info(f"ℹ️ **{val_model}** — using **{rate_label}**, not WACC. Net Debt excluded from equity bridge.")

    def gpick(label, key, default, ticker):
        mode = st.radio(label, ["Low (5%)","Moderate (10%)","High (15%)","Custom"],
                        key=f"m_{key}_{ticker}", horizontal=True)
        if mode == "Custom":
            return st.number_input(f"Custom {label}", min_value=0.0, max_value=50.0,
                value=default, step=0.5, key=f"c_{key}_{ticker}", format="%.1f")
        return {"Low (5%)":5.0,"Moderate (10%)":10.0,"High (15%)":15.0}[mode]

    with cb:
        g1_in = gpick("Growth Y1–Y5",  "g1", 10.0, tk)
        g2_in = gpick("Growth Y6–Y10", "g2",  7.0, tk)
    with cc:
        tgr_in = st.number_input("Terminal Growth Rate (%)", value=3.0, min_value=0.1, max_value=6.0, step=0.1, format="%.1f", key=f"tgr_{tk}")
        mos_in = st.number_input("Margin of Safety (%)",     value=20.0,min_value=0.0, max_value=50.0,step=1.0, format="%.0f", key=f"mos_{tk}")

run_btn = st.button("🚀  Run DCF Analysis", type="primary", use_container_width=True)

if run_btn:
    data["fcf"]=fcf_in; data["mkt_cap"]=mktcap_in
    data["price"]=price_in; data["net_debt"]=debt_in
    so = data["shares_out"]

    if tgr_in >= wacc_in:
        st.warning(f"⚠️ Terminal growth ({tgr_in:.1f}%) must be below the {rate_label} "
                   f"({wacc_in:.1f}%) — a perpetuity can't grow as fast as, or faster than, "
                   f"its own discount rate. Using {max(wacc_in-0.5,0.1):.1f}% for this calculation; "
                   "raise the discount rate or lower terminal growth above to set this yourself.")

    with st.spinner("Running DCF model…"):
        dcf_res   = run_dcf(fcf_in,wacc_in,g1_in,g2_in,tgr_in,debt_in,so,price_in,market,val_model)
        intrinsic = dcf_res["intrinsic_price"]
        verdict,upside,mos_price = get_conviction_level(intrinsic,price_in,mos_in)
        sens_mat  = build_sensitivity(fcf_in,g1_in,g2_in,tgr_in,debt_in,so,price_in,market,val_model)
        scenarios = get_scenarios(fcf_in,wacc_in,g1_in,g2_in,tgr_in,debt_in,so,price_in,market,val_model)

    peer_tickers = peers_map.get(sector_sel,[])
    if data["ticker"] not in peer_tickers:
        peer_tickers = [data["ticker"]] + peer_tickers[:4]
    with st.spinner(f"Fetching {len(peer_tickers)} peer tickers (~{len(peer_tickers)*2}s)…"):
        peers_data = fetch_peers(tuple(peer_tickers), market)

    risks   = generate_risks(data,wacc_in,g1_in,g2_in,tgr_in,val_model)
    hist_df = fetch_price_history(data["ticker"])

    # ── v10: complete the forensics suite with ROIC-WACC spread (needs the
    # WACC/Ke the user actually chose, so computed here at report-time
    # rather than at fetch-time) ────────────────────────────────────────────
    forensics = dict(data.get("forensics") or {})
    # ROIC needs the raw income/balance-sheet DataFrames, which aren't kept
    # on `data` after fetch completes -- approximate the spread from the
    # already-computed DuPont ROE and Debt/Equity instead of re-fetching,
    # clearly labeled as an approximation rather than the exact
    # NOPAT/Invested-Capital formula.
    if forensics.get("dupont", {}).get("roe_check") is not None and data.get("debt_equity") is not None:
        # Rough ROIC proxy from already-stored ratios when the full
        # statement-level ROIC calc isn't available post-fetch: blend ROE
        # down toward an unlevered figure using the D/E ratio, clearly
        # labeled as an approximation rather than presented as the exact
        # NOPAT/Invested-Capital formula (which needs raw EBIT/Debt/Equity
        # figures only available inside fetch_company_data itself).
        roe_v = forensics["dupont"]["roe_check"]
        de_v = data.get("debt_equity", 0) / 100
        approx_roic = roe_v / (1 + de_v) if (1 + de_v) > 0 else roe_v
        spread_v = approx_roic - wacc_in
        forensics["roic_spread"] = {
            "roic": round(approx_roic, 2), "spread": round(spread_v, 2),
            "verdict": ("STRONG ECONOMIC MOAT — value creation well above cost of capital" if spread_v>3
                        else "MODEST VALUE CREATION — ROIC exceeds WACC" if spread_v>0
                        else "ROUGHLY VALUE-NEUTRAL — ROIC near WACC" if spread_v>-3
                        else "VALUE DESTRUCTIVE — ROIC below cost of capital"),
            "note": "Approximated from ROE and Debt/Equity (post-fetch); a small deviation from a "
                     "full NOPAT/Invested-Capital calculation is expected."}
    else:
        forensics["roic_spread"] = {"roic": None, "spread": None, "note": "Insufficient data."}

    # ── v10: Reverse DCF solver — what growth rate does the current price imply? ──
    implied_growth, _solve_iters, solve_converged = reverse_dcf_solve(
        current_price=price_in, fcf=fcf_in, nd=debt_in, so=so, market=market,
        model=val_model, wacc=wacc_in, g2=g2_in, tr=tgr_in)

    # ── v10: Football field — DCF range already known; multiples/peer ranges
    # derived from the peer comps table + this company's own TTM figures.
    # EV/EBITDA is an enterprise-level multiple -- correctly bridged to a
    # per-share PRICE via (multiple x EBITDA - Net Debt) / Shares, not a
    # naive per-share multiplication (that earlier version overstated the
    # peer-relative price by ~15-20x for a net-cash company; caught by an
    # end-to-end test, fixed in compute_peer_relative_range itself). ───────
    peer_pe_list = [p.get("P/E") for p in peers_data if p.get("P/E")]
    peer_ev_list = [p.get("EV/EBITDA") for p in peers_data if p.get("EV/EBITDA")]
    ebitda_abs = data["ebitda"] * MACROS[market]["div"]          # back to raw currency units
    net_debt_abs = debt_in * MACROS[market]["div"]               # same raw units, for the EV->equity bridge
    peer_lo, peer_hi = compute_peer_relative_range(
        peer_pe_list, peer_ev_list, data.get("eps"), ebitda_abs, net_debt_abs, so)
    football_data = {
        "dcf_bear": scenarios["Bear"]["intrinsic_price"], "dcf_base": scenarios["Base"]["intrinsic_price"],
        "dcf_bull": scenarios["Bull"]["intrinsic_price"],
        "pe_low": None, "pe_high": None, "ev_low": None, "ev_high": None,  # needs 3yr history; not available post-fetch
        "peer_low": peer_lo, "peer_high": peer_hi,
        "week52_low": data.get("week52_low"), "week52_high": data.get("week52_high"),
    }

    # ── v10: automated investment thesis ─────────────────────────────────────
    thesis = generate_investment_thesis(data, dcf_res, intrinsic, upside, verdict, forensics,
        val_model, rate_label, wacc_in, currency, unit)

    # ── v10: consensus estimates — best-effort only, never blocks the report
    # if this particular yfinance endpoint is unavailable or shaped
    # differently than expected (see fetch_consensus_estimates docstring). ──
    consensus_data = fetch_consensus_estimates(data["ticker"])

    st.markdown("---")
    st.markdown('<div class="section-header">Valuation Results — Model-Implied Conviction (Not a Recommendation)</div>',
                unsafe_allow_html=True)
    vcls = ("conviction-high" if verdict=="HIGH CONVICTION" else
            "conviction-moderate" if verdict=="MODERATE CONVICTION" else "conviction-low")
    vico = "🟢" if verdict=="HIGH CONVICTION" else ("🟡" if verdict=="MODERATE CONVICTION" else "🔴")
    r1,r2,r3,r4,r5 = st.columns(5)
    with r1:
        st.markdown(f'<div class="{vcls}">{vico}<br><b>{verdict}</b></div>', unsafe_allow_html=True)
    with r2:
        st.markdown(f'<div class="metric-card"><div class="metric-label">Intrinsic Value</div>'
                    f'<div class="metric-value" style="color:#2563EB;">{currency}{intrinsic:,.1f}</div></div>',
                    unsafe_allow_html=True)
    with r3:
        st.markdown(f'<div class="metric-card"><div class="metric-label">Current Price</div>'
                    f'<div class="metric-value">{currency}{price_in:,.1f}</div></div>',
                    unsafe_allow_html=True)
    with r4:
        clr = "#059669" if upside>0 else "#DC2626"
        st.markdown(f'<div class="metric-card"><div class="metric-label">Upside / Downside</div>'
                    f'<div class="metric-value" style="color:{clr};">{upside:+.1f}%</div></div>',
                    unsafe_allow_html=True)
    with r5:
        st.markdown(f'<div class="metric-card"><div class="metric-label">High-Conviction ≤</div>'
                    f'<div class="metric-value">{currency}{mos_price:,.1f}</div></div>',
                    unsafe_allow_html=True)
    st.caption("⚠️ Conviction labels describe model output only — not investment advice or buy/sell/hold signals. EquityLens is not a registered investment adviser.")

    st.markdown("<div style='margin-top:24px;'></div>", unsafe_allow_html=True)
    ch1,ch2 = st.columns(2)
    with ch1: st.plotly_chart(chart_waterfall(dcf_res["projections"],dcf_res["pv_terminal"],dcf_res["sum_pv_fcf"],cf_short),use_container_width=True,config={"displayModeBar":False})
    with ch2: st.plotly_chart(chart_value_bridge(dcf_res["sum_pv_fcf"],dcf_res["pv_terminal"],debt_in,dcf_res["equity_val"],unit,val_model),use_container_width=True,config={"displayModeBar":False})
    ch3,ch4 = st.columns(2)
    with ch3: st.plotly_chart(chart_fcf_growth(dcf_res["projections"],unit,cf_short),use_container_width=True,config={"displayModeBar":False})
    with ch4: st.plotly_chart(chart_scenarios(scenarios,price_in,currency),use_container_width=True,config={"displayModeBar":False})
    st.plotly_chart(chart_sensitivity(sens_mat,price_in,rate_label),use_container_width=True,config={"displayModeBar":False})
    if hist_df is not None:
        hf = chart_price_history(hist_df,data["ticker"])
        if hf: st.plotly_chart(hf,use_container_width=True,config={"displayModeBar":False})

    # ── v10: Triangulated Valuation — football field + reverse DCF ──────────
    st.markdown('<div class="section-header" style="margin-top:8px;">Triangulated Valuation</div>',
                unsafe_allow_html=True)
    ff_fig = chart_football_field(
        data["ticker"], price_in, currency,
        football_data["dcf_bear"], football_data["dcf_base"], football_data["dcf_bull"],
        football_data["pe_low"], football_data["pe_high"], football_data["ev_low"], football_data["ev_high"],
        football_data["peer_low"], football_data["peer_high"],
        football_data["week52_low"], football_data["week52_high"])
    if ff_fig is not None:
        st.plotly_chart(ff_fig, use_container_width=True, config={"displayModeBar": False})
    else:
        st.caption("Not enough independent methodologies had usable data to render a football field for this ticker.")

    rc1, rc2 = st.columns([1, 2])
    with rc1:
        if solve_converged:
            st.markdown(f'<div class="metric-card"><div class="metric-label">Market-Implied FCF Growth (Reverse DCF)</div>'
                        f'<div class="metric-value">{implied_growth:+.1f}%</div></div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="metric-card"><div class="metric-label">Market-Implied FCF Growth (Reverse DCF)</div>'
                        f'<div class="metric-value" style="font-size:1rem;">Outside solvable range</div></div>', unsafe_allow_html=True)
    with rc2:
        st.caption(f"To justify the current price of {currency}{price_in:,.2f}, the market is implicitly pricing in "
                   f"**{implied_growth:+.1f}% annual {cf_short.lower()} growth** for Years 1–5 (holding the {rate_label}, "
                   f"Stage-2 growth, and terminal growth you set above constant). "
                   + ("" if solve_converged else "This price falls outside what a −20% to +60% growth range can explain under these assumptions."))

    # ── v10: Forensic Diagnostics ─────────────────────────────────────────────
    st.markdown('<div class="section-header" style="margin-top:8px;">Forensic Diagnostics</div>',
                unsafe_allow_html=True)
    fc1, fc2, fc3, fc4 = st.columns(4)
    sloan = forensics.get("sloan", {})
    altman = forensics.get("altman", {})
    dupont = forensics.get("dupont", {})
    roic_sp = forensics.get("roic_spread", {})
    with fc1:
        val = f"{sloan['value']*100:.1f}%" if sloan.get("value") is not None else "N/A"
        st.markdown(f'<div class="metric-card"><div class="metric-label">Sloan Accruals Ratio</div>'
                    f'<div class="metric-value">{val}</div></div>', unsafe_allow_html=True)
    with fc2:
        val = f"{altman['value']:.2f}" if altman.get("value") is not None else "N/A"
        st.markdown(f'<div class="metric-card"><div class="metric-label">Altman Z-Score</div>'
                    f'<div class="metric-value">{val}</div></div>', unsafe_allow_html=True)
    with fc3:
        val = f"{dupont['roe_check']:.1f}%" if dupont.get("roe_check") is not None else "N/A"
        st.markdown(f'<div class="metric-card"><div class="metric-label">DuPont ROE</div>'
                    f'<div class="metric-value">{val}</div></div>', unsafe_allow_html=True)
    with fc4:
        val = f"{roic_sp['spread']:+.1f}pp" if roic_sp.get("spread") is not None else "N/A"
        st.markdown(f'<div class="metric-card"><div class="metric-label">ROIC-{rate_label} Spread</div>'
                    f'<div class="metric-value">{val}</div></div>', unsafe_allow_html=True)
    for label, met in [("Sloan Accruals", sloan), ("Altman Z-Score", altman),
                        ("DuPont Breakdown", dupont), (f"ROIC-{rate_label} Spread", roic_sp)]:
        note = met.get("note") or met.get("verdict") or met.get("zone")
        if note:
            st.caption(f"**{label}:** {note}")

    # ── v10: automated investment thesis ─────────────────────────────────────
    st.markdown('<div class="section-header" style="margin-top:8px;">Automated Investment Thesis</div>',
                unsafe_allow_html=True)
    for p in thesis:
        if p:
            st.markdown(f'<p style="font-size:.88rem;line-height:1.6;color:#374151;">{p}</p>', unsafe_allow_html=True)
    st.caption("Deterministic, template-generated summary of the metrics above — not written or reviewed by a human analyst, and not investment advice.")

    st.markdown(f'<div class="section-header" style="margin-top:8px;">{val_model} Model — Full Projection Table</div>',
                unsafe_allow_html=True)
    pj = pd.DataFrame(dcf_res["projections"])
    pj.columns = ["Year",f"{cf_short} ({unit})","Growth Rate","PV Factor",f"PV of {cf_short} ({unit})"]
    st.dataframe(pj.style.format({f"{cf_short} ({unit})":"{:,.2f}","PV Factor":"{:.4f}",
                                   f"PV of {cf_short} ({unit})":"{:,.2f}"}),
                 use_container_width=True, hide_index=True)

    if peers_data:
        st.markdown('<div class="section-header" style="margin-top:8px;">Comparable Company Analysis</div>',
                    unsafe_allow_html=True)
        # Same None -> "N/A" handling as the PDF's Section 07: without this,
        # st.dataframe renders a genuinely missing metric as a bare "None"/
        # blank cell, indistinguishable from a real value of zero.
        peers_df = pd.DataFrame(peers_data).fillna("N/A")
        st.dataframe(peers_df, use_container_width=True, hide_index=True)

    st.markdown('<div class="section-header" style="margin-top:8px;">Key Risk Flags</div>',
                unsafe_allow_html=True)
    for sev,txt in risks:
        cls = ("risk-flag" if sev=="HIGH" else
               "risk-moderate" if sev=="MODERATE" else "risk-low")
        ico = "🔴" if sev=="HIGH" else ("🟡" if sev=="MODERATE" else "🟢")
        st.markdown(f'<div class="{cls}">{ico} <b>{sev}</b> — {txt}</div>',
                    unsafe_allow_html=True)

    st.markdown("<div style='margin-top:30px;'></div>", unsafe_allow_html=True)
    st.markdown('<div class="section-header">Export Institutional Report (PDF)</div>',
                unsafe_allow_html=True)
    with st.spinner("Rendering PDF with charts…"):
        pdf_bytes = build_pdf(
            data,dcf_res,scenarios,sens_mat,peers_data,risks,
            verdict,intrinsic,mos_price,upside,
            wacc_in,g1_in,g2_in,tgr_in,mos_in,
            market,macro,currency,unit,
            forensics=forensics, thesis=thesis, football_data=football_data,
            multi_year=data.get("multi_year", []), consensus=consensus_data)
    fname = f"EquityLens_{data['ticker']}_{datetime.date.today().strftime('%Y%m%d')}.pdf"
    st.download_button("📄  Download Institutional PDF Report", data=pdf_bytes,
        file_name=fname, mime="application/pdf",
        use_container_width=True, type="primary")
    st.markdown("""<div class="info-box" style="margin-top:12px;">
      <b>PDF includes:</b> Cover page · Data quality notices · Company description ·
      Model-aware DCF table (Ke for FCFE/DDM, WACC for FCFF) ·
      Cash-flow projection &amp; value-bridge charts (Net Debt bar only for FCFF) ·
      WACC/Ke sensitivity heatmap · Bear/Base/Bull scenario analysis ·
      Comparable company analysis · Risk flags · Conviction level (not a recommendation) ·
      Watermark &amp; batch tracking
    </div>""", unsafe_allow_html=True)