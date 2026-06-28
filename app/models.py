from pydantic import BaseModel
from typing import Optional


class Channel(BaseModel):
    id: str
    tvg_id: str
    tvg_name: str
    tvg_logo: str = ""
    group_title: str = ""
    title: str
    rtsp_url: str


class ChannelUpdate(BaseModel):
    tvg_id: Optional[str] = None
    tvg_name: Optional[str] = None
    tvg_logo: Optional[str] = None
    group_title: Optional[str] = None
    title: Optional[str] = None
    rtsp_url: Optional[str] = None


class ImportRequest(BaseModel):
    url: Optional[str] = None
    replace: bool = False


class EpgSource(BaseModel):
    name: str
    url: str
    enabled: bool = True


class ServerStatus(BaseModel):
    active_streams: int
    max_streams: int
    channels_count: int
    epg_sources: list[str]
