import urllib.request
import json
import sys
import html
from datetime import datetime, date
import yfinance as yf

URL = "https://apewisdom.io/api/v1.0/filter/wallstreetbets"

def fetch_trending():
    req = urllib.request.Request(
        URL, headers={"User-Agent": "wsb-tracker/0.1 (personal project)"}
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read()).get("results", [])

def get_next_earnings(ticker_symbol):
    try:
        cal = yf.Ticker(ticker_symbol).calendar
        if cal and "Earnings Date" in cal:
            dates = cal["Earnings Date"]
            d = dates[0] if isinstance(dates, list) and dates else dates
            if isinstance(d, datetime):
                return d.date()
            if isinstance(d, date):
                return d
    except Exception as e:
        print(f"  (no earnings for {ticker_symbol}: {e})", file=sys.stderr)
    return None

def main():
    results = fetch_trending()
    if not results:
        print("No trending tickers returned")
        sys.exit(1)

    print(f"{'#':>3}  {'TICKER':<7} {'NAME':<28} {'MENTIONS':>9}  {'MOMENTUM':<10} {'EARNINGS':<12}")
    print("-" * 75)

    for stock in results[:15]:
        rank = int(stock.get("rank", 0))
        ticker = stock.get("ticker", "?")
        name = html.unescape(stock.get("name", "?"))
        mentions = int(stock.get("mentions", 0))

        old = stock.get("rank_24h_ago")
        if old and old != "0":
            change = int(old) - rank
            momentum = f"up {change}" if change > 0 else (f"down {abs(change)}" if change < 0 else "flat")
        else:
            momentum = "NEW"

        earnings = get_next_earnings(ticker)
        earnings_str = earnings.strftime("%Y-%m-%d") if earnings else "—"

        print(f"{rank:>3}. {ticker:<7} {name[:28]:<28} {mentions:>9}  {momentum:<10} {earnings_str:<12}")

if __name__ == "__main__":
    main()
