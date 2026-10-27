import json
import logging
import os
import re
from contextvars import ContextVar
from datetime import datetime, timezone

request_id = ContextVar("request_id", default="-")

def redact(text):
    text = str(text)
    for key, value in os.environ.items():
        if any(x in key for x in ("PASSWORD", "TOKEN", "API_KEY", "SECRET")) and len(value) >= 4:
            text = text.replace(value, "[REDACTED]")
    text = re.sub(r"bot\d{6,}:[\w-]+|sk-or-v1-[\w-]+", "[REDACTED]", text)
    return re.sub(r"(?i)(authorization|password|token|secret|api_key)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", text)

class Structured(logging.Formatter):
    def format(self, record):
        result = {"time": datetime.now(timezone.utc).isoformat(), "level": record.levelname,
            "logger": record.name, "request_id": request_id.get(), "event": redact(record.getMessage())}
        if record.exc_info:
            result["trace"] = redact(self.formatException(record.exc_info))
        return json.dumps(result, ensure_ascii=False)

def configure():
    handler = logging.StreamHandler()
    handler.setFormatter(Structured())
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), handlers=[handler], force=True)
    for logger in ("httpx", "httpcore", "openai", "telegram", "routeros_api"):
        logging.getLogger(logger).setLevel(logging.WARNING)
