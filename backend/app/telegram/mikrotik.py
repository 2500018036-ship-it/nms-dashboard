"""Deterministic Telegram views; detailed router data never needs an AI completion."""
from datetime import datetime
import shlex
from app.monitoring.mikrotik_catalog import SECTIONS, ERROR_HINTS

ALIASES = {'cpu':'system','ram':'system','sistem':'system','interface':'interfaces','trafik':'traffic',
    'dhcp':'dhcp_leases','klien':'dhcp_leases','ip':'addresses','route':'routes','queue':'queues',
    'firewall':'firewall_filter','nat':'firewall_nat','mangle':'firewall_mangle','sensor':'health'}

def help_text():
    lines=['**Data MikroTik yang bisa diminta**',
        'Ketik pertanyaan biasa atau pilih pembacaan langsung berikut. Data dibaca saat diminta, tanpa perubahan router.','']
    for name,spec in SECTIONS.items():
        lines.append(f'• `/mikrotik {name}` — {spec.title}')
    lines += ['', '**Filter dan halaman berikutnya**',
        '`/mikrotik interfaces name=ether1`', '`/mikrotik dhcp_leases status=bound`',
        '`/mikrotik dhcp_leases 10` — mulai offset 10 (baris ke-11)',
        'Filter memakai nama field persis. Hanya filter yang sesuai bagian diterima.',
        'Maksimal 10 baris per pembacaan; ikuti offset kelanjutan yang ditampilkan.',
        'Password, VPN secret, backup/export konfigurasi dan perubahan router tidak tersedia.']
    return '\n'.join(lines)

def parse_args(args):
    if not args:
        return None
    args=shlex.split(' '.join(args))
    if not args:raise ValueError('empty arguments')
    section=ALIASES.get(args[0].lower(),args[0].lower())
    if section not in SECTIONS or len(args)>3:
        raise ValueError('invalid section')
    kwargs={'section':section}
    for value in args[1:]:
        if value.isdecimal() and 'offset' not in kwargs:
            offset=int(value)
            if not 0<=offset<500:raise ValueError('invalid offset')
            kwargs['offset']=offset
        elif '=' in value and 'filter_field' not in kwargs:
            field,text=value.split('=',1)
            if field not in SECTIONS[section].filters or not text or len(text)>80 or not all(c.isprintable() for c in text):
                raise ValueError('invalid filter')
            kwargs.update(filter_field=field,filter_value=text)
        else:
            raise ValueError('invalid arguments')
    return kwargs

LABELS={'name':'Nama','version':'RouterOS','board-name':'Board','architecture-name':'Arsitektur','uptime':'Uptime',
    'cpu':'CPU','cpu-load':'CPU (%)','cpu-count':'Core CPU','cpu-frequency':'Frekuensi CPU (MHz)',
    'total-memory':'RAM total (byte)','free-memory':'RAM bebas (byte)',
    'total-hdd-space':'Storage total (byte)','free-hdd-space':'Storage bebas (byte)',
    'rx-byte':'RX kumulatif (byte)','tx-byte':'TX kumulatif (byte)','rx-packet':'RX paket','tx-packet':'TX paket',
    'rx-error':'RX error','tx-error':'TX error','rx-drop':'RX drop','tx-drop':'TX drop',
    'rx_bits_per_second':'RX (bit/detik)','tx_bits_per_second':'TX (bit/detik)','sample_seconds':'Interval sampel (detik)',
    'running':'Running','disabled':'Disabled','interface':'Interface','address':'Alamat','mac-address':'MAC',
    'host-name':'Hostname','status':'Status','comment':'Komentar','type':'Jenis','value':'Nilai','time':'Jam','date':'Tanggal',
    'rate_sample_valid':'Sampel kecepatan valid (false = counter hilang/reset)'}

def code(value):
    # A device value cannot break out of its inline code markup.
    text='belum tersedia' if value is None else str(value)
    return '`'+text.replace('`','ˋ').replace('\n',' ').replace('\r',' ')+'`'

def render(value, query):
    section=query['section']
    lines=[f'**MikroTik · {SECTIONS[section].title}**',f"Status pemeriksaan: {value['status']}"]
    if value.get('error'):
        lines += ['',value.get('detail',ERROR_HINTS.get(value['error'],'Data belum tersedia.')),
            'Belum ada hasil aktual yang dapat dipastikan. `/mikrotik` menampilkan pilihan data.']
        return '\n'.join(lines)
    try:
        stamp=datetime.fromisoformat(value['timestamp']).astimezone().strftime('%d/%m/%Y %H:%M:%S %Z')
    except (ValueError,KeyError):stamp='belum tersedia'
    lines += [f"Diperiksa: {stamp}",f"Metode: {value['method']}",f"Usia cache: {value.get('cache_age_seconds',0)} detik"]
    for path,rows in value.get('data',{}).items():
        meta=value.get('resources',{}).get(path,{})
        total=meta.get('total')
        lines += ['',f'**{path}**',f"Ditampilkan {len(rows)} dari {total if total is not None else 'setidaknya '+str(meta.get('total_at_least',len(rows)))} baris."]
        if not rows:
            lines.append('Tidak ada baris yang cocok pada halaman ini. Ini bukan bukti fitur/host mati.')
        for index,row in enumerate(rows,1+meta.get('offset',0)):
            lines.append(f'\n**Data {index}**')
            for key,item in row.items():
                lines.append(f'• {LABELS.get(key,key)}: {code(item)}')
        if meta.get('has_more'):
            next_offset=meta.get('next_offset')
            if next_offset is not None:
                extra=f" {query['filter_field']}={query['filter_value']}" if query.get('filter_field') else ''
                lines += ['', 'Masih ada data. Lanjutkan dengan:',code(f'/mikrotik {section} {next_offset}{extra}')]
            else:
                lines.append('Masih ada data di luar batas pembacaan. Gunakan filter lebih spesifik.')
        if meta.get('error'):
            lines.append(ERROR_HINTS.get(meta['error'],meta['error']))
        if meta.get('fields_truncated'):
            lines.append('Sebagian nilai panjang dipotong pada 160 karakter; hasil bukan salinan konfigurasi lengkap.')
        if meta.get('scan_truncated'):
            lines.append('Batas pembacaan 500 baris tercapai; jumlah total belum diketahui. Gunakan filter.')
    for path,error in value.get('errors',{}).items():
        lines.append(f"• {path}: {ERROR_HINTS.get(error,error)}")
    if value.get('rate_method'):lines += ['',value['rate_method']]
    lines += ['', 'Status di atas menyatakan hasil pembacaan API. Interface running tidak membuktikan VLAN/routing sehat; counter byte bukan kecepatan.']
    return '\n'.join(lines)
