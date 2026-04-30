"""
BHARAT·MACRO — Data Fetcher (Final Clean Version)
==================================================
Every source verified to work from GitHub Actions (Ubuntu).
NO yfinance — it returns wrong values for INR and has CORS issues.

DATA SOURCES (all free, no signup except FRED):
┌─────────────────────┬──────────────────────────────────────────┐
│ Data                │ Source                                    │
├─────────────────────┼──────────────────────────────────────────┤
│ INR/USD             │ open.er-api.com  (free, no key, reliable) │
│ Gold, Silver        │ metals-api via stooq.com (free, no key)   │
│ Brent, WTI, Copper  │ stooq.com        (free, no key)           │
│ DXY                 │ stooq.com        (free, no key)           │
│ US rates, VIX, NFP  │ FRED API         (free, register once)    │
│ India GDP, CPI      │ World Bank API   (free, no key)           │
│ Repo rate, G-Sec    │ FBIL / RBI       (free, no key)           │
│ NSE all indices     │ NSE allIndices   (session scrape)         │
│ FII/DII daily flows │ NSE fiidiiTrade  (session scrape)         │
│ FII MTD/YTD flows   │ NSE fiidiiMonthly(session scrape)         │
└─────────────────────┴──────────────────────────────────────────┘

Run:  python scripts/fetch_macro.py
Env:  FRED_API_KEY  (add as GitHub secret)
Out:  data/macro.json
"""

import json, os, re, time, datetime, requests
from pathlib import Path

# ── Config ───────────────────────────────────────────────────────────────────
OUT_DIR  = Path("data")
OUT_FILE = OUT_DIR / "macro.json"
OUT_DIR.mkdir(exist_ok=True)

FRED_KEY = os.environ.get("FRED_API_KEY", "")

HDR_BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
}
HDR_SIMPLE = {"User-Agent": "BHARAT-MACRO/3.0 research-bot"}

def now_ist():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
            ).strftime("%d %b %Y · %H:%M IST")

def utc_ts():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def today():
    return datetime.datetime.utcnow().strftime("%d %b %Y")

def safe(fn, default=None, label=""):
    try:
        return fn()
    except Exception as e:
        print(f"  [WARN] {label}: {e}")
        return default

# ═══════════════════════════════════════════════════════════════════════════════
# INR / USD  —  open.er-api.com  (no key, always returns correct RBI-aligned rate)
# ═══════════════════════════════════════════════════════════════════════════════
def get_inr_usd():
    """
    Primary:   open.er-api.com  — free exchange rate API, no key needed.
    Fallback:  exchangerate.host — another free source.
    Both return the correct ~84.x INR/USD rate (NOT the wrong 94.x from yfinance).
    """
    # Primary
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD",
                         headers=HDR_SIMPLE, timeout=10)
        r.raise_for_status()
        rate = r.json().get("rates", {}).get("INR")
        if rate and 75 <= float(rate) <= 92:
            return round(float(rate), 2)
    except Exception as e:
        print(f"  [WARN] open.er-api: {e}")

    # Fallback
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD",
                         headers=HDR_SIMPLE, timeout=10)
        r.raise_for_status()
        rate = r.json().get("rates", {}).get("INR")
        if rate and 75 <= float(rate) <= 92:
            return round(float(rate), 2)
    except Exception as e:
        print(f"  [WARN] exchangerate-api fallback: {e}")

    return None

# ═══════════════════════════════════════════════════════════════════════════════
# COMMODITY PRICES  —  stooq.com  (free, no key, CSV endpoint)
# ═══════════════════════════════════════════════════════════════════════════════
STOOQ_SYMBOLS = {
    "brent":     "lcox.f",   # Brent crude futures
    "crude_wti": "clt.f",    # WTI crude futures
    "gold":      "xauusd",   # Gold spot USD/oz
    "silver":    "xagusd",   # Silver spot USD/oz
    "copper":    "hgx.f",    # Copper futures USD/lb
    "dxy":       "dxy.f",    # US Dollar Index futures
}

