"""Fixed read-only RouterOS subscription; no commands/paths supplied by the AI."""
import logging
import os
import socket
import ssl
import threading
import time
import routeros_api
from app.monitoring.mikrotik import ALLOWED_READONLY_POLICIES,error_category

log=logging.getLogger(__name__)
FIELDS=('.id','name','type','running','disabled','link-downs','last-link-down-time','last-link-up-time')

class InterfaceEvents:
    def __init__(self,settings,callback):
        self.settings,self.callback=settings,callback
        self.stopping=threading.Event();self.pool=None;self.thread=None
        self.state={'connected':False,'mode':'not_started','received':0}

    def disconnect(self):
        pool=self.pool
        if pool:
            try:pool.socket.socket.shutdown(socket.SHUT_RDWR)
            except (OSError,AttributeError):pass
            try:pool.disconnect()
            except Exception:pass

    def start(self):
        if self.thread and self.thread.is_alive():return
        self.thread=threading.Thread(target=self._run,name='routeros-interface-events',daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping.set();self.disconnect()
        if self.thread:self.thread.join(timeout=2)

    def _run(self):
        delay=2
        while not self.stopping.is_set():
            timer=None
            rotating=threading.Event()
            try:
                if not self.settings.mikrotik_readonly:raise PermissionError('readonly_account_required')
                port=int(os.getenv('MIKROTIK_PORT','8729'));tls=port==8729
                if tls and os.getenv('MIKROTIK_SSL_VERIFY','true').lower()!='true':raise PermissionError('tls_verification_required')
                if not tls and os.getenv('MIKROTIK_ALLOW_PLAINTEXT','false').lower()!='true':raise PermissionError('plaintext_not_allowed')
                context=ssl.create_default_context(cafile=os.getenv('MIKROTIK_CA_FILE') or None) if tls else None
                self.pool=routeros_api.RouterOsApiPool(os.getenv('MIKROTIK_HOST','192.168.20.1'),
                    username=os.environ['MIKROTIK_USER'],password=os.environ['MIKROTIK_PASSWORD'],port=port,
                    use_ssl=tls,ssl_verify=True,ssl_verify_hostname=True,ssl_context=context,plaintext_login=True)
                self.pool.socket_timeout=10
                api=self.pool.get_api();self.pool.set_timeout(5)
                users=api.get_resource('/user').call('print',{'.proplist':'name,group'},{'name':os.environ['MIKROTIK_USER']})
                if len(users)!=1:raise PermissionError('cannot_verify_account')
                groups=api.get_resource('/user/group').call('print',{'.proplist':'policy'},{'name':users[0]['group']})
                grants={p for p in groups[0]['policy'].split(',') if p and not p.startswith('!')} if len(groups)==1 else set()
                if not {'read','api'}<=grants or grants-ALLOWED_READONLY_POLICIES and os.getenv('MIKROTIK_MONITOR_ALLOW_ELEVATED','false').lower()!='true':raise PermissionError('policy_rejected')
                # An idle subscription must not reconnect every socket timeout.
                # Rotate after 5 minutes to recheck credentials/permission changes.
                self.pool.set_timeout(None)
                def rotate():
                    rotating.set();self.disconnect()
                timer=threading.Timer(300,rotate);timer.daemon=True;timer.start()
                delay=2
                self.state={**self.state,'connected':True,'mode':'listen','connected_at':time.time(),'error':None}
                log.info('interface_event_stream_connected')
                for row in api.get_resource('/interface').call_async('listen',{'.proplist':','.join(FIELDS)}):
                    if self.stopping.is_set():break
                    clean={('id' if key in {'.id','id'} else key):''.join(c for c in str(value)[:160] if c.isprintable())
                        for key,value in row.items() if key in set(FIELDS)|{'id'} or key=='.dead'}
                    self.state={**self.state,'received':self.state['received']+1,'last_event_at':time.time()}
                    self.callback(clean,time.time())
                    delay=2
                self.state={**self.state,'connected':False,'mode':'polling_fallback'}
            except Exception as exc:
                category=error_category(exc)
                self.state={**self.state,'connected':False,'mode':'revalidating' if rotating.is_set() else 'polling_fallback',
                    'error':None if rotating.is_set() else category}
                if not self.stopping.is_set():
                    if rotating.is_set():log.info('interface_event_stream_revalidating')
                    else:log.warning('interface_event_stream_failed category=%s',category)
                if isinstance(exc,PermissionError) or category in {'permission_denied','authentication_failed','unsupported_section'}:return
            finally:
                if timer:timer.cancel()
                self.disconnect();self.pool=None
            if self.stopping.wait(delay):break
            delay=min(60,delay*2)
        self.state={**self.state,'connected':False,'mode':'stopped'}
