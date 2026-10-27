import asyncio
import json
import logging
import time
import uuid

from telegram.error import TelegramError, TimedOut, BadRequest
from app import __version__
from app.ai.client import AIError, MESSAGES
from app.ai.context import ContextStore, reference
from app.logging_config import request_id, redact
from app.telegram.formatting import format_messages, status_text
from app.telegram.delivery import send_part
from app.telegram.mikrotik import help_text as mikrotik_help, parse_args as mikrotik_args, render as mikrotik_text

log=logging.getLogger(__name__)
HELP='''AI NMS Homelab
/status — pemeriksaan nyata DNS, HTTP, host, Docker, router/PVE jika akses tersedia
/ask pertanyaan — analisis dengan tool read-only
/diagnostics — versi, collector, provider (GET /key; cache 10 menit)
/history target — dua sampel monitoring terakhir
/mikrotik — pilihan data router dan pembacaan langsung tanpa AI
/events — riwayat kejadian dan recovery tanpa AI
/alerts — gangguan yang masih aktif dan antrean notifikasi
/devices — inventaris perangkat dan hasil pemeriksaan terakhir
/reset — hapus rujukan topik percakapan sementara
/help — bantuan

Contoh: Cek CPU dan RAM MikroTik; Container apa yang bermasalah?; Kenapa DNS saya gagal?; Bandingkan kondisi debian dengan sebelumnya.
Data percakapan tidak disimpan permanen. Perintah infrastruktur tidak tersedia.'''

