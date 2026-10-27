import asyncio
import json
import logging
import time
from dataclasses import dataclass

from jsonschema import Draft202012Validator, ValidationError
from app.logging_config import redact

log = logging.getLogger(__name__)

@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    handler: object
    timeout: int = 25

class Registry:
    def __init__(self):
        self.tools = {}
        self.semaphore = asyncio.Semaphore(3)

    def add(self, tool):
        if tool.name in self.tools:
            raise ValueError("duplicate tool")
        Draft202012Validator.check_schema(tool.schema)
        self.tools[tool.name] = tool

    def definitions(self):
        return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.schema}} for t in self.tools.values()]

    async def execute(self, name, raw):
        start = time.monotonic()
        if name not in self.tools:
            return {"status": "UNKNOWN", "error": "unknown_tool"}
        tool = self.tools[name]
        try:
            if len(raw) > 2000:
                raise ValueError("arguments too large")
            arguments = json.loads(raw)
            Draft202012Validator(tool.schema).validate(arguments)
            async with self.semaphore:
                result = await asyncio.wait_for(tool.handler(**arguments), tool.timeout)
            def clean(value):
                if isinstance(value,str):return redact(value)
                if isinstance(value,dict):return {k:clean(v) for k,v in value.items()}
                if isinstance(value,list):return [clean(v) for v in value]
                return value
            result=clean(result)
            encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
            if len(encoded) > 22000:
                return {"status": "UNKNOWN", "error": "result_too_large", "hint": "Pilih pemeriksaan lebih spesifik"}
            log.info("tool_completed tool=%s duration_ms=%s", name, round((time.monotonic() - start) * 1000))
            return result
        except (ValueError, TypeError, ValidationError):
            log.warning("tool_rejected tool=%s category=arguments", name)
            return {"status": "UNKNOWN", "error": "invalid_arguments"}
        except asyncio.TimeoutError:
            log.warning("tool_failed tool=%s category=timeout", name)
            return {"status": "UNKNOWN", "error": "timeout"}
        except Exception as exc:
            log.warning("tool_failed tool=%s category=%s", name, type(exc).__name__)
            return {"status": "UNKNOWN", "error": "collector_failed"}
