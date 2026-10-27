import json
import time
from pathlib import Path
from app.monitoring.common import result

def read_snapshot(directory, section):
    path = Path(directory)/'snapshot.json'
    try:
        if path.stat().st_size > 512000:
            raise ValueError('oversized')
        data = json.loads(path.read_text())
        age = time.time()-data['collected_at']
        if age < -30 or age > 180:
            return result(section,'host snapshot',error='stale_snapshot',age_seconds=round(age))
        if section == 'docker':
            return result('docker','restricted host collector',data['docker']['status'],age_seconds=round(age),**{k:v for k,v in data['docker'].items() if k!='status'})
        return result('debian','host /proc snapshot','UP',age_seconds=round(age),**data['host'])
    except (OSError, ValueError, KeyError, TypeError):
        return result(section,'host snapshot',error='snapshot_unavailable')
