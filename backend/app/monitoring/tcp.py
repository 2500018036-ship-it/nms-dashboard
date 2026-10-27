import asyncio
import time
from app.monitoring.common import result

async def probe(target, host, port):
    start = time.monotonic()
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), 3)
        writer.close()
        await asyncio.wait_for(writer.wait_closed(), 2)
        return result(target, "TCP", "UP", host=host, port=port, latency_ms=round((time.monotonic()-start)*1000, 2), scope="Koneksi TCP berhasil; kesehatan host/aplikasi belum dibuktikan")
    except (OSError, asyncio.TimeoutError) as exc:
        return result(target, "TCP", "DOWN", host=host, port=port, error=type(exc).__name__, scope="Koneksi TCP gagal; host belum tentu mati")
