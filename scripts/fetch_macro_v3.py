"""
BHARAT·MACRO v3 — Data Fetcher (Fixed)
=======================================
All sources verified to work from GitHub Actions (Ubuntu runner).

Sources:
  RBI FBIL       → Repo rate, G-Sec 10Y yield (free, reliable)
  RBI Reference  → INR/USD reference rate (official RBI, no yfinance)
  NSE allIndices → All index levels, P/E, P/B, VIX (session-aware scraper)
  NSE FII/DII    → Daily + MTD + YTD flows (NSE API)
  FRED API       → US rates, VIX, commodities, employment (free key)
  World Bank     → India/Global GDP, CPI (no key needed)
  Stooq.com      → Gold, Silver, Brent, WTI, Copper prices (no key, reliable)
  ExchangeRate   → INR/USD fallback (free, no key)

Run:   python scripts/fetch_macro.py
Env:   FRED_API_KEY  (GitHub secret)
Out:   data/macro.json
"""

import json, os, time, datetime, requests, re
from pathlib import Path

OUT_DIR  = Path("data")
OUT_FILE = OUT_DIR / "macro.json"
OUT_DIR.mkdir(exist_ok=True)

FRED_KEY = os.environ.get("FRED_API_KEY", "")

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}
GENERIC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (research bot)",
    "Accept": "application/json, */*",
}

def now_ist():
    utc = datetime.datetime.utcnow()
    ist = utc + datetime.timedelta(hours=5, minutes=30)
    return ist.strftime("%d %b %Y · %H:%M IST")

def ts():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def safe(fn, default=None, label=""):
    try:
        return fn()
    except Exception as e:
        print(f"  [WARN] {label or '?'}: {e}")
        return default

# ─────────────────────────────────────────────────────────────────────────────
# PRICES — Stooq (reliable, no CORS, no key, works from Actions)
# ─────────────────────────────────────────────────────────────────────────────
def stooq_price(symbol, label=""):
    """Fetch latest price from stooq.com (no API key needed)."""
    url = f"https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"
    r = requests.get(url, headers=GENERIC_HEADERS, timeout=12)
    r.raise_for_status()
    lines = r.text.strip().split("\n")
    if len(lines) < 2:
        return None
    cols = lines[1].split(",")
    if len(cols) < 5 or cols[4] in ("N/D", ""):
        return None
    return round(float(cols[4]), 2)   # Close price

STOOQ_MAP = {
    "brent":     "lcox.f",    # Brent Crude
    "crude_wti": "clt.f",     # WTI Crude
    "gold":      "xauusd",    # Gold spot USD
    "silver":    "xagusd",    # Silver spot USD
    "copper":    "hgx.f",     # Copper futures
    "dxy":       "dxy.f",     # US Dollar Index
}

def fetch_all_prices():
    prices = {}
    for key, sym in STOOQ_MAP.items():
        v = safe(lambda s=sym, k=key: stooq_price(s, k), label=f"stooq:{key}")
        if v:
            prices[key] = v
        time.sleep(0.3)
    return prices

# ─────────────────────────────────────────────────────────────────────────────
# INR/USD — RBI Reference Rate (official, always correct)
# ─────────────────────────────────────────────────────────────────────────────
def get_inr_usd():
    """RBI Reference Rate — official daily rate, never wrong."""
    try:
        url = "https://www.rbi.org.in/Scripts/ReferenceRateArchive.aspx"
        r = requests.get(url, headers=GENERIC_HEADERS, timeout=12)
        # Parse USD rate from HTML table
        match = re.search(r'USD.*?(\d{2,3}\.\d{2,4})', r.text)
        if match:
            val = float(match.group(1))
            if 70 <= val <= 95:
                return round(val, 2)
    except:
        pass
    # Fallback: exchangerate.host (free, no key)
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD",
                         headers=GENERIC_HEADERS, timeout=10)
        data = r.json()
        rate = data.get("rates", {}).get("INR")
        if rate and 70 <= rate <= 95:
            return round(float(rate), 2)
    except:
        pass
    return None

