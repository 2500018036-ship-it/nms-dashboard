"""Ephemeral native browser display. This container has no network interface."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time

root = Path('/run/session')
children = []


def launch(args, env=None):
    log = open('/tmp/browser-runtime.log', 'ab')
    child = subprocess.Popen(args, stdout=log, stderr=log, env=env)
    log.close()
    children.append(child)
    return child


def stop(*_):
    for child in reversed(children):
        if child.poll() is None:
            child.terminate()
    raise SystemExit(0)


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
config = json.loads((root / 'start.json').read_text())
for name in ('profile', 'downloads', 'uploads'):
    (root / name).mkdir(mode=0o700, exist_ok=True)
profile = root / 'profile'
(profile / 'Default').mkdir(exist_ok=True)
(profile / 'Default/Preferences').write_text(json.dumps({'download': {'default_directory': str(root / 'downloads'),
    'prompt_for_download': False}, 'credentials_enable_service': False, 'profile': {'password_manager_enabled': False},
    'browser': {'check_default_browser': False}}))
for _ in range(100):
    if (root / 'egress.sock').is_socket():
        break
    time.sleep(0.1)
else:
    raise SystemExit('egress_not_ready')
environment = {**os.environ, 'DISPLAY': ':99', 'HOME': '/tmp/home', 'XDG_RUNTIME_DIR': '/tmp/runtime'}
Path('/tmp/home').mkdir(mode=0o700)
Path('/tmp/runtime').mkdir(mode=0o700)
launch(['Xvfb', ':99', '-screen', '0', '1366x768x24', '-nolisten', 'tcp'], environment)
time.sleep(0.5)
launch(['openbox', '--config-file', '/opt/access/openbox.xml'], environment)
launch(['socat', 'TCP-LISTEN:3128,bind=127.0.0.1,reuseaddr,fork', 'UNIX-CONNECT:/run/session/egress.sock'], environment)
launch(['x11vnc', '-display', ':99', '-localhost', '-rfbport', '5900', '-forever', '-shared', '-nopw', '-quiet', '-noxdamage'], environment)
launch(['socat', 'UNIX-LISTEN:/run/session/vnc.sock,fork,mode=0600', 'TCP:127.0.0.1:5900'], environment)
arguments = ['chromium', '--user-data-dir=' + str(profile), '--no-first-run', '--no-default-browser-check',
    '--disable-background-networking', '--disable-component-update', '--disable-sync', '--disable-quic',
    '--disable-features=Translate,MediaRouter', '--force-webrtc-ip-handling-policy=disable_non_proxied_udp',
    '--proxy-server=http://127.0.0.1:3128', '--proxy-bypass-list=<-loopback>',
    '--disable-dev-shm-usage', '--disable-setuid-sandbox', '--password-store=basic',
    '--window-size=1366,768', '--start-maximized', '--app=' + config['url']]
if config.get('tls_spki'):
    arguments.append('--ignore-certificate-errors-spki-list=' + ','.join(config['tls_spki']))
browser = launch(arguments, environment)
time.sleep(1)
if browser.poll() is not None:
    (root / 'state.json').write_text('{"state":"failed","error":"browser_start_failed"}')
    stop()
(root / 'state.json').write_text('{"state":"ready"}')
while browser.poll() is None and all(child.poll() is None for child in children):
    time.sleep(1)
(root / 'state.json').write_text('{"state":"failed","error":"browser_runtime_stopped"}')
stop()
