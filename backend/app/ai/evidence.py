"""Facts and completeness notices rendered independently from model prose."""
import json
import re
from app.monitoring.mikrotik_catalog import SECTIONS, ERROR_HINTS

FULL=re.compile(r'\b(semua|seluruh|lengkap|rinci|detail|daftar)\b',re.I)
FOLLOWUP=re.compile(r'\b(lanjut\w*|tadi|tersebut|itu|yang\s+down|yang\s+bermasalah|ramnya|cpunya|trafiknya|detailnya)\b',re.I)

def full_requested(question):return bool(FULL.search(question))

def rows(value):
    if isinstance(value.get('results'),list):
        return value['results']
    if isinstance(value.get('current'),dict):
        return [value['current']]
    return [value]

def code(value):
    raw='belum tersedia' if value is None else str(value)
    return '`'+raw.replace('`','ˋ').replace('\r',' ').replace('\n',' ')+'`'

def unavailable(evidence):
    notes=[]
    for entry in evidence:
        for value in rows(entry['result']):
            target=value.get('target',entry['arguments'].get('section','tool'))
            section=value.get('section')
            label=('MikroTik '+section) if section else target
            if value.get('status')=='UNKNOWN':
                error=value.get('error','unknown')
                hint=value.get('detail') or ERROR_HINTS.get(error)
                if error=='missing_readonly_token':
                    label='Proxmox VM/LXC'
                    hint='Belum disiapkan: token API read-only belum tersedia. Data node/VM/LXC tidak dapat ditampilkan.'
                notes.append(f'• {code(label)}: {hint or code(error)}')
            for path,error in value.get('errors',{}).items():
                notes.append(f'• {code(path)}: {ERROR_HINTS.get(error,code(error))}')
    return list(dict.fromkeys(notes))

def completeness(evidence):
    notes=[]
    latest={}
    for entry in evidence:
        if entry['result'].get('summary_only'):
            notes.append('• Ringkasan mencakup seluruh target yang diperiksa, dengan detail field/baris dibatasi. Gunakan pemeriksaan perangkat tertentu untuk data rinci.')
        for value in rows(entry['result']):
            if not value.get('resources'):continue
            key=(entry['tool'],value.get('target'),value.get('section'),json.dumps({k:v for k,v in entry['arguments'].items() if k not in {'offset','limit'}},sort_keys=True))
            previous=latest.get(key)
            if previous:
                highest=max(m.get('offset',0) for m in previous['result']['resources'].values())
                if highest>max(m.get('offset',0) for m in value['resources'].values()):continue
            latest[key]={**entry,'result':value}
    for entry in latest.values():
        value=entry['result'];args=entry['arguments']
        for path,meta in value.get('resources',{}).items():
            label=code(value.get('section',path))
            if meta.get('has_more'):
                offset=meta.get('next_offset')
                if offset is not None:
                    query=f"/mikrotik {args.get('section',value.get('section'))} {offset}"
                    if args.get('filter_field'):
                        query+=' '+args['filter_field']+'='+json.dumps(args['filter_value'],ensure_ascii=False)
                    extra=' atau tulis “lanjutkan”' if entry['tool']=='get_mikrotik_data' else ''
                    notes.append(f'• {label}: daftar belum lengkap. Lanjutkan dengan {code(query)}{extra}.')
                else:
                    notes.append(f'• {label}: batas pembacaan tercapai. Gunakan filter lebih spesifik; daftar belum lengkap.')
            if meta.get('scan_truncated'):notes.append(f'• {label}: batas 500 baris tercapai; total sebenarnya belum diketahui.')
            if meta.get('fields_truncated'):notes.append(f'• {label}: sebagian nilai panjang dipotong; data bukan salinan konfigurasi lengkap.')
    return list(dict.fromkeys(notes))

def field_lines(value,depth=0):
    lines=[]
    for key,item in value.items():
        indent='  '*min(depth,3)
        if isinstance(item,dict):
            lines.append(f'{indent}• {key}:')
            lines.extend(field_lines(item,depth+1))
        elif isinstance(item,list):
            lines.append(f'{indent}• {key}: {len(item)} item')
            for child in item:
                if isinstance(child,dict):
                    lines.extend(field_lines(child,depth+1))
                else:lines.append(f'{indent}  • {code(child)}')
        else:lines.append(f'{indent}• {key}: {code(item)}')
    return lines

