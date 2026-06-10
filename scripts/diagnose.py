#!/usr/bin/env python3
"""Quick diagnostic — verifies auth, checks market fields, and shows screener results."""
import asyncio, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
from kannon.api.auth import KalshiAuth
from kannon.api.client import KalshiClient
from kannon.api.models import Market
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
        while pages < 5 and len(quoted) < 5:
            params = {"status": "open", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            data = await client._request("GET", "/markets", params=params)
            for raw in data.get("markets", []):
                bid = float(raw.get("yes_bid_dollars") or "0") * 100
                ask = float(raw.get("yes_ask_dollars") or "1") * 100
                if 1 <= bid < ask <= 99:
                    quoted.append(raw)
            cursor = data.get("cursor")
            pages += 1
            if not cursor:
                break
        print(f"  Found {len(quoted)} markets with real quotes in {pages} pages")
        for raw in quoted[:5]:
            bid = float(raw.get("yes_bid_dollars") or "0") * 100
            ask = float(raw.get("yes_ask_dollars") or "1") * 100
            print(f"  {raw.get('ticker'):50s}  bid={bid:.0f}c  ask={ask:.0f}c  "
                  f"vol24h_fp={raw.get('volume_24h_fp')}  oi_fp={raw.get('open_interest_fp')}")
        print()

        # ── Raw order response keys ─────────────────────────────────────
        print("── Raw GET /portfolio/orders response keys ──")
        try:
            raw_orders = await client._request("GET", "/portfolio/orders",
                                               params={"status": "resting"})
            orders = raw_orders.get("orders", [])
            if orders:
                print(f"  keys: {sorted(orders[0].keys())}")
                print(f"  first order: {orders[0]}")
            else:
                print("  (no resting orders — place one first)")
        except Exception as e:
            print(f"  FAILED: {e}")
        print()

        # ── Settled market fields ───────────────────────────────────────
        print("── Sample settled markets ──")
        data = await client._request("GET", "/markets", params={"status": "settled", "limit": 5})
        for raw in data.get("markets", [])[:3]:
            print(f"  ticker={raw.get('ticker')}  status={raw.get('status')}  "
                  f"result={raw.get('result')!r}  close_time={raw.get('close_time')}")
        print()

asyncio.run(main())
