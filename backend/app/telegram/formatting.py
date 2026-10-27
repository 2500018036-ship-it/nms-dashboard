"""Render untrusted Markdown as a small, escaped subset of Telegram HTML."""
from dataclasses import dataclass
from datetime import datetime,timezone,timedelta
from html import escape, unescape
import re

import mistune


@dataclass(frozen=True)
class Span:
    text: str
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class MessagePart:
    html: str
    plain: str


def chunks(text, limit=3500):
    """Split on paragraph, line or word boundaries; count Telegram UTF-16 units."""
    if limit < 2:
        raise ValueError('limit must allow one non-BMP character')
    start=0
    while start < len(text):
        end=start; units=0
        while end < len(text):
            size=2 if ord(text[end])>65535 else 1
            if units+size>limit:break
            units+=size;end+=1
        if end < len(text):
            window=text[start:end]
            for separator in ('\n\n','\n',' '):
                boundary=window.rfind(separator)
                minimum=len(window)//3 if separator=='\n\n' else len(window)//2
                if boundary >= minimum:
                    end=start+boundary+len(separator)
                    break
        yield text[start:end]
        start=end


def _inline(nodes, tags=()):
    spans=[]
    for node in nodes:
        kind=node['type']
        if kind=='strong':
            spans.extend(_inline(node['children'],tuple(dict.fromkeys((*tags,'b')))))
        elif kind=='emphasis':
            spans.extend(_inline(node['children'],tuple(dict.fromkeys((*tags,'i')))))
        elif kind=='codespan':
            # Telegram forbids nesting code/pre with bold/italic entities.
            spans.append(Span(node['raw'],('code',)))
        elif kind in {'softbreak','linebreak'}:
            spans.append(Span('\n'))
        elif kind in {'link','image'}:
            spans.extend(_inline(node.get('children',[]),tags))
            url=node.get('attrs',{}).get('url','')
            if kind=='link' and url.startswith(('https://','http://')):
                spans.append(Span(' ('+url+')'))
        elif 'children' in node:
            spans.extend(_inline(node['children'],tags))
        else:
            raw=node.get('raw','')
            spans.append(Span(unescape(raw) if kind=='text' else raw,tags))
    return spans


def _plain(spans):
    return ''.join(span.text for span in spans)


def _blocks(nodes, depth=0):
    blocks=[]
    for node in nodes:
        kind=node['type'];children=node.get('children',[])
        if kind in {'blank_line','thematic_break'}:continue
        if kind=='heading':
            blocks.append(_inline(children,('b',)))
        elif kind in {'paragraph','block_text'}:
            blocks.append(_inline(children))
        elif kind=='block_code':
            blocks.append([Span(node.get('raw','').rstrip('\n'),('pre',))])
        elif kind=='table':
            headers=[]
            for section in children:
                if section['type']=='table_head':
                    headers=[_plain(_inline(cell.get('children',[]))) for cell in section['children']]
                elif section['type']=='table_body':
                    for row in section['children']:
                        cells=row['children']
                        if not cells:continue
                        block=[Span(_plain(_inline(cells[0].get('children',[]))),('b',))]
                        for index,cell in enumerate(cells[1:],1):
                            label=headers[index] if index<len(headers) else f'Kolom {index+1}'
                            block.extend([Span('\n• '),Span(label+': ',('b',))])
                            block.extend(_inline(cell.get('children',[])) or [Span('—')])
                        blocks.append(block)
        elif kind=='list':
            block=[];attrs=node.get('attrs',{});start=attrs.get('start',1)
            for index,item in enumerate(children):
                if block:block.append(Span('\n'))
                prefix=f'{start+index}. ' if attrs.get('ordered') else '• '
                block.append(Span('  '*min(depth,3)+prefix))
                for child_index,part in enumerate(_blocks(item.get('children',[]),depth+1)):
                    if child_index:block.append(Span('\n'))
                    block.extend(part)
            blocks.append(block)
        elif kind=='block_quote':
            for block in _blocks(children,depth):blocks.append([Span('› '),*block])
        elif children:
            blocks.extend(_blocks(children,depth))
        elif node.get('raw'):
            # Raw model/device HTML never becomes Telegram markup.
            blocks.append([Span(node['raw'])])
    return [block for block in blocks if _plain(block).strip()]


