import asyncio
import httpx
import pandas as pd
from loguru import logger
from config.settings import settings


class FinMindClient:
    """Thin async wrapper around the FinMind v4 REST API."""

    BASE = settings.finmind_base_url

    async def query_dataset(self, dataset: str) -> pd.DataFrame:
        """Query a FinMind dataset that returns a full list (no data_id needed)."""
        params = {"dataset": dataset}
        if settings.finmind_api_token:
            params["token"] = settings.finmind_api_token

        async with httpx.AsyncClient() as client:
            resp = await client.get(self.BASE, params=params, timeout=30)
            resp.raise_for_status()
            payload = resp.json()

        if payload.get("status") != 200:
            logger.warning(f"FinMind [{dataset}]: {payload.get('msg')}")
            return pd.DataFrame()

        return pd.DataFrame(payload["data"])

    async def query(
        self,
        dataset: str,
        stock_id: str,
        start_date: str,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        params = {
            "dataset": dataset,
            "data_id": stock_id,
            "start_date": start_date,
        }
        if end_date:
            params["end_date"] = end_date
        if settings.finmind_api_token:
            params["token"] = settings.finmind_api_token

        async with httpx.AsyncClient() as client:
            resp = await client.get(self.BASE, params=params, timeout=30)
            if resp.status_code >= 400:
                logger.warning(f"FinMind [{dataset}] {stock_id}: HTTP {resp.status_code} — treating as empty")
                return pd.DataFrame()
            payload = resp.json()

        if payload.get("status") != 200:
            logger.warning(f"FinMind [{dataset}] {stock_id}: {payload.get('msg')}")
            return pd.DataFrame()

        df = pd.DataFrame(payload["data"])
        await asyncio.sleep(settings.finmind_rate_limit_delay)
        return df


finmind = FinMindClient()
