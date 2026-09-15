"""サンプル MCP 相当の内蔵ツール（時刻・天気・Wikipedia）。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

REQUEST_TIMEOUT = 12.0
USER_AGENT = "open-genai-notebook/0.2"

_WMO = {
    0: "快晴",
    1: "ほぼ晴れ",
    2: "一部曇り",
    3: "曇り",
    45: "霧",
    48: "着氷性の霧",
    51: "弱い霧雨",
    53: "霧雨",
    55: "強い霧雨",
    61: "弱い雨",
    63: "雨",
    65: "強い雨",
    71: "弱い雪",
    73: "雪",
    75: "強い雪",
    80: "にわか雨",
    81: "強いにわか雨",
    82: "激しいにわか雨",
    95: "雷雨",
    96: "雹を伴う雷雨",
    99: "強い雹を伴う雷雨",
}


def current_time_payload() -> dict[str, Any]:
    now = datetime.now(ZoneInfo("Asia/Tokyo"))
    weekdays = "月火水木金土日"
    return {
        "timezone": "Asia/Tokyo",
        "iso": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": weekdays[now.weekday()] + "曜日",
        "display": (
            f"{now.year}年{now.month}月{now.day}日"
            f"（{weekdays[now.weekday()]}）"
            f"{now.strftime('%H:%M')}"
        ),
    }


async def get_current_time() -> str:
    return json.dumps(current_time_payload(), ensure_ascii=False)


def _headers() -> dict[str, str]:
    return {"User-Agent": USER_AGENT, "Accept": "application/json"}


async def get_weather(city: str = "") -> str:
    place = (city or "").strip() or "東京"
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, headers=_headers()) as client:
        geo = await client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": place, "count": 1, "language": "ja", "format": "json"},
        )
        geo.raise_for_status()
        hits = (geo.json() or {}).get("results") or []
        if not hits:
            return json.dumps(
                {"error": f"都市が見つかりません: {place}"},
                ensure_ascii=False,
            )
        hit = hits[0] if isinstance(hits[0], dict) else {}
        lat = hit.get("latitude")
        lon = hit.get("longitude")
        forecast = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,weather_code,wind_speed_10m,relative_humidity_2m",
                "timezone": "Asia/Tokyo",
            },
        )
        forecast.raise_for_status()
        current = (forecast.json() or {}).get("current") or {}
        code = current.get("weather_code")
        try:
            code_i = int(code)
        except (TypeError, ValueError):
            code_i = -1
        return json.dumps(
            {
                "query": place,
                "name": hit.get("name") or place,
                "country": hit.get("country") or "",
                "latitude": lat,
                "longitude": lon,
                "timezone": "Asia/Tokyo",
                "temperature_c": current.get("temperature_2m"),
                "humidity": current.get("relative_humidity_2m"),
                "wind_speed_kmh": current.get("wind_speed_10m"),
                "weather_code": code,
                "condition": _WMO.get(code_i, "不明"),
                "source": "Open-Meteo",
            },
            ensure_ascii=False,
        )


async def wikipedia_search(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return json.dumps({"error": "query が空です"}, ensure_ascii=False)
    snippets: list[str] = []
    heading = ""
    url = ""
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, headers=_headers()) as client:
        wiki = await client.get(
            "https://ja.wikipedia.org/w/api.php",
            params={
                "action": "opensearch",
                "search": q,
                "limit": 5,
                "namespace": 0,
                "format": "json",
            },
        )
        wiki.raise_for_status()
        parsed = wiki.json()
        titles = parsed[1] if isinstance(parsed, list) and len(parsed) > 1 else []
        descs = parsed[2] if isinstance(parsed, list) and len(parsed) > 2 else []
        links = parsed[3] if isinstance(parsed, list) and len(parsed) > 3 else []
        for i, title in enumerate(titles):
            desc = descs[i] if i < len(descs) else ""
            link = links[i] if i < len(links) else ""
            line = f"{title}: {desc}".strip(": ")
            if link:
                line += f" ({link})"
            if line:
                snippets.append(line)
        if titles:
            heading = str(titles[0])
            url = str(links[0]) if links else ""
    if not snippets:
        return json.dumps(
            {
                "query": q,
                "error": "Wikipedia に該当する記事が見つかりませんでした。",
                "source": "Wikipedia",
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "query": q,
            "heading": heading,
            "url": url,
            "snippets": snippets[:8],
            "source": "Wikipedia",
            "note": "日本語 Wikipedia の検索です。百科事典に無い固有の会社・人物は見つからないことがあります。",
        },
        ensure_ascii=False,
    )


async def web_search(query: str) -> str:
    return await wikipedia_search(query)
