from datetime import datetime, timezone

def result(target, method, status="UNKNOWN", **details):
    return {"target": target, "method": method, "status": status, "timestamp": datetime.now(timezone.utc).isoformat(), **details}
