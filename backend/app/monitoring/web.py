import time
import os
import ssl
from urllib.parse import urlsplit
import httpx
from app.monitoring.common import result

async def probe(target, url):
    start = time.monotonic()
    try:
        verify = ssl.create_default_context(cafile=os.getenv('PROXMOX_CA_FILE')) if target == 'proxmox' and urlsplit(url).hostname == os.getenv('PROXMOX_HOST', '192.168.20.200') else True
        async with httpx.AsyncClient(verify=verify, timeout=5, follow_redirects=False, trust_env=False) as client:
            # Streaming prevents untrusted endpoints from returning unbounded bodies.
            async with client.stream("GET", url, headers={"User-Agent": "NMS-Homelab/1.0"}) as response:
                code = response.status_code
        return result(target, "HTTP GET (TLS verified)", "UP" if 200 <= code < 400 else "DEGRADED" if code in {401, 403} else "DOWN", http_status=code, latency_ms=round((time.monotonic()-start)*1000, 2), scope="Respons HTTP saja; redirect tidak diikuti dan transaksi aplikasi belum diuji")
    except (httpx.HTTPError, OSError, ValueError) as exc:
        tls = "CERTIFICATE_VERIFY_FAILED" in str(exc)
        return result(target, "HTTP GET (TLS verified)", "UNKNOWN" if tls else "DOWN", error="tls_verification_failed" if tls else type(exc).__name__)