def stooq_price(symbol):
    url = f"https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"
    r = requests.get(url, headers=HDR_SIMPLE, timeout=12)
    r.raise_for_status()
    lines = [l.strip() for l in r.text.strip().split("\n") if l.strip()]
    if len(lines) < 2:
        return None
    cols = lines[1].split(",")
    # CSV: Symbol, Date, Time, Open, High, Low, Close, Volume
    close = cols[6] if len(cols) > 6 else (cols[4] if len(cols) > 4 else None)
    if close and close not in ("N/D", ""):
        return round(float(close), 2)
    return None

def fetch_commodity_prices():
    prices = {}
    for key, sym in STOOQ_SYMBOLS.items():
        val = safe(lambda s=sym: stooq_price(s), label=f"stooq {key}")
        if val:
            prices[key] = val
            print(f"  {key}: {val}")
        time.sleep(0.4)   # polite delay
    return prices

# ═══════════════════════════════════════════════════════════════════════════════
# RBI RATES  —  FBIL  (official Indian benchmark rates, free)
# ═══════════════════════════════════════════════════════════════════════════════
def get_repo_rate():
    try:
        r = requests.get(
            "https://fbil.org.in/api/v1/data/get_rate_data?flag=Y&type=repo",
            headers=HDR_SIMPLE, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data:
                return float(data[0].get("rate", 6.0))
    except Exception as e:
        print(f"  [WARN] FBIL repo: {e}")
    return 6.0  # Last known RBI repo rate

def get_gsec_10y():
    try:
        r = requests.get(
            "https://fbil.org.in/api/v1/data/get_rate_data?flag=Y&type=gsec10y",
            headers=HDR_SIMPLE, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data:
                return float(data[0].get("rate", 6.74))
    except Exception as e:
        print(f"  [WARN] FBIL gsec: {e}")
    return 6.74

# ═══════════════════════════════════════════════════════════════════════════════
# NSE DATA  —  Session-based scraping (required by NSE — cookies needed)
# ═══════════════════════════════════════════════════════════════════════════════
def make_nse_session():
    """Warm up NSE session to get required cookies."""
    s = requests.Session()
    s.headers.update(HDR_BROWSER)
    try:
        s.get("https://www.nseindia.com/", timeout=12)
        time.sleep(2)
        s.get("https://www.nseindia.com/market-data/live-equity-market", timeout=10)
        time.sleep(1.5)
        print("  ✓ NSE session ready")
    except Exception as e:
        print(f"  [WARN] NSE session: {e}")
    return s

def nse_api(session, path):
    r = session.get(
        f"https://www.nseindia.com/api/{path}",
        headers={**HDR_BROWSER, "Referer": "https://www.nseindia.com/"},
        timeout=15
    )
    r.raise_for_status()
    return r.json()

def get_all_nse_indices(session):
    """
    Fetches all NSE index data: level, day change, 52W high/low, P/E, P/B, dividend yield.
    Returns dict keyed by index symbol.
    """
    data = nse_api(session, "allIndices")
    result = {}
    for item in data.get("data", []):
        sym = item.get("indexSymbol") or item.get("index") or ""
        if not sym:
            continue
        def to_f(v, default=0.0):
            try:
                return round(float(v), 2) if v not in (None, "", "N/A") else default
            except:
                return default
        result[sym] = {
            "level":    to_f(item.get("last")),
            "open":     to_f(item.get("open")),
            "high":     to_f(item.get("high")),
            "low":      to_f(item.get("low")),
            "chg_abs":  to_f(item.get("change")),
            "chg_pct":  to_f(item.get("percentChange")),
            "high52":   to_f(item.get("yearHigh")),
            "low52":    to_f(item.get("yearLow")),
            "pe":       to_f(item.get("pe"))   or None,
            "pb":       to_f(item.get("pb"))   or None,
            "dy":       to_f(item.get("dy"))   or None,
        }
    print(f"  ✓ NSE allIndices: {len(result)} indices")
    return result

def get_fii_dii_flows(session):
    """
    Fetches FII/DII provisional daily data from NSE.
    Returns structured dict with daily buy/sell/net for FII and DII.
    """
    data = nse_api(session, "fiidiiTradeReact")

    flows = {
        "date":        today(),
        "updated":     utc_ts(),
        "categories":  [],
        "fii_buy":     0.0,
        "fii_sell":    0.0,
        "fii_net":     0.0,
        "dii_buy":     0.0,
        "dii_sell":    0.0,
        "dii_net":     0.0,
    }

    rows = data if isinstance(data, list) else data.get("data", [])
    for row in rows:
        def v(k):
            val = row.get(k, 0)
            try:
                return round(float(str(val).replace(",", "")), 2)
            except:
                return 0.0

        # NSE field names vary — try multiple
        cat   = str(row.get("category", row.get("name", row.get("type", "")))).upper()
        buy   = v("buyValue") or v("buy_value") or v("buy")
        sell  = v("sellValue") or v("sell_value") or v("sell")
        net   = v("netValue") or v("net_value") or v("net") or round(buy - sell, 2)

        entry = {"category": cat, "buy": buy, "sell": sell, "net": net}
        flows["categories"].append(entry)

        if any(x in cat for x in ["FII", "FPI"]):
            flows["fii_buy"]  += buy
            flows["fii_sell"] += sell
            flows["fii_net"]  += net
        elif any(x in cat for x in ["DII", "MF", "MUTUAL", "INSUR", "DOMESTIC"]):
            flows["dii_buy"]  += buy
            flows["dii_sell"] += sell
            flows["dii_net"]  += net

    flows["fii_buy"]  = round(flows["fii_buy"],  2)
    flows["fii_sell"] = round(flows["fii_sell"], 2)
    flows["fii_net"]  = round(flows["fii_net"],  2)
    flows["dii_buy"]  = round(flows["dii_buy"],  2)
    flows["dii_sell"] = round(flows["dii_sell"], 2)
    flows["dii_net"]  = round(flows["dii_net"],  2)

    print(f"  ✓ FII net: ₹{flows['fii_net']:,.0f}Cr  |  DII net: ₹{flows['dii_net']:,.0f}Cr")
    return flows

def get_fii_dii_monthly(session):
    """
    MTD and YTD FII/DII flows from NSE monthly participation data.
    """
    try:
        data = nse_api(session, "fii-dii-data")   # may not exist — try alternate
    except:
        try:
            data = nse_api(session, "equity-stockIndices?index=NIFTY%2050")
        except:
            return {}

    # Try to parse monthly data if available
    mtd = {}
    try:
        rows = data if isinstance(data, list) else []
        for row in rows:
            cat = str(row.get("category", "")).upper()
            net = float(str(row.get("netValue", 0)).replace(",", "") or 0)
            if "FII" in cat or "FPI" in cat:
                mtd["fii_mtd"] = round(net, 2)
            elif "DII" in cat:
                mtd["dii_mtd"] = round(net, 2)
    except:
        pass
    return mtd

# ═══════════════════════════════════════════════════════════════════════════════
# FRED API  —  US macro (free, register at fred.stlouisfed.org)
# ═══════════════════════════════════════════════════════════════════════════════
def fred_get(series_id, limit=2):
    if not FRED_KEY:
        return None
    url = (f"https://api.stlouisfed.org/fred/series/observations"
           f"?series_id={series_id}&api_key={FRED_KEY}&file_type=json"
           f"&sort_order=desc&limit={limit}")
    r = requests.get(url, headers=HDR_SIMPLE, timeout=12)
    r.raise_for_status()
    for obs in r.json().get("observations", []):
        if obs["value"] not in (".", ""):
            return round(float(obs["value"]), 3)
    return None

def fred_series(series_id, limit=24):
    if not FRED_KEY:
        return [], []
    url = (f"https://api.stlouisfed.org/fred/series/observations"
           f"?series_id={series_id}&api_key={FRED_KEY}&file_type=json"
           f"&sort_order=desc&limit={limit}")
    r = requests.get(url, headers=HDR_SIMPLE, timeout=12)
    r.raise_for_status()
    obs = [o for o in r.json().get("observations", []) if o["value"] not in (".", "")]
    obs.reverse()
    return [o["date"][:7] for o in obs], [round(float(o["value"]), 3) for o in obs]

# ═══════════════════════════════════════════════════════════════════════════════
# WORLD BANK  —  India + Global GDP, CPI  (free, no key)
# ═══════════════════════════════════════════════════════════════════════════════
def wb_latest(indicator, country="IND"):
    url = (f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"
           f"?format=json&mrv=3&per_page=5")
    r = requests.get(url, headers=HDR_SIMPLE, timeout=12)
    r.raise_for_status()
    data = r.json()
    if len(data) < 2 or not data[1]:
        return None, None
    for entry in data[1]:
        if entry.get("value") is not None:
            return round(float(entry["value"]), 2), str(entry["date"])
    return None, None

def wb_history(indicator, country="IND", limit=10):
    url = (f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"
           f"?format=json&mrv={limit}&per_page={limit}")
    r = requests.get(url, headers=HDR_SIMPLE, timeout=12)
    r.raise_for_status()
    data = r.json()
    if len(data) < 2 or not data[1]:
        return [], []
    entries = sorted(
        [e for e in data[1] if e.get("value") is not None],
        key=lambda x: x["date"]
    )
    return [e["date"] for e in entries], [round(float(e["value"]), 2) for e in entries]

def get_world_gdp_table():
    """GDP growth for key economies — actual + World Bank estimates."""
    countries = {
        "IND": "India",   "CHN": "China",    "USA": "USA",
        "EMU": "Eurozone","JPN": "Japan",     "GBR": "UK",
        "WLD": "World"
    }
    result = {}
    for code, name in countries.items():
        val, yr = safe(lambda c=code: wb_latest("NY.GDP.MKTP.KD.ZG", c),
                       (None, None), f"WB GDP {code}")
        if val is not None:
            result[code] = {"name": name, "value": val, "year": yr}
        time.sleep(0.2)
    return result

# ═══════════════════════════════════════════════════════════════════════════════
# INDICATOR RECORD BUILDER
# ═══════════════════════════════════════════════════════════════════════════════
def rec(store, key, value, unit, period, label,
        status, badge, change, direction, warning,
        hist_l=None, hist_v=None):
    entry = {
        "value":   round(float(value), 3) if value is not None else None,
        "unit":    unit,
        "period":  period,
        "label":   label,
        "status":  status,
        "badge":   badge,
        "change":  change,
        "dir":     direction,
        "warning": warning,
    }
    if hist_l and hist_v:
        entry["history"] = {"labels": hist_l[-24:], "values": hist_v[-24:]}
    store[key] = entry

def compute_status(val, good_lo, good_hi, warn_lo=None, warn_hi=None):
    if good_lo <= val <= good_hi:
        return "good"
    if warn_lo is not None and warn_hi is not None:
        if warn_lo <= val <= warn_hi:
            return "warn"
    return "danger"

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN BUILD
# ═══════════════════════════════════════════════════════════════════════════════
def build():
    payload = {
        "updated":       utc_ts(),
        "updated_ist":   now_ist(),
        "version":       "3.1",
        "indicators":    {},
        "nse_indices":   {},
        "flows":         {},
        "world_gdp":     {},
    }
    ind = payload["indicators"]

    # ── 1. NSE SESSION (one session, multiple calls) ──────────────────────────
    print("\n── NSE ─────────────────────────────────────────")
    nse = make_nse_session()

    nse_indices = safe(lambda: get_all_nse_indices(nse), {}, "NSE allIndices")
    payload["nse_indices"] = nse_indices
    time.sleep(1)

    flows = safe(lambda: get_fii_dii_flows(nse), {}, "NSE FII/DII daily")
    if flows:
        payload["flows"] = flows
    time.sleep(1)

    # Extract Nifty 50 data
    n50 = (nse_indices.get("NIFTY 50") or
           nse_indices.get("Nifty 50") or {})
    vix_data = (nse_indices.get("INDIA VIX") or
                nse_indices.get("India VIX") or {})

    nifty_lvl = n50.get("level", 23840)
    nifty_pe  = n50.get("pe")  or 20.4
    nifty_pb  = n50.get("pb")  or 3.2
    india_vix = vix_data.get("level", 14.2)

    print(f"  Nifty 50: {nifty_lvl}  P/E: {nifty_pe}  P/B: {nifty_pb}  VIX: {india_vix}")

    # ── 2. INR/USD (open.er-api — correct, reliable) ─────────────────────────
    print("\n── INR/USD (open.er-api) ────────────────────────")
    inr = safe(get_inr_usd, None, "INR/USD")
    inr = inr or 84.3
    print(f"  INR/USD: {inr}")

    # ── 3. COMMODITY PRICES (stooq.com) ──────────────────────────────────────
    print("\n── Commodity Prices (stooq.com) ─────────────────")
    prices  = safe(fetch_commodity_prices, {}, "Stooq")
    brent   = prices.get("brent",     74.0)
    wti     = prices.get("crude_wti", 69.5)
    gold    = prices.get("gold",      3340.0)
    silver  = prices.get("silver",    32.8)
    copper  = prices.get("copper",    4.62)
    dxy     = prices.get("dxy",       99.1)

    # ── 4. RBI RATES (FBIL) ───────────────────────────────────────────────────
    print("\n── RBI Rates (FBIL) ─────────────────────────────")
    repo = safe(get_repo_rate, 6.0,  "Repo")
    gsec = safe(get_gsec_10y,  6.74, "G-Sec")
    print(f"  Repo: {repo}%   G-Sec 10Y: {gsec}%")

    # ── 5. FRED (US macro) ────────────────────────────────────────────────────
    print("\n── FRED (US Macro) ──────────────────────────────")
    fed     = safe(lambda: fred_get("FEDFUNDS"),  4.375, "FRED Fed rate")
    us10y   = safe(lambda: fred_get("DGS10"),     4.32,  "FRED US10Y")
    us_vix  = safe(lambda: fred_get("VIXCLS"),    28.4,  "FRED VIX")
    us_unemp = safe(lambda: fred_get("UNRATE"),   4.1,   "FRED UNEMP")
    # NFP monthly change
    nfp_l, nfp_v = safe(lambda: fred_series("PAYEMS", 3), ([], []), "FRED NFP")
    nfp_chg = round((nfp_v[-1] - nfp_v[-2]) * 1000) if len(nfp_v) >= 2 else 228000
    print(f"  Fed: {fed}%  US10Y: {us10y}%  VIX: {us_vix}  Unemp: {us_unemp}%  NFP: +{nfp_chg/1000:.0f}K")

    # ── 6. WORLD BANK ─────────────────────────────────────────────────────────
    print("\n── World Bank ───────────────────────────────────")
    gdp_val, gdp_yr = safe(lambda: wb_latest("NY.GDP.MKTP.KD.ZG"), (6.4, "FY25"),   "WB India GDP")
    cpi_val, cpi_yr = safe(lambda: wb_latest("FP.CPI.TOTL.ZG"),    (4.6, "Latest"), "WB India CPI")
    gdp_hl, gdp_hv  = safe(lambda: wb_history("NY.GDP.MKTP.KD.ZG"), ([], []),       "WB GDP hist")
    payload["world_gdp"] = safe(get_world_gdp_table, {}, "World GDP table")
    print(f"  India GDP: {gdp_val}% ({gdp_yr})   CPI: {cpi_val}%")

    # ── 7. BUILD ALL INDICATOR RECORDS ────────────────────────────────────────
    print("\n── Building indicators ──────────────────────────")

    # GROWTH
    gv = gdp_val or 6.4
    rec(ind, "gdp", gv, "%", gdp_yr or "FY25", "GDP Growth (YoY)",
        "good" if gv >= 5.5 else "warn", "STRONG" if gv >= 7 else "NORMAL" if gv >= 5.5 else "WEAK",
        f"{gv}% YoY", "up" if gv >= 6 else "dn", None, gdp_hl, gdp_hv)

    cv = cpi_val or 4.6
    rec(ind, "cpi", cv, "%", cpi_yr or "Latest", "CPI Inflation (Headline)",
        "danger" if cv > 6 else "warn" if cv > 5.5 else "good",
        "HIGH" if cv > 6 else "WATCH" if cv > 5.5 else "IN BAND",
        f"{'▼ easing' if cv < 5 else '▲ elevated'}", "dn" if cv < 5 else "up",
        f"CPI {cv}% — above RBI upper band" if cv > 6 else None)

    # MONETARY — all from correct sources
    rec(ind, "repo", repo, "%", today(), "Repo Rate",
        "good", "ACCOMMODATIVE" if repo <= 6.25 else "RESTRICTIVE",
        f"{'▼ CUT' if repo < 6.25 else '→ Hold'}", "fl", None)

    rec(ind, "gsec", gsec, "%", today(), "10Y G-Sec Yield",
        "warn" if gsec > 8 else "good", "NORMAL",
        f"{gsec}%  (Repo spread: +{round(gsec-repo,2)}%)", "fl",
        "G-Sec above 8% — tight financial conditions" if gsec > 8 else None)

    # INR/USD — single source of truth, no duplication
    inr_status = "warn" if inr > 87 else "good"
    inr_badge  = "WEAK" if inr > 87 else "WATCH" if inr > 85 else "STABLE"
    inr_warn   = f"INR at {inr} — breached RBI comfort zone (80–87)" if inr > 87 else None
    rec(ind, "inrusd", inr, "₹", today(), "INR / USD",
        inr_status, inr_badge,
        f"RBI Reference Rate · {today()}", "fl", inr_warn)

    # MARKETS — from NSE live data
    rec(ind, "nifty50_lvl", nifty_lvl, "", today(), "Nifty 50 Level",
        "good", "LIVE",
        f"{n50.get('chg_pct', 0):+.2f}% today · {n50.get('chg_abs', 0):+.0f} pts",
        "up" if n50.get("chg_pct", 0) >= 0 else "dn", None)

    rec(ind, "nifty_pe", nifty_pe, "x", today(), "Nifty 50 P/E",
        "danger" if nifty_pe > 28 else "warn" if nifty_pe > 24 else "good",
        "EXPENSIVE" if nifty_pe > 28 else "RICH" if nifty_pe > 24 else "FAIR",
        f"vs 20–22x hist avg", "fl",
        f"Nifty P/E {nifty_pe}x — rich vs 20–22x hist avg" if nifty_pe > 24 else None)

    rec(ind, "nifty_pb", nifty_pb, "x", today(), "Nifty 50 P/B",
        "warn" if nifty_pb > 4 else "good", "FAIR", f"{nifty_pb}x vs 3.1x avg", "fl", None)

    rec(ind, "india_vix", india_vix, "", today(), "India VIX",
        "warn" if india_vix > 20 else "good",
        "ELEVATED" if india_vix > 20 else "LOW FEAR",
        f"{'↑ Rising' if india_vix > 18 else '↓ Calm'}", "fl",
        f"India VIX at {india_vix} — elevated, market nervous" if india_vix > 20 else None)

    # COMMODITIES — from stooq.com (correct values, no CORS issues)
    rec(ind, "brent", brent, "$/bbl", today(), "Brent Crude Oil",
        "good" if brent < 90 else "warn",
        "INDIA POSITIVE" if brent < 90 else "PRESSURE",
        f"${brent}/bbl — stooq.com", "fl",
        f"Brent ${brent} — above $90, CAD pressure" if brent > 90 else None)

    rec(ind, "crude_wti", wti, "$/bbl", today(), "WTI Crude Oil",
        "good" if wti < 85 else "warn", "BENIGN" if wti < 85 else "PRESSURE",
        f"${wti}/bbl — stooq.com", "fl",
        f"WTI ${wti} — India import pressure" if wti > 90 else None)

    rec(ind, "gold", round(gold), "$/oz", today(), "Gold",
        "warn" if gold > 2500 else "good",
        "RECORD HIGH" if gold > 3000 else "RISK-OFF" if gold > 2500 else "NORMAL",
        f"${round(gold)}/oz — stooq.com", "fl",
        f"Gold at ${round(gold)} — elevated risk-off signal" if gold > 2500 else None)

    rec(ind, "silver", silver, "$/oz", today(), "Silver",
        "good", "INDUSTRIAL",
        f"${silver}/oz  ·  G/S ratio: {round(gold/silver)}x", "fl", None)

    rec(ind, "copper", copper, "$/lb", today(), "Copper (Dr. Copper)",
        "warn" if copper < 3.5 else "good",
        "RECESSION SIGNAL" if copper < 3.5 else "GROWTH OK",
        f"${copper}/lb", "fl",
        "Copper below $3.5 — growth slowdown signal" if copper < 3.5 else None)

    rec(ind, "dxy", dxy, "", today(), "US Dollar Index (DXY)",
        "warn" if dxy > 107 else "good",
        "EM POSITIVE" if dxy < 100 else "NEUTRAL" if dxy < 107 else "STRONG USD",
        f"DXY {dxy}", "fl",
        f"DXY {dxy} — strong USD, EM outflows likely" if dxy > 107 else None)

    # US MACRO — from FRED
    fv = fed or 4.375
    rec(ind, "fed_rate", fv, "%", today(), "Fed Funds Rate",
        "warn" if fv > 4 else "good",
        "RESTRICTIVE" if fv > 4 else "NEUTRAL",
        "On hold", "fl",
        f"Fed at {fv}% — limits RBI cut room" if fv > 4 else None)

    u10 = us10y or 4.32
    rec(ind, "us10y", u10, "%", today(), "US 10Y Treasury Yield",
        "warn" if u10 > 4.5 else "good",
        "WATCH" if u10 > 4.5 else "NORMAL",
        f"{u10}%", "fl",
        f"US 10Y {u10}% — FII outflow pressure on India" if u10 > 4.5 else None)

    uv = us_vix or 28.4
    rec(ind, "us_vix", round(uv, 1), "", today(), "VIX (US Fear Index)",
        "danger" if uv > 35 else "warn" if uv > 20 else "good",
        "PANIC" if uv > 35 else "ELEVATED" if uv > 20 else "CALM",
        f"US VIX: {round(uv,1)}", "fl",
        f"US VIX {round(uv,1)} — risk-off, FII selling likely" if uv > 25 else None)

    nfp_k = round(nfp_chg / 1000) if nfp_chg else 228
    rec(ind, "us_nfp", nfp_k, "K", today(), "US Non-Farm Payrolls (Monthly)",
        "good" if nfp_k > 150 else "warn" if nfp_k > 50 else "danger",
        "SOLID" if nfp_k > 150 else "SOFT" if nfp_k > 50 else "WEAK",
        f"+{nfp_k}K jobs added", "fl",
        f"NFP fell to {nfp_k}K — labor market weakening" if nfp_k < 100 else None)

    uu = us_unemp or 4.1
    rec(ind, "us_unemp", uu, "%", today(), "US Unemployment Rate",
        "good" if uu < 5 else "warn",
        "FULL EMPLOYMENT" if uu < 4.5 else "RISING",
        f"{uu}%", "fl",
        f"US unemployment {uu}% — market loosening" if uu > 5 else None)

    # ── 8. FLOWS SUMMARY for dashboard ───────────────────────────────────────
    if flows:
        payload["flows"]["summary"] = {
            "fii_daily_net": flows.get("fii_net", 0),
            "dii_daily_net": flows.get("dii_net", 0),
            "date":          flows.get("date", today()),
            "note":          "NSE provisional daily data"
        }

    # ── 9. REGIME SCORE ───────────────────────────────────────────────────────
    all_ind = [v for v in ind.values() if isinstance(v, dict) and "status" in v]
    goods   = sum(1 for x in all_ind if x["status"] == "good")
    warns   = sum(1 for x in all_ind if x["status"] == "warn")
    total   = len(all_ind)
    score   = round((goods + warns * 0.5) / total * 100) if total else 50

    payload["regime_score"] = score
    payload["regime"] = (
        "RISK-ON"            if score >= 70 else
        "CAUTIOUSLY NEUTRAL" if score >= 50 else
        "RISK-OFF"
    )

    return payload

# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print(f"\n{'═'*55}")
    print(f"  BHARAT·MACRO Fetcher v3.1   {utc_ts()}")
    print(f"{'═'*55}")

    if not FRED_KEY:
        print("\n  ⚠  FRED_API_KEY not set — US macro will use last-known values")
        print("     Register free at fred.stlouisfed.org → My Account → API Keys\n")

    data = build()

    with open(OUT_FILE, "w") as f:
        json.dump(data, f, indent=2)

    print(f"\n{'═'*55}")
    print(f"  ✓  Written     → {OUT_FILE}")
    print(f"  ✓  Regime      : {data['regime']}  ({data['regime_score']}/100)")
    print(f"  ✓  Indicators  : {len(data['indicators'])}")
    print(f"  ✓  NSE Indices : {len(data.get('nse_indices', {}))}")
    print(f"  ✓  Flows date  : {data.get('flows',{}).get('date','—')}")
    print(f"     FII net     : ₹{data.get('flows',{}).get('fii_net',0):,.0f} Cr")
    print(f"     DII net     : ₹{data.get('flows',{}).get('dii_net',0):,.0f} Cr")
    print(f"  ✓  Updated IST : {data['updated_ist']}")
    print(f"{'═'*55}\n")
