import asyncio
from datetime import datetime,timezone
import logging
import re
import time
from app.monitoring.common import result
from app.monitoring.interface_events import InterfaceEvents

log=logging.getLogger(__name__)

class NetworkService:
    def __init__(self,settings,database,monitor,scheduler):
        self.settings,self.database,self.monitor,self.scheduler=settings,database,monitor,scheduler
        self.events=scheduler.network_events
        self.queue=asyncio.Queue(maxsize=128);self.rows={};self.last_saved=0;self.dropped=0
        self.watcher=None;self.loop=None;self.native_times={}

    def enqueue(self,row,observed_at):
        def put():
            try:self.queue.put_nowait((row,observed_at))
            except asyncio.QueueFull:self.dropped+=1
        if self.loop and not self.loop.is_closed():self.loop.call_soon_threadsafe(put)

    def stop(self):
        if self.watcher:self.watcher.stop()

    def _cache(self,value,save=True):
        self.monitor.cache[value['target']]=(time.monotonic(),value)
        if save:self.database.save(value)

    def switch_links(self,now):
        uplinks=self.settings.switch.get('uplinks',[])
        if not uplinks or any(name not in self.rows for name in uplinks):return
        states={name:self.rows[name].get('running') for name in uplinks}
        if any(v not in {'true','false'} for v in states.values()):return
        running=sum(v=='true' for v in states.values())
        status='UP' if running==len(states) else ('DOWN' if running==0 else 'DEGRADED')
        self.events.change('network:cisco:uplinks',status,{'uplinks':states,
            'scope':'Status sisi MikroTik; tidak membuktikan status 24 port internal atau daya switch.'},
            'Uplink Cisco '+status,self.settings.switch.get('name','Cisco'),now=now,bad=status!='UP',
            severity='CRITICAL' if status=='DOWN' else 'WARNING')

    async def poll_once(self):
        observed=time.time()
        value=await self.monitor.router.collect('interfaces',fresh=True)
        value['target']='mikrotik_interfaces'
        if value['status']=='UP':
            rows=value.get('data',{}).get('/interface',[])
            for row in rows:
                old=self.rows.get(row.get('name'),{})
                if self.native_times.get(row.get('name'),0)>observed:
                    for field in ('running','disabled'):
                        if field in old:row[field]=old[field]
            self.rows={row['name']:row for row in rows if row.get('name')}
            rates=self.events.interfaces(rows,time.time(),link_observed_at=observed)
            traffic=result('network_traffic','delta counter byte / selang aktual','UP' if any(r['rx_bps'] is not None for r in rates) else 'UNKNOWN',
                interfaces=rates,scope='Bit/detik dari dua polling; counter reset/gap belum memiliki nilai valid.')
            old_traffic=self.monitor.cache.get('network_traffic',(0,{}))[1]
            self._cache(traffic,save=time.time()-self.last_saved>=60 or old_traffic.get('status')!=traffic['status'])
            self.switch_links(observed)
            if self.settings.interface_events and self.watcher is None:
                self.watcher=InterfaceEvents(self.settings,self.enqueue);self.watcher.start()
        else:
            self.events.missing_sample()
            traffic=result('network_traffic','delta counter',error='interface_sample_unavailable',detail='Sampel interface gagal; tidak menganggap trafik nol.')
            old=self.monitor.cache.get('network_traffic',(0,{}))[1]
            self._cache(traffic,save=old.get('status')!='UNKNOWN')
        save=time.time()-self.last_saved>=60
        self._cache(value,save)
        if save:self.last_saved=time.time()
        self.scheduler.network_at=time.time()
        self.database.metadata('network_runtime',__import__('json').dumps({'poll_at':time.time(),
            'status':value['status'],'interval':self.settings.network_interval,
            'stream':self.watcher.state if self.watcher else {'connected':False,'mode':'disabled'},'dropped_events':self.dropped}))

    async def event_once(self,row,now):
        name=row.get('name') or next((n for n,r in self.rows.items() if r.get('id')==row.get('id') and row.get('id')),None)
        if not name or name not in self.rows:return
        physical=name in self.settings.mikrotik_interfaces if self.settings.mikrotik_interfaces else bool(re.fullmatch(r'ether\d+',name))
        if not physical:return
        merged={**self.rows[name],**row,'name':name}
        self.rows[name]=merged
        if 'running' in row or 'disabled' in row:
            self.native_times[name]=now
            self.events.link(merged,now,'RouterOS /interface/listen')
            cached=self.monitor.cache.get('mikrotik_interfaces')
            if cached:
                cached[1]['data']['/interface']=[self.rows.get(r['name'],r) for r in cached[1]['data']['/interface']]
                cached[1]['timestamp']=datetime.fromtimestamp(now,timezone.utc).isoformat()
            self.switch_links(now)

    async def _poll(self):
        while True:
            started=time.monotonic()
            try:await self.poll_once()
            except asyncio.CancelledError:raise
            except Exception:log.exception('network_poll_failed')
            await asyncio.sleep(max(1,self.settings.network_interval-(time.monotonic()-started)))

    async def _events(self):
        while True:
            row,observed=await self.queue.get()
            try:await self.event_once(row,observed)
            except Exception:log.exception('network_event_failed')
            finally:self.queue.task_done()

    async def _details(self):
        while True:
            for target in ('mikrotik_routes','wireguard','cisco_sf200'):
                try:
                    value=await self.monitor.check(target)
                    if target=='mikrotik_routes':self.events.routes(value)
                    if target=='wireguard':self.events.wireguard(value)
                except asyncio.CancelledError:raise
                except Exception:log.exception('network_detail_failed target=%s',target)
            await asyncio.sleep(60)

    async def run(self):
        self.loop=asyncio.get_running_loop()
        try:
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(self._poll());tasks.create_task(self._events());tasks.create_task(self._details())
        finally:self.stop()
