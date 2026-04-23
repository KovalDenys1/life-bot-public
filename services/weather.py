"""
yr.no weather with 10-minute cache.
"""
import time
import logging
import requests
from datetime import datetime
import user_profile as p
from config import LOCAL_TZ

logger = logging.getLogger(__name__)

YR_SYMBOLS = {
    "clearsky_day": "☀️ Clear", "clearsky_night": "🌙 Clear",
    "fair_day": "🌤 Fair", "fair_night": "🌤 Fair",
    "partlycloudy_day": "⛅️ Partly cloudy", "partlycloudy_night": "⛅️ Partly cloudy",
    "cloudy": "☁️ Cloudy", "fog": "🌫 Fog",
    "lightrain": "🌦 Light rain", "rain": "🌧 Rain", "heavyrain": "🌧 Heavy rain",
    "lightrainshowers_day": "🌦 Light showers", "rainshowers_day": "🌧 Showers",
    "heavyrainshowers_day": "⛈ Heavy showers",
    "lightsleet": "🌨 Light sleet", "sleet": "🌨 Sleet",
    "lightsnow": "🌨 Light snow", "snow": "❄️ Snow", "heavysnow": "❄️ Heavy snow",
    "thunderstorm": "⛈ Thunderstorm",
}

_weather_cache: dict = {"data": None, "ts": 0.0}
_WEATHER_TTL = 600  # 10 minutes


def _get_weather_raw() -> dict | None:
    now = time.time()
    if _weather_cache["data"] and now - _weather_cache["ts"] < _WEATHER_TTL:
        return _weather_cache["data"]
    try:
        url = (
            "https://api.met.no/weatherapi/locationforecast/2.0/compact"
            f"?lat={p.WEATHER_LAT}&lon={p.WEATHER_LON}"
        )
        headers = {"User-Agent": "life-bot/1.0 (personal assistant)"}
        data = requests.get(url, headers=headers, timeout=10).json()
        _weather_cache["data"] = data
        _weather_cache["ts"] = now
        return data
    except Exception as e:
        logger.error(f"Weather fetch error: {e}")
        return _weather_cache["data"]


def get_oslo_weather() -> str:
    try:
        data = _get_weather_raw()
        if not data:
            return ""
        now = data["properties"]["timeseries"][0]
        instant = now["data"]["instant"]["details"]
        temp = round(instant["air_temperature"])
        wind = round(instant["wind_speed"] * 3.6)
        symbol = now["data"].get("next_1_hours", now["data"].get("next_6_hours", {})).get("summary", {}).get("symbol_code", "")
        desc = YR_SYMBOLS.get(symbol, "🌡 " + symbol.split("_")[0].capitalize() if symbol else "🌡 Unknown")
        return f"{desc}, {temp}°C, wind {wind} km/h"
    except Exception as e:
        logger.error(f"Weather error: {e}")
        return ""


def get_oslo_weather_daily() -> str:
    """Returns average day and night temperatures for today."""
    try:
        data = _get_weather_raw()
        if not data:
            return get_oslo_weather()
        timeseries = data["properties"]["timeseries"]
        today = datetime.now(LOCAL_TZ).date()
        day_temps, night_temps = [], []
        for entry in timeseries:
            dt = datetime.fromisoformat(entry["time"].replace("Z", "+00:00")).astimezone(LOCAL_TZ)
            if dt.date() != today:
                continue
            temp = entry["data"]["instant"]["details"]["air_temperature"]
            if 6 <= dt.hour <= 17:
                day_temps.append(temp)
            elif dt.hour >= 18:
                night_temps.append(temp)
        parts = []
        if day_temps:
            parts.append(f"☀️ Day avg: {round(sum(day_temps) / len(day_temps))}°C")
        if night_temps:
            parts.append(f"🌙 Night avg: {round(sum(night_temps) / len(night_temps))}°C")
        return ", ".join(parts) if parts else get_oslo_weather()
    except Exception as e:
        logger.error(f"Weather daily error: {e}")
        return get_oslo_weather()
