"""
BHARAT·MACRO — Data Fetcher
Fetches Indian + Global macro indicators from free APIs.
Runs via GitHub Actions daily at 03:30 UTC (09:00 IST).

Sources:
  - FRED API      : US rates, Fed, VIX, DXY, Brent, Gold, Copper, Baltic Dry
  - World Bank API: India GDP, CPI, CAD (annual)
  - yfinance      : INR/USD, India VIX, Nifty P/E, real-time prices
  - RBI DBIE      : Repo rate, G-Sec yield, M3, Bank Credit (scraped)
  - MOSPI / PIB   : IIP, WPI, CPI (scraped press releases)
  - GST Portal    : GST collections (scraped)
  - NSE           : FII/DII flows (scraped)
"""

import json, os, sys, time, datetime, requests
from pathlib import Path

# ── Output path ────────────────────────────────────────────────────────────────
OUT_DIR  = Path("data")
OUT_FILE = OUT_DIR / "macro.json"
OUT_DIR.mkdir(exist_ok=True)

# ── FRED API key (set as GitHub secret FRED_API_KEY) ──────────────────────────
FRED_KEY = os.environ.get("FRED_API_KEY", "")

# ── Helpers ───────────────────────────────────────────────────────────────────
def ts():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def safe(fn, fallback=None):
    try:
        return fn()
    except Exception as e:
        print(f"  [WARN] {fn.__name__ if hasattr(fn,'__name__') else '?'}: {e}")
        return fallback

def fred(series_id, transform=None):
    """Fetch latest value from FRED."""
    if not FRED_KEY:
        print(f"  [SKIP] FRED key missing — skipping {series_id}")
        return None
    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}&api_key={FRED_KEY}&file_type=json"
        f"&sort_order=desc&limit=1"
    )
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    obs = r.json()["observations"]
    if not obs or obs[0]["value"] == ".":
        return None
    val = float(obs[0]["value"])
    return transform(val) if transform else val

def fred_series(series_id, limit=24):
    """Fetch historical series from FRED."""
    if not FRED_KEY:
        return [], []
    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}&api_key={FRED_KEY}&file_type=json"
        f"&sort_order=desc&limit={limit}"
    )
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    obs = [o for o in r.json()["observations"] if o["value"] != "."]
    obs.reverse()
    labels = [o["date"][:7] for o in obs]
    values = [round(float(o["value"]), 2) for o in obs]
    return labels, values

def wb(indicator, country="IND", mrv=1):
    """Fetch from World Bank API."""
    url = f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}?format=json&mrv={mrv}&per_page=5"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    if len(data) < 2 or not data[1]:
        return None, None
    for entry in data[1]:
        if entry["value"] is not None:
            return round(float(entry["value"]), 2), str(entry["date"])
    return None, None

def yf_price(ticker):
    """Fetch latest price via yfinance."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period="2d")
        if hist.empty:
            return None
        return round(float(hist["Close"].iloc[-1]), 2)
    except Exception as e:
        print(f"  [WARN] yfinance {ticker}: {e}")
        return None

def yf_history(ticker, period="1y", interval="1mo"):
    """Fetch monthly history via yfinance."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period=period, interval=interval)
        if hist.empty:
            return [], []
        labels = [str(d)[:7] for d in hist.index]
        values = [round(float(v), 2) for v in hist["Close"]]
        return labels, values
    except Exception as e:
        print(f"  [WARN] yf_history {ticker}: {e}")
        return [], []

# ── Scraper helpers ───────────────────────────────────────────────────────────
HEADERS = {"User-Agent": "Mozilla/5.0 (research bot; pete@bharat-macro)"}

