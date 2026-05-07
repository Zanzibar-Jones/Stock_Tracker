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
    return row.get("lastPrice", 0) or 0


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
        "days_post_earnings": None,
        "straddle_price": None,
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
                exp_date = datetime.strptime(post_exp, "%Y-%m-%d").date()
                out["days_post_earnings"] = (exp_date - earnings_date).days
            except Exception:
                pass

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
                        out["straddle_price"] = round(straddle, 2)
                        out["implied_move_pct"] = round((straddle / spot) * 100, 2)

                    civ = c.get("impliedVolatility", 0) or 0
                    piv = p.get("impliedVolatility", 0) or 0
                    if civ > 0 or piv > 0:
                        out["atm_iv_pct"] = round(((civ + piv) / 2) * 100, 2)
            except Exception as e:
                print(f"  option_chain failed for {ticker_symbol}: {e}", file=sys.stderr)

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


def compute_verdict(play, rank_change):
    if not play or not play.get("implied_move_pct"):
        return None
    moves = play.get("historical_moves") or []
    if len(moves) < 2:
        return None
    im = play["implied_move_pct"]
    avg_hist = sum(abs(m["move_pct"]) for m in moves) / len(moves)
    if avg_hist <= 0:
        return None
    ratio = im / avg_hist

    rc = rank_change if rank_change is not None else 0
    if rc >= 15:
        direction = "bullish"
    elif rc <= -15:
        direction = "bearish"
    else:
        direction = "neutral"

    confidence = "high" if len(moves) >= 4 else ("medium" if len(moves) >= 3 else "low")

    if ratio > 1.20:
        signal = "sell_premium"
        label = "Premium expensive"
        diff = round((ratio - 1) * 100)
        reason = (f"Implied move (±{im}%) is {diff}% above historical avg "
                  f"(±{avg_hist:.1f}%, last {len(moves)}). Market pricing more vol than typical.")
        if direction == "bullish":
            suggested = "Put credit spread (sell premium, bullish bias)"
        elif direction == "bearish":
            suggested = "Call credit spread (sell premium, bearish bias)"
        else:
            suggested = "Iron condor (sell premium, neutral)"
    elif ratio < 0.80:
        signal = "buy_premium"
        label = "Premium cheap"
        diff = round((1 - ratio) * 100)
        reason = (f"Implied move (±{im}%) is {diff}% below historical avg "
                  f"(±{avg_hist:.1f}%, last {len(moves)}). Market under-pricing typical earnings vol.")
        if direction == "bullish":
            suggested = "Long calls (buy premium, bullish bias)"
        elif direction == "bearish":
            suggested = "Long puts (buy premium, bearish bias)"
        else:
            suggested = "Long straddle (buy premium, neutral)"
    else:
        signal = "neutral"
        label = "Fairly priced"
        diff = round((ratio - 1) * 100)
        reason = (f"Implied move (±{im}%) within {abs(diff)}% of historical avg "
                  f"(±{avg_hist:.1f}%, last {len(moves)}).")
        suggested = "No edge from this signal — trade only on direction conviction"

    return {
        "signal": signal,
        "label": label,
        "reason": reason,
        "suggested": suggested,
        "confidence": confidence,
        "ratio": round(ratio, 2),
    }


def main():
    results = fetch_trending()
    if not results:
        print("No trending tickers returned")
        sys.exit(1)

    cal = Calendar()
    tickers_data = []
    today = date.today()

    print(f"{'#':>3}. {'TICKER':<7} {'EARN':<10} {'STR$':>6} {'IM%':>7} {'HIST%':>7}  VERDICT")
    print("-" * 65)

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
        verdict = compute_verdict(play_data, change) if play_data else None
        if play_data:
            play_data["verdict"] = verdict if verdict else None

        if play_data:
            sp = play_data.get("straddle_price")
            im = play_data.get("implied_move_pct")
            moves = play_data.get("historical_moves") or []
            avg_hist = round(sum(abs(m["move_pct"]) for m in moves) / len(moves), 2) if moves else None
            v_label = verdict["label"] if verdict else "—"
            print(f"{rank:>3}. {ticker:<7} {earnings.isoformat():<10} "
                  f"{('$'+str(sp)) if sp else '—':>6} "
                  f"{(str(im)+'%') if im else '—':>7} "
                  f"{(str(avg_hist)+'%') if avg_hist else '—':>7}  {v_label}")
        else:
            print(f"{rank:>3}. {ticker:<7} {'—':<10} {'—':>6} {'—':>7} {'—':>7}  —")

        # Try to get spot even when no earnings (so SPY/QQQ get a price too)
        spot_only = None
        if not play_data:
            try:
                spot_only = get_spot(yf.Ticker(ticker))
                if spot_only:
                    spot_only = round(float(spot_only), 2)
            except Exception:
                pass

        tickers_data.append({
            "rank": rank,
            "ticker": ticker,
            "name": name,
            "mentions": mentions,
            "rank_change": change,
            "momentum_label": momentum_label,
            "next_earnings": earnings.isoformat() if earnings else None,
            "days_to_earnings": days_to_earnings,
            "spot": (play_data["spot"] if play_data and play_data.get("spot") else spot_only),
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
                if play_data.get("straddle_price"):
                    desc_lines.append(f"ATM straddle: ${play_data['straddle_price']} (exp {play_data.get('post_earnings_exp')})")
                hm = play_data.get("historical_moves") or []
                if hm:
                    avg = sum(abs(m["move_pct"]) for m in hm) / len(hm)
                    desc_lines.append(f"Historical avg: ±{avg:.1f}% (last {len(hm)})")
            if verdict:
                desc_lines.append("")
                desc_lines.append(f"VERDICT: {verdict['label']}")
                desc_lines.append(verdict["reason"])
                desc_lines.append(f"Suggested: {verdict['suggested']}")
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
