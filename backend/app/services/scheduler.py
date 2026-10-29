import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time
from telegram.error import TimedOut,RetryAfter

from app import __version__
from app.dashboard.platform import Platform
from app.alerts.engine import Alerts
from app.alerts.outbox import Outbox
from app.alerts.network import NetworkEvents
from app.telegram.formatting import format_messages,status_text
from app.telegram.delivery import send_part
from app.logging_config import redact

log=logging.getLogger(__name__)

class Scheduler:
    def __init__(self,settings,database,monitor,bot):
        self.settings,self.database,self.monitor,self.bot=settings,database,monitor,bot
        self.platform=getattr(monitor,'platform',None) or Platform(str(Path(database.db.execute('PRAGMA database_list').fetchone()[2]).parent),settings)
        self.alerts=Alerts(settings,database)
        self.last_cycle=time.time()
        self.cycle_error=None
        self.readiness=lambda:True
        silent_devices=tuple('network:device:'+identity for identity,target in settings.targets.items()
            if target.get('kind')=='icmp' and not target.get('alert_on_unreachable',False))
        self.outbox=Outbox(database,settings.cooldown,silenced=self.platform.maintenance,
            ignored_prefixes=() if settings.traffic_baseline_alerts else ('network:traffic:',),ignored_keys=silent_devices)
        self.network_events=NetworkEvents(settings,database)
        self.notifier_at=time.time()
        self.network_at=time.time()

    async def heartbeat(self):
        path=Path(self.settings.data_dir)/'health.json'
        while True:
            value={'version':__version__,'at':time.time(),'last_cycle':self.last_cycle,'scheduler_error':self.cycle_error,'poller_ready':self.readiness(),
                'notifier_at':self.notifier_at,'network_at':self.network_at}
            temporary=path.with_suffix('.tmp')
            temporary.write_text(json.dumps(value))
            temporary.replace(path)
            await asyncio.sleep(15)

    async def notify(self,text):
        try:
            for part in format_messages(redact(text)):
                self.notifier_at=time.time()
                await send_part(self.bot.send_message,part,chat_id=self.settings.alert_chat_id)
            return True
        except Exception as exc:
            log.warning('alert_delivery_failed category=%s',type(exc).__name__)
            return False

    async def run(self):
        while True:
            start=time.monotonic()
            try:
                self.platform.apply(self.settings)
                self.outbox.cooldown=self.settings.cooldown
                results=await self.monitor.all()
                self.alerts.evaluate(results['results'])
                self.observe_devices(results['results'])
                day=datetime.now(timezone.utc).astimezone().date().isoformat()
                if self.settings.daily_summary and self.database.metadata('last_summary_day')!=day:
                    if await self.notify('RINGKASAN HARIAN\n'+status_text(results['results'])):
                        self.database.metadata('last_summary_day',day)
                if self.database.metadata('last_cleanup_day')!=day:
                    self.database.cleanup(self.settings.retention_days)
                    with self.platform.db() as db:
                        db.execute('DELETE FROM audit WHERE ts<?',(time.time()-365*86400,))
                        db.execute('DELETE FROM annotations WHERE at<?',(time.time()-365*86400,))
                    self.database.metadata('last_cleanup_day',day)
                self.last_cycle=time.time(); self.cycle_error=None
                log.info('monitor_cycle_completed counts=%s duration=%.2f',results['counts'],time.monotonic()-start)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.cycle_error=type(exc).__name__
                log.exception('scheduler_cycle_failed')
            await asyncio.sleep(max(10,self.settings.poll_interval-(time.monotonic()-start)))

    async def device_backups(self):
        while True:
            try:
                await self.monitor.device_backups.run_due()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error('device_backup_scheduler_failed category=%s',type(exc).__name__)
            await asyncio.sleep(60)

    def observe_devices(self,results):
        for value in results:
            target=self.settings.targets.get(value['target'],{})
            if value['method'].startswith('ICMP') and value['status'] in {'UP','DOWN'} and target.get('alert_on_unreachable',False):
                self.network_events.change('network:device:'+value['target'],value['status'],
                    {'host':value.get('host'),'method':value['method'],'detail':value.get('detail')},
                    'Perangkat '+('merespons' if value['status']=='UP' else 'tidak merespons'),
                    target['name'],bad=value['status']=='DOWN',required=2)

    async def flush_notifications(self):
        self.outbox.stage(self.settings.alerts)
        if not self.settings.alerts:return
        pending=self.outbox.pending()
        if not pending:return
        identities=[identity for identity,event in pending]
        text='\n\n'.join(self.alerts.text(event) for identity,event in pending)
        sent_parts=0
        try:
            for part in format_messages(redact(text)):
                await send_part(self.bot.send_message,part,chat_id=self.settings.alert_chat_id)
                sent_parts+=1
            self.outbox.mark(identities,'sent')
            log.info('notifications_delivered events=%s parts=%s',len(identities),sent_parts)
        except TimedOut:
            self.outbox.mark(identities,'uncertain','telegram_timeout')
            log.warning('notification_delivery_uncertain events=%s; no blind resend',len(identities))
        except RetryAfter as exc:
            wait=exc.retry_after.total_seconds() if hasattr(exc.retry_after,'total_seconds') else exc.retry_after
            self.outbox.mark(identities,'uncertain' if sent_parts else 'retry','telegram_rate_limit',retry_after=wait)
        except Exception as exc:
            self.outbox.mark(identities,'uncertain' if sent_parts else 'retry',type(exc).__name__)
            log.warning('notification_delivery_failed category=%s',type(exc).__name__)

    async def notifier(self):
        while True:
            try:await self.flush_notifications()
            except asyncio.CancelledError:raise
            except Exception:log.exception('notification_worker_failed')
            self.notifier_at=time.time()
            await asyncio.sleep(5)
