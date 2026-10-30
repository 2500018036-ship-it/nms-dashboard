"""Verify diagram relationships against current, server-owned observations only."""
import json
import re
import time
from app.monitoring.device_capabilities import telemetry


def verify(graph, store, samples, now=None):
    now = time.time() if now is None else now
    inventory = {item['id']: item for item in store.list('inventory')}
    result_nodes = []
    resolved = {}
    for node in graph['nodes']:
        if node.get('resource_id') and not node['resource_id'].startswith('node/'):
            sample = samples.get('proxmox_resources')
            guests = sample.get('guests', []) if sample else []
            guest = next((g for g in guests if node['resource_id'] in (g.get('id'), str(g.get('type', '')) + '/' + str(g.get('vmid', '')))), None)
            row = dict(id=node['id'], name=node['name'], recognized=guest is not None, ready=False,
                       status='UP' if guest and guest.get('status') == 'running' and fresh(sample, now) else 'UNKNOWN',
                       issues=['Resource virtual tidak menggunakan IP host Proxmox. Tautkan IP manajemen guest melalui inventaris untuk memverifikasi koneksi.'])
            result_nodes.append(row); resolved[node['id']] = (None, row)
            continue
        item = inventory.get(node.get('device_id'))
        # Older diagrams may refer to a collector rather than an inventory ID.
        if not item and not node.get('device_id') and node.get('collector'):
            source = store.source(target=node['collector'])
            item = inventory.get(source[1]) if source else None
        issues = []
        sample = None
        target = ''
        if not item:
            issues.append('Tautkan node ke perangkat inventaris yang masih tersedia.')
        else:
            target = store.inventory_target(item)
            source = store.source(identity=item['id'])
            permitted = {target} | (set(json.loads(source[3])) if source and source[0] == item['host'] else set())
            if node.get('collector') and node['collector'] not in permitted:
                issues.append('Collector node tidak sesuai dengan perangkat inventaris.')
            sample = samples.get(target)
            if sample and sample.get('host') and sample['host'] != item['host']:
                issues.append('Alamat IP sampel berbeda dari IP manajemen inventaris.')
                sample = None
            if not item['enabled']:
                issues.append('Monitoring perangkat dinonaktifkan.')
            if not fresh(sample, now):
                issues.append('Diperlukan sampel monitoring terbaru berstatus UP.')
        known = item is not None and not any('Collector' in i or 'Alamat IP' in i for i in issues)
        active = known and item['enabled'] and fresh(sample, now)
        row = dict(id=node['id'], name=node['name'], recognized=known, ready=active,
                   status=sample.get('status', 'UNKNOWN') if sample else 'UNKNOWN', issues=issues)
        if item:
            row.update(device_id=item['id'], host=item['host'], vendor=item.get('vendor', ''),
                       model=item.get('model', ''), method=item.get('monitor_method', ''),
                       target=target, sampled=sample.get('sample_epoch') if sample else None,
                       telemetry=telemetry(sample) if sample and not sample.get('stale') else {})
        result_nodes.append(row)
        resolved[node['id']] = (item, row)

    links = []
    for edge in graph['links']:
        a, ar = resolved[edge['source']]
        b, br = resolved[edge['target']]
        row = dict(id=edge['id'], status='UNPROVEN', verified=False, animate=False,
                   message='Perlu observasi LLDP/CDP terbaru, IP neighbor yang sesuai, dan interface lokal UP.', evidence=[])
        if not ar['ready'] or not br['ready']:
            row['message'] = 'Kedua node harus dikenali dan memiliki sampel monitoring terbaru berstatus UP.'
        elif a['host'] == b['host']:
            row.update(status='MISMATCH', message='Kedua node merujuk perangkat/IP yang sama.')
        elif edge.get('vlan') or edge['type'] not in {'Ethernet', 'Fiber', 'Physical', 'Logical', 'Trunk', 'Access', 'LAG/LACP'}:
            row['message'] = 'Jenis relasi ini memerlukan bukti khusus (VLAN, route, peer VPN, atau asosiasi wireless); neighbor Ethernet tidak cukup.'
        else:
            for local, remote, local_row, side in ((a, b, ar, 'source'), (b, a, br, 'target')):
                source = store.source(identity=local['id'])
                targets = set(json.loads(source[3])) if source and source[0] == local['host'] else {local_row['target']}
                for target in targets:
                    sample = samples.get(target)
                    if not fresh(sample, now) or sample.get('host') not in (None, '', local['host']):
                        continue
                    for neighbor in sample.get('data', {}).get('/ip/neighbor', []):
                        if neighbor.get('address') != remote['host']:
                            continue
                        protocols = set(re.findall(r'[a-z]+', neighbor.get('discovered-by', '').lower()))
                        if not protocols.intersection({'lldp', 'cdp'}):
                            row['message'] = 'IP neighbor ditemukan, tetapi MNDP/ARP/ping belum membuktikan link langsung. Diperlukan LLDP/CDP.'
                            continue
                        ports = [p.strip() for p in neighbor.get('interface', '').split(',') if p.strip()]
                        selected_port = edge.get(side + '_port')
                        if selected_port and selected_port not in ports:
                            row.update(status='MISMATCH', message='Port pada diagram berbeda dari port observasi neighbor.')
                            continue
                        port_name = selected_port or (ports[0] if len(ports) == 1 else '')
                        if not port_name:
                            row['message'] = 'Neighbor terlihat pada beberapa interface. Pilih port sumber/tujuan yang tepat.'
                            continue
                        if remote.get('mac_address') and neighbor.get('mac-address') and remote['mac_address'].lower() != neighbor['mac-address'].lower():
                            row.update(status='MISMATCH', message='MAC neighbor tidak sesuai inventaris tujuan.')
                            continue
                        port, port_sample = find_port(targets, samples, port_name, now)
                        if not port or port.get('disabled') in (True, 'true') or not (port.get('status') == 'UP' or port.get('running') in (True, 'true')):
                            row['message'] = 'Neighbor cocok, tetapi status interface lokal belum tersedia atau bukan UP.'
                            continue
                        if edge['type'] in {'Ethernet','Fiber','Physical'} and port.get('type') in {'bridge','vlan','bonding','wireguard','wlan','wifi'}:
                            row['message'] = 'Interface ini bukan port Ethernet fisik. Pilih port fisik penerima LLDP/CDP atau jenis relasi yang sesuai.'
                            continue
                        # A target port assertion also needs reciprocal evidence.
                        opposite = 'target' if side == 'source' else 'source'
                        if edge.get(opposite + '_port'):
                            remote_source = store.source(identity=remote['id'])
                            remote_targets = set(json.loads(remote_source[3])) if remote_source and remote_source[0] == remote['host'] else {store.inventory_target(remote)}
                            if not reciprocal(remote_targets, samples, local['host'], edge[opposite + '_port'], now):
                                row['message'] = 'Port tujuan perlu observasi LLDP/CDP balik yang sesuai; label port manual belum cukup.'
                                continue
                        expires = min(expiry(samples[local_row['target']]), expiry(samples[store.inventory_target(remote)]), expiry(sample), expiry(port_sample))
                        row.update(status='VERIFIED', verified=True, animate=True, expires_at=expires,
                                   message='Relasi neighbor LLDP/CDP dan interface lokal UP terverifikasi; animasi menggambarkan relasi, bukan packet capture.',
                                   evidence=[dict(collector=target, protocol='/'.join(sorted(protocols.intersection({'lldp', 'cdp'}))),
                                                  host=local['host'], remote_host=remote['host'], port=port_name,
                                                  sampled=sample['sample_epoch'])],
                                   traffic={k: port[k] for k in ('rx_bps', 'tx_bps', 'rx_bits_per_second', 'tx_bits_per_second', 'rx-byte', 'tx-byte', 'rx_bytes', 'tx_bytes') if k in port})
                        break
                    if row['verified']: break
                if row['verified']: break
        links.append(row)
    valid = bool(result_nodes) and all(n['ready'] for n in result_nodes) and all(e['verified'] for e in links)
    return dict(checked_at=now, valid=valid, nodes=result_nodes, links=links,
                summary=dict(recognized=sum(n['recognized'] for n in result_nodes), nodes=len(result_nodes),
                             verified=sum(e['verified'] for e in links), unproven=sum(not e['verified'] for e in links)))


def expiry(sample):
    return sample.get('sample_epoch', 0) + min(120, sample.get('stale_after_seconds', 120))


def fresh(sample, now):
    return bool(sample and sample.get('status') == 'UP' and not sample.get('error') and not sample.get('stale')
                and sample.get('sample_epoch', 0) <= now + 30 and expiry(sample) > now)


def find_port(targets, samples, name, now):
    for target in targets:
        sample = samples.get(target)
        if fresh(sample, now):
            for port in sample.get('data', {}).get('/interface', []) + sample.get('interfaces', []):
                if port.get('name') == name:
                    return port, sample
    return None, None


def reciprocal(targets, samples, host, port, now):
    found, _ = find_port(targets, samples, port, now)
    if not found or not (found.get('status') == 'UP' or found.get('running') in (True, 'true')) or found.get('disabled') in (True, 'true'):
        return False
    return any(n.get('address') == host and port in [p.strip() for p in n.get('interface', '').split(',')]
               and set(re.findall(r'[a-z]+', n.get('discovered-by', '').lower())).intersection({'lldp', 'cdp'})
               for target in targets if fresh(samples.get(target), now)
               for n in samples[target].get('data', {}).get('/ip/neighbor', []))
