import httpx
from abc import ABC, abstractmethod
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from loguru import logger
from fake_useragent import UserAgent

_ua = UserAgent()


class BaseScraper(ABC):
    def __init__(self):
        self._headers = {
            "User-Agent": _ua.random,
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
            "Accept": "application/json, text/html, */*",
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _get(self, client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
        logger.debug(f"GET {url}")
        response = await client.get(url, headers=self._headers, timeout=30, **kwargs)
        response.raise_for_status()
        return response

    @abstractmethod
    async def fetch(self, symbol: str, **kwargs):
        ...
