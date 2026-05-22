"""Profile a short BTC backtest to find hot functions."""
import asyncio
import cProfile
import io
import os
import pstats
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.crypto_data import crypto_fetch_daily, crypto_fetch_m1
from backend.smc_analyst.backtest import backtest_symbol


async def run() -> None:
    os.environ["SMC_SESSION_WINDOW_HOURS"] = "4.0"
    await backtest_symbol(
        "BTC/USDT", days=2, step=5,
        fetch_m1=crypto_fetch_m1, fetch_daily=crypto_fetch_daily,
    )


def main() -> None:
    pr = cProfile.Profile()
    pr.enable()
    asyncio.run(run())
    pr.disable()

    stream = io.StringIO()
    stats = pstats.Stats(pr, stream=stream).sort_stats("cumulative")
    stats.print_stats(30)
    print(stream.getvalue())

    stream2 = io.StringIO()
    pstats.Stats(pr, stream=stream2).sort_stats("tottime").print_stats(30)
    print("\n=== by tottime ===")
    print(stream2.getvalue())


if __name__ == "__main__":
    main()
