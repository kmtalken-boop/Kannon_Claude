#!/usr/bin/env python3
"""Quick diagnostic — verifies auth, checks market fields, and shows screener results."""
import asyncio, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
from kannon.api.auth import KalshiAuth
from kannon.api.client import KalshiClient
from kannon.api.models import Market, Position
import yaml

async def main():
    load_dotenv()
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)
    auth = KalshiAuth(os.environ["KALSHI_API_KEY_ID"], os.environ["KALSHI_PRIVATE_KEY_PATH"])
    async with KalshiClient(cfg["kalshi"]["base_url"], auth, rate_limit_rps=2) as client:

        # ── Auth check ──────────────────────────────────────────────────
        print("── Auth check (GET /portfolio/balance) ──")
        try:
            balance = await client.get_balance()
            print(f"  OK — balance: ${balance.balance_dollars:.2f}")
        except Exception as e:
            print(f"  FAILED: {e}")
        print()

        # ── All open positions with P&L ─────────────────────────────────
        print("── All open positions ──")
        try:
            raw_pos = await client._request("GET", "/portfolio/positions")
            positions = raw_pos.get("market_positions", [])
            if not positions:
                print("  (no open positions)")
            else:
                total_unrealized = 0.0
                total_realized = 0.0
                for p in positions:
                    ticker = p.get("ticker", "?")
                    pos_fp = p.get("position_fp") or p.get("market_exposure_fp") or "0"
                    realized = float(p.get("realized_pnl_dollars") or "0")
                    fees = float(p.get("fees_paid_dollars") or "0")
                    # Estimate unrealized from resting_orders_count if available
                    resting = p.get("resting_orders_count", 0)
                    net_pos = int(float(pos_fp))
                    total_realized += realized
                    sign = "+" if net_pos >= 0 else ""
                    pnl_str = f"  realized=${realized:+.4f}  fees=${fees:.4f}"
                    print(f"  {ticker:60s}  pos={sign}{net_pos:4d}{pnl_str}  resting={resting}")
                print(f"\n  TOTAL realized P&L: ${total_realized:+.4f}")
        except Exception as e:
            print(f"  FAILED: {e}")
        print()

        # ── Resting orders ──────────────────────────────────────────────
        print("── Resting orders ──")
        try:
            raw_orders = await client._request("GET", "/portfolio/orders",
                                               params={"status": "resting"})
            orders = raw_orders.get("orders", [])
            if not orders:
                print("  (no resting orders)")
            else:
                for o in orders:
                    ticker = o.get("ticker", "?")
                    action = o.get("action", "?")
                    side = o.get("side", "?")
                    price = float(o.get("yes_price_dollars") or "0") * 100
                    count = o.get("remaining_count_fp") or o.get("initial_count_fp") or "?"
                    print(f"  {ticker:60s}  {action} {side}  @{price:.0f}¢  qty={count}")
        except Exception as e:
            print(f"  FAILED: {e}")
        print()

        # ── Model parsing check ─────────────────────────────────────────
        print("── Market model parsing (first 3 open markets) ──")
        data = await client._request("GET", "/markets", params={"status": "open", "limit": 5})
        raw_markets = data.get("markets", [])
        for raw in raw_markets[:3]:
            try:
                m = Market(**raw)
                print(f"  {m.ticker[:50]:50s}  bid={m.yes_bid}¢  ask={m.yes_ask}¢  "
                      f"vol24h={m.volume_24h}  OI={m.open_interest}  mid={m.mid_price}")
            except Exception as e:
                print(f"  PARSE ERROR: {e}")
        print()

        # ── Scan for markets with real bid/ask (not 0/100 extremes) ────
        print("── Scanning for markets with real quotes (up to 1000) ──")
        quoted = []
        cursor = None
        pages = 0
        while pages < 5 and len(quoted) < 10:
            params = {"status": "open", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            data = await client._request("GET", "/markets", params=params)
            for raw in data.get("markets", []):
                bid = float(raw.get("yes_bid_dollars") or "0") * 100
                ask = float(raw.get("yes_ask_dollars") or "1") * 100
                ticker = raw.get("ticker", "")
                if 1 <= bid < ask <= 99:
                    quoted.append(raw)
            cursor = data.get("cursor")
            pages += 1
            if not cursor:
                break
        print(f"  Found {len(quoted)} markets with real quotes in {pages} pages")
        for raw in quoted[:10]:
            bid = float(raw.get("yes_bid_dollars") or "0") * 100
            ask = float(raw.get("yes_ask_dollars") or "1") * 100
            spread = ask - bid
            ticker = raw.get("ticker", "")
            print(f"  {ticker:60s}  bid={bid:.0f}¢  ask={ask:.0f}¢  spread={spread:.0f}¢  "
                  f"oi={raw.get('open_interest_fp')}")
        print()

asyncio.run(main())
