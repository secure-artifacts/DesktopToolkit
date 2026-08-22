"""Local weather fetch + speakable summary.

Primary source: Open-Meteo (open-meteo.com) — free, no API key,
backed by national weather models (ECMWF / DWD / NOAA GFS, etc.).
Optional: OpenWeatherMap Current Weather when user provides an API key.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


OPEN_METEO_GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
OPENWEATHER_CURRENT = "https://api.openweathermap.org/data/2.5/weather"
IP_LOCATE = "https://ipapi.co/json/"


class WeatherError(RuntimeError):
    pass


@dataclass
class WeatherReport:
    place: str
    latitude: float
    longitude: float
    temperature_c: float
    humidity: int | None
    wind_kmh: float | None
    description: str
    source: str  # open-meteo | openweathermap

    def speak_text(self, *, lang: str = "zh") -> str:
        """Human sentence for TTS / subtitle."""
        t = f"{self.temperature_c:.0f}"
        hum = f"，湿度 {self.humidity}%" if self.humidity is not None else ""
        wind = f"，风速约 {self.wind_kmh:.0f} 公里每小时" if self.wind_kmh is not None else ""
        if lang.startswith("en"):
            bits = [f"Weather in {self.place}: {self.description}, {t} degrees Celsius"]
            if self.humidity is not None:
                bits.append(f"humidity {self.humidity} percent")
            if self.wind_kmh is not None:
                bits.append(f"wind about {self.wind_kmh:.0f} kilometers per hour")
            return ". ".join(bits) + "."
        return f"{self.place}天气：{self.description}，气温 {t} 摄氏度{hum}{wind}。"


# WMO weather interpretation codes (Open-Meteo)
_WMO_ZH: dict[int, str] = {
    0: "晴朗",
    1: "大部晴朗",
    2: "局部多云",
    3: "阴天",
    45: "有雾",
    48: "霜雾",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "大毛毛雨",
    56: "冻毛毛雨",
    57: "强冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "小阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "强阵雪",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴大冰雹",
}


def _http_json(url: str, *, timeout: float = 12.0) -> Any:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "DesktopToolkit/1.1.9 (weather; +https://github.com/secure-artifacts/DesktopToolkit)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:240]
        raise WeatherError(f"HTTP {e.code}: {body}") from e
    except Exception as e:
        raise WeatherError(str(e)) from e


def detect_location_by_ip() -> tuple[str, float, float]:
    """Approximate location from public IP (city-level)."""
    data = _http_json(IP_LOCATE)
    lat = data.get("latitude")
    lon = data.get("longitude")
    if lat is None or lon is None:
        raise WeatherError("无法从 IP 解析位置，请手动填写城市")
    city = str(data.get("city") or "").strip()
    region = str(data.get("region") or data.get("region_code") or "").strip()
    country = str(data.get("country_name") or data.get("country") or "").strip()
    parts = [p for p in (city, region, country) if p]
    place = " · ".join(parts) if parts else "当前位置"
    return place, float(lat), float(lon)


def geocode_place(name: str, *, language: str = "zh") -> tuple[str, float, float]:
    """Resolve city/place name via Open-Meteo geocoding."""
    q = (name or "").strip()
    if not q:
        raise WeatherError("请填写地点名称")
    url = (
        f"{OPEN_METEO_GEOCODE}?name={urllib.parse.quote(q)}"
        f"&count=1&language={urllib.parse.quote(language)}&format=json"
    )
    data = _http_json(url)
    results = data.get("results") or []
    if not results:
        raise WeatherError(f"找不到地点：{q}")
    r0 = results[0]
    label_parts = [
        str(r0.get("name") or q),
        str(r0.get("admin1") or ""),
        str(r0.get("country") or ""),
    ]
    place = " · ".join(p for p in label_parts if p)
    return place, float(r0["latitude"]), float(r0["longitude"])


def fetch_open_meteo(lat: float, lon: float, place: str) -> WeatherReport:
    url = (
        f"{OPEN_METEO_FORECAST}?latitude={lat:.5f}&longitude={lon:.5f}"
        f"&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
        f"&wind_speed_unit=kmh&timezone=auto"
    )
    data = _http_json(url)
    cur = data.get("current") or {}
    code = int(cur.get("weather_code") or 0)
    desc = _WMO_ZH.get(code, f"天气代码 {code}")
    hum = cur.get("relative_humidity_2m")
    wind = cur.get("wind_speed_10m")
    return WeatherReport(
        place=place,
        latitude=lat,
        longitude=lon,
        temperature_c=float(cur.get("temperature_2m") or 0.0),
        humidity=int(hum) if hum is not None else None,
        wind_kmh=float(wind) if wind is not None else None,
        description=desc,
        source="open-meteo",
    )


def fetch_openweathermap(lat: float, lon: float, place: str, api_key: str, *, lang: str = "zh_cn") -> WeatherReport:
    key = (api_key or "").strip()
    if not key:
        raise WeatherError("未填写 OpenWeatherMap API Key")
    url = (
        f"{OPENWEATHER_CURRENT}?lat={lat:.5f}&lon={lon:.5f}"
        f"&appid={urllib.parse.quote(key)}&units=metric&lang={urllib.parse.quote(lang)}"
    )
    data = _http_json(url)
    weather = (data.get("weather") or [{}])[0]
    main = data.get("main") or {}
    wind = data.get("wind") or {}
    # m/s → km/h
    speed = wind.get("speed")
    wind_kmh = float(speed) * 3.6 if speed is not None else None
    name = str(data.get("name") or place)
    return WeatherReport(
        place=name,
        latitude=lat,
        longitude=lon,
        temperature_c=float(main.get("temp") or 0.0),
        humidity=int(main["humidity"]) if main.get("humidity") is not None else None,
        wind_kmh=wind_kmh,
        description=str(weather.get("description") or "天气"),
        source="openweathermap",
    )


def resolve_coords(cfg: dict) -> tuple[str, float, float]:
    """cfg: location_mode=auto|manual, location_text, latitude, longitude."""
    mode = str(cfg.get("location_mode") or "auto").strip().lower()
    if mode == "coords":
        try:
            lat = float(cfg.get("latitude"))
            lon = float(cfg.get("longitude"))
        except Exception as e:
            raise WeatherError("经纬度无效") from e
        place = str(cfg.get("location_text") or f"{lat:.2f},{lon:.2f}").strip()
        return place, lat, lon
    text = str(cfg.get("location_text") or "").strip()
    if mode == "manual" or text:
        if not text:
            raise WeatherError("请填写城市或地点名称")
        return geocode_place(text)
    # auto via IP
    return detect_location_by_ip()


def fetch_weather(cfg: dict) -> WeatherReport:
    """Fetch using prefs dict under state['weather']."""
    place, lat, lon = resolve_coords(cfg)
    provider = str(cfg.get("provider") or "open-meteo").strip().lower()
    if provider in ("openweathermap", "owm"):
        return fetch_openweathermap(lat, lon, place, str(cfg.get("owm_api_key") or ""))
    return fetch_open_meteo(lat, lon, place)
