#!/usr/bin/env python3
"""Quick diagnostic — prints raw fields from the first few settled markets."""
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
        # Fetch raw JSON without any filtering
        data = await client._request("GET", "/markets", params={"status": "settled", "limit": 5})
        markets = data.get("markets", [])
        print(f"\nGot {len(markets)} markets. Showing key fields:\n")
        for m in markets[:5]:
            print(f"  ticker:      {m.get('ticker')}")
            print(f"  status:      {m.get('status')}")
            print(f"  result:      {m.get('result')!r}")
            print(f"  last_price:  {m.get('last_price')}")
            print(f"  close_time:  {m.get('close_time')}")
            print()

asyncio.run(main())
