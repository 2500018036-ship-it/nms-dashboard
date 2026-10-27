"""Guest list facts with deterministic units, independent of model arithmetic."""
import math
import re
from app.ai.evidence import code,finish

def requested(question):
    return bool(re.search(r'\b(vm|lxc|guest)\b',question,re.I) and re.search(r'\b(tampilkan|sebutkan|daftar|list)\b',question,re.I)
        and not re.search(r'\b(kenapa|mengapa|analisis|bandingkan|penyebab|rekomendasi|storage|node|host|disk|jaringan)\b',question,re.I))

def number(value):
    return value if type(value) in (int,float) and math.isfinite(value) and value>=0 else None

def percent(value):
    value=number(value)
    return f'{value*100:.1f}%' if value is not None and value<=1 else 'belum tersedia'

def uptime(value):
    value=number(value)
    if value is None:return 'belum tersedia'
    seconds=int(value)
    return f'{seconds//86400} hari {seconds%86400//3600} jam {seconds%3600//60} menit'

def summary(question,evidence):
    value=evidence[-1]['result']
    if value.get('status') not in {'UP','DEGRADED'} or not isinstance(value.get('guests'),list):return finish('',evidence)
    guests=value['guests']
    stopped=bool(re.search(r'\b(stopped|berhenti|mati|tidak\s+(?:berjalan|aktif))\b',question,re.I))
    running=bool(re.search(r'\b(berjalan|running|aktif)\b',re.sub(r'\btidak\s+(?:berjalan|aktif)\b','',question,flags=re.I),re.I))
    only_running=running and not stopped
    only_stopped=stopped and not running
    guests=[g for g in guests if not only_running or g.get('status')=='running']
    guests=[g for g in guests if not only_stopped or g.get('status')=='stopped']
    label='running' if only_running else 'stopped' if only_stopped else 'semua status'
    lines=['**VM / LXC Proxmox**',f"Waktu pemeriksaan: {code(value.get('timestamp'))}",f'Ditampilkan: {len(guests)} guest ({label}) dalam scope token monitoring.']
    for g in guests:
        lines+=['',f"**{code(g.get('name') or g.get('id'))}**",f"• ID: {code(g.get('id'))} · VMID/CTID: {code(g.get('vmid'))}",
            f"• Node: {code(g.get('node'))} · Jenis: {code(g.get('type'))}",f"• Status: {code(g.get('status'))}",f"• CPU: {percent(g.get('cpu'))}"]
        used,total=number(g.get('mem')),number(g.get('maxmem'))
        memory=f'{used/1024**2:.1f} MiB / {total/1024**2:.1f} MiB ({used/total*100:.1f}%)' if used is not None and total and used<=total else 'belum tersedia'
        lines += [f'• RAM: {memory}',f"• Uptime: {uptime(g.get('uptime'))}"]
    if not guests:lines.append('Tidak ada guest yang cocok pada hasil API saat ini.')
    lines+=['','Status running tidak membuktikan seluruh aplikasi di dalam guest sehat. Filesystem VM belum dikumpulkan.']
    return '\n'.join(lines)
