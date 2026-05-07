import urllib.request
import json
import sys

URL = "https://apewisdom.io/api/v1.0/filter/wallstreetbets"

def main():
    req = urllib.request.Request(
        URL,
        headers={"User-Agent": "wsb-tracker/0.1 (personal project)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read())
    except Exception as e:
        print(f"ERROR fetching {URL}: {e}", file=sys.stderr)
        raise

    results = data.get("results", [])
    if not results:
        print("No results. Raw response:")
        print(json.dumps(data, indent=2)[:500])
        sys.exit(1)

    print("Top 20 trending tickers on r/wallstreetbets")
    print("=" * 60)

    for stock in results[:20]:
        rank = int(stock.get("rank", 0))
        ticker = stock.get("ticker", "?")
        name = stock.get("name", "?")
        mentions = int(stock.get("mentions", 0))

        old = stock.get("rank_24h_ago")
        if old and old != "0":
            change = int(old) - rank
            arrow = f"up {change}" if change > 0 else (f"down {abs(change)}" if change < 0 else "flat")
        else:
            arrow = "NEW"

        print(f"{rank:>3}. {ticker:<6} {name[:28]:<28} {mentions:>5} mentions  {arrow}")

if __name__ == "__main__":
    main()
