import time
import dns.asyncresolver
import dns.exception
from app.monitoring.common import result

async def probe(target, host, port, query):
    resolver = dns.asyncresolver.Resolver(configure=False)
    resolver.nameservers, resolver.port = [host], port
    resolver.timeout, resolver.lifetime = 2, 4
    start = time.monotonic()
    try:
        answer = await resolver.resolve(query, "A", search=False)
        return result(target, "DNS A/UDP (TCP fallback)", "UP", query=query, answers=[str(a) for a in answer][:8], latency_ms=round((time.monotonic()-start)*1000, 2), scope="Satu resolusi dari server bot; bukan bukti semua klien/VLAN sehat")
    except dns.exception.DNSException as exc:
        return result(target, "DNS A", "DOWN", query=query, error=type(exc).__name__)