def detailed(evidence):
    blocks=[]
    for entry in evidence:
        args=entry['arguments']
        for value in rows(entry['result']):
            if value.get('status') not in {'UP','DEGRADED','DOWN'}:continue
            section=value.get('section')
            if section in SECTIONS and isinstance(value.get('data'),dict):
                lines=[f"**Data MikroTik · {section}**",f"Diperiksa: {code(value.get('timestamp'))}"]
                for path,items in value['data'].items():
                    meta=value.get('resources',{}).get(path,{})
                    lines += ['',code(path),f"Ditampilkan {len(items)} baris; total {code(meta.get('total'))}."]
                    if not items:lines.append('Tidak ada baris yang cocok pada halaman ini.')
                    for index,item in enumerate(items,1+meta.get('offset',0)):
                        lines.append(f'\n**Baris {index}**')
                        lines.extend(f'• {key}: {code(val)}' for key,val in item.items())
                blocks.append('\n'.join(lines))
            elif value.get('target')=='docker' and isinstance(value.get('containers'),list):
                lines=['**Daftar container dari collector**',f"Diperiksa: {code(value.get('timestamp'))}"]
                for item in value['containers']:
                    lines+=['',f"**{code(item.get('name'))}**"]
                    lines.extend(field_lines({key:val for key,val in item.items() if key!='name'}))
                blocks.append('\n'.join(lines))
            elif value.get('target')=='proxmox_resources' and value.get('guests') is not None:
                lines=['**Data Proxmox yang tersedia**']
                for group in ('nodes','guests','storage','tasks'):
                    lines+=['',f'**{group}**']
                    for item in value.get(group,[]):
                        lines.append('• '+'; '.join(f'{key}: {code(val)}' for key,val in item.items()))
                blocks.append('\n'.join(lines))
            elif value.get('target')=='debian':
                lines=['**Data server Debian dari collector**',*field_lines(value)]
                blocks.append('\n'.join(lines))
            elif value.get('target'):
                blocks.append('\n'.join([f"**Data {code(value['target'])}**",*field_lines(value)]))
    return '\n\n'.join(dict.fromkeys(blocks))

def finish(answer,evidence,full=False):
    missing=unavailable(evidence)
    if evidence and not any(value.get('status') in {'UP','DEGRADED','DOWN'} for entry in evidence for value in rows(entry['result'])):
        return 'Data monitoring belum cukup untuk menyimpulkan kondisi aktual.\n\n**Data belum tersedia**\n'+'\n'.join(missing or ['• Pemeriksaan belum menghasilkan bukti aktual.'])+'\n\nTidak ada angka/status perangkat yang dapat dipastikan. Gunakan /diagnostics untuk tindak lanjut.'
    if missing:
        if re.search(r'\b(semua|seluruh)\b[^\n.!?]{0,80}\b(sehat|normal|aman|up)\b',answer,re.I):
            answer='Sebagian pemeriksaan menghasilkan data. Bagian yang belum tersedia dijelaskan terpisah.'
            full=True
        pve_missing=any(value.get('error')=='missing_readonly_token' for entry in evidence for value in rows(entry['result']))
        if pve_missing:
            lines=[]
            for line in answer.splitlines():
                if re.search(r'\b(proxmox|pve|vm|lxc)\b',line,re.I) and not re.search(r'belum|unknown|tidak (?:dapat|bisa)|tidak tersedia',line,re.I):
                    full=True
                    continue
                lines.append(line)
            answer='\n'.join(lines).strip()
    parts=[answer.strip() or 'Berikut hasil pemeriksaan yang tersedia.']
    if full:
        facts=detailed(evidence)
        if facts:parts.append(facts)
    if missing:parts.append('**Data belum tersedia**\n'+'\n'.join(missing))
    pending=completeness(evidence)
    if pending:parts.append('**Batas kelengkapan data**\n'+'\n'.join(pending))
    return '\n\n'.join(filter(None,parts))
