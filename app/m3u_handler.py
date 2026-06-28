import json
import re
from pathlib import Path
from typing import Optional

import httpx

from app.config import CHANNELS_FILE
from app.models import Channel


EXTINF_RE = re.compile(
    r'#EXTINF:\-?\d+\s*'
    r'(?:tvg-id="(?P<tvg_id>[^"]*)")?\s*'
    r'(?:tvg-name="(?P<tvg_name>[^"]*)")?\s*'
    r'(?:tvg-logo="(?P<tvg_logo>[^"]*)")?\s*'
    r'(?:group-title="(?P<group_title>[^"]*)")?\s*'
    r',(?P<title>.+)'
)

EXTINF_SIMPLE_RE = re.compile(r'#EXTINF:\-?\d+\s*,?(?P<title>.+)')

CHANNELS: dict[str, Channel] = {}


def load_channels():
    global CHANNELS
    if CHANNELS_FILE.exists():
        data = json.loads(CHANNELS_FILE.read_text())
        CHANNELS = {ch["id"]: Channel(**ch) for ch in data}
    else:
        CHANNELS = {}


def save_channels():
    CHANNELS_FILE.write_text(
        json.dumps([ch.model_dump() for ch in CHANNELS.values()], indent=2)
    )


def parse_m3u(content: str, base_url: str = "") -> list[Channel]:
    channels = []
    lines = content.strip().splitlines()
    i = 0
    idx = 1
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTM3U"):
            i += 1
            continue
        if line.startswith("#EXTINF"):
            m = EXTINF_RE.match(line) or EXTINF_SIMPLE_RE.match(line)
            if m:
                i += 1
                # überspringe Kommentarzeilen (z.B. #EXTVLCOPT) zwischen EXTINF und URL
                while i < len(lines) and lines[i].strip().startswith("#"):
                    i += 1
                if i < len(lines):
                    url = lines[i].strip()
                    if url:
                        data = m.groupdict()
                        tvg_id = data.get("tvg_id") or str(idx)
                        tvg_name = data.get("tvg_name") or data["title"]
                        channels.append(Channel(
                            id=str(idx),
                            tvg_id=tvg_id,
                            tvg_name=tvg_name,
                            tvg_logo=data.get("tvg_logo") or "",
                            group_title=data.get("group_title") or "",
                            title=data["title"],
                            rtsp_url=url,
                        ))
                        idx += 1
        i += 1
    return channels


async def import_from_url(url: str) -> list[Channel]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return parse_m3u(resp.text)


def import_from_text(content: str) -> list[Channel]:
    return parse_m3u(content)


def merge_channels(new_channels: list[Channel], replace: bool = False) -> int:
    global CHANNELS
    if replace:
        CHANNELS = {}
    existing_urls = {ch.rtsp_url for ch in CHANNELS.values()}
    next_id = max((int(c.id) for c in CHANNELS.values()), default=0) + 1
    added = 0
    for ch in new_channels:
        if ch.rtsp_url in existing_urls:
            continue
        ch.id = str(next_id)
        CHANNELS[ch.id] = ch
        existing_urls.add(ch.rtsp_url)
        next_id += 1
        added += 1
    save_channels()
    return added


def update_channel(channel_id: str, updates: dict) -> Channel | None:
    ch = CHANNELS.get(channel_id)
    if not ch:
        return None
    for key, val in updates.items():
        if val is not None and hasattr(ch, key):
            setattr(ch, key, val)
    CHANNELS[channel_id] = ch
    save_channels()
    return ch


def generate_m3u(base_url: str = "http://localhost:8181") -> str:
    lines = ["#EXTM3U"]
    for ch in sorted(CHANNELS.values(), key=lambda c: int(c.id)):
        logo_url = f"{base_url}/api/logo/{ch.id}" if ch.tvg_logo else ""
        attrs = f'tvg-id="{ch.tvg_id}" tvg-name="{ch.tvg_name}"'
        if logo_url:
            attrs += f' tvg-logo="{logo_url}"'
        if ch.group_title:
            attrs += f' group-title="{ch.group_title}"'
        lines.append(f'#EXTINF:0 {attrs},{ch.title}')
        lines.append(f'{base_url}/stream/{ch.id}')
    return "\n".join(lines) + "\n"