class Handlers:
    def __init__(self,settings,client,agent,monitor,database):
        self.settings,self.client,self.agent,self.monitor,self.database=settings,client,agent,monitor,database
        self.last_requests={}
        self.contexts=ContextStore()
        self.question_locks={}

    def allowed(self,update):
        user=update.effective_user
        # Restrict to private chats too: avoid leaking monitoring in an authorized user's group.
        return bool(user and user.id in self.settings.allowed_ids and update.effective_chat and update.effective_chat.type=='private')

    async def guard(self,update):
        if not self.allowed(update):
            log.warning('telegram_unauthorized')
            return False
        now=time.monotonic(); user=update.effective_user.id
        if now-self.last_requests.get(user,0)<2:
            return False
        self.last_requests[user]=now
        request_id.set(uuid.uuid4().hex[:12])
        return True

    async def deliver(self,message,text,placeholder=None,*,markdown=True):
        parts=list(format_messages(redact(text),markdown=markdown))
        for index,part in enumerate(parts):
            if index==0 and placeholder:
                try:
                    await send_part(placeholder.edit_text,part)
                    continue
                except BadRequest as exc:
                    if 'not modified' in str(exc).lower():
                        continue
                    log.warning('telegram_edit_failed category=BadRequest fallback=send')
                except TelegramError as exc:
                    log.warning('telegram_edit_failed category=%s fallback=send',type(exc).__name__)
            try:
                await send_part(message.reply_text,part)
            except TelegramError as exc:
                # A timed-out send can have arrived; do not blindly resend and create duplicates.
                log.error('telegram_delivery_failed category=%s part=%s',type(exc).__name__,index)
                return False
        return True

    async def start(self,update,context):
        if await self.guard(update):
            await self.deliver(update.effective_message,HELP)

    async def status(self,update,context):
        if await self.guard(update):
            results=await self.monitor.all()
            await self.deliver(update.effective_message,status_text(results['results']))

    async def diagnostics(self,update,context):
        if not await self.guard(update): return
        status=await self.client.diagnostics()
        checks=[await self.monitor.check(t) for t in ('docker','debian','mikrotik_system','proxmox_resources')]
        import importlib.metadata as md
        payload={'app':__version__,'models':self.settings.models,'provider':status,'last_completion':self.client.last,
            'dependencies':{k:md.version(k) for k in ('openai','python-telegram-bot','RouterOS-api')},
            'collectors':[{k:r[k] for k in ('target','status','error') if k in r} for r in checks],
            'metrics':dict(self.monitor.metrics),'note':'Tidak menjalankan completion AI atau menyimpan percakapan.'}
        payload['network_runtime']=json.loads(self.database.metadata('network_runtime') or '{}')
        payload['notification_delivery']=dict(self.database.db.execute('SELECT status,count(*) FROM notifications GROUP BY status'))
        await self.deliver(update.effective_message,json.dumps(payload,ensure_ascii=False,indent=2),markdown=False)

    async def mikrotik(self,update,context):
        if not await self.guard(update):return
        try:
            query=mikrotik_args(context.args)
        except ValueError:
            await self.deliver(update.effective_message,'Pilihan tidak valid. Gunakan `/mikrotik`, misalnya `/mikrotik traffic name=ether1` atau `/mikrotik dhcp_leases 10`.')
            return
        if query is None:
            await self.deliver(update.effective_message,mikrotik_help())
            return
        value=await self.monitor.router.query(**query)
        self.contexts.set(update.effective_user.id,[reference('get_mikrotik_data',query,value)])
        log.info('mikrotik_command section=%s status=%s',query['section'],value['status'])
        await self.deliver(update.effective_message,mikrotik_text(value,query))

    async def reset(self,update,context):
        if not await self.guard(update):return
        self.contexts.clear(update.effective_user.id)
        await self.deliver(update.effective_message,'Rujukan topik sementara sudah dihapus. Pertanyaan berikutnya dimulai tanpa topik sebelumnya.')

    async def history(self,update,context):
        if not await self.guard(update):return
        target=' '.join(context.args)
        if not target:
            await self.deliver(update.effective_message,self.event_text())
            return
        allowed=set(self.settings.targets)|{'docker','debian','mikrotik_system','mikrotik_interfaces','proxmox_resources'}|set(self.monitor.extra_targets)
        if target not in allowed:
            await self.deliver(update.effective_message,'Gunakan /history '+', '.join(sorted(allowed)))
            return
        values=self.database.history(target,2)
        await self.deliver(update.effective_message,status_text(values) if values else 'Belum ada riwayat untuk target ini.')

    async def events(self,update,context):
        if not await self.guard(update):return
        await self.deliver(update.effective_message,self.event_text())

    def event_text(self):
        from app.alerts.engine import Alerts
        values=self.database.events(8)
        text='\n\n'.join(Alerts.text(v) for v in values if v.get('time')) or 'Belum ada kejadian yang tercatat.'
        queue=dict(self.database.db.execute('SELECT status,count(*) FROM notifications GROUP BY status'))
        if queue:text+='\n\n**Pengiriman notifikasi**\n'+'\n'.join(f'• {key}: {val}' for key,val in queue.items())+'\nuncertain berarti pengiriman belum dapat dipastikan; tidak dikirim ulang otomatis.'
        return text

    async def alerts(self,update,context):
        if not await self.guard(update):return
        from app.alerts.engine import Alerts
        active={k:s for k,s in self.database.states().items() if s.get('active')}
        lines=['**Gangguan aktif**',f'{len(active)} kondisi belum memiliki konfirmasi pemulihan.']
        for key,state in list(sorted(active.items()))[:12]:
            row=self.database.db.execute('SELECT payload FROM events WHERE key=? AND kind=\'ALERT\' ORDER BY id DESC LIMIT 1',(key,)).fetchone()
            if row:lines+=['',Alerts.text(json.loads(row[0]))]
            else:lines+=['',f'• `{key}` — masih aktif; detail kejadian belum tersedia.']
        if len(active)>12:lines+=['',f'Menampilkan 12 dari {len(active)} kondisi; /events untuk riwayat.']
        queue=dict(self.database.db.execute('SELECT status,count(*) FROM notifications GROUP BY status'))
        lines+=['','**Pengiriman**',' • '.join(f'{k}: {v}' for k,v in queue.items()) or 'Belum ada notifikasi.',
            'Data UNKNOWN tidak dianggap pulih. Monitoring dan notifikasi bekerja tanpa AI.']
        await self.deliver(update.effective_message,'\n'.join(lines))

    async def devices(self,update,context):
        if not await self.guard(update):return
        rows=[]
        for target,definition in self.settings.targets.items():
            if definition.get('kind')!='icmp':continue
            latest=self.database.history(target,1)
            value=latest[0] if latest else {'status':'UNKNOWN','method':'ICMP','error':'Belum ada pemeriksaan.'}
            rows.append({**value,'target':target,'display_name':definition['name']+' · '+definition['host'],
                'alert_on_unreachable':definition.get('alert_on_unreachable',False)})
        for target,name in [('mikrotik_system','MikroTik · resource/API'),('docker','Docker · container'),('debian','Debian · resource'),
                ('proxmox_resources','Proxmox · VM/LXC'),('wireguard','WireGuard · handshake'),('cisco_sf200','Cisco SF200-24 · manajemen')]:
            latest=self.database.history(target,1)
            rows.append({**(latest[0] if latest else {'status':'UNKNOWN','method':'Belum ada pemeriksaan.'}),'target':target,'display_name':name})
        await self.deliver(update.effective_message,'**Inventaris dan pemeriksaan terakhir**\n\n'+status_text(rows)+
            '\n\nAlamat inventaris berasal dari audit; IP DHCP dapat berubah. Cisco hanya terlihat dari uplink MikroTik sampai akses manajemen tersedia.')

    async def ask(self,update,context):
        await self.question(update,' '.join(context.args))

    async def chat(self,update,context):
        await self.question(update,update.effective_message.text or '')

    async def question(self,update,question):
        if not await self.guard(update):return
        message=update.effective_message
        if not question.strip() or len(question)>4000:
            await self.deliver(message,'Kirim pertanyaan 1–4000 karakter.')
            return
        placeholder=None
        try:
            placeholder=await message.reply_text('Memeriksa pertanyaan dan data yang diperlukan…',read_timeout=30)
        except TelegramError as exc:
            log.warning('telegram_placeholder_failed category=%s',type(exc).__name__)
        try:
            user=update.effective_user.id
            lock=self.question_locks.setdefault(user,asyncio.Lock())
            if lock.locked():
                await self.deliver(message,'Analisis sebelumnya masih berjalan. Tunggu jawabannya sebelum mengirim pertanyaan lanjutan.',placeholder)
                return
            async with lock:
                context=self.contexts.get(user)
                version=self.contexts.version(user)
                trace=[]
                answer=await self.agent.run(question.strip(),context=context,trace=trace)
                if trace:self.contexts.set(user,trace,expected_version=version)
        except AIError as exc:
            answer=MESSAGES[exc.category]+f'\nID pemeriksaan: {request_id.get()}. /status tetap tersedia tanpa AI.'
        except asyncio.TimeoutError:
            log.warning('ai_request_deadline')
            answer='Analisis melewati batas waktu 150 detik. Gunakan /status untuk hasil langsung.'
        except Exception:
            log.exception('ai_unexpected_failure')
            answer=f'Terjadi error internal. ID: {request_id.get()}. Gunakan /diagnostics.'
        await self.deliver(message,answer,placeholder)

    async def error(self,update,context):
        log.error('telegram_handler_error category=%s',type(context.error).__name__)
