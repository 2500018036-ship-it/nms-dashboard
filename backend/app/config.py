import json
import os
import ipaddress
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_TARGETS = {
    "mikrotik": {"name": "MikroTik Winbox", "host": "192.168.20.1", "port": 8291, "kind": "tcp"},
    "technitium_dns": {"name": "Technitium DNS", "host": "192.168.20.199", "port": 53, "kind": "dns", "query": "example.com"},
    "proxmox": {"name": "Proxmox HTTPS", "url": "https://192.168.20.200:8006/", "kind": "web"},
    "debian_ssh": {"name": "Debian SSH", "host": "192.168.20.195", "port": 22, "kind": "tcp"},
    "web_http": {"name": "Web HTTP", "url": "http://192.168.20.195/", "kind": "web"},
    "web_https": {"name": "Web HTTPS virtual host", "url": "https://azrilachdi.web.id/", "kind": "web"},
    "cloud_storage": {"name": "Cloud storage HTTPS", "url": "https://cloud.azrilachdi.web.id/", "kind": "web"},
    "portfolio": {"name": "Portfolio HTTPS", "url": "https://azrilachdi.web.id/", "kind": "web"},
}

def flag(name, default=False):
    value = os.getenv(name, str(default)).lower()
    if value not in {"true", "false", "1", "0"}:
        raise ValueError(f"{name}: gunakan true/false")
    return value in {"true", "1"}

def number(name, default, low, high):
    result = int(os.getenv(name, str(default)))
    if not low <= result <= high:
        raise ValueError(f"{name}: harus {low}..{high}")
    return result