def format_messages(text, limit=3500, *, markdown=True):
    """Each part has balanced tags, escaped text and a clean plain-text fallback."""
    text=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',str(text)).replace('\r\n','\n').strip()
    if not text:text='Tidak ada isi jawaban.'
    if markdown:
        parser=mistune.create_markdown(renderer='ast',plugins=['table'])
        blocks=_blocks(parser(text))
        spans=[]
        for block in blocks:
            if spans:spans.append(Span('\n\n'))
            spans.extend(block)
    else:
        spans=[Span(text)]
    plain=_plain(spans)
    if not plain.strip():
        spans=[Span('Tidak ada isi jawaban.')];plain=_plain(spans)
    # Split visible text first, then render spans intersecting each part. Tags are
    # reopened at boundaries, so neither tags, entities nor emoji are cut in half.
    span_index=0;span_offset=0
    for part in chunks(plain,limit):
        remaining=len(part);rendered=[]
        while remaining:
            span=spans[span_index]
            take=min(remaining,len(span.text)-span_offset)
            if take:
                raw=span.text[span_offset:span_offset+take]
                encoded=escape(raw,quote=False)
                rendered.append(''.join(f'<{tag}>' for tag in span.tags)+encoded+''.join(f'</{tag}>' for tag in reversed(span.tags)))
                remaining-=take;span_offset+=take
            if span_offset==len(span.text):
                span_index+=1;span_offset=0
        yield MessagePart(''.join(rendered),part)

def status_text(results):
    counts={status:sum(r['status']==status for r in results) for status in ('UP','DEGRADED','DOWN','UNKNOWN')}
    lines=['**Kondisi homelab**',f"{counts['UP']} UP · {counts['DEGRADED']} DEGRADED · {counts['DOWN']} DOWN · {counts['UNKNOWN']} UNKNOWN",'']
    names={'cloud_storage':'Cloud storage','debian':'Server Debian','debian_ssh':'SSH Debian','docker':'Docker','mikrotik':'MikroTik · koneksi Winbox','mikrotik_system':'MikroTik · CPU/RAM','mikrotik_interfaces':'MikroTik · interface','portfolio':'Portfolio','proxmox':'Proxmox · HTTPS','proxmox_resources':'Proxmox · VM/LXC','technitium_dns':'Technitium DNS','web_http':'Web HTTP','web_https':'Web HTTPS'}
    reasons={'readonly_account_required':'Menunggu akun MikroTik read-only.','missing_readonly_token':'Token PVE read-only belum tersedia.','tls_verification_failed':'Sertifikat TLS belum dipercaya.','stale_snapshot':'Snapshot collector sudah kedaluwarsa.','snapshot_unavailable':'Snapshot collector belum tersedia.'}
    names.update(wireguard='WireGuard · peer',cisco_sf200='Cisco SF200-24 · cakupan manajemen',mikrotik_routes='MikroTik · routing',network_traffic='MikroTik · RX/TX otomatis')
    reasons.update(missing_switch_management='IP/kredensial manajemen Cisco belum tersedia; uplink dipantau dari MikroTik.',
        waiting_for_samples='Menunggu dua sampel counter yang valid.',interface_sample_unavailable='Sampel interface belum tersedia; trafik tidak dianggap nol.',
        icmp_not_permitted='Kernel belum mengizinkan ICMP datagram.',icmp_no_reply='Tidak mendapat balasan ICMP; host, jalur dan firewall perlu dibedakan.')
    icons={'UP':'✅','DEGRADED':'⚠️','DOWN':'🔴','UNKNOWN':'❔'}
    for r in results:
        detail=reasons.get(r.get('error'),r.get('error')) or (f"HTTP {r['http_status']}" if 'http_status' in r else '')
        if r['target']=='docker':
            containers=r.get('containers',[])
            detail=f"{sum(c.get('state')=='running' for c in containers)}/{len(containers)} container running" if containers else detail
        if r['target']=='debian' and r['status']=='UP':
            detail=f"CPU {r.get('cpu_percent')}%, RAM {r.get('memory_percent')}%"
        lines.append(f"{icons.get(r['status'],'❔')} **{r.get('display_name') or names.get(r['target'],r['target'])}** — {r['status']}")
        lines.append(str(detail or r['method']))
        if 'alert_on_unreachable' in r:
            lines.append('Notifikasi perangkat: '+('aktif' if r['alert_on_unreachable'] else 'observasi saja'))
        if r.get('timestamp'):
            try:stamp=datetime.fromisoformat(r['timestamp']).astimezone(timezone(timedelta(hours=7))).strftime('%d/%m %H:%M:%S WIB')
            except (TypeError,ValueError):stamp='waktu belum tersedia'
            lines.append('Diperiksa: '+stamp)
        if r['target']=='network_traffic':
            for point in r.get('interfaces',[])[:12]:
                rate=lambda x:'belum tersedia' if x is None else f'{x/1000000:.2f} Mbps'
                percent='belum tersedia' if point.get('utilization_percent') is None else f"{point['utilization_percent']:.1f}%"
                lines.append(f"• {point['name']}: RX {rate(point.get('rx_bps'))}, TX {rate(point.get('tx_bps'))}; utilisasi {percent}")
        lines.append('')
    lines += ['**Catatan**','UNKNOWN berarti data belum tersedia, bukan bukti perangkat mati.','Hasil dapat memakai cache hingga 60 detik. Gunakan /ask untuk detail.']
    return '\n'.join(lines)