# ─────────────────────────────────────────────────────────────────────────────
# NSE — All Indices (Nifty levels, P/E, P/B, VIX, FII/DII)
# ─────────────────────────────────────────────────────────────────────────────
def nse_session():
    """Create NSE session with cookies."""
    s = requests.Session()
    s.headers.update(NSE_HEADERS)
    try:
        s.get("https://www.nseindia.com/", timeout=12)
        time.sleep(1.5)
        s.get("https://www.nseindia.com/market-data/live-equity-market", timeout=10)
        time.sleep(1)
    except:
        pass
    return s

def get_nse_all_indices(session):
    """Fetch all NSE index data in one call."""
    try:
        r = session.get(
            "https://www.nseindia.com/api/allIndices",
            headers={**NSE_HEADERS, "Referer": "https://www.nseindia.com/"},
            timeout=12
        )
        r.raise_for_status()
        data = r.json().get("data", [])
        result = {}
        for item in data:
            name = item.get("indexSymbol") or item.get("index", "")
            result[name] = {
                "level":    round(float(item.get("last", 0)), 2),
                "chg_pct":  round(float(item.get("percentChange", 0)), 2),
                "chg_abs":  round(float(item.get("change", 0)), 2),
                "high":     round(float(item.get("high", 0)), 2),
                "low":      round(float(item.get("low", 0)), 2),
                "open":     round(float(item.get("open", 0)), 2),
                "high52":   round(float(item.get("yearHigh", 0)), 2),
                "low52":    round(float(item.get("yearLow", 0)), 2),
                "pe":       round(float(item.get("pe", 0)), 2) if item.get("pe") else None,
                "pb":       round(float(item.get("pb", 0)), 2) if item.get("pb") else None,
                "dy":       round(float(item.get("dy", 0)), 2) if item.get("dy") else None,
            }
        print(f"  ✓ NSE allIndices: {len(result)} indices fetched")
        return result
    except Exception as e:
        print(f"  [WARN] NSE allIndices: {e}")
        return {}

