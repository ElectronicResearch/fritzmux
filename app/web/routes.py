import logging
import mimetypes
from pathlib import Path

import httpx
from fastapi import APIRouter, File, Form, UploadFile, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response, StreamingResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app import m3u_handler
from app import stream_manager
from app import epg_manager
from app.config import DATA_DIR
from app.models import ChannelUpdate, ImportRequest, ServerStatus

logger = logging.getLogger(__name__)

router = APIRouter()

_tpl_dir = Path(__file__).parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_tpl_dir)),
    autoescape=select_autoescape(["html", "xml"]),
)


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    tpl = _jinja_env.get_template("index.html")
    html = tpl.render(
        channels=list(m3u_handler.CHANNELS.values()),
        active_streams=stream_manager.active_stream_count(),
        max_streams=4,
        epg_sources=epg_manager.EPG_SOURCES,
    )
    return HTMLResponse(html)


@router.get("/api/status")
async def api_status():
    return ServerStatus(
        active_streams=stream_manager.active_stream_count(),
        max_streams=4,
        channels_count=len(m3u_handler.CHANNELS),
        epg_sources=[s["name"] for s in epg_manager.EPG_SOURCES],
    )


@router.get("/api/channels")
async def api_channels():
    return list(m3u_handler.CHANNELS.values())


@router.get("/api/channels.m3u")
async def api_m3u(request: Request):
    base_url = str(request.base_url).rstrip("/")
    content = m3u_handler.generate_m3u(base_url)
    return PlainTextResponse(content, media_type="audio/x-mpegurl")


@router.get("/api/epg.xml")
async def api_epg(request: Request):
    channel_map = {
        ch.tvg_id: ch.tvg_name for ch in m3u_handler.CHANNELS.values()
    }
    xml = epg_manager.generate_xmltv(channel_map)
    return PlainTextResponse(xml, media_type="application/xml")


@router.get("/api/epg/channels")
async def api_epg_channels():
    return epg_manager.get_epg_channels()


@router.get("/api/epg/refresh")
async def api_epg_refresh():
    await epg_manager.fetch_all()
    icons = epg_manager.get_channel_icons()
    for ch in m3u_handler.CHANNELS.values():
        if not ch.tvg_logo and ch.tvg_id in icons:
            ch.tvg_logo = icons[ch.tvg_id]
    m3u_handler.save_channels()
    return {"status": "ok", "events": len(epg_manager.get_epg_data())}


@router.post("/api/import/url")
async def api_import_url(req: ImportRequest):
    if not req.url:
        return {"error": "URL is required"}, 400
    try:
        channels = await m3u_handler.import_from_url(req.url)
        if not channels:
            return {"status": "ok", "imported": 0, "total": len(m3u_handler.CHANNELS), "warning": "URL enthielt keine gültigen M3U-Einträge. Prüfe die URL oder lade die M3U-Datei manuell hoch."}
        added = m3u_handler.merge_channels(channels, replace=req.replace)
        return {"status": "ok", "imported": added, "total": len(m3u_handler.CHANNELS)}
    except httpx.ConnectError:
        return {"error": "Fritzbox nicht erreichbar. Prüfe die IP-Adresse."}, 400
    except httpx.TimeoutException:
        return {"error": "Zeitüberschreitung – Fritzbox antwortet nicht."}, 400
    except Exception as e:
        logger.exception("Import failed")
        return {"error": str(e)}, 400


@router.post("/api/scan/fritzbox")
async def api_scan_fritzbox(ip: str = Form(...)):
    base = ip.rstrip("/")
    urls_to_try = [
        # Fritzbox DVB-C Senderliste (nach "Senderliste erzeugen" im WebUI)
        f"http://{base}/dvb/m3u/tvhd.m3u",
        f"http://{base}/dvb/m3u/tvsd.m3u",
        f"http://{base}/dvb/m3u/radio.m3u",
        f"http://{base}/dvb/m3u/tvall.m3u",
        # TR-064 / UPnP Port
        f"http://{base}:49000/m3u",
        f"http://{base}:49000/m3u.m3u",
        f"http://{base}:49000/tonline.m3u",
        # Legacy WEBCM
        f"http://{base}/cgi-bin/webcm?getpage=../html/de/internet/tvapp.m3u",
        f"http://{base}/internet/tvapp.m3u",
    ]
    async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
        for url in urls_to_try:
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    channels = m3u_handler.parse_m3u(resp.text)
                    if channels:
                        added = m3u_handler.merge_channels(channels, replace=False)
                        return {"status": "ok", "url": url, "imported": added, "total": len(m3u_handler.CHANNELS)}
                    # URL gefunden, aber kein gültiges M3U
                    return {"status": "ok", "url": url, "imported": 0}
            except Exception:
                continue
    return {"status": "not_found", "message": "Keine M3U-URL auf der Fritzbox gefunden. Lade die M3U-Datei manuell hoch."}, 404