@dataclass
class Settings:
    telegram_token: str = field(repr=False)
    allowed_ids: frozenset[int]
    api_key: str = field(repr=False)
    models: tuple[str, ...]
    api_base: str = "https://openrouter.ai/api/v1"
    data_dir: str = "/data"
    snapshot_dir: str = "/collector"
    poll_interval: int = 180
    retention_days: int = 30
    alerts: bool = False
    alert_chat_id: int = 0
    daily_summary: bool = False
    targets: dict = field(default_factory=lambda: dict(DEFAULT_TARGETS))
    mikrotik_readonly: bool = False
    mikrotik_interfaces: tuple[str, ...] = ()
    expected_guests: tuple[str, ...] = ()
    cpu_threshold: int = 90
    memory_threshold: int = 90
    storage_threshold: int = 90
    cooldown: int = 600
    dashboard: bool = False
    dashboard_password: str = field(default="", repr=False)
    docker_ignored_containers: tuple[str, ...] = ()
    continuous_enabled: bool = False
    network_interval: int = 15
    traffic_warmup: int = 5
    traffic_min_bps: int = 100000
    traffic_spike_min_bps: int = 1000000
    traffic_spike_factor: int = 2
    traffic_drop_factor: float = .1
    wireguard_stale: int = 180
    interface_events: bool = True
    switch: dict = field(default_factory=dict)
    traffic_spike_seconds: int = 60
    bandwidth_warning: int = 85
    bandwidth_critical: int = 95
    bandwidth_seconds: int = 30
    bandwidth_hysteresis: int = 5
    traffic_baseline_alerts: bool = False
    traffic_zero_seconds: int = 300
    traffic_resume_seconds: int = 60

    @classmethod
    def load(cls):
        ids = frozenset(int(v.strip()) for v in os.getenv("ALLOWED_TELEGRAM_IDS", os.getenv("ALLOWED_TELEGRAM_ID", "")).split(",") if v.strip())
        token, key = os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("OPENROUTER_API_KEY", "")
        if not ids or any(i <= 0 for i in ids) or not token:
            raise ValueError("Token Telegram dan allowlist user wajib diisi; AI key opsional untuk monitoring tanpa AI")
        models = tuple(dict.fromkeys(v.strip() for v in (os.getenv("OPENROUTER_MODEL", "openrouter/free") + "," + os.getenv("OPENROUTER_FALLBACK_MODELS", "")).split(",") if v.strip()))
        if len(models) > 3:
            raise ValueError("Maksimal tiga model yang dikonfigurasi eksplisit")
        base = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
        if urlsplit(base).scheme != "https" or urlsplit(base).username:
            raise ValueError("OPENROUTER_BASE_URL wajib HTTPS tanpa kredensial URL")
        targets = json.loads(Path(os.getenv("TARGETS_FILE", "/app/targets.json")).read_text()) if Path(os.getenv("TARGETS_FILE", "/app/targets.json")).is_file() else dict(DEFAULT_TARGETS)
        if not isinstance(targets, dict) or len(targets) > 30:
            raise ValueError("Allowlist target tidak valid")
        for name, t in targets.items():
            if not isinstance(name, str) or t.get("kind") not in {"dns", "tcp", "web"}:
                raise ValueError("Jenis target tidak valid")
            if t["kind"] == "web":
                u = urlsplit(t["url"])
                if u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password or u.fragment:
                    raise ValueError("URL target tidak valid")
            elif not t.get("host") or not 1 <= int(t.get("port", 0)) <= 65535:
                raise ValueError("Host/port target tidak valid")
        continuous=flag('CONTINUOUS_ENABLED')
        switch={}
        if continuous:
            path=Path(os.getenv('NETWORK_CONFIG_FILE','/app/network.json'))
            if not path.is_file():raise ValueError('NETWORK_CONFIG_FILE belum tersedia')
            network=json.loads(path.read_text())
            if not isinstance(network,dict) or set(network)-{'devices','switch'}:raise ValueError('network.json tidak valid')
            devices=network.get('devices',{})
            if not isinstance(devices,dict) or len(devices)>24:raise ValueError('Maksimal 24 perangkat inventaris')
            for identity,device in devices.items():
                if not re.fullmatch(r'[a-z0-9_]{1,50}',identity) or identity in targets:raise ValueError('ID perangkat tidak valid/duplikat')
                if not isinstance(device,dict) or set(device)-{'name','host','alert_on_unreachable','mac_address','follow_dhcp'}:raise ValueError('Field perangkat tidak valid')
                if type(device.get('alert_on_unreachable',False)) is not bool:raise ValueError('alert_on_unreachable harus boolean')
                address=ipaddress.ip_address(device['host'])
                if address.version!=4 or not any(address in ipaddress.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')):
                    raise ValueError('Inventaris hanya IPv4 privat hasil audit')
                targets[identity]={'name':str(device.get('name',identity))[:80],'host':str(address),'kind':'icmp',
                    'alert_on_unreachable':device.get('alert_on_unreachable',False),
                    'mac_address':str(device.get('mac_address','')).upper(),'follow_dhcp':device.get('follow_dhcp',False)}
                if type(device.get('follow_dhcp',False)) is not bool or device.get('follow_dhcp') and not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}',device.get('mac_address','')):
                    raise ValueError('Identitas DHCP tidak valid')
            switch=network.get('switch',{})
            if not isinstance(switch,dict) or set(switch)-{'name','uplinks','management_host'}:raise ValueError('Konfigurasi switch tidak valid')
            uplinks=switch.get('uplinks',[])
            if not isinstance(uplinks,list) or len(uplinks)>8 or any(not re.fullmatch(r'ether\d+',p) for p in uplinks):raise ValueError('Uplink switch tidak valid')
        dashboard = flag("DASHBOARD_ENABLED")
        dashboard_password = os.getenv("DASHBOARD_PASSWORD", "")
        if dashboard and len(dashboard_password) < 24:
            raise ValueError("Dashboard membutuhkan password minimal 24 karakter")
        chat_id = int(os.getenv("ALERT_CHAT_ID") or str(min(ids)))
        if chat_id not in ids:
            raise ValueError("ALERT_CHAT_ID harus ada dalam allowlist user")
        warning=number('BANDWIDTH_WARNING_PERCENT',85,1,98)
        critical=number('BANDWIDTH_CRITICAL_PERCENT',95,2,100)
        hysteresis=number('BANDWIDTH_HYSTERESIS_PERCENT',5,1,20)
        if warning>=critical or hysteresis>=warning:
            raise ValueError('Ambang bandwidth harus WARNING < CRITICAL; hysteresis lebih kecil daripada WARNING')
        return cls(token, ids, key, models, base,
            os.getenv("DATA_DIR", "/data"), os.getenv("SNAPSHOT_DIR", "/collector"),
            number("MONITOR_INTERVAL", 180, 30, 3600), number("RETENTION_DAYS", 30, 1, 365),
            flag("ALERTS_ENABLED"), chat_id, flag("DAILY_SUMMARY_ENABLED"), targets,
            flag("MIKROTIK_READONLY_CONFIRMED"), tuple(filter(None, os.getenv("MIKROTIK_INTERFACES", "").split(","))),
            tuple(filter(None, os.getenv("PROXMOX_EXPECTED_GUESTS", "").split(","))),
            number("CPU_THRESHOLD", 90, 50, 100), number("MEMORY_THRESHOLD", 90, 50, 100),
            number("STORAGE_THRESHOLD", 90, 50, 100), number("ALERT_COOLDOWN", 600, 300, 86400),
            dashboard, dashboard_password, tuple(filter(None,os.getenv('DOCKER_IGNORED_CONTAINERS','').split(','))),
            continuous,number('NETWORK_INTERVAL',15,10,120),number('TRAFFIC_WARMUP_SAMPLES',5,3,30),
            number('TRAFFIC_MIN_BASELINE_BPS',100000,1000,10000000000),
            number('TRAFFIC_MIN_SPIKE_BPS',1000000,1000,10000000000),number('TRAFFIC_SPIKE_FACTOR',2,2,20),
            number('TRAFFIC_DROP_PERCENT',10,1,50)/100,number('WIREGUARD_STALE_SECONDS',180,120,3600),flag('MIKROTIK_INTERFACE_EVENTS',True),switch,
            number('TRAFFIC_SPIKE_SECONDS',60,30,600),warning,critical,number('BANDWIDTH_SUSTAIN_SECONDS',30,15,600),hysteresis,
            flag('TRAFFIC_BASELINE_ALERTS_ENABLED'),number('TRAFFIC_ZERO_SECONDS',300,60,86400),
            number('TRAFFIC_RESUME_SECONDS',60,15,3600))
