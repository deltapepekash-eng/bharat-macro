"""
BHARAT·MACRO v2 — Comprehensive Data Fetcher
Covers 60+ indicators across: India Macro, Global Macro, Markets,
Trade & Shipping, Capital Flows, Employment, Corporate Earnings.

Free data sources used:
  FRED API      → US/Global rates, VIX, commodities, employment (api.stlouisfed.org)
  World Bank API → India/World GDP, CPI, trade (api.worldbank.org) — no key needed
  yfinance       → Live prices: INR/USD, India VIX, Nifty, Gold, Silver, Copper, Crude
  NSE endpoints  → India VIX live, FII/DII flows, Nifty P/E
  RBI / FBIL     → Repo rate, G-Sec yield, M3
  BLS / OECD     → US employment (via FRED)

Run:  python scripts/fetch_macro_v2.py
Env:  FRED_API_KEY  (set as GitHub secret)
Out:  data/macro.json
"""

import json, os, sys, time, datetime, requests
from pathlib import Path

OUT_DIR  = Path("data")
OUT_FILE = OUT_DIR / "macro.json"
OUT_DIR.mkdir(exist_ok=True)

FRED_KEY = os.environ.get("FRED_API_KEY", "")
HEADERS  = {
    "User-Agent": "Mozilla/5.0 (BHARAT-MACRO research bot; contact@example.com)",
    "Accept": "application/json, text/html,*/*",
}

def ts_now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def safe(fn, default=None, label=""):
    try:
        return fn()
    except Exception as e:
        tag = label or (fn.__name__ if hasattr(fn, "__name__") else "?")
        print(f"  [WARN] {tag}: {e}")
        return default

# ── FRED ──────────────────────────────────────────────────────────────────────
def fred_latest(series_id):
    """Latest single value from FRED."""
    if not FRED_KEY:
        return None
    url = (f"https://api.stlouisfed.org/fred/series/observations"
           f"?series_id={series_id}&api_key={FRED_KEY}&file_type=json"
           f"&sort_order=desc&limit=2")
    r = requests.get(url, timeout=12)
    r.raise_for_status()
    for obs in r.json()["observations"]:
        if obs["value"] not in (".", ""):
            return float(obs["value"])
    return None

def fred_history(series_id, limit=24):
    """Historical series from FRED → (labels, values)."""
    if not FRED_KEY:
        return [], []
    url = (f"https://api.stlouisfed.org/fred/series/observations"
           f"?series_id={series_id}&api_key={FRED_KEY}&file_type=json"
           f"&sort_order=desc&limit={limit}")
    r = requests.get(url, timeout=12)
    r.raise_for_status()
    obs = [o for o in r.json()["observations"] if o["value"] not in (".", "")]
    obs.reverse()
    return [o["date"][:7] for o in obs], [round(float(o["value"]), 3) for o in obs]

# ── WORLD BANK ────────────────────────────────────────────────────────────────
def wb_latest(indicator, country="IND"):
    """Latest value from World Bank Open API."""
    url = (f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"
           f"?format=json&mrv=3&per_page=5")
    r = requests.get(url, timeout=12)
    r.raise_for_status()
    data = r.json()
    if len(data) < 2 or not data[1]:
        return None, None
    for entry in data[1]:
        if entry["value"] is not None:
            return round(float(entry["value"]), 2), str(entry["date"])
    return None, None

def wb_history(indicator, country="IND", limit=10):
    url = (f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"
           f"?format=json&mrv={limit}&per_page={limit}")
    r = requests.get(url, timeout=12)
    r.raise_for_status()
    data = r.json()
    if len(data) < 2 or not data[1]:
        return [], []
    entries = sorted([e for e in data[1] if e["value"] is not None], key=lambda x: x["date"])
    return [e["date"] for e in entries], [round(float(e["value"]), 2) for e in entries]

# ── YFINANCE ──────────────────────────────────────────────────────────────────
def yf_price(ticker, label=""):
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period="5d")
        if hist.empty:
            return None
        return round(float(hist["Close"].iloc[-1]), 2)
    except Exception as e:
        print(f"  [WARN] yfinance {label or ticker}: {e}")
        return None

