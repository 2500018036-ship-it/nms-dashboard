"""Monitoring lifetime is independent from optional Telegram connectivity."""
import asyncio
import logging
from pathlib import Path
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from app.ai.agent import Agent
from app.ai.client import AIClient
from app.ai.tool_registry import Registry
from app.dashboard.server import Dashboard
from app.logging_config import configure
from app.services.health import Monitoring
from app.services.scheduler import Scheduler
from app.storage.database import Database
from app.telegram.control import TelegramControl
from app.telegram.handlers import Handlers

log=logging.getLogger(__name__)


class TelegramBridge:
    def __init__(self,control,handlers):self.control,self.handlers,self.application=control,handlers,None

    async def send_message(self,**kwargs):
        if not self.application:raise RuntimeError('telegram_unavailable')
        recipients=self.control.recipients()
        if not recipients:raise RuntimeError('telegram_no_recipient')
        # The outbox marks partial/uncertain delivery without blindly repeating it.
        result=None
        for identity in recipients:result=await self.application.bot.send_message(**{**kwargs,'chat_id':identity})
        return result

    async def run(self):
        while True:
            app=None
            try:
                config=self.control.public()
                if not config['enabled'] or not config['token_configured']:
                    self.control.status('disabled');await asyncio.sleep(10);continue
                app=Application.builder().token(self.control.token()).concurrent_updates(4).build()
                for command in ('start','help','status','ask','diagnostics','history','mikrotik','reset','events','alerts','devices'):
                    app.add_handler(CommandHandler(command,getattr(self.handlers,'start' if command=='help' else command)))
                app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,self.handlers.chat));app.add_error_handler(self.handlers.error)
                await app.initialize();await app.start();await app.updater.start_polling(drop_pending_updates=False)
                self.application=app
                self.control.status('connected',username=app.bot.username)
                while self.control.public()['revision']==config['revision']:await asyncio.sleep(5)
            except asyncio.CancelledError:raise
            except Exception as exc:
                self.control.status('failed',error='telegram_connection_failed')
                log.warning('telegram_transport_failed category=%s',type(exc).__name__)
                await asyncio.sleep(15)
            finally:
                self.application=None
                if app:
                    if app.updater and app.updater.running:await app.updater.stop()
                    if app.running:await app.stop()
                    await app.shutdown()


async def run(settings):
    (Path(settings.data_dir)/'health.json').unlink(missing_ok=True)
    database=Database(settings.data_dir);monitor=Monitoring(settings,database);monitor.platform.sync_inventory()
    if monitor.platform.inventory_authoritative():
        settings.continuous_enabled=False;settings.targets={};settings.switch={};monitor.extra_targets=[]
    registry=Registry();monitor.register(registry);client=AIClient(settings)
    agent=Agent(client,registry,capabilities=monitor.capabilities)
    handlers=Handlers(settings,client,agent,monitor,database)
    control=TelegramControl(monitor.platform,settings);bridge=TelegramBridge(control,handlers)
    scheduler=Scheduler(settings,database,monitor,bridge);tasks=[];dashboard=None
    from app.storage.application_logs import LogSink
    sink=LogSink(settings.data_dir);logging.getLogger().addHandler(sink)
    try:
        loop=asyncio.get_running_loop()
        tasks=[asyncio.create_task(fn(),name=name) for name,fn in (
            ('monitor-scheduler',scheduler.run),('heartbeat',scheduler.heartbeat),
            ('inventory-polling',scheduler.inventory_polling),('device-config-backups',scheduler.device_backups),
            ('notification-worker',scheduler.notifier),('telegram-transport',bridge.run),('portal-verification',scheduler.portal_polling))]
        scheduler.readiness=lambda:all(not t.done() for t in tasks if t.get_name()!='telegram-transport')
        if settings.continuous_enabled:
            from app.services.network import NetworkService
            network=NetworkService(settings,database,monitor,scheduler)
            tasks.append(asyncio.create_task(network.run(),name='continuous-network'))
        if settings.dashboard:
            dashboard=Dashboard(settings,monitor=monitor,agent=agent,loop=loop);dashboard.start()
        log.info('nms_runtime_started dashboard=%s telegram_optional=true',bool(dashboard))
        await asyncio.gather(*tasks)
    finally:
        if dashboard:await asyncio.to_thread(dashboard.stop)
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        await client.close();logging.getLogger().removeHandler(sink);await asyncio.to_thread(sink.close);database.close()