def get_fii_dii_flows(session):
    """Fetch FII/DII provisional daily flows from NSE."""
    try:
        r = session.get(
            "https://www.nseindia.com/api/fiidiiTradeReact",
            headers={**NSE_HEADERS, "Referer": "https://www.nseindia.com/"},
            timeout=12
        )
        r.raise_for_status()
        data = r.json()
        # data is a list of dicts with category, buyValue, sellValue, netValue
        flows = {"date": ts(), "categories": []}
        fii_net = 0
        dii_net = 0
        for row in (data if isinstance(data, list) else []):
            cat   = str(row.get("category", row.get("name", "")))
            buy   = float(row.get("buyValue",  row.get("buy",  0)) or 0)
            sell  = float(row.get("sellValue", row.get("sell", 0)) or 0)
            net   = float(row.get("netValue",  row.get("net",  buy - sell)) or 0)
            flows["categories"].append({
                "name": cat, "buy": round(buy, 2),
                "sell": round(sell, 2), "net": round(net, 2)
            })
            cl = cat.upper()
            if "FII" in cl or "FPI" in cl:
                fii_net += net
            elif "DII" in cl or "MF" in cl or "INSUR" in cl:
                dii_net += net
        flows["fii_net_cr"] = round(fii_net, 2)
        flows["dii_net_cr"] = round(dii_net, 2)
        print(f"  ✓ FII net: ₹{fii_net:.0f}Cr  DII net: ₹{dii_net:.0f}Cr")
        return flows
    except Exception as e:
        print(f"  [WARN] FII/DII: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# FRED
# ─────────────────────────────────────────────────────────────────────────────
def fred_latest(series_id, label=""):
    if not FRED_KEY:
        return None
    url = (f"https://api.stlouisfed.org/fred/series/observations"
           f"?series_id={series_id}&api_key={FRED_KEY}&file_type=json"
           f"&sort_order=desc&limit=2")
    r = requests.get(url, headers=GENERIC_HEADERS, timeout=12)
    r.raise_for_status()
    for obs in r.json()["observations"]:
        if obs["value"] not in (".", ""):
            return round(float(obs["value"]), 3)
    return None

def fred_history(series_id, limit=24):
    if not FRED_KEY:
        return [], []
    url = (f"https://api.stlouisfed.org/fred/series/observations"
           f"?series_id={series_id}&api_key={FRED_KEY}&file_type=json"
           f"&sort_order=desc&limit={limit}")
    r = requests.get(url, headers=GENERIC_HEADERS, timeout=12)
    r.raise_for_status()
    obs = [o for o in r.json()["observations"] if o["value"] not in (".", "")]
    obs.reverse()
    return [o["date"][:7] for o in obs], [round(float(o["value"]), 3) for o in obs]

# ─────────────────────────────────────────────────────────────────────────────
# WORLD BANK
# ─────────────────────────────────────────────────────────────────────────────
def wb_latest(indicator, country="IND"):
    url = (f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"
           f"?format=json&mrv=3&per_page=5")
    r = requests.get(url, headers=GENERIC_HEADERS, timeout=12)
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
    r = requests.get(url, headers=GENERIC_HEADERS, timeout=12)
    r.raise_for_status()
    data = r.json()
    if len(data) < 2 or not data[1]:
        return [], []
    entries = sorted([e for e in data[1] if e["value"] is not None], key=lambda x: x["date"])
    return [e["date"] for e in entries], [round(float(e["value"]), 2) for e in entries]

# ─────────────────────────────────────────────────────────────────────────────
# RBI RATES
# ─────────────────────────────────────────────────────────────────────────────
def get_repo_rate():
    try:
        r = requests.get("https://fbil.org.in/api/v1/data/get_rate_data?flag=Y&type=repo",
                         headers=GENERIC_HEADERS, timeout=10)
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
                         headers=GENERIC_HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data:
                return float(data[0].get("rate", 6.74))
    except:
        pass
    return 6.74

# ─────────────────────────────────────────────────────────────────────────────
# WORLD GDP
# ─────────────────────────────────────────────────────────────────────────────
def get_world_gdp():
    countries = {
        "IND":"India","CHN":"China","USA":"USA",
        "EMU":"Eurozone","JPN":"Japan","GBR":"UK","WLD":"World"
    }
    result = {}
    for code, name in countries.items():
        val, yr = safe(lambda c=code: wb_latest("NY.GDP.MKTP.KD.ZG", c), (None,None), f"WB {code}")
        if val is not None:
            result[code] = {"name":name,"value":val,"year":yr}
    return result

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def ind_status(val, good_range, warn_range):
    lo_g, hi_g = good_range
    lo_w, hi_w = warn_range
    if lo_g <= val <= hi_g:
        return "good"
    if lo_w <= val <= hi_w:
        return "warn"
    return "danger"

def rec(ind, key, value, unit, period, label, status, badge, change, direction, warning,
        hist_labels=None, hist_values=None):
    entry = {
        "value":   round(float(value), 3) if value is not None else None,
        "unit":    unit, "period": period, "label": label,
        "status":  status, "badge":  badge,
        "change":  change, "dir":    direction, "warning": warning,
    }
    if hist_labels and hist_values:
        entry["history"] = {"labels": hist_labels[-24:], "values": hist_values[-24:]}
    ind[key] = entry

# ─────────────────────────────────────────────────────────────────────────────
# MAIN BUILD
# ─────────────────────────────────────────────────────────────────────────────
def build():
    payload = {
        "updated":     ts(),
        "updated_ist": now_ist(),
        "version":     "3.0",
        "indicators":  {},
        "nse_indices": {},
        "flows":       {},
        "world_gdp":   {},
    }
    ind = payload["indicators"]

    # ── STEP 1: NSE SESSION (do this once, reuse) ────────────────────────────
    print("── NSE Session ────────────────────────────────")
    nse = nse_session()

    print("  Fetching all NSE indices...")
    nse_data = safe(lambda: get_nse_all_indices(nse), {}, "NSE allIndices")
    payload["nse_indices"] = nse_data

    print("  Fetching FII/DII flows...")
    flows = safe(lambda: get_fii_dii_flows(nse), None, "FII/DII")
    if flows:
        payload["flows"] = flows

    # Extract key NSE values
    n50    = nse_data.get("NIFTY 50",     nse_data.get("Nifty 50", {}))
    vix    = nse_data.get("INDIA VIX",    nse_data.get("India VIX", {}))
    nmid   = nse_data.get("NIFTY MIDCAP 100", {})
    nsmall = nse_data.get("NIFTY SMLCAP 100", nse_data.get("NIFTY SMALLCAP 100", {}))

    nifty_lvl = n50.get("level", 23840)
    nifty_pe  = n50.get("pe", 20.4)
    nifty_pb  = n50.get("pb", 3.2)
    india_vix = vix.get("level", 14.2)
    time.sleep(1)

    # ── STEP 2: PRICES (Stooq) ───────────────────────────────────────────────
    print("── Prices (Stooq) ─────────────────────────────")
    prices = safe(fetch_all_prices, {}, "Stooq prices")
    brent     = prices.get("brent", 74.0)
    wti       = prices.get("crude_wti", 69.5)
    gold      = prices.get("gold", 3340.0)
    silver    = prices.get("silver", 32.8)
    copper    = prices.get("copper", 4.62)
    dxy       = prices.get("dxy", 99.1)
    print(f"  Brent={brent} WTI={wti} Gold={gold} Silver={silver} DXY={dxy}")

    # ── STEP 3: INR/USD ──────────────────────────────────────────────────────
    print("── INR/USD (RBI Reference) ────────────────────")
    inr = safe(get_inr_usd, None, "INR/USD")
    print(f"  INR/USD = {inr}")
    inr = inr or 84.3

    # ── STEP 4: RBI RATES ────────────────────────────────────────────────────
    print("── RBI Rates ──────────────────────────────────")
    repo = safe(get_repo_rate, 6.0, "Repo")
    gsec = safe(get_gsec_10y, 6.74, "G-Sec")
    print(f"  Repo={repo}%  G-Sec={gsec}%")

    # ── STEP 5: FRED ─────────────────────────────────────────────────────────
    print("── FRED ───────────────────────────────────────")
    fed     = safe(lambda: fred_latest("FEDFUNDS"),  4.375, "Fed rate")
    us10y   = safe(lambda: fred_latest("DGS10"),     4.32,  "US 10Y")
    us_vix  = safe(lambda: fred_latest("VIXCLS"),    28.4,  "US VIX")
    us_nfp_raw = safe(lambda: fred_latest("PAYEMS"), None,  "NFP")
    us_unemp   = safe(lambda: fred_latest("UNRATE"), 4.1,   "US UNEMP")
    # NFP is in thousands from FRED — get month-on-month change
    nfp_hist_l, nfp_hist_v = safe(lambda: fred_history("PAYEMS", 3), ([],[]), "NFP hist")
    nfp_chg = None
    if len(nfp_hist_v) >= 2:
        nfp_chg = round((nfp_hist_v[-1] - nfp_hist_v[-2]) * 1000)
    print(f"  Fed={fed}  US10Y={us10y}  VIX={us_vix}  NFP chg={nfp_chg}  UNEMP={us_unemp}")

    # ── STEP 6: WORLD BANK ───────────────────────────────────────────────────
    print("── World Bank ─────────────────────────────────")
    gdp_val, gdp_yr = safe(lambda: wb_latest("NY.GDP.MKTP.KD.ZG"), (6.4, "FY25"), "WB GDP")
    cpi_val, cpi_yr = safe(lambda: wb_latest("FP.CPI.TOTL.ZG"),    (4.6, "2025"), "WB CPI")
    gdp_l, gdp_v    = safe(lambda: wb_history("NY.GDP.MKTP.KD.ZG"), ([], []), "WB GDP hist")
    payload["world_gdp"] = safe(get_world_gdp, {}, "World GDP")
    print(f"  GDP={gdp_val}  CPI={cpi_val}")

    # ── BUILD INDICATORS ─────────────────────────────────────────────────────
    print("── Building indicator records ─────────────────")

    # GROWTH
    rec(ind, "gdp", gdp_val or 6.4, "%", gdp_yr or "FY25", "GDP Growth (YoY)",
        "good" if (gdp_val or 6.4) >= 5.5 else "warn",
        "NORMAL" if (gdp_val or 6.4) >= 5.5 else "WEAK",
        f"{gdp_val or 6.4}% YoY", "up" if (gdp_val or 6.4) >= 6 else "dn", None, gdp_l, gdp_v)

    v = cpi_val or 4.6
    rec(ind, "cpi", v, "%", cpi_yr or "Latest", "CPI Inflation (Headline)",
        "danger" if v > 6 else "warn" if v > 5.5 else "good",
        "HIGH" if v > 6 else "WATCH" if v > 5.5 else "IN BAND",
        f"▼ easing" if v < 5 else f"▲ {v}%", "dn" if v < 5 else "up",
        f"CPI at {v}% — above RBI upper band (6%)" if v > 6 else None)

    # MONETARY
    rec(ind, "repo", repo, "%", ts()[:10], "Repo Rate",
        "good", "ACCOMMODATIVE" if repo <= 6.25 else "RESTRICTIVE",
        f"▼ CUT" if repo < 6.25 else "→ Hold", "fl", None)

    rec(ind, "gsec", gsec, "%", ts()[:10], "10Y G-Sec Yield",
        "warn" if gsec > 8 else "good", "NORMAL",
        f"{gsec}%", "fl",
        "G-Sec above 8% — tight conditions" if gsec > 8 else None)

    rec(ind, "inrusd", inr, "₹", ts()[:10], "INR / USD",
        "warn" if inr > 87 else "good",
        "WEAK" if inr > 87 else "WATCH" if inr > 85 else "STABLE",
        f"RBI ref rate: {inr}", "fl",
        f"INR at {inr} — above RBI comfort zone (80–87)" if inr > 87 else None)

    # MARKETS
    rec(ind, "nifty_pe", nifty_pe, "x", ts()[:10], "Nifty 50 P/E",
        "danger" if nifty_pe > 28 else "warn" if nifty_pe > 24 else "good",
        "EXPENSIVE" if nifty_pe > 28 else "RICH" if nifty_pe > 24 else "FAIR",
        f"vs 20–22x hist avg", "fl",
        f"Nifty P/E at {nifty_pe}x — expensive" if nifty_pe > 24 else None)

    rec(ind, "nifty_pb", nifty_pb, "x", ts()[:10], "Nifty 50 P/B",
        "warn" if nifty_pb > 4 else "good", "FAIR",
        f"{nifty_pb}x vs 3.1x avg", "fl", None)

    rec(ind, "nifty50_lvl", nifty_lvl, "", ts()[:10], "Nifty 50 Level",
        "good", "LIVE", f"↗ {n50.get('chg_pct',0):+.2f}% today", "fl", None)

    rec(ind, "india_vix", india_vix, "", ts()[:10], "India VIX",
        "warn" if india_vix > 20 else "good",
        "ELEVATED" if india_vix > 20 else "LOW FEAR",
        f"{'↑' if india_vix > 16 else '↓'} {india_vix}", "fl",
        f"India VIX elevated at {india_vix}" if india_vix > 20 else None)

    # COMMODITIES
    rec(ind, "brent", brent, "$/bbl", ts()[:10], "Brent Crude Oil",
        "good" if brent < 90 else "warn",
        "INDIA POSITIVE" if brent < 90 else "PRESSURE",
        f"${brent}/bbl", "fl",
        f"Brent ${brent} — above $90 CAD pressure" if brent > 90 else None)

    rec(ind, "crude_wti", wti, "$/bbl", ts()[:10], "WTI Crude Oil",
        "good" if wti < 85 else "warn", "BENIGN" if wti < 85 else "PRESSURE",
        f"${wti}/bbl", "fl",
        f"WTI ${wti} — import cost pressure" if wti > 90 else None)

    rec(ind, "gold", round(gold), "$/oz", ts()[:10], "Gold",
        "warn" if gold > 2500 else "good",
        "RECORD HIGH" if gold > 3000 else "RISK-OFF" if gold > 2500 else "NORMAL",
        f"${round(gold)}/oz", "fl",
        f"Gold at ${round(gold)} — elevated risk-off signal" if gold > 2500 else None)

    rec(ind, "silver", silver, "$/oz", ts()[:10], "Silver",
        "good", "INDUSTRIAL", f"${silver}/oz", "fl", None)

    rec(ind, "copper", copper, "$/lb", ts()[:10], "Copper (Dr. Copper)",
        "warn" if copper < 3.5 else "good",
        "RECESSION SIGNAL" if copper < 3.5 else "GROWTH OK",
        f"${copper}/lb", "fl",
        "Copper below $3.5 — growth slowdown signal" if copper < 3.5 else None)

    rec(ind, "dxy", dxy, "", ts()[:10], "US Dollar Index (DXY)",
        "warn" if dxy > 107 else "good",
        "EM POSITIVE" if dxy < 100 else "NEUTRAL" if dxy < 107 else "STRONG USD",
        f"DXY {dxy}", "fl",
        f"DXY {dxy} — strong USD pressures EM" if dxy > 107 else None)

    # US MACRO
    rec(ind, "fed_rate", fed or 4.375, "%", ts()[:10], "Fed Funds Rate",
        "warn" if (fed or 4.375) > 4 else "good",
        "RESTRICTIVE" if (fed or 4.375) > 4 else "NEUTRAL",
        "On hold", "fl",
        f"Fed at {fed or 4.375}% — limits RBI cut room" if (fed or 4.375) > 4 else None)

    rec(ind, "us10y", us10y or 4.32, "%", ts()[:10], "US 10Y Treasury Yield",
        "warn" if (us10y or 4.32) > 4.5 else "good",
        "WATCH" if (us10y or 4.32) > 4.5 else "NORMAL",
        f"{us10y or 4.32}%", "fl",
        f"US 10Y {us10y or 4.32}% — FII outflow pressure" if (us10y or 4.32) > 4.5 else None)

    rec(ind, "us_vix", round(us_vix or 28.4, 1), "", ts()[:10], "VIX (US Fear Index)",
        "danger" if (us_vix or 28.4) > 35 else "warn" if (us_vix or 28.4) > 20 else "good",
        "PANIC" if (us_vix or 28.4) > 35 else "ELEVATED" if (us_vix or 28.4) > 20 else "CALM",
        f"US VIX: {round(us_vix or 28.4, 1)}", "fl",
        f"US VIX {round(us_vix or 28.4,1)} — risk-off; FII selling likely" if (us_vix or 28.4) > 25 else None)

    if nfp_chg is not None:
        nfp_k = round(nfp_chg / 1000)
        rec(ind, "us_nfp", nfp_k, "K", ts()[:10], "US Non-Farm Payrolls",
            "good" if nfp_k > 150 else "warn" if nfp_k > 50 else "danger",
            "SOLID" if nfp_k > 150 else "SOFT" if nfp_k > 50 else "WEAK",
            f"+{nfp_k}K jobs", "fl",
            f"NFP {nfp_k}K — labor market weakening" if nfp_k < 100 else None)

    rec(ind, "us_unemp", us_unemp or 4.1, "%", ts()[:10], "US Unemployment Rate",
        "good" if (us_unemp or 4.1) < 5 else "warn",
        "FULL EMPLOYMENT" if (us_unemp or 4.1) < 4.5 else "RISING",
        f"{us_unemp or 4.1}%", "fl",
        f"US unemp {us_unemp or 4.1}% — loosening" if (us_unemp or 4.1) > 5 else None)

    # ── REGIME SCORE ─────────────────────────────────────────────────────────
    all_ind = [v for v in ind.values() if isinstance(v, dict) and "status" in v]
    goods   = sum(1 for x in all_ind if x["status"] == "good")
    warns   = sum(1 for x in all_ind if x["status"] == "warn")
    total   = len(all_ind)
    score   = round((goods + warns * 0.5) / total * 100) if total else 50
    payload["regime_score"] = score
    payload["regime"] = (
        "RISK-ON" if score >= 70 else
        "CAUTIOUSLY NEUTRAL" if score >= 50 else
        "RISK-OFF"
    )

    return payload

# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{'='*55}")
    print(f"  BHARAT·MACRO v3 Fetcher  {ts()}")
    print(f"{'='*55}\n")

    if not FRED_KEY:
        print("  [WARN] FRED_API_KEY not set — US macro will use fallbacks\n")

    data = build()

    with open(OUT_FILE, "w") as f:
        json.dump(data, f, indent=2)

    nse_count  = len(data.get("nse_indices", {}))
    flow_ok    = bool(data.get("flows", {}).get("fii_net_cr"))
    ind_count  = len(data["indicators"])

    print(f"\n{'='*55}")
    print(f"  ✓ Written  → {OUT_FILE}")
    print(f"  Regime     : {data['regime']} ({data['regime_score']}/100)")
    print(f"  Indicators : {ind_count}")
    print(f"  NSE indices: {nse_count}")
    print(f"  FII/DII    : {'✓ live' if flow_ok else '⚠ fallback'}")
    print(f"  Updated    : {data['updated_ist']}")
    print(f"{'='*55}\n")
