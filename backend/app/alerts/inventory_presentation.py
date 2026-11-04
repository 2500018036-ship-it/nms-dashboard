"""Human incident context from explicit inventory ownership; never guesses root cause."""
import re
import time

def describe(store,item):
    key=item.get('key') or item.get('target') or ''
    evidence=item.get('evidence') or item.get('value') or {}
    if not isinstance(evidence,dict):evidence={}
    target=key.split(':',1)[0];devices=store.list('inventory');owner=None;component=None;service=None
    if target.startswith('inventory_'):owner=next((d for d in devices if d['id']==target.removeprefix('inventory_')),None)
    elif target.startswith('service_'):service=store.get('integrations',target.removeprefix('service_'))
    technical=key.split(':',1)[1] if key.startswith(('container:','guest:')) else evidence.get('name','')
    if technical:component=next((d for d in devices if d.get('component_ref')==technical or d.get('parent_id') and d['name']==technical),None)
    if component:owner=component
    if not owner:
        source=store.source(target='docker' if key.startswith('container:') else target)
        if source:owner=next((d for d in devices if d['id']==source[1]),None)
    parent=next((d for d in devices if owner and d['id']==owner.get('parent_id')),None)
    name=(component or service or owner or {}).get('name')
    known=bool(name)
    label=name if known else 'Perangkat atau layanan belum dikenali'
    component_label=component['name'] if component else ('Komponen '+re.sub(r'[_-]+',' ',technical) if technical else None)
    parent_label=parent['name'] if parent else owner['name'] if owner and technical and not component else None
    severity=item.get('severity') or 'WARNING';status=item.get('status') or item.get('kind','')
    if ':cpu' in key:issue='penggunaan CPU melewati ambang';recommendation='Periksa proses aktif, beban kerja dan sampel CPU pada perangkat.'
    elif ':memory' in key:issue='penggunaan memori melewati ambang';recommendation='Periksa pemakaian RAM, proses terbesar dan tekanan memori.'
    elif any(k in key for k in (':disk',':storage')):issue='penggunaan penyimpanan melewati ambang';recommendation='Periksa kapasitas filesystem, pertumbuhan log dan retensi data.'
    elif key.startswith('container:'):issue='komponen container mengalami gangguan';recommendation='Periksa status, health check dan log container pada server induk.'
    elif ':collector' in key:issue='pengumpulan data gagal';recommendation='Periksa kredensial baca-saja, izin protokol dan jalur koneksi dari poller.'
    elif ':availability' in key or key.startswith('network:device:'):issue='tidak merespons pemeriksaan monitoring';recommendation='Periksa daya perangkat, alamat manajemen, konektivitas dan protokol yang digunakan.'
    else:issue='mengalami kejadian monitoring';recommendation='Periksa bukti teknis dan sampel terbaru; penyebab belum terkonfirmasi.'
    recovered=status in {'RECOVERY','RECOVERED'}
    description=f'{label} '+('telah pulih' if recovered else issue)
    if component_label and not component:description+=' pada '+component_label
    if parent_label:description+=' di '+parent_label
    first=item.get('first_seen');end=item.get('resolved_at') or item.get('recovered_at') or time.time()
    return {'display_name':label,'component':component_label,'parent_name':parent_label,
        'location':(parent or owner or {}).get('location') or None,'description':description,
        'recommendations':[recommendation],'impact':None,'cause':None,'name_resolved':known,
        'technical_key':key,'duration_seconds':max(0,end-first) if type(first) in (int,float) else None}
