import asyncio
import json
import logging
import os
from pathlib import Path
import time

from telegram.ext import Application,CommandHandler,MessageHandler,filters
from telegram.request import HTTPXRequest
from app import __version__
from app.config import Settings
from app.logging_config import configure
from app.ai.client import AIClient
from app.ai.agent import Agent
from app.ai.tool_registry import Registry
from app.storage.database import Database
from app.services.health import Monitoring
from app.services.scheduler import Scheduler
from app.telegram.handlers import Handlers

def healthcheck():
    try:
        settings=Settings.load()
        from app.dashboard.platform import Platform
        Platform(settings.data_dir,settings).apply(settings,mark=False)
        value=json.loads((Path(settings.data_dir)/'health.json').read_text())
        return (time.time()-value['at']<45 and time.time()-value['last_cycle']<settings.poll_interval+90
            and time.time()-value.get('notifier_at',0)<75
            and (not settings.continuous_enabled or time.time()-value.get('network_at',0)<settings.network_interval+90)
            and not value['scheduler_error'] and value.get('poller_ready',False))
    except (OSError,ValueError,KeyError):
        return False

def build(settings=None):
    settings=settings or Settings.load()
    # A replacement container must establish its own readiness; an old heartbeat
    # in the persistent data volume cannot make the new process healthy.
    (Path(settings.data_dir)/'health.json').unlink(missing_ok=True)
    database=Database(settings.data_dir)
    monitor=Monitoring(settings,database)
    monitor.platform.sync_inventory()
    registry=Registry(); monitor.register(registry)
    client=AIClient(settings)
    agent=Agent(client,registry,capabilities=monitor.capabilities)
    handlers=Handlers(settings,client,agent,monitor,database)
    async def started(app):
        # PTB 22.5 sets Bot._initialized before getMe; a timed-out bootstrap retry can
        # otherwise skip identity loading. Verify it explicitly before creating tasks.
        await app.bot.get_me(read_timeout=30,connect_timeout=10)
        from app.storage.application_logs import LogSink
        sink=LogSink(settings.data_dir);logging.getLogger().addHandler(sink);app.bot_data['log_sink']=sink
        scheduler=Scheduler(settings,database,monitor,app.bot)
        scheduler.readiness=lambda:app.running and app.updater.running
        app.bot_data['tasks']=[asyncio.create_task(scheduler.run(),name='monitor-scheduler'),asyncio.create_task(scheduler.heartbeat(),name='heartbeat'),
            asyncio.create_task(scheduler.inventory_polling(),name='inventory-polling'),
            asyncio.create_task(scheduler.device_backups(),name='device-config-backups'),
            asyncio.create_task(scheduler.notifier(),name='notification-worker')]
        if settings.continuous_enabled:
            from app.services.network import NetworkService
            network=NetworkService(settings,database,monitor,scheduler)
            app.bot_data['network']=network
            app.bot_data['tasks'].append(asyncio.create_task(network.run(),name='continuous-network'))
        if settings.dashboard:
            from app.dashboard.server import Dashboard
            dashboard=Dashboard(settings,monitor=monitor,agent=agent,loop=asyncio.get_running_loop())
            dashboard.start()
            app.bot_data['dashboard']=dashboard
        logging.info('nms_started version=%s models=%s targets=%s',__version__,settings.models,len(settings.targets))
    async def stopped(app):
        network=app.bot_data.pop('network',None)
        if network:network.stop()
        dashboard=app.bot_data.pop('dashboard',None)
        if dashboard:
            await asyncio.to_thread(dashboard.stop)
        tasks=app.bot_data.pop('tasks',[])
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        sink=app.bot_data.pop('log_sink',None)
        if sink:
            logging.getLogger().removeHandler(sink);await asyncio.to_thread(sink.close)
    async def shutdown(app):
        await stopped(app)
        await client.close(); database.close()
    request=HTTPXRequest(connection_pool_size=12,read_timeout=30,write_timeout=30,connect_timeout=10,pool_timeout=10)
    polling=HTTPXRequest(connection_pool_size=1,read_timeout=40,write_timeout=30,connect_timeout=10,pool_timeout=10)
    app=Application.builder().token(settings.telegram_token).request(request).get_updates_request(polling).concurrent_updates(4).post_init(started).post_stop(stopped).post_shutdown(shutdown).build()
    for command,handler in [('start',handlers.start),('help',handlers.start),('status',handlers.status),('ask',handlers.ask),('diagnostics',handlers.diagnostics),('history',handlers.history),('mikrotik',handlers.mikrotik),('reset',handlers.reset),('events',handlers.events),('alerts',handlers.alerts),('devices',handlers.devices)]:
        app.add_handler(CommandHandler(command,handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handlers.chat))
    app.add_error_handler(handlers.error)
    app.bot_data.update(monitor=monitor,client=client,agent=agent,handlers=handlers)
    return app

def main():
    configure()
    settings=Settings.load()
    # The persistent data volume enforces one scheduler/poller for this deployment.
    import fcntl
    Path(settings.data_dir).mkdir(parents=True,exist_ok=True)
    lock=open(Path(settings.data_dir)/'instance.lock','w')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    os.environ.setdefault('TZ','Asia/Jakarta')
    if hasattr(time,'tzset'):time.tzset()
    try:
        build(settings).run_polling(timeout=25,bootstrap_retries=3,drop_pending_updates=False)
    except Exception:
        logging.exception('application_start_or_run_failed')
        raise SystemExit(1) from None

if __name__=='__main__':main()
