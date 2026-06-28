import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx

from app.config import EPG_CACHE_DIR, EPG_FETCH_INTERVAL

logger = logging.getLogger(__name__)

EPG_SOURCES: list[dict] = []
_epg_data: list[dict] = []
_last_fetch: Optional[datetime] = None
_fetch_lock = asyncio.Lock()


def add_source(name: str, url: str):
    EPG_SOURCES.append({"name": name, "url": url, "enabled": True})


def load_sources(path: Path):
    if path.exists():
        data = json.loads(path.read_text())
        EPG_SOURCES.extend(data)


async def fetch_all():
    global _epg_data, _last_fetch

    async with _fetch_lock:
        if _last_fetch and (datetime.now() - _last_fetch).seconds < EPG_FETCH_INTERVAL:
            return

        all_events = []
        async with httpx.AsyncClient(timeout=30) as client:
            for src in EPG_SOURCES:
                if not src.get("enabled"):
                    continue
                try:
                    resp = await client.get(src["url"])
                    resp.raise_for_status()
                    text = resp.text
                    cache_file = EPG_CACHE_DIR / f"{src['name']}.xml"
                    cache_file.write_text(text)
                    events = _parse_xmltv(text)
                    all_events.extend(events)
                    logger.info("Fetched %d events from %s", len(events), src["name"])
                except Exception as e:
                    logger.warning("Failed to fetch EPG from %s: %s", src["name"], e)
                    cache_file = EPG_CACHE_DIR / f"{src['name']}.xml"
                    if cache_file.exists():
                        text = cache_file.read_text()
                        events = _parse_xmltv(text)
                        all_events.extend(events)
                        logger.info("Loaded %d events from cache for %s", len(events), src["name"])

        _epg_data = all_events
        _last_fetch = datetime.now()


_channel_icons: dict[str, str] = {}


def get_channel_icons() -> dict[str, str]:
    return dict(_channel_icons)


def _parse_xmltv(xml: str) -> list[dict]:
    global _channel_icons
    events = []
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
        for channel_el in root.findall("channel"):
            ch_id = channel_el.get("id", "")
            icon_el = channel_el.find("icon")
            if icon_el is not None and icon_el.get("src"):
                _channel_icons[ch_id] = icon_el.get("src")

        for programme in root.findall("programme"):
            ch = programme.get("channel", "")
            start_str = programme.get("start", "")
            stop_str = programme.get("stop", "")
            title_el = programme.find("title")
            title = title_el.text if title_el is not None else ""
            desc_el = programme.find("desc")
            desc = desc_el.text.strip() if desc_el is not None and desc_el.text else ""
            icon_el = programme.find("icon")
            icon_src = icon_el.get("src", "") if icon_el is not None else ""
            events.append({
                "channel": ch,
                "start": start_str,
                "stop": stop_str,
                "title": title,
                "description": desc,
                "icon": icon_src,
            })
    except ET.ParseError as e:
        logger.error("XML parse error: %s", e)
    return events


def get_epg_data() -> list[dict]:
    return _epg_data


def generate_xmltv(channel_map: dict[str, str]) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<tv>",
    ]

    seen = set()
    for ev in _epg_data:
        ch_id = ev["channel"]
        display_name = channel_map.get(ch_id, ch_id)
        if ch_id not in seen:
            lines.append(f'  <channel id="{ch_id}">')
            lines.append(f'    <display-name>{display_name}</display-name>')
            lines.append("  </channel>")
            seen.add(ch_id)

    for ev in _epg_data:
        ch_id = ev["channel"]
        display_name = channel_map.get(ch_id, ch_id)
        lines.append(f'  <programme channel="{ch_id}" start="{ev["start"]}" stop="{ev["stop"]}">')
        lines.append(f'    <title>{_escape(ev["title"])}</title>')
        if ev.get("description"):
            lines.append(f'    <desc>{_escape(ev["description"])}</desc>')
        lines.append("  </programme>")

    lines.append("</tv>")
    return "\n".join(lines) + "\n"


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
