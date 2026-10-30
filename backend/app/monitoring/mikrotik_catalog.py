"""Explicit RouterOS read surface. Callers cannot supply API paths or commands."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Section:
    title: str
    path: str
    fields: str
    filters: tuple[str, ...] = ()
    network: bool = True
    stats: bool = False

SECTIONS = {
    'system': Section('Identitas, CPU, RAM, penyimpanan dan waktu', '/system/resource', 'version,board-name,architecture-name,uptime,cpu,cpu-load,cpu-count,cpu-frequency,free-memory,total-memory,free-hdd-space,total-hdd-space', network=False),
    'interfaces': Section('Interface dan counter RX/TX', '/interface', '.id,name,type,mtu,actual-mtu,mac-address,running,disabled,comment,rx-byte,tx-byte,rx-packet,tx-packet,rx-error,tx-error,rx-drop,tx-drop,link-downs,last-link-up-time,last-link-down-time', ('name','type','running','disabled'), False, True),
    'wireguard_peers': Section('Status peer WireGuard tanpa key', '/interface/wireguard/peers', '.id,name,interface,disabled,last-handshake,rx,tx,persistent-keepalive,current-endpoint-address',('name','interface','disabled')),
    'traffic': Section('Kecepatan RX/TX dari dua sampel counter', '/interface', 'name,rx-byte,tx-byte,rx-packet,tx-packet', ('name',), False, True),
    'addresses': Section('Alamat IPv4', '/ip/address', 'address,network,interface,disabled,invalid,dynamic', ('address','interface')),
    'routes': Section('Route IPv4', '/ip/route', 'dst-address,gateway,immediate-gw,distance,scope,target-scope,routing-table,active,disabled,dynamic', ('dst-address','gateway','active','routing-table')),
    'ipv6_addresses': Section('Alamat IPv6', '/ipv6/address', 'address,interface,advertise,disabled,invalid,dynamic', ('address','interface')),
    'ipv6_routes': Section('Route IPv6', '/ipv6/route', 'dst-address,gateway,distance,routing-table,active,disabled,dynamic', ('dst-address','gateway','active','routing-table')),
    'dhcp_leases': Section('Klien dan lease DHCP', '/ip/dhcp-server/lease', 'address,mac-address,host-name,status,server,active-address,active-mac-address,expires-after,last-seen,dynamic,disabled', ('address','mac-address','host-name','status','server')),
    'dhcp_servers': Section('Server DHCP', '/ip/dhcp-server', 'name,interface,address-pool,lease-time,disabled,invalid', ('name','interface','disabled')),
    'dhcp_networks': Section('Network dan opsi dasar DHCP', '/ip/dhcp-server/network', 'address,gateway,netmask,dns-server,domain,ntp-server', ('address',)),
    'dns': Section('Resolver DNS router', '/ip/dns', 'servers,dynamic-servers,allow-remote-requests,cache-size,cache-used,max-concurrent-queries,query-server-timeout,query-total-timeout'),
    'arp': Section('Tabel ARP', '/ip/arp', 'address,mac-address,interface,status,complete,invalid,dynamic,disabled', ('address','mac-address','interface','status')),
    'vlan': Section('Interface VLAN', '/interface/vlan', 'name,vlan-id,interface,running,disabled,mtu,arp', ('name','interface','vlan-id')),
    'bridge': Section('Bridge', '/interface/bridge', 'name,mtu,actual-mtu,running,disabled,vlan-filtering,protocol-mode,pvid', ('name','running','disabled')),
    'bridge_ports': Section('Port anggota bridge', '/interface/bridge/port', 'interface,bridge,pvid,hw,inactive,disabled,edge,point-to-point,ingress-filtering,frame-types', ('interface','bridge','disabled')),
    'bridge_vlans': Section('Keanggotaan VLAN pada bridge', '/interface/bridge/vlan', 'bridge,vlan-ids,tagged,untagged,current-tagged,current-untagged,disabled,dynamic', ('bridge','vlan-ids')),
    'neighbors': Section('Neighbor discovery', '/ip/neighbor', 'identity,address,address6,mac-address,interface,platform,board,version,uptime,discovered-by', ('identity','interface','address')),
    'queues': Section('Simple queue dan statistik', '/queue/simple', 'name,target,parent,max-limit,limit-at,rate,packet-rate,bytes,packets,dropped,disabled,invalid', ('name','parent','disabled'), stats=True),
    'queue_tree': Section('Queue tree dan statistik', '/queue/tree', 'name,parent,max-limit,limit-at,rate,packet-rate,bytes,packets,dropped,disabled,invalid', ('name','parent','disabled'), stats=True),
    'firewall_filter': Section('Rule filter dan counter', '/ip/firewall/filter', 'chain,action,protocol,src-address,dst-address,src-port,dst-port,in-interface,out-interface,bytes,packets,disabled,invalid,dynamic', ('chain','action','disabled'), stats=True),
    'firewall_nat': Section('Rule NAT dan counter', '/ip/firewall/nat', 'chain,action,protocol,src-address,dst-address,src-port,dst-port,in-interface,out-interface,to-addresses,to-ports,bytes,packets,disabled,invalid,dynamic', ('chain','action','disabled'), stats=True),
    'firewall_mangle': Section('Rule mangle dan counter', '/ip/firewall/mangle', 'chain,action,protocol,src-address,dst-address,in-interface,out-interface,bytes,packets,disabled,invalid,dynamic', ('chain','action','disabled'), stats=True),
    'health': Section('Sensor suhu, tegangan dan kipas', '/system/health', 'name,type,value,temperature,voltage,cpu-temperature,fan1-speed,fan2-speed', network=False),
    'ppp_active': Section('Sesi PPP aktif, tanpa secret', '/ppp/active', 'name,service,address,caller-id,uptime,encoding,session-id', ('name','service','address')),
    'hotspot_active': Section('Sesi hotspot aktif', '/ip/hotspot/active', 'user,address,mac-address,server,uptime,idle-time,session-time-left,bytes-in,bytes-out', ('user','address','mac-address','server')),
    'wireless': Section('Klien wireless paket lama', '/interface/wireless/registration-table', 'interface,mac-address,uptime,signal-strength,tx-rate,rx-rate,tx-ccq,rx-ccq,bytes,packets', ('interface','mac-address')),
    'wifi': Section('Klien WiFi paket baru', '/interface/wifi/registration-table', 'interface,mac-address,ssid,uptime,signal,tx-rate,rx-rate,bytes,packets', ('interface','mac-address')),
    'services': Section('Status dan port layanan RouterOS', '/ip/service', 'name,port,disabled,invalid,address', ('name','disabled')),
}
LEGACY_NETWORK = ('addresses', 'routes', 'dhcp_leases', 'dns')
FILTER_FIELDS = sorted({key for section in SECTIONS.values() for key in section.filters})
ERROR_HINTS = {
    'readonly_account_required': 'Akun MikroTik khusus read,api belum diaktifkan. Administrator perlu menyiapkannya; bot tidak mengubah akun router.',
    'excessive_or_unverified_permissions': 'Akun API memiliki izin berlebih atau belum dapat diverifikasi. Wajib read,api; test/Winbox read-only dapat diterima. Hak write/policy/reboot/password/sensitive/sniff/FTP dan hak lain tetap ditolak.',
    'cannot_verify_account': 'Bot belum dapat memverifikasi grup akun API. Periksa akses akun khusus monitoring.',
    'network_details_disabled': 'Detail jaringan belum diaktifkan admin melalui MIKROTIK_NETWORK_DETAILS_ENABLED.',
    'plaintext_not_explicitly_allowed': 'API 8728 belum diizinkan. Utamakan API-SSL; pengecualian plaintext perlu disetujui admin untuk jaringan internal tepercaya.',
    'tls_verification_required': 'API-SSL wajib memverifikasi sertifikat. Setel CA tepercaya dan MIKROTIK_SSL_VERIFY=true.',
    'tls_verification_failed': 'Sertifikat API-SSL belum dipercaya atau nama host tidak cocok; verifikasi tetap diwajibkan.',
    'missing_credentials': 'Akun atau password MikroTik belum tersedia pada konfigurasi server.',
    'authentication_failed': 'Autentikasi API gagal. Periksa akun/password dan izin api tanpa membagikan rahasia ke chat.',
    'permission_denied': 'Akun API tidak diizinkan membaca bagian ini.',
    'unsupported_section': 'Menu tidak tersedia pada RouterOS, model perangkat, atau paket yang terpasang.',
    'timeout': 'Pembacaan API melewati batas waktu. Data perangkat belum dapat dipastikan.',
    'connection_failed': 'Koneksi API gagal. Periksa service API dan akses dari server NMS.',
    'collector_busy': 'Collector MikroTik sedang digunakan. Coba lagi setelah beberapa detik.',
    'invalid_arguments': 'Bagian, filter, atau offset tidak valid. Gunakan /mikrotik untuk pilihan.',
    'page_out_of_range': 'Offset melewati data tersedia. Mulai dari offset 0 atau gunakan filter lebih spesifik.',
    'empty_response': 'API tidak mengembalikan data perangkat yang diperlukan. Pemeriksaan belum berhasil.',
    'missing_switch_management': 'Cisco ditemukan melalui LLDP/uplink. IP manajemen dan akses baca belum tersedia; status 24 port internal belum diketahui.',
}
