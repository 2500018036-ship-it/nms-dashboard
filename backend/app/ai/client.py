import asyncio
import logging
import random
import time

import httpx
from openai import AsyncOpenAI, APIStatusError, APIConnectionError, APITimeoutError

log = logging.getLogger(__name__)

class AIError(Exception):
    def __init__(self, category, status=None):
        self.category, self.status = category, status
        super().__init__(category)

MESSAGES = {
    "not_configured": "AI belum dikonfigurasi. Monitoring dan notifikasi otomatis tetap berjalan; gunakan /status, /events atau /mikrotik.",
    "auth": "Autentikasi OpenRouter ditolak. Admin perlu memeriksa API key.",
    "quota": "Kredit/kuota OpenRouter tidak mencukupi. Periksa akun provider.",
    "rate_limit": "OpenRouter sedang membatasi permintaan. Coba lagi beberapa saat.",
    "daily_limit": "Batas harian model gratis OpenRouter telah tercapai. Monitoring dan notifikasi otomatis tetap berjalan. Gunakan /status, /events, atau /mikrotik untuk data langsung.",
    "timeout": "OpenRouter melewati batas waktu. Coba lagi beberapa saat.",
    "network": "Koneksi ke OpenRouter gagal. Periksa konektivitas server.",
    "server": "Provider AI sedang mengalami gangguan.",
    "model": "Model atau dukungan tool tidak tersedia. Admin perlu memeriksa konfigurasi model.",
    "empty": "Model mengembalikan jawaban kosong atau terpotong.",
    "tool_limit": "Batas pemeriksaan AI tercapai. Gunakan /status untuk hasil langsung.",
    "protocol": "Format respons AI tidak valid. Admin dapat memeriksa /diagnostics.",
}

def classify(exc):
    if isinstance(exc, (APITimeoutError, asyncio.TimeoutError)):
        return AIError("timeout")
    if isinstance(exc, APIConnectionError):
        return AIError("network")
    if isinstance(exc, APIStatusError):
        code = exc.status_code
        if code==429 and 'free-models-per-day' in str(exc.body).lower():return AIError('daily_limit',429)
        return AIError({400: "model", 401: "auth", 402: "quota", 403: "auth", 404: "model", 408: "timeout", 429: "rate_limit"}.get(code, "server" if code >= 500 else "protocol"), code)
    return AIError("protocol")

class AIClient:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.sdk = transport or (AsyncOpenAI(api_key=settings.api_key, base_url=settings.api_base,
            timeout=httpx.Timeout(40, connect=10), max_retries=0) if settings.api_key else None)
        self.last = {"status": "UNKNOWN", "reason": "belum diuji"}
        self.diagnostic_cache = None

    async def complete(self, messages, tools=None, tool_choice="auto"):
        if self.sdk is None:raise AIError('not_configured')
        for index, model in enumerate(self.settings.models):
            for attempt in range(2):
                try:
                    kwargs = dict(model=model, messages=messages, max_tokens=1800)
                    if tools:
                        kwargs.update(tools=tools, tool_choice=tool_choice, extra_body={"provider": {"require_parameters": True}})
                    response = await self.sdk.chat.completions.create(**kwargs)
                    if not response or not response.choices:
                        raise AIError("empty")
                    actual=str(getattr(response,'model','')).lower()
                    if 'content-safety' in actual or '/llama-guard-' in actual:
                        # A free router can select a moderation classifier for a
                        # no-tool request. HTTP 200 and 'safe' are not an answer.
                        log.warning('ai_non_assistant_model model=%s actual=%s',model,response.model)
                        raise AIError('model')
                    choice = response.choices[0]
                    message = choice.message
                    if choice.finish_reason in {"length", "content_filter"}:
                        raise AIError("empty")
                    if not message or not (message.content and message.content.strip() or message.tool_calls):
                        raise AIError("empty")
                    if tools and tool_choice == 'required' and not message.tool_calls:
                        # Some routed models ignore tool_choice despite HTTP 200.
                        # Never accept invented live status as a successful completion.
                        log.warning('ai_required_tool_ignored model=%s actual=%s',model,response.model)
                        raise AIError('protocol')
                    self.last = {"status": "UP", "configured_model": model, "actual_model": response.model, "at": time.time()}
                    log.info("ai_completed model=%s actual=%s fallback=%s", model, response.model, index > 0)
                    return message
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    error = exc if isinstance(exc, AIError) else classify(exc)
                    self.last = {"status": "DOWN", "category": error.category, "http": error.status, "model": model, "at": time.time()}
                    log.warning("ai_failed model=%s category=%s http=%s attempt=%s", model, error.category, error.status, attempt + 1)
                    # Authentication and exhausted account credit cannot be repaired by a model switch.
                    if error.category in {"auth", "quota"}:
                        raise error from None
                    if error.category=='daily_limit' and all(m=='openrouter/free' or m.endswith(':free') for m in self.settings.models):
                        raise error from None
                    if error.category in {"server", "network", "timeout"} and attempt == 0:
                        await asyncio.sleep(0.5 + random.random())
                        continue
                    break
            if index + 1 < len(self.settings.models):
                log.warning("ai_fallback from=%s to=%s reason=%s", model, self.settings.models[index + 1], error.category)
        raise error

    async def diagnostics(self):
        if not self.settings.api_key:return {'status':'UNKNOWN','reason':'ai_not_configured','method':'tanpa request API'}
        if self.diagnostic_cache and time.monotonic() - self.diagnostic_cache[0] < 600:
            return self.diagnostic_cache[1]
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(self.settings.api_base + "/key", headers={"Authorization": "Bearer " + self.settings.api_key})
                result = {"http": response.status_code, "status": "UP" if response.status_code == 200 else "DOWN", "method": "GET /key (tanpa completion)", "at": time.time()}
        except httpx.HTTPError as exc:
            result = {"status": "UNKNOWN", "error": type(exc).__name__, "at": time.time()}
        self.diagnostic_cache = (time.monotonic(), result)
        return result

    async def close(self):
        if self.sdk is not None:await self.sdk.close()
