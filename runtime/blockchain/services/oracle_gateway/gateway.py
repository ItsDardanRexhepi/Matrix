"""
OracleGateway — single entry point for ALL oracle data across 0pnMatrx.

Every component that needs external data (prices, weather, sports,
randomness, etc.) must route through this gateway.  It provides:

- Unified ``request()`` API keyed by oracle type
- Per-type TTL caching (via :class:`OracleCache`)
- Per-caller rate limiting
- Config-driven provider wiring (no hardcoded secrets)
"""

import hashlib
import json
import logging
import time
from typing import Any

from .cache import OracleCache
from .price_feeds import PriceFeedProvider
from .vrf_provider import VRFProvider
from .weather_oracle import WeatherOracle

logger = logging.getLogger(__name__)

# Recognised oracle types
ORACLE_TYPES: set[str] = {"price_feed", "weather", "sports", "random_vrf", "custom"}

# Default rate-limit: requests per minute per caller
_DEFAULT_RATE_LIMIT = 60


class OracleGateway:
    """Unified oracle gateway for the 0pnMatrx platform.

    Parameters
    ----------
    config : dict
        Full platform config dictionary.  The gateway reads:

        - ``oracle.cache_ttls`` — per-type TTL overrides (dict[str, int])
        - ``oracle.rate_limit`` — requests/min per caller (int)
        - ``oracle.sports.api_base`` — sports data API base URL
        - ``oracle.sports.api_key`` — sports data API key

        Plus provider-specific keys (see individual provider docs).

    Example config snippet::

        {
            "blockchain": {
                "rpc_url": "YOUR_BASE_RPC_URL",
                "chain_id": 8453,
                "platform_wallet": "YOUR_PLATFORM_WALLET"
            },
            "oracle": {
                "cache_ttls": {"price_feed": 60, "weather": 300},
                "rate_limit": 120,
                "price_feeds": {"MATIC/USD": "0x..."},
                "vrf": {
                    "coordinator_address": "YOUR_VRF_COORDINATOR_ADDRESS",
                    "subscription_id": "YOUR_VRF_SUBSCRIPTION_ID",
                    "key_hash": "YOUR_VRF_KEY_HASH"
                },
                "weather": {
                    "api_base": "https://api.openweathermap.org/data/2.5",
                    "api_key": "YOUR_WEATHER_API_KEY"
                },
                "sports": {
                    "api_base": "YOUR_SPORTS_API_BASE",
                    "api_key": "YOUR_SPORTS_API_KEY"
                }
            }
        }
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        oracle_cfg: dict[str, Any] = config.get("oracle", {})

        # Cache
        cache_ttls: dict[str, int] | None = oracle_cfg.get("cache_ttls")
        self._cache = OracleCache(ttls=cache_ttls)

        # Rate limiting
        self._rate_limit: int = int(
            oracle_cfg.get("rate_limit", _DEFAULT_RATE_LIMIT)
        )
        self._caller_windows: dict[str, list[float]] = {}

        # Providers (lazy-initialised)
        self._price_provider: PriceFeedProvider | None = None
        self._vrf_provider: VRFProvider | None = None
        self._weather_provider: WeatherOracle | None = None

        # Sports config
        self._sports_api_base: str = oracle_cfg.get("sports", {}).get(
            "api_base", ""
        )
        self._sports_api_key: str = oracle_cfg.get("sports", {}).get(
            "api_key", ""
        )

        logger.info(
            "OracleGateway initialised (rate_limit=%d req/min)", self._rate_limit
        )

    # ------------------------------------------------------------------
    # Provider accessors (lazy init)
    # ------------------------------------------------------------------

    @property
    def price_feeds(self) -> PriceFeedProvider:
        if self._price_provider is None:
            self._price_provider = PriceFeedProvider(self._config)
        return self._price_provider

    @property
    def vrf(self) -> VRFProvider:
        if self._vrf_provider is None:
            self._vrf_provider = VRFProvider(self._config)
        return self._vrf_provider

    @property
    def weather(self) -> WeatherOracle:
        if self._weather_provider is None:
            self._weather_provider = WeatherOracle(self._config)
        return self._weather_provider

    # ------------------------------------------------------------------
    # Unified request API
    # ------------------------------------------------------------------

    async def request(
        self,
        oracle_type: str,
        params: dict[str, Any],
        *,
        caller: str = "anonymous",
    ) -> dict[str, Any]:
        """Single entry point for all oracle data requests.

        Parameters
        ----------
        oracle_type : str
            One of ``price_feed``, ``weather``, ``sports``,
            ``random_vrf``, ``custom``.
        params : dict
            Type-specific parameters (see dispatch methods).
        caller : str
            Identifier of the calling component, used for rate limiting.

        Returns
        -------
        dict
            Oracle response payload.  Always includes ``oracle_type``,
            ``cached`` (bool), and ``timestamp``.

        Raises
        ------
        ValueError
            If *oracle_type* is unknown or params are invalid.
        RuntimeError
            If rate-limited or the upstream provider fails.
        """
        if oracle_type not in ORACLE_TYPES:
            raise ValueError(
                f"Unknown oracle_type '{oracle_type}'. "
                f"Must be one of: {', '.join(sorted(ORACLE_TYPES))}"
            )

        # Rate-limit check
        self._enforce_rate_limit(caller)

        # Build cache key from type + sorted params
        cache_key = self._cache_key(params)

        # Try cache first
        cached = await self._cache.get(oracle_type, cache_key)
        if cached is not None:
            logger.debug(
                "Cache hit for %s:%s (caller=%s)", oracle_type, cache_key, caller
            )
            return {**cached, "cached": True}

        # Dispatch to the appropriate handler
        handler = self._dispatch(oracle_type)
        result = await handler(params)

        # Wrap response
        response: dict[str, Any] = {
            "oracle_type": oracle_type,
            "cached": False,
            "timestamp": int(time.time()),
            **result,
        }

        # Store in cache (no-op for TTL=0 types like VRF)
        await self._cache.set(oracle_type, cache_key, response)

        return response

    # ------------------------------------------------------------------
    # Dispatch & handlers
    # ------------------------------------------------------------------

    def _dispatch(self, oracle_type: str):
        """Return the async handler for *oracle_type*."""
        handlers = {
            "price_feed": self._handle_price_feed,
            "weather": self._handle_weather,
            "sports": self._handle_sports,
            "random_vrf": self._handle_vrf,
            "custom": self._handle_custom,
        }
        return handlers[oracle_type]

    async def _handle_price_feed(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle ``price_feed`` requests.

        Params
        ------
        pair : str
            Price pair, e.g. ``ETH/USD``.
        round_id : int, optional
            If provided, fetch historical price for this round.
        """
        pair: str = params.get("pair", "")
        if not pair:
            raise ValueError("price_feed requires 'pair' parameter")

        round_id = params.get("round_id")
        if round_id is not None:
            return await self.price_feeds.get_historical_price(pair, int(round_id))
        return await self.price_feeds.get_latest_price(pair)

    async def _handle_weather(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle ``weather`` requests.

        Params
        ------
        location : str
            City name or ``lat,lon``.
        date : str, optional
            ISO date for historical queries.
        """
        location: str = params.get("location", "")
        if not location:
            raise ValueError("weather requires 'location' parameter")

        date = params.get("date")
        if date:
            return await self.weather.get_historical_weather(location, date)
        return await self.weather.get_weather(location)

    async def _handle_sports(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle ``sports`` requests.

        Params
        ------
        sport : str
            Sport type (``soccer``, ``basketball``, ``baseball``, etc.).
        event_id : str
            Unique event / match identifier.
        query : str
            What to retrieve: ``score``, ``result``, ``odds``, ``schedule``.
        """
        if not self._sports_api_base or not self._sports_api_key:
            raise ValueError(
                "Sports oracle not configured.  "
                "Set oracle.sports.api_base and oracle.sports.api_key in config."
            )

        sport = params.get("sport", "")
        event_id = params.get("event_id", "")
        query = params.get("query", "result")

        if not sport:
            raise ValueError("sports requires 'sport' parameter")

        try:
            import aiohttp
        except ImportError:
            raise RuntimeError("aiohttp required — run: pip install aiohttp")

        url = f"{self._sports_api_base}/{sport}/{query}"
        request_params = {"apiKey": self._sports_api_key}
        if event_id:
            request_params["eventId"] = event_id

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                params=request_params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(
                        f"Sports API returned {resp.status}: {body}"
                    )
                data = await resp.json()

        return {
            "sport": sport,
            "event_id": event_id,
            "query": query,
            "data": data,
        }

    async def _handle_vrf(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle ``random_vrf`` requests.

        Params
        ------
        action : str
            ``request`` to submit a new VRF request, ``get_result`` to
            poll for fulfilment.
        num_words : int
            Number of random words (for ``request``).
        callback_gas_limit : int
            Gas limit for callback (for ``request``, default 200000).
        request_id : str
            VRF request ID (for ``get_result``).
        """
        action = params.get("action", "request")

        if action == "request":
            num_words = int(params.get("num_words", 1))
            gas_limit = int(params.get("callback_gas_limit", 200_000))
            return await self.vrf.request_random(num_words, gas_limit)

        if action == "get_result":
            request_id = params.get("request_id", "")
            if not request_id:
                raise ValueError("get_result requires 'request_id'")
            return await self.vrf.get_random_result(request_id)

        raise ValueError(
            f"Unknown VRF action '{action}'. Use 'request' or 'get_result'."
        )

    async def _handle_custom(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle ``custom`` oracle requests.

        Params
        ------
        url : str
            HTTP endpoint to query.
        method : str
            HTTP method (default ``GET``).
        headers : dict, optional
            Extra headers.
        body : dict, optional
            JSON body for POST/PUT.
        """
        url = params.get("url", "")
        if not url:
            raise ValueError("custom oracle requires 'url' parameter")

        method = params.get("method", "GET").upper()
        headers = params.get("headers", {})
        body = params.get("body")

        try:
            import aiohttp
        except ImportError:
            raise RuntimeError("aiohttp required — run: pip install aiohttp")

        async with aiohttp.ClientSession() as session:
            kwargs: dict[str, Any] = {
                "headers": headers,
                "timeout": aiohttp.ClientTimeout(total=30),
            }
            if body and method in ("POST", "PUT", "PATCH"):
                kwargs["json"] = body

            async with session.request(method, url, **kwargs) as resp:
                response_body = await resp.text()
                try:
                    data = json.loads(response_body)
                except json.JSONDecodeError:
                    data = {"raw": response_body}

        return {
            "url": url,
            "method": method,
            "status_code": resp.status,
            "data": data,
        }

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _enforce_rate_limit(self, caller: str) -> None:
        """Sliding-window rate limiter per caller."""
        now = time.monotonic()
        window = self._caller_windows.setdefault(caller, [])

        # Prune timestamps older than 60 seconds
        cutoff = now - 60.0
        self._caller_windows[caller] = [t for t in window if t > cutoff]
        window = self._caller_windows[caller]

        if len(window) >= self._rate_limit:
            raise RuntimeError(
                f"Rate limit exceeded for caller '{caller}' "
                f"({self._rate_limit} requests/min)"
            )
        window.append(now)

    # ------------------------------------------------------------------
    # Cache management helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key(params: dict[str, Any]) -> str:
        """Deterministic cache key from request params."""
        serialised = json.dumps(params, sort_keys=True, default=str)
        return hashlib.sha256(serialised.encode()).hexdigest()[:24]

    @property
    def cache_stats(self) -> dict[str, int]:
        """Expose cache statistics."""
        return self._cache.stats

    async def invalidate_cache(
        self, oracle_type: str, params: dict[str, Any] | None = None
    ) -> None:
        """Invalidate cached oracle data.

        If *params* is provided, only that specific entry is removed.
        Otherwise the entire oracle type is flushed.
        """
        if params is not None:
            key = self._cache_key(params)
            await self._cache.invalidate(oracle_type, key)
        else:
            await self._cache.invalidate_type(oracle_type)
