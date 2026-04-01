"""
Weather data oracle for parametric insurance (Component 13) and other
location-aware contracts.

Fetches current and historical weather from a configurable API endpoint.
All API keys and URLs are config-driven — no secrets in source.
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_API_BASE = "https://api.openweathermap.org/data/2.5"


class WeatherOracle:
    """Provides weather data for on-chain parametric triggers.

    Parameters
    ----------
    config : dict
        Full platform config.  Reads ``oracle.weather``:

        - ``api_base`` — base URL for the weather API
        - ``api_key`` — API key (use ``YOUR_WEATHER_API_KEY`` placeholder)
        - ``default_units`` — ``metric`` | ``imperial`` (default ``metric``)
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        weather_cfg: dict[str, Any] = config.get("oracle", {}).get(
            "weather", {}
        )

        self._api_base: str = weather_cfg.get("api_base", _DEFAULT_API_BASE)
        self._api_key: str = weather_cfg.get("api_key", "")
        self._units: str = weather_cfg.get("default_units", "metric")

        if not self._api_key:
            logger.warning(
                "Weather oracle API key not set. "
                "Configure oracle.weather.api_key in config."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_weather(self, location: str) -> dict[str, Any]:
        """Fetch current weather for *location*.

        Parameters
        ----------
        location : str
            City name, city+country code (``London,GB``), or
            ``lat,lon`` pair (``51.5,-0.12``).

        Returns
        -------
        dict
            Keys: ``location``, ``temp``, ``humidity``, ``wind_speed``,
            ``wind_direction``, ``conditions``, ``pressure``,
            ``timestamp``.
        """
        if not self._api_key:
            raise ValueError(
                "Weather API key not configured.  "
                "Set oracle.weather.api_key in config."
            )

        params = self._build_location_params(location)
        params.update({
            "appid": self._api_key,
            "units": self._units,
        })

        url = f"{self._api_base}/weather"
        data = await self._http_get(url, params)

        return self._normalise_current(data, location)

    async def get_historical_weather(
        self, location: str, date: str
    ) -> dict[str, Any]:
        """Fetch historical weather for *location* on *date*.

        Parameters
        ----------
        location : str
            Same format as :meth:`get_weather`.
        date : str
            ISO-8601 date string (``YYYY-MM-DD``).

        Returns
        -------
        dict
            Same shape as :meth:`get_weather` plus ``date`` field.
        """
        if not self._api_key:
            raise ValueError(
                "Weather API key not configured.  "
                "Set oracle.weather.api_key in config."
            )

        # Convert date to Unix timestamp (start of day UTC)
        try:
            import datetime as _dt

            dt = _dt.datetime.fromisoformat(date).replace(
                hour=12, tzinfo=_dt.timezone.utc
            )
            unix_ts = int(dt.timestamp())
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"Invalid date format '{date}'.  Use YYYY-MM-DD."
            ) from exc

        params = self._build_location_params(location)
        params.update({
            "appid": self._api_key,
            "units": self._units,
            "dt": unix_ts,
            "type": "hour",
        })

        url = f"{self._api_base}/timemachine"
        data = await self._http_get(url, params)

        result = self._normalise_historical(data, location)
        result["date"] = date
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_location_params(location: str) -> dict[str, str]:
        """Detect whether *location* is a lat/lon pair or city name."""
        parts = [p.strip() for p in location.split(",")]
        try:
            lat, lon = float(parts[0]), float(parts[1])
            return {"lat": str(lat), "lon": str(lon)}
        except (ValueError, IndexError):
            return {"q": location}

    @staticmethod
    def _normalise_current(data: dict[str, Any], location: str) -> dict[str, Any]:
        """Map raw API response to our canonical shape."""
        main = data.get("main", {})
        wind = data.get("wind", {})
        weather_list = data.get("weather", [{}])
        conditions = weather_list[0].get("description", "unknown") if weather_list else "unknown"

        return {
            "location": data.get("name", location),
            "temp": main.get("temp"),
            "feels_like": main.get("feels_like"),
            "humidity": main.get("humidity"),
            "pressure": main.get("pressure"),
            "wind_speed": wind.get("speed"),
            "wind_direction": wind.get("deg"),
            "conditions": conditions,
            "timestamp": data.get("dt", int(time.time())),
        }

    @staticmethod
    def _normalise_historical(
        data: dict[str, Any], location: str
    ) -> dict[str, Any]:
        """Normalise a historical / timemachine response."""
        # The timemachine endpoint returns a list of hourly entries;
        # we pick the midday entry (index 12) or the first available.
        hourly = data.get("data", data.get("hourly", []))
        entry = hourly[len(hourly) // 2] if hourly else data

        return {
            "location": location,
            "temp": entry.get("temp"),
            "feels_like": entry.get("feels_like"),
            "humidity": entry.get("humidity"),
            "pressure": entry.get("pressure"),
            "wind_speed": entry.get("wind_speed"),
            "wind_direction": entry.get("wind_deg"),
            "conditions": (
                entry.get("weather", [{}])[0].get("description", "unknown")
                if entry.get("weather")
                else "unknown"
            ),
            "timestamp": entry.get("dt", 0),
        }

    @staticmethod
    async def _http_get(url: str, params: dict[str, str]) -> dict[str, Any]:
        """Perform an async HTTP GET request."""
        try:
            import aiohttp
        except ImportError:
            raise RuntimeError(
                "aiohttp package is required — run: pip install aiohttp"
            )

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(
                        f"Weather API returned {resp.status}: {body}"
                    )
                return await resp.json()
