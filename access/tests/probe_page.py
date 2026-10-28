"""Read-only native login-page probe, run only in a network-none test worker."""
import json
from pathlib import Path
import re
import subprocess

root=Path('/run/session')
config=json.loads((root/'start.json').read_text())
args=['chromium','--headless','--disable-setuid-sandbox','--no-first-run','--no-default-browser-check',
    '--user-data-dir=/tmp/probe-profile','--disable-background-networking','--disable-component-update',
    '--disable-sync','--disable-quic','--disable-dev-shm-usage',
    '--proxy-server=http://127.0.0.1:3128','--proxy-bypass-list=<-loopback>',
    '--window-size=1366,768','--virtual-time-budget=7000','--screenshot=/run/session/page.png','--dump-dom']
if config.get('tls_spki'):args+=['--ignore-certificate-errors-spki-list='+','.join(config['tls_spki'])]
proxy=subprocess.Popen(['socat','TCP-LISTEN:3128,bind=127.0.0.1,reuseaddr,fork','UNIX-CONNECT:/run/session/egress.sock'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
    result=subprocess.run(args+[config['url']],capture_output=True,timeout=45)
    body=result.stdout.decode(errors='replace')
    title=re.search(r'<title[^>]*>(.*?)</title>',body,re.S|re.I)
    value={'exit':result.returncode,'title':re.sub(r'\s+',' ',title.group(1))[:160] if title else '',
        'dom_bytes':len(result.stdout),'screenshot':(root/'page.png').is_file(),
        'browser_error':bool(re.search(r'chrome-error://|ERR_(?:PROXY|TUNNEL|CERT|CONNECTION|NAME)',body))}
    if result.returncode:value['runtime_diagnostic']=result.stderr.decode(errors='replace')[-1600:]
    (root/'result.json').write_text(json.dumps(value))
finally:proxy.terminate();proxy.wait()
