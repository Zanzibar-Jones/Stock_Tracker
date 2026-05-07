import urllib.request
import json
import sys
import html
from datetime import datetime, date, timezone
import pandas as pd
import yfinance as yf
from ics import Calendar, Event

URL = "https://apewisdom.io/api/v1.0/filter/wallstreetbets"
ICS_OUTPUT = "wsb_catalysts.ics"
JSON_OUTPUT = "data.json"
TOP_N = 25


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
                d = d.date()
            if isinstance(d, date) and d >= date.today():
                return d
    except Exception as e:
        print(f"  (no earnings for {ticker_symbol}: {e})", file=sys.stderr)
    return None


def _midprice(row):
    bid = row.get("bid", 0) or 0
    ask = row.get("ask", 0) or 0
    if bid > 0 and ask > 0:
        return (bid + ask) / 2
    last = row.get("lastPrice", 0) or 0
    return last


def get_spot(t):
    try:
        fi = t.fast_info
        if hasattr(fi, "get"):
            return fi.get("lastPrice")
        return getattr(fi, "last_price", None)
    except Exception:
        pass
    try:
        return t.info.get("regularMarketPrice")
    except Exception:
        return None


def get_post_earnings_exp(t, earnings_date):
    try:
        for exp in t.options:
            try:
                ed = datetime.strptime(exp, "%Y-%m-%d").date()
            except Exception:
                continue
            if ed >= earnings_date:
                return exp
    except Exception:
        pass
    return None


def get_options_play_data(ticker_symbol, earnings_date):
    out = {
        "spot": None,
        "post_earnings_exp": None,
        "implied_move_pct": None,
        "atm_iv_pct": None,
        "historical_moves": [],
    }
    try:
        t = yf.Ticker(ticker_symbol)
        spot = get_spot(t)
        if spot:
            out["spot"] = round(float(spot), 2)

        post_exp = get_post_earnings_exp(t, earnings_date)
        if post_exp and spot:
            out["post_earnings_exp"] = post_exp
            try:
                chain = t.option_chain(post_exp)
                calls, puts = chain.calls, chain.puts
                if not calls.empty and not puts.empty:
                    c_idx = (calls["strike"] - spot).abs().idxmin()
                    p_idx = (puts["strike"] - spot).abs().idxmin()
                    c = calls.loc[c_idx]
                    p = puts.loc[p_idx]

                    cm = _midprice(c)
                    pm = _midprice(p)
                    if cm > 0 and pm > 0:
                        straddle = cm + pm
                        out["implied_move_pct"] = round((straddle / spot) * 100, 2)

                    civ = c.get("impliedVolatility", 0) or 0
                    piv = p.get("impliedVolatility", 0) or 0
                    if civ > 0 or piv > 0:
                        out["atm_iv_pct"] = round(((civ + piv) / 2) * 100, 2)
            except Exception as e:
                print(f"  option_chain failed for {ticker_symbol}: {e}", file=sys.stderr)

        # Historical earnings reactions
        try:
            ed_df = t.earnings_dates
            if ed_df is not None and not ed_df.empty:
                tz = ed_df.index.tz
                now_ts = pd.Timestamp.now(tz=tz) if tz is not None else pd.Timestamp.now()
                past = ed_df[ed_df.index < now_ts].head(4)
                if not past.empty:
                    hist = t.history(period="2y", auto_adjust=True)
                    if not hist.empty:
                        moves = []
                        for ts in past.index:
                            ed = ts.date()
                            before = hist[hist.index.date < ed]
                            after = hist[hist.index.date > ed]
                            if not before.empty and not after.empty:
                                bc = float(before.iloc[-1]["Close"])
                                ac = float(after.iloc[0]["Close"])
                                pct = ((ac - bc) / bc) * 100
                                moves.append({
                                    "date": ed.isoformat(),
                                    "move_pct": round(pct, 2),
                                })
                        out["historical_moves"] = moves
        except Exception as e:
            print(f"  historical moves failed for {ticker_symbol}: {e}", file=sys.stderr)

    except Exception as e:
        print(f"  options data failed for {ticker_symbol}: {e}", file=sys.stderr)
    return out


def main():
    results = fetch_trending()
    if not results:
        print("No trending tickers returned")
        sys.exit(1)

    cal = Calendar()
    tickers_data = []
    today = date.today()

    print(f"{'#':>3}. {'TICKER':<7} {'EARN':<10} {'IM%':>7} {'AVG HIST%':>10}")
    print("-" * 50)

    for stock in results[:TOP_N]:
        rank = int(stock.get("rank", 0))
        ticker = stock.get("ticker", "?")
        name = html.unescape(stock.get("name", "?"))
        mentions = int(stock.get("mentions", 0))

        old = stock.get("rank_24h_ago")
        if old and old != "0":
            change = int(old) - rank
            momentum_label = f"up {change}" if change > 0 else (f"down {abs(change)}" if change < 0 else "flat")
        else:
            change = None
            momentum_label = "NEW"

        earnings = get_next_earnings(ticker)
        days_to_earnings = (earnings - today).days if earnings else None

        play_data = get_options_play_data(ticker, earnings) if earnings else None

        if play_data:
            im = play_data["implied_move_pct"]
            moves = play_data["historical_moves"]
            avg_hist = round(sum(abs(m["move_pct"]) for m in moves) / len(moves), 2) if moves else None
            print(f"{rank:>3}. {ticker:<7} {earnings.isoformat():<10} "
                  f"{(str(im)+'%') if im else '—':>7} "
                  f"{(str(avg_hist)+'%') if avg_hist else '—':>10}")
        else:
            print(f"{rank:>3}. {ticker:<7} {'—':<10} {'—':>7} {'—':>10}")

        tickers_data.append({
            "rank": rank,
            "ticker": ticker,
            "name": name,
            "mentions": mentions,
            "rank_change": change,
            "momentum_label": momentum_label,
            "next_earnings": earnings.isoformat() if earnings else None,
            "days_to_earnings": days_to_earnings,
            "play": play_data,
        })

        if earnings:
            event = Event()
            event.name = f"${ticker} Earnings — #{rank} WSB ({mentions} mentions, {momentum_label})"
            event.begin = earnings.isoformat()
            event.make_all_day()
            event.uid = f"{ticker}-earnings-{earnings.isoformat()}@wsb-tracker"

            desc_lines = [
                name,
                f"WSB rank: #{rank}",
                f"Mentions (24h): {mentions}",
                f"Momentum: {momentum_label}",
            ]
            if play_data and play_data.get("implied_move_pct"):
                desc_lines.append(f"Implied move: ±{play_data['implied_move_pct']}%")
                hm = play_data.get("historical_moves") or []
                if hm:
                    avg = sum(abs(m["move_pct"]) for m in hm) / len(hm)
                    desc_lines.append(f"Historical avg: ±{avg:.1f}% (last {len(hm)})")
            event.description = "\n".join(desc_lines) + "\n\nhttps://apewisdom.io/wallstreetbets/"
            cal.events.add(event)

    with open(ICS_OUTPUT, "w") as f:
        f.write(str(cal))

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tickers": tickers_data,
    }
    with open(JSON_OUTPUT, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nWrote {len(cal.events)} events to {ICS_OUTPUT}")
    print(f"Wrote {len(tickers_data)} tickers to {JSON_OUTPUT}")


if __name__ == "__main__":
    main()
