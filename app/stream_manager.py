import asyncio
import logging
import signal
from typing import Optional

from app.config import DEFAULT_FFMPEG_PATH, MAX_STREAMS

logger = logging.getLogger(__name__)

_active_streams: dict[str, asyncio.subprocess.Process] = {}
_stream_lock = asyncio.Lock()


async def start_ffmpeg(rtsp_url: str, channel_id: str) -> Optional[asyncio.subprocess.Process]:
    async with _stream_lock:
        if channel_id in _active_streams:
            proc = _active_streams[channel_id]
            if proc.returncode is None:
                return proc
            del _active_streams[channel_id]

        if len(_active_streams) >= MAX_STREAMS:
            logger.warning("Max streams (%d) reached, rejecting %s", MAX_STREAMS, channel_id)
            return None

        logger.info("Starting ffmpeg for channel %s: %s", channel_id, rtsp_url)

        process = await asyncio.create_subprocess_exec(
            DEFAULT_FFMPEG_PATH,
            "-rtsp_transport", "udp",
            "-timeout", "5000000",
            "-i", rtsp_url,
            "-c", "copy",
            "-f", "mpegts",
            "-",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=lambda: signal.signal(signal.SIGPIPE, signal.SIG_DFL),
        )

        async def _log_stderr():
            try:
                err = await asyncio.wait_for(process.stderr.read(), timeout=10)
            except asyncio.TimeoutError:
                return
            if err:
                text = err.decode("utf-8", errors="replace")[:2000]
                for line in text.splitlines():
                    logger.warning("ffmpeg[%s]: %s", channel_id, line)

        asyncio.create_task(_log_stderr())
        _active_streams[channel_id] = process
        return process


async def stop_ffmpeg(channel_id: str):
    async with _stream_lock:
        process = _active_streams.pop(channel_id, None)
        if process and process.returncode is None:
            logger.info("Stopping ffmpeg for channel %s", channel_id)
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                try:
                    await process.wait()
                except ProcessLookupError:
                    pass


def active_stream_count() -> int:
    return sum(1 for p in _active_streams.values() if p.returncode is None)


async def cleanup_stale():
    async with _stream_lock:
        stale = [cid for cid, p in _active_streams.items() if p.returncode is not None]
        for cid in stale:
            del _active_streams[cid]


async def stream_generator(rtsp_url: str, channel_id: str):
    process = await start_ffmpeg(rtsp_url, channel_id)
    if process is None:
        return

    async def _log_stderr():
        assert process.stderr is not None
        err = await process.stderr.read()
        if err:
            text = err.decode("utf-8", errors="replace")[:2000]
            for line in text.splitlines():
                logger.warning("ffmpeg[%s]: %s", channel_id, line)

    stderr_task = asyncio.create_task(_log_stderr())

    try:
        assert process.stdout is not None
        # Kurz warten ob ffmpeg sofort stirbt
        await asyncio.sleep(0.5)
        if process.returncode is not None and process.returncode != 0:
            logger.error("ffmpeg died immediately for %s (rc=%d)", channel_id, process.returncode)
            return

        while True:
            chunk = await process.stdout.read(8192)
            if not chunk:
                break
            yield chunk
    except (asyncio.CancelledError, GeneratorExit):
        pass
    except Exception:
        logger.exception("Stream error for channel %s", channel_id)
    finally:
        await stop_ffmpeg(channel_id)
        await stderr_task