@router.post("/api/import/upload")
async def api_import_upload(file: UploadFile = File(...), replace: bool = Form(False)):
    try:
        content = await file.read()
        text = content.decode("utf-8")
        channels = m3u_handler.import_from_text(text)
        added = m3u_handler.merge_channels(channels, replace=replace)
        return {"status": "ok", "imported": added, "total": len(m3u_handler.CHANNELS)}
    except Exception as e:
        return {"error": str(e)}, 400


@router.post("/api/epg/source")
async def api_epg_add_source(name: str = Form(...), url: str = Form(...)):
    epg_manager.add_source(name, url)
    return {"status": "ok"}


@router.get("/api/channels/{channel_id}")
async def api_channel_detail(channel_id: str):
    ch = m3u_handler.CHANNELS.get(channel_id)
    if not ch:
        return {"error": "not found"}, 404
    return ch


@router.delete("/api/channels/{channel_id}")
async def api_channel_delete(channel_id: str):
    if channel_id in m3u_handler.CHANNELS:
        del m3u_handler.CHANNELS[channel_id]
        m3u_handler.save_channels()
    return {"status": "ok"}


@router.put("/api/channels/{channel_id}")
async def api_channel_update(channel_id: str, update: ChannelUpdate):
    ch = m3u_handler.update_channel(channel_id, update.model_dump(exclude_none=True))
    if not ch:
        return {"error": "not found"}, 404
    return ch


@router.post("/api/channels/clear")
async def api_channels_clear():
    m3u_handler.CHANNELS.clear()
    m3u_handler.save_channels()
    return {"status": "ok"}


@router.get("/api/logo/{channel_id}")
async def api_logo(channel_id: str):
    ch = m3u_handler.CHANNELS.get(channel_id)
    if not ch or not ch.tvg_logo:
        return Response(status_code=404, content="No logo")

    logo_dir = DATA_DIR / "logos"
    logo_dir.mkdir(parents=True, exist_ok=True)
    cache_file = logo_dir / f"{channel_id}"
    meta_file = logo_dir / f"{channel_id}.meta"

    # Serve uploaded logo
    if ch.tvg_logo == "__uploaded__":
        if cache_file.exists() and meta_file.exists():
            media_type = meta_file.read_text().strip()
            return Response(content=cache_file.read_bytes(), media_type=media_type)
        return Response(status_code=404, content="Uploaded logo not found")

    if cache_file.exists() and meta_file.exists():
        media_type = meta_file.read_text().strip()
        return Response(content=cache_file.read_bytes(), media_type=media_type)

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(ch.tvg_logo)
            resp.raise_for_status()
            data = resp.content
            media_type = resp.headers.get("content-type", "image/png")
            cache_file.write_bytes(data)
            meta_file.write_text(media_type)
            return Response(content=data, media_type=media_type)
    except Exception as e:
        logger.warning("Failed to fetch logo for %s: %s", channel_id, e)
        return Response(status_code=502, content="Logo fetch failed")


@router.post("/api/logo/{channel_id}/upload")
async def api_logo_upload(channel_id: str, file: UploadFile = File(...)):
    ch = m3u_handler.CHANNELS.get(channel_id)
    if not ch:
        return {"error": "not found"}, 404

    logo_dir = DATA_DIR / "logos"
    logo_dir.mkdir(parents=True, exist_ok=True)
    cache_file = logo_dir / f"{channel_id}"
    meta_file = logo_dir / f"{channel_id}.meta"

    data = await file.read()
    media_type = file.content_type or "image/png"
    cache_file.write_bytes(data)
    meta_file.write_text(media_type)

    ch.tvg_logo = "__uploaded__"
    m3u_handler.save_channels()
    return {"status": "ok", "logo": f"/api/logo/{channel_id}"}


@router.get("/stream/{channel_id}")
async def stream_channel(channel_id: str):
    ch = m3u_handler.CHANNELS.get(channel_id)
    if not ch:
        return Response(status_code=404, content="Channel not found")

    if stream_manager.active_stream_count() >= 4:
        return Response(status_code=503, content="All tuners busy")

    return StreamingResponse(
        stream_manager.stream_generator(ch.rtsp_url, channel_id),
        media_type="video/MP2T",
        headers={
            "Transfer-Encoding": "chunked",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