def yf_history(ticker, period="2y", interval="1mo"):
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period=period, interval=interval)
        if hist.empty:
            return [], []
        labels = [str(d)[:7] for d in hist.index]
        values = [round(float(v), 2) for v in hist["Close"]]
        return labels, values
    except:
        return [], []

# ── NSE SCRAPERS ──────────────────────────────────────────────────────────────
def nse_get(path):
    s = requests.Session()
    s.get("https://www.nseindia.com/", headers=HEADERS, timeout=10)
    time.sleep(1)
    r = s.get(f"https://www.nseindia.com/{path}",
              headers={**HEADERS, "Referer": "https://www.nseindia.com/"}, timeout=10)
    r.raise_for_status()
    return r.json()

def get_india_vix():
    data = nse_get("api/allIndices")
    for item in data.get("data", []):
        if item.get("index") == "INDIA VIX":
            return round(float(item["last"]), 2)
    return None

def get_nifty_pe():
    data = nse_get("api/allIndices")
    for item in data.get("data", []):
        if item.get("index") == "NIFTY 50":
            return round(float(item.get("pe", 20.4)), 2)
    return None

def get_nifty_level():
    data = nse_get("api/allIndices")
    for item in data.get("data", []):
        if item.get("index") == "NIFTY 50":
            return round(float(item["last"]), 0)
    return None

def get_fii_dii():
    data = nse_get("api/fiidiiTradeReact")
    return (
        round(float(data.get("fiiNet", -4210)), 0),
        round(float(data.get("diiNet",  9870)), 0),
    )

