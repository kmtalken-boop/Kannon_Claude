#!/usr/bin/env python3
"""Quick diagnostic — verifies auth, checks market fields, and shows screener results."""
import asyncio, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
from kannon.api.auth import KalshiAuth
from kannon.api.client import KalshiClient
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

        # ── Open market fields ──────────────────────────────────────────
        print("── Sample open markets (raw fields) ──")
        data = await client._request("GET", "/markets", params={"status": "open", "limit": 5})
        markets = data.get("markets", [])
        for m in markets[:3]:
            print(f"  {m.get('ticker'):40s}  status={m.get('status')}  "
                  f"vol24h={m.get('volume_24h')}  OI={m.get('open_interest')}  "
                  f"bid={m.get('yes_bid')}  ask={m.get('yes_ask')}")
        print()

        # ── Settled market fields ───────────────────────────────────────
        print("── Sample settled markets (raw fields) ──")
        data = await client._request("GET", "/markets", params={"status": "settled", "limit": 5})
        markets = data.get("markets", [])
        for m in markets[:3]:
            print(f"  ticker={m.get('ticker')}  status={m.get('status')}  "
                  f"result={m.get('result')!r}  close_time={m.get('close_time')}")
        print()

asyncio.run(main())
