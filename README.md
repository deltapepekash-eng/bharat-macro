# BHARAT·MACRO

Live Indian + Global economic intelligence dashboard for equity investors.

## Features
- 25+ macro indicators with benchmark zones and warnings
- Buffett Indicator (MCap/GDP) gauge
- FII/DII flow tracker
- Historical trend charts (click any indicator)
- AI-powered Buy/Hold/Sell analysis via Claude API
- Auto-refreshes daily via GitHub Actions

## Setup
See deployment instructions in the project documentation.

## Data Sources
- FRED API (St. Louis Fed) — free, register at fred.stlouisfed.org
- World Bank Open Data — no key needed
- yfinance — no key needed
- NSE/RBI — scraped from public endpoints

## Structure
```
bharat-macro/
├── index.html                      ← Dashboard (GitHub Pages)
├── data/
│   └── macro.json                  ← Updated daily by Actions
├── scripts/
│   └── fetch_macro.py              ← Data fetcher
├── .github/workflows/
│   └── refresh.yml                 ← Daily cron job
└── requirements.txt
```