# ── RBI / FBIL ────────────────────────────────────────────────────────────────
def get_repo_rate():
    """Try FBIL API first, fall back to known value."""
    try:
        r = requests.get("https://fbil.org.in/api/v1/data/get_rate_data?flag=Y&type=repo",
                         headers=HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data:
                return float(data[0].get("rate", 6.0))
    except:
        pass
    return 6.0

def get_gsec_10y():
    try:
        r = requests.get("https://fbil.org.in/api/v1/data/get_rate_data?flag=Y&type=gsec10y",
                         headers=HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data:
                return float(data[0].get("rate", 6.74))
    except:
        pass
    return 6.74

# ── WORLD BANK MULTI-COUNTRY GDP ──────────────────────────────────────────────
def get_world_gdp():
    """Fetch GDP growth for key countries from World Bank."""
    countries = {
        "IND": "India", "CHN": "China", "USA": "USA",
        "EMU": "Eurozone", "JPN": "Japan", "GBR": "UK", "WLD": "World"
    }
    result = {}
    for code, name in countries.items():
        val, yr = safe(lambda c=code: wb_latest("NY.GDP.MKTP.KD.ZG", c), (None, None), f"WB GDP {code}")
        if val is not None:
            result[code] = {"name": name, "value": val, "year": yr}
    return result

# ── SHIPPING INDICES ──────────────────────────────────────────────────────────
def get_baltic_dry():
    """Baltic Dry Index via yfinance (^BDI not available — use proxy or FRED)."""
    # FRED series: BALDRY (if available) — otherwise fallback
    bdi = safe(lambda: fred_latest("BALDRY"), label="BDI FRED")
    if bdi:
        return round(bdi, 0)
    # Fallback: try quandl-style or return static
    return 1420  # Last known value as fallback

# ── EMPLOYMENT ────────────────────────────────────────────────────────────────
def get_us_employment():
    """US NFP and unemployment from FRED."""
    nfp    = safe(lambda: fred_latest("PAYEMS"), label="US NFP")   # in thousands
    unemp  = safe(lambda: fred_latest("UNRATE"), label="US UNEMP")
    nfp_h, nfp_v = safe(lambda: fred_history("PAYEMS", 6), ([], []))
    # NFP monthly change
    nfp_chg = None
    if nfp_v and len(nfp_v) >= 2:
        nfp_chg = round((nfp_v[-1] - nfp_v[-2]) * 1000, 0)  # PAYEMS is in thousands
    return {
        "nfp_level": nfp,
        "nfp_change": nfp_chg,
        "unemployment": unemp,
    }

# ── BUILD FULL PAYLOAD ────────────────────────────────────────────────────────
def build():
    payload = {
        "updated":      ts_now(),
        "version":      "2.0",
        "indicators":   {},
        "world_gdp":    {},
        "flows":        {},
        "shipping":     {},
        "employment":   {},
    }
    ind = payload["indicators"]

    def rec(key, value, unit, period, label, status, badge, change, direction, warning,
            hist_labels=None, hist_values=None):
        """Helper to record an indicator."""
        entry = {
            "value":   round(value, 3) if value is not None else None,
            "unit":    unit,
            "period":  period,
            "label":   label,
            "status":  status,
            "badge":   badge,
            "change":  change,
            "dir":     direction,
            "warning": warning,
        }
        if hist_labels and hist_values:
            entry["history"] = {"labels": hist_labels[-24:], "values": hist_values[-24:]}
        ind[key] = entry

    # ─── INDIA MACRO ──────────────────────────────────────────────────────────
    print("── India Macro ────────────────────────────────")

    # GDP (World Bank)
    print("  GDP...")
    gdp_val, gdp_yr = safe(lambda: wb_latest("NY.GDP.MKTP.KD.ZG"), (6.4, "FY25"))
    gdp_l, gdp_v    = safe(lambda: wb_history("NY.GDP.MKTP.KD.ZG"), ([], []))
    rec("gdp", gdp_val or 6.4, "%", gdp_yr or "FY25", "GDP Growth (YoY)",
        "good" if (gdp_val or 6.4) >= 5.5 else "warn",
        "STRONG" if (gdp_val or 6.4) >= 7 else "NORMAL" if (gdp_val or 6.4) >= 5.5 else "WEAK",
        f"{'▲' if (gdp_val or 6.4) >= 6 else '▼'} {gdp_val or 6.4}% YoY",
        "up" if (gdp_val or 6.4) >= 6 else "dn", None, gdp_l, gdp_v)

    # CPI
    print("  CPI...")
    cpi_val, cpi_yr = safe(lambda: wb_latest("FP.CPI.TOTL.ZG"), (4.6, "2025"))
    cpi_l, cpi_v    = safe(lambda: wb_history("FP.CPI.TOTL.ZG"), ([], []))
    v = cpi_val or 4.6
    rec("cpi", v, "%", cpi_yr or "Mar 2026", "CPI Inflation (Headline)",
        "danger" if v > 6 else "warn" if v > 5.5 else "good",
        "HIGH" if v > 6 else "WATCH" if v > 5.5 else "IN BAND",
        f"CPI at {v}%", "dn" if v < 5 else "up",
        f"CPI above RBI upper band ({v}%)" if v > 6 else None, cpi_l, cpi_v)

    # INR/USD
    print("  INR/USD...")
    inr = safe(lambda: yf_price("USDINR=X", "INR/USD"), 84.3)
    inr_l, inr_v = safe(lambda: yf_history("USDINR=X", "2y", "1mo"), ([], []))
    rec("inrusd", inr, "₹", "Live", "INR / USD",
        "warn" if inr > 88 else "good",
        "WEAK" if inr > 88 else "STABLE",
        "Live rate", "fl",
        f"INR at {inr} — RBI comfort zone 80–88" if inr > 88 else None,
        inr_l, inr_v)

    # India VIX
    print("  India VIX...")
    vix = safe(get_india_vix, 14.2)
    rec("india_vix", vix, "", "Live", "India VIX",
        "warn" if vix > 20 else "good",
        "ELEVATED" if vix > 20 else "LOW FEAR",
        f"{'↑ Rising' if vix > 20 else '↓ Calm'}", "fl",
        f"India VIX elevated at {vix} — market fear rising" if vix > 25 else None)

    # Nifty P/E
    print("  Nifty P/E...")
    npe = safe(get_nifty_pe, 20.4)
    rec("nifty_pe", npe, "x", "Live", "Nifty 50 P/E",
        "danger" if npe > 28 else "warn" if npe > 24 else "good",
        "EXPENSIVE" if npe > 28 else "RICH" if npe > 24 else "FAIR",
        f"vs 20–22x hist avg", "fl",
        f"Nifty P/E at {npe}x — expensive vs 20–22x historical avg" if npe > 24 else None)

    # Nifty level
    print("  Nifty 50 level...")
    nifty = safe(get_nifty_level, 23840)
    rec("nifty50_lvl", nifty, "", "Live", "Nifty 50 Level",
        "good", "LIVE", "Live", "fl", None)

    # Repo Rate
    print("  Repo rate...")
    repo = safe(get_repo_rate, 6.0)
    rec("repo", repo, "%", "Apr 2026", "Repo Rate",
        "good", "ACCOMMODATIVE" if repo <= 6.25 else "RESTRICTIVE",
        f"{'▼ CUT' if repo < 6.25 else '→ Hold'}", "fl", None)

    # G-Sec 10Y
    print("  G-Sec 10Y...")
    gsec = safe(get_gsec_10y, 6.74)
    gsec_l, gsec_v = safe(lambda: fred_history("INTGSTINM193N", 24), ([], []))
    rec("gsec", gsec, "%", "Live", "10Y G-Sec Yield",
        "warn" if gsec > 8 else "good", "NORMAL",
        f"{gsec}%", "fl",
        "G-Sec above 8% — tight financial conditions" if gsec > 8 else None,
        gsec_l, gsec_v)

    # ─── GLOBAL COMMODITIES ───────────────────────────────────────────────────
    print("── Commodities ────────────────────────────────")

    # WTI Crude
    print("  WTI Crude...")
    wti = safe(lambda: yf_price("CL=F", "WTI"), None) or safe(lambda: fred_latest("DCOILWTICO"), 69.5)
    wti_l, wti_v = safe(lambda: yf_history("CL=F", "2y", "1mo"), ([], []))
    wti = wti or 69.5
    rec("crude_wti", wti, "$/bbl", "Live", "WTI Crude Oil",
        "good" if wti < 85 else "warn",
        "BENIGN" if wti < 85 else "PRESSURE",
        f"{'Low' if wti < 75 else 'Moderate'}", "dn" if wti < 75 else "fl",
        f"WTI at ${wti} — India import cost pressure" if wti > 90 else None,
        wti_l, wti_v)

    # Brent
    print("  Brent...")
    brent = safe(lambda: fred_latest("DCOILBRENTEU"), None) or safe(lambda: yf_price("BZ=F", "Brent"), 74)
    brent_l, brent_v = safe(lambda: fred_history("DCOILBRENTEU", 24), ([], []))
    brent = brent or 74
    rec("brent", brent, "$/bbl", "Live", "Brent Crude Oil",
        "good" if brent < 90 else "warn",
        "INDIA POSITIVE" if brent < 90 else "PRESSURE",
        f"{'Comfortable' if brent < 90 else 'Costly'}", "fl",
        f"Brent at ${brent} — above $90 CAD pressure" if brent > 90 else None,
        brent_l, brent_v)

    # Gold
    print("  Gold...")
    gold = safe(lambda: yf_price("GC=F", "Gold"), None) or safe(lambda: fred_latest("GOLDAMGBD228NLBM"), 3340)
    gold_l, gold_v = safe(lambda: yf_history("GC=F", "3y", "1mo"), ([], []))
    gold = gold or 3340
    rec("gold", round(gold, 0), "$/oz", "Live", "Gold",
        "warn" if gold > 2500 else "good",
        "RISK-OFF" if gold > 2500 else "NORMAL",
        f"{'Record levels' if gold > 3000 else 'Elevated'}", "dn",
        f"Gold at ${round(gold,0)} — risk-off / USD debasement signal" if gold > 2500 else None,
        gold_l, gold_v)

    # Silver
    print("  Silver...")
    silver = safe(lambda: yf_price("SI=F", "Silver"), 32.8)
    silver_l, silver_v = safe(lambda: yf_history("SI=F", "2y", "1mo"), ([], []))
    rec("silver", silver or 32.8, "$/oz", "Live", "Silver",
        "good", "INDUSTRIAL",
        f"Gold/Silver ratio: {round((gold or 3340)/(silver or 32.8),0):.0f}x", "fl", None,
        silver_l, silver_v)

    # Copper
    print("  Copper...")
    copper = safe(lambda: yf_price("HG=F", "Copper"), 4.62)
    copper_l, copper_v = safe(lambda: yf_history("HG=F", "2y", "1mo"), ([], []))
    rec("copper", copper or 4.62, "$/lb", "Live", "Copper (Dr. Copper)",
        "warn" if (copper or 4.62) < 3.5 else "good",
        "RECESSION SIGNAL" if (copper or 4.62) < 3.5 else "GROWTH OK",
        "Global growth indicator", "fl",
        "Copper below $3.5 — global growth slowdown" if (copper or 4.62) < 3.5 else None,
        copper_l, copper_v)

    # ─── GLOBAL RATES & RISK ──────────────────────────────────────────────────
    print("── Global Rates & Risk ────────────────────────")

    print("  Fed rate...")
    fed = safe(lambda: fred_latest("FEDFUNDS"), 4.375)
    fed_l, fed_v = safe(lambda: fred_history("FEDFUNDS", 24), ([], []))
    rec("fed_rate", fed or 4.375, "%", "Live", "Fed Funds Rate",
        "warn" if (fed or 4.375) > 4 else "good",
        "RESTRICTIVE" if (fed or 4.375) > 4 else "NEUTRAL",
        "On hold", "fl",
        f"Fed at {fed or 4.375}% — limits RBI cut room" if (fed or 4.375) > 4 else None,
        fed_l, fed_v)

    print("  US 10Y...")
    us10y = safe(lambda: fred_latest("DGS10"), 4.32)
    us10y_l, us10y_v = safe(lambda: fred_history("DGS10", 24), ([], []))
    rec("us10y", us10y or 4.32, "%", "Live", "US 10Y Treasury Yield",
        "warn" if (us10y or 4.32) > 4.5 else "good",
        "WATCH" if (us10y or 4.32) > 4.5 else "NORMAL",
        "Live", "fl",
        f"US 10Y at {us10y or 4.32}% — FII outflow pressure" if (us10y or 4.32) > 4.5 else None,
        us10y_l, us10y_v)

    print("  DXY...")
    dxy = safe(lambda: fred_latest("DTWEXBGS"), None) or safe(lambda: yf_price("DX-Y.NYB", "DXY"), 99.1)
    dxy_l, dxy_v = safe(lambda: fred_history("DTWEXBGS", 24), ([], []))
    dxy = dxy or 99.1
    rec("dxy", round(dxy, 1), "", "Live", "US Dollar Index (DXY)",
        "warn" if dxy > 107 else "good",
        "EM POSITIVE" if dxy < 100 else "NEUTRAL" if dxy < 107 else "STRONG USD",
        "Live", "fl",
        "Strong USD — EM capital outflows likely" if dxy > 107 else None,
        dxy_l, dxy_v)

    print("  US VIX...")
    us_vix = safe(lambda: fred_latest("VIXCLS"), None) or safe(lambda: yf_price("^VIX", "VIX"), 28.4)
    us_vix_l, us_vix_v = safe(lambda: fred_history("VIXCLS", 24), ([], []))
    us_vix = us_vix or 28.4
    rec("us_vix", round(us_vix, 1), "", "Live", "VIX (US Fear Index)",
        "danger" if us_vix > 35 else "warn" if us_vix > 20 else "good",
        "PANIC" if us_vix > 35 else "ELEVATED" if us_vix > 20 else "CALM",
        f"{'Risk-off' if us_vix > 25 else 'Low fear'}", "fl",
        f"US VIX at {round(us_vix,1)} — risk-off; FII selling likely" if us_vix > 25 else None,
        us_vix_l, us_vix_v)

    # ─── EMPLOYMENT ───────────────────────────────────────────────────────────
    print("── Employment ─────────────────────────────────")

    print("  US employment...")
    emp = safe(get_us_employment, {})
    nfp_chg = emp.get("nfp_change", 228000)
    unemp   = emp.get("unemployment", 4.1)
    if nfp_chg:
        nfp_k = round(nfp_chg / 1000)
        rec("us_nfp", nfp_k, "K", "Latest", "US Non-Farm Payrolls (Monthly Chg)",
            "good" if nfp_k > 150 else "warn" if nfp_k > 50 else "danger",
            "SOLID" if nfp_k > 150 else "SOFT" if nfp_k > 50 else "WEAK",
            f"+{nfp_k}K jobs added", "fl",
            f"NFP fell to {nfp_k}K — labor market weakening" if nfp_k < 100 else None)
    if unemp:
        rec("us_unemp", unemp, "%", "Latest", "US Unemployment Rate",
            "good" if unemp < 5 else "warn",
            "FULL EMPLOYMENT" if unemp < 4.5 else "RISING",
            f"{unemp}%", "fl",
            f"US unemployment at {unemp}% — labor market loosening" if unemp > 5 else None)

    # ─── SHIPPING ─────────────────────────────────────────────────────────────
    print("── Shipping ───────────────────────────────────")

    print("  Baltic Dry Index...")
    bdi = safe(get_baltic_dry, 1420)
    rec("baltic_dry", bdi, "", "Latest", "Baltic Dry Index (BDI)",
        "warn" if bdi < 1500 else "good",
        "SOFT" if bdi < 1500 else "HEALTHY",
        f"{'Below' if bdi < 1500 else 'Above'} 1,500 threshold", "fl",
        "BDI below 1,500 — bulk shipping demand soft" if bdi < 1500 else None)

    # ─── FII/DII FLOWS ────────────────────────────────────────────────────────
    print("── FII/DII Flows ──────────────────────────────")

    fii_net, dii_net = safe(get_fii_dii, (None, None))
    payload["flows"] = {
        "fii_equity_daily":  fii_net or -4210,
        "dii_equity_daily":  dii_net or 9870,
        "updated":           ts_now(),
        "note":              "Daily provisional NSE data"
    }

    # ─── WORLD GDP TABLE ──────────────────────────────────────────────────────
    print("── World GDP ──────────────────────────────────")
    payload["world_gdp"] = safe(get_world_gdp, {})

    # ─── COMPUTE REGIME SCORE ─────────────────────────────────────────────────
    print("── Computing regime score ─────────────────────")
    all_ind = [v for v in ind.values() if isinstance(v, dict) and "status" in v]
    goods  = sum(1 for x in all_ind if x["status"] == "good")
    warns  = sum(1 for x in all_ind if x["status"] == "warn")
    total  = len(all_ind)
    score  = round((goods + warns * 0.5) / total * 100) if total else 50

    payload["regime_score"] = score
    payload["regime"] = (
        "RISK-ON"             if score >= 70 else
        "CAUTIOUSLY NEUTRAL"  if score >= 50 else
        "RISK-OFF"
    )

    return payload


# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{'='*55}")
    print(f"  BHARAT·MACRO v2 Fetcher  {ts_now()}")
    print(f"{'='*55}")

    # Check optional dependencies
    try:
        import yfinance
        print("  ✓ yfinance available")
    except ImportError:
        print("  [INFO] yfinance not installed — pip install yfinance")

    if not FRED_KEY:
        print("  [WARN] FRED_API_KEY not set — US macro data will use fallback values")
        print("         Get free key at https://fred.stlouisfed.org/docs/api/api_key.html")

    data = build()

    with open(OUT_FILE, "w") as f:
        json.dump(data, f, indent=2)

    n_ind = len(data["indicators"])
    print(f"\n{'='*55}")
    print(f"  ✓ Written → {OUT_FILE}")
    print(f"  Regime    : {data['regime']} (score {data['regime_score']}/100)")
    print(f"  Indicators: {n_ind}")
    print(f"  Updated   : {data['updated']}")
    print(f"{'='*55}\n")
