import asyncio
import logging

from fastapi import FastAPI

from app import m3u_handler
from app import epg_manager
from app.config import EPG_FETCH_INTERVAL
from app.web.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="FritzMux", version="1.0.0")
_shutdown = asyncio.Event()

app.include_router(router)


async def _epg_loop():
    while not _shutdown.is_set():
        try:
            await asyncio.wait_for(_shutdown.wait(), timeout=EPG_FETCH_INTERVAL)
        except asyncio.TimeoutError:
            pass
        if _shutdown.is_set():
            break
        if epg_manager.EPG_SOURCES:
            logger.info("Background EPG refresh...")
            await epg_manager.fetch_all()
            logger.info("Background EPG done (%d events)", len(epg_manager.get_epg_data()))


@app.on_event("startup")
async def startup():
    logger.info("FritzMux starting up...")
    m3u_handler.load_channels()
    logger.info("Loaded %d channels", len(m3u_handler.CHANNELS))
    epg_manager.load_sources()
    logger.info("Loaded %d EPG sources", len(epg_manager.EPG_SOURCES))
    await epg_manager.fetch_all()
    logger.info("Loaded EPG data")
    asyncio.create_task(_epg_loop())


@app.on_event("shutdown")
async def shutdown():
    _shutdown.set()
