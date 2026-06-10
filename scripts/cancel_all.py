#!/usr/bin/env python3
"""Emergency: cancel ALL resting orders. Run this before restarting the bot."""
import asyncio, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
from kannon.api.auth import KalshiAuth
from kannon.api.client import KalshiClient, KalshiAPIError
import yaml

async def main():
    load_dotenv()
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)
    auth = KalshiAuth(os.environ["KALSHI_API_KEY_ID"], os.environ["KALSHI_PRIVATE_KEY_PATH"])
    async with KalshiClient(cfg["kalshi"]["base_url"], auth, rate_limit_rps=2) as client:
        raw = await client._request("GET", "/portfolio/orders", params={"status": "resting", "limit": 200})
        orders = raw.get("orders", [])
        if not orders:
            print("No resting orders found.")
            return

        print(f"Found {len(orders)} resting orders. Cancelling...")
        cancelled = 0
        failed = 0
        for o in orders:
            order_id = o.get("order_id")
            ticker = o.get("ticker", "?")
            action = o.get("action", "?")
            price = float(o.get("yes_price_dollars") or "0") * 100
            try:
                await client.cancel_order(order_id)
                print(f"  CANCELLED {ticker} {action} @{price:.0f}¢  (id={order_id})")
                cancelled += 1
            except KalshiAPIError as e:
                if e.status_code == 404:
                    print(f"  SKIP {ticker} — already filled/cancelled")
                else:
                    print(f"  FAILED {ticker}: {e}")
                    failed += 1
            await asyncio.sleep(0.6)  # stay under rate limit

        print(f"\nDone: {cancelled} cancelled, {failed} failed.")

asyncio.run(main())
