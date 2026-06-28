import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import m3u_handler
from app import epg_manager
from app.web.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="FritzMux", version="1.0.0")

app.include_router(router)


@app.on_event("startup")
async def startup():
    logger.info("FritzMux starting up...")
    m3u_handler.load_channels()
    logger.info("Loaded %d channels", len(m3u_handler.CHANNELS))
    await epg_manager.fetch_all()
    logger.info("Loaded EPG data")