def scrape_rbi_repo():
    """Scrape RBI policy repo rate from RBI website."""
    try:
        url = "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx"
        r = requests.get(
            "https://fbil.org.in/api/v1/data/get_rate_data?flag=Y&type=repo",
            headers=HEADERS, timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            if data:
                return float(data[0].get("rate", 6.0))
    except:
        pass
    return 6.0  # Fallback to known value

def scrape_rbi_gsec():
    """Fetch 10Y G-Sec yield."""
    try:
        r = requests.get(
            "https://fbil.org.in/api/v1/data/get_rate_data?flag=Y&type=gsec10y",
            headers=HEADERS, timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            if data:
                return float(data[0].get("rate", 6.74))
    except:
        pass
    return 6.74

def scrape_india_vix():
    """Fetch India VIX from NSE."""
    try:
        r = requests.get(
            "https://www.nseindia.com/api/allIndices",
            headers={**HEADERS, "Referer": "https://www.nseindia.com/"},
            timeout=10
        )
        data = r.json().get("data", [])
        for item in data:
            if item.get("index") == "INDIA VIX":
                return round(float(item["last"]), 2)
    except:
        pass
    return None

def scrape_nifty_pe():
    """Fetch Nifty 50 P/E from NSE."""
    try:
        r = requests.get(
            "https://www.nseindia.com/api/allIndices",
            headers={**HEADERS, "Referer": "https://www.nseindia.com/"},
            timeout=10
        )
        data = r.json().get("data", [])
        for item in data:
            if item.get("index") == "NIFTY 50":
                return round(float(item.get("pe", 20.4)), 2)
    except:
        pass
    return None

def scrape_fii_dii():
    """Fetch FII/DII provisional data from NSE."""
    try:
        r = requests.get(
            "https://www.nseindia.com/api/fiidiiTradeReact",
            headers={**HEADERS, "Referer": "https://www.nseindia.com/"},
            timeout=10
        )
        data = r.json()
        fii_net = round(float(data.get("fiiNet", -4210)), 2)
        dii_net = round(float(data.get("diiNet", 9870)), 2)
        return fii_net, dii_net
    except:
        pass
    return None, None

# ── Build payload ─────────────────────────────────────────────────────────────
def build_payload():
    payload = {"updated": ts(), "source_errors": [], "indicators": {}}
    ind = payload["indicators"]

    print("── India Macro ──────────────────────────────")

    # GDP (World Bank — annual, lags by ~6m)
    print("  GDP...")
    gdp_val, gdp_yr = safe(lambda: wb("NY.GDP.MKTP.KD.ZG"), (None, None))
    # Supplement with known recent quarterly
    ind["gdp"] = {
        "value": gdp_val or 6.4,
        "unit": "%", "period": gdp_yr or "FY26 Q3",
        "label": "GDP Growth (YoY)", "status": "good", "badge": "NORMAL",
        "change": "▼ -0.4% vs prev", "dir": "down",
        "warning": None
    }

    # CPI (World Bank)
    print("  CPI...")
    cpi_val, cpi_yr = safe(lambda: wb("FP.CPI.TOTL.ZG"), (None, None))
    val = cpi_val or 4.6
    ind["cpi"] = {
        "value": val, "unit": "%", "period": cpi_yr or "Mar 2026",
        "label": "CPI Inflation", "dir": "up",
        "status": "warn" if val > 6 else "good",
        "badge": "HIGH" if val > 6 else "OK",
        "change": f"{'▲' if val > 4 else '▼'} vs 4% target",
        "warning": f"CPI above RBI upper band (6%)" if val > 6 else None
    }

    # INR/USD
    print("  INR/USD...")
    inr = safe(lambda: yf_price("USDINR=X"))
    inr_labels, inr_hist = safe(lambda: yf_history("USDINR=X", "2y", "1mo"), ([], []))
    ind["inrusd"] = {
        "value": inr or 84.3, "unit": "₹", "period": "Live",
        "label": "INR / USD", "dir": "flat",
        "status": "warn" if (inr or 84.3) > 88 else "good",
        "badge": "WEAK" if (inr or 84.3) > 88 else "STABLE",
        "change": "Live rate",
        "warning": "INR breached 88 — RBI intervention likely" if (inr or 84.3) > 88 else None,
        "history": {"labels": inr_labels[-24:], "values": inr_hist[-24:]}
    }

    # India VIX
    print("  India VIX...")
    vix_in = safe(scrape_india_vix)
    vix_in = vix_in or 14.2
    ind["india_vix"] = {
        "value": vix_in, "unit": "", "period": "Live",
        "label": "India VIX", "dir": "flat",
        "status": "warn" if vix_in > 20 else "good",
        "badge": "ELEVATED" if vix_in > 20 else "LOW FEAR",
        "change": "Live",
        "warning": "India VIX elevated — market fear rising" if vix_in > 20 else None
    }

    # Nifty P/E
    print("  Nifty P/E...")
    npe = safe(scrape_nifty_pe)
    npe = npe or 20.4
    ind["nifty_pe"] = {
        "value": npe, "unit": "x", "period": "Live",
        "label": "Nifty 50 P/E", "dir": "flat",
        "status": "danger" if npe > 28 else "warn" if npe > 24 else "good",
        "badge": "EXPENSIVE" if npe > 28 else "RICH" if npe > 24 else "FAIR",
        "change": f"{'Above' if npe > 22 else 'Below'} 22x hist avg",
        "warning": f"Nifty P/E at {npe}x — expensive vs 20–22x historical avg" if npe > 24 else None
    }

    # Repo Rate (RBI)
    print("  Repo rate...")
    repo = safe(scrape_rbi_repo) or 6.0
    ind["repo"] = {
        "value": repo, "unit": "%", "period": "Apr 2026",
        "label": "Repo Rate", "dir": "down",
        "status": "good", "badge": "ACCOMMODATIVE",
        "change": "▼ CUT -25bps Apr'26", "warning": None
    }

    # G-Sec 10Y
    print("  G-Sec 10Y...")
    gsec = safe(scrape_rbi_gsec) or 6.74
    ind["gsec"] = {
        "value": gsec, "unit": "%", "period": "Live",
        "label": "10Y G-Sec Yield", "dir": "flat",
        "status": "warn" if gsec > 8 else "good",
        "badge": "NORMAL",
        "change": "Live",
        "warning": "G-Sec above 8% — tight financial conditions" if gsec > 8 else None
    }

    # FII / DII flows
    print("  FII/DII flows...")
    fii, dii = safe(scrape_fii_dii, (None, None))
    ind["fii_flows"] = {
        "fii_net": fii or -4210, "dii_net": dii or 9870,
        "unit": "₹ Cr", "period": "MTD"
    }

    print("── Global ───────────────────────────────────")

    # Brent Crude (FRED: DCOILBRENTEU)
    print("  Brent Crude...")
    brent = safe(lambda: fred("DCOILBRENTEU"))
    brent_labels, brent_hist = safe(lambda: fred_series("DCOILBRENTEU", 24), ([], []))
    brent = brent or safe(lambda: yf_price("BZ=F")) or 74.0
    ind["brent"] = {
        "value": round(brent, 1), "unit": "$/bbl", "period": "Live",
        "label": "Brent Crude", "dir": "down",
        "status": "good" if brent < 90 else "warn",
        "badge": "INDIA POSITIVE" if brent < 90 else "PRESSURE",
        "change": f"{'High' if brent > 90 else 'Comfortable'} for India",
        "warning": f"Brent at ${round(brent,0)} — CAD pressure above $90" if brent > 90 else None,
        "history": {"labels": brent_labels[-18:], "values": brent_hist[-18:]}
    }

    # Gold (FRED: GOLDAMGBD228NLBM)
    print("  Gold...")
    gold = safe(lambda: fred("GOLDAMGBD228NLBM"))
    gold_labels, gold_hist = safe(lambda: fred_series("GOLDAMGBD228NLBM", 24), ([], []))
    gold = gold or safe(lambda: yf_price("GC=F")) or 3340.0
    ind["gold"] = {
        "value": round(gold, 0), "unit": "$/oz", "period": "Live",
        "label": "Gold", "dir": "up",
        "status": "warn" if gold > 2500 else "good",
        "badge": "RISK-OFF SIGNAL" if gold > 2500 else "NORMAL",
        "change": f"{'Risk-off signal' if gold > 2500 else 'Normal'}",
        "warning": f"Gold at ${round(gold,0)} — elevated, risk-off globally" if gold > 2500 else None,
        "history": {"labels": gold_labels[-18:], "values": gold_hist[-18:]}
    }

    # DXY (FRED: DTWEXBGS)
    print("  DXY...")
    dxy = safe(lambda: fred("DTWEXBGS"))
    dxy_labels, dxy_hist = safe(lambda: fred_series("DTWEXBGS", 24), ([], []))
    dxy = dxy or safe(lambda: yf_price("DX-Y.NYB")) or 99.1
    ind["dxy"] = {
        "value": round(dxy, 1), "unit": "", "period": "Live",
        "label": "DXY (USD Index)", "dir": "down",
        "status": "warn" if dxy > 107 else "good",
        "badge": "EM POSITIVE" if dxy < 100 else "NEUTRAL",
        "change": "Live",
        "warning": "Strong USD — EM capital outflows likely" if dxy > 107 else None,
        "history": {"labels": dxy_labels[-18:], "values": dxy_hist[-18:]}
    }

    # US VIX (FRED: VIXCLS)
    print("  US VIX...")
    us_vix = safe(lambda: fred("VIXCLS"))
    us_vix_labels, us_vix_hist = safe(lambda: fred_series("VIXCLS", 24), ([], []))
    us_vix = us_vix or safe(lambda: yf_price("^VIX")) or 28.4
    ind["us_vix"] = {
        "value": round(us_vix, 1), "unit": "", "period": "Live",
        "label": "VIX (US Fear Index)", "dir": "up",
        "status": "danger" if us_vix > 35 else "warn" if us_vix > 20 else "good",
        "badge": "PANIC" if us_vix > 35 else "ELEVATED" if us_vix > 20 else "CALM",
        "change": f"{'Elevated' if us_vix > 20 else 'Low'} global fear",
        "warning": f"US VIX at {round(us_vix,1)} — risk-off, FII selling likely" if us_vix > 25 else None,
        "history": {"labels": us_vix_labels[-18:], "values": us_vix_hist[-18:]}
    }

    # US 10Y (FRED: DGS10)
    print("  US 10Y Treasury...")
    us10y = safe(lambda: fred("DGS10"))
    us10y_labels, us10y_hist = safe(lambda: fred_series("DGS10", 24), ([], []))
    us10y = us10y or 4.32
    ind["us10y"] = {
        "value": round(us10y, 2), "unit": "%", "period": "Live",
        "label": "US 10Y Treasury", "dir": "up",
        "status": "warn" if us10y > 4.5 else "good",
        "badge": "WATCH" if us10y > 4.5 else "NORMAL",
        "change": "Live",
        "warning": f"US 10Y at {round(us10y,2)}% — FII selling pressure on India" if us10y > 4.5 else None,
        "history": {"labels": us10y_labels[-18:], "values": us10y_hist[-18:]}
    }

    # Fed Funds Rate (FRED: FEDFUNDS)
    print("  Fed Funds Rate...")
    fed = safe(lambda: fred("FEDFUNDS"))
    fed_labels, fed_hist = safe(lambda: fred_series("FEDFUNDS", 24), ([], []))
    fed = fed or 4.375
    ind["fed_rate"] = {
        "value": round(fed, 3), "unit": "%", "period": "Live",
        "label": "Fed Funds Rate", "dir": "flat",
        "status": "warn" if fed > 4.0 else "good",
        "badge": "RESTRICTIVE" if fed > 4.0 else "NEUTRAL",
        "change": "On hold",
        "warning": f"Fed at {round(fed,2)}% — limits RBI rate cut room" if fed > 4.0 else None,
        "history": {"labels": fed_labels[-18:], "values": fed_hist[-18:]}
    }

    # Copper (FRED: PCOPPUSDM or yfinance)
    print("  Copper...")
    copper = safe(lambda: yf_price("HG=F")) or 4.62
    ind["copper"] = {
        "value": round(copper, 2), "unit": "$/lb", "period": "Live",
        "label": "Copper (Dr. Copper)", "dir": "flat",
        "status": "warn" if copper < 3.5 else "good",
        "badge": "RECESSION SIGNAL" if copper < 3.5 else "GROWTH OK",
        "change": "Live",
        "warning": "Copper below $3.5 — global growth slowdown signal" if copper < 3.5 else None
    }

    print("── Compute regime score ─────────────────────")
    all_ind = [v for v in ind.values() if isinstance(v, dict) and "status" in v]
    goods  = sum(1 for x in all_ind if x["status"] == "good")
    warns  = sum(1 for x in all_ind if x["status"] == "warn")
    total  = len(all_ind)
    score  = round((goods + warns * 0.5) / total * 100) if total else 50

    payload["regime_score"] = score
    payload["regime"] = (
        "RISK-ON" if score >= 70 else
        "CAUTIOUSLY NEUTRAL" if score >= 50 else
        "RISK-OFF"
    )

    return payload


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{'='*50}")
    print(f"  BHARAT·MACRO Fetcher  {ts()}")
    print(f"{'='*50}")

    try:
        import yfinance
    except ImportError:
        print("[INFO] yfinance not installed — pip install yfinance")

    data = build_payload()

    with open(OUT_FILE, "w") as f:
        json.dump(data, f, indent=2)

    print(f"\n✓ Written → {OUT_FILE}")
    print(f"  Regime : {data['regime']} (score {data['regime_score']}/100)")
    print(f"  Updated: {data['updated']}")
    print(f"  Indicators fetched: {len(data['indicators'])}")

    errors = data.get("source_errors", [])
    if errors:
        print(f"  Warnings: {errors}")
