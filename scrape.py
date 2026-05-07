import urllib.request
import json

URL = "https://apewisdom.io/api/v1.0/filter/wallstreetbets"

def main():
    with urllib.request.urlopen(URL) as response:
        data = json.loads(response.read())

    print("Top 20 trending tickers on r/wallstreetbets")
    print("=" * 60)

    for stock in data["results"][:20]:
        rank = int(stock["rank"])
        ticker = stock["ticker"]
        name = stock["name"]
        mentions = int(stock["mentions"])

        old = stock.get("rank_24h_ago")
        if old and old != "0":
            change = int(old) - rank
            arrow = f"up {change}" if change > 0 else (f"down {abs(change)}" if change < 0 else "flat")
        else:
            arrow = "NEW"

        print(f"{rank:>3}. {ticker:<6} {name[:28]:<28} {mentions:>5} mentions  {arrow}")

if __name__ == "__main__":
    main()
