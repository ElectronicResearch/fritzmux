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
    return Response(
        content=content,
        media_type="application/x-mpegurl",
    )


@router.get("/api/epg.xml")
async def api_epg(request: Request):
    channel_map = {
        ch.tvg_id: ch.tvg_name for ch in m3u_handler.CHANNELS.values()
    }
    xml = epg_manager.generate_xmltv(channel_map)
    return Response(
        content=xml.encode("utf-8"),
        media_type="application/xml; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="fritzmux.xml"'},
    )


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


@router.get("/api/epg/sources")
async def api_epg_list_sources():
    return epg_manager.EPG_SOURCES


@router.delete("/api/epg/source/{name}")
async def api_epg_remove_source(name: str):
    epg_manager.remove_source(name)
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


@router.post("/api/logos/avm")
async def api_fetch_avm_logos():
    AVM_BASE = "https://download.avm.de/tv/logos/"
    logo_dir = DATA_DIR / "logos"
    logo_dir.mkdir(parents=True, exist_ok=True)

    # Hole verfügbare Logos von AVM
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(AVM_BASE)
            resp.raise_for_status()
            import re
            avm_logos = set(re.findall(r'href="([^"]+\.png)"', resp.text))
    except Exception as e:
        return {"error": f"AVM-Repository nicht erreichbar: {e}"}, 502

    if not avm_logos:
        return {"error": "Keine Logos im AVM-Repository gefunden"}, 404

    def normalize(name: str) -> str:
        n = name.lower().strip()
        n = n.replace("ü", "ue").replace("ö", "oe").replace("ä", "ae").replace("ß", "ss")
        n = re.sub(r"[^a-z0-9]+", "_", n).strip("_")
        # Entferne häufige Suffixe
        for suffix in ["_hd", "_sd", "_de"]:
            if n.endswith(suffix):
                n = n[:-len(suffix)]
        return n

    # Baue Mapping: normalized_name -> original filename
    logo_map = {}
    for fn in avm_logos:
        base = fn.replace(".png", "")
        # auch mit _hd, _sd versionen
        logo_map[base] = fn
        for suffix in ["_hd", "_sd"]:
            if base.endswith(suffix):
                logo_map[base[:-len(suffix)]] = fn

    found = 0
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        for ch in m3u_handler.CHANNELS.values():
            for name_candidate in [ch.tvg_name, ch.title, ch.tvg_id]:
                if not name_candidate:
                    continue
                norm = normalize(name_candidate)
                fn = logo_map.get(norm)
                if not fn:
                    # Versuche mit _hd suffix
                    fn = logo_map.get(f"{norm}_hd") or logo_map.get(f"{norm}_sd")
                if fn:
                    cache_file = logo_dir / ch.id
                    meta_file = logo_dir / f"{ch.id}.meta"
                    if cache_file.exists():
                        # bereits vorhanden
                        if ch.tvg_logo != "__uploaded__":
                            ch.tvg_logo = "__uploaded__"
                            found += 1
                        break
                    try:
                        url = AVM_BASE + fn
                        resp = await client.get(url)
                        resp.raise_for_status()
                        cache_file.write_bytes(resp.content)
                        meta_file.write_text(resp.headers.get("content-type", "image/png"))
                        ch.tvg_logo = "__uploaded__"
                        found += 1
                        break
                    except Exception:
                        continue

    if found:
        m3u_handler.save_channels()
    return {"status": "ok", "found": found, "total": len(m3u_handler.CHANNELS)}


@router.get("/stream/{channel_id}")
async def stream_channel(channel_id: str):
    ch = m3u_handler.CHANNELS.get(channel_id)
    if not ch:
        return Response(status_code=404, content="Channel not found")

    if stream_manager.active_stream_count() >= 4:
        return Response(status_code=503, content="All tuners busy")

    # Starte ffmpeg und warte auf erste Daten (max 10s)
    import asyncio
    process = await stream_manager.start_ffmpeg(ch.rtsp_url, channel_id)
    if process is None:
        return Response(status_code=503, content="Stream unavailable")

    first_chunk = None
    for attempt in range(40):  # 40 × 250ms = 10s timeout
        await asyncio.sleep(0.25)
        if process.returncode is not None:
            return Response(status_code=502, content=f"ffmpeg exited with code {process.returncode}")
        try:
            assert process.stdout is not None
            first_chunk = await asyncio.wait_for(process.stdout.read(8192), timeout=0.25)
            if first_chunk:
                break
        except (asyncio.TimeoutError, asyncio.CancelledError):
            continue

    if not first_chunk:
        await stream_manager.stop_ffmpeg(channel_id)
        return Response(status_code=502, content="ffmpeg produced no data after 10s")

    async def gen():
        yield first_chunk
        try:
            while True:
                chunk = await process.stdout.read(8192)
                if not chunk:
                    break
                yield chunk
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except Exception:
            logger.exception("Stream error for channel %s", channel_id)
        finally:
            await stream_manager.stop_ffmpeg(channel_id)

    return StreamingResponse(
        gen(),
        media_type="video/MP2T",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/api/stream/test")
async def api_stream_test(channel_id: str = Form(...)):
    ch = m3u_handler.CHANNELS.get(channel_id)
    if not ch:
        return {"error": "Channel not found"}
    import subprocess, sys
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-rtsp_transport", "tcp",
        "-rtsp_flags", "prefer_tcp",
        "-i", ch.rtsp_url,
        "-c", "copy",
        "-f", "null",
        "-",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=10,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        rc = proc.returncode
        err_text = stderr.decode("utf-8", errors="replace")[-1000:]
        if rc == 0:
            return {"status": "ok", "message": "ffmpeg connected successfully"}
        else:
            return {"status": "error", "message": err_text}
    except asyncio.TimeoutError:
        proc.kill()
        return {"status": "error", "message": "Timeout (10s) – Fritzbox antwortet nicht"}
    except Exception as e:
        return {"error": str(e)}
