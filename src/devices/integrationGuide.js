export const standardMethods = [
  {id:'snmp',label:'SNMPv3 / SNMPv2c',detail:'Identitas, uptime, interface dan metrik MIB yang benar-benar didukung. SNMPv3 authPriv disarankan.'},
  {id:'ssh',label:'SSH Linux baca-saja',detail:'Metrik Linux melalui perintah tetap, akun non-root dan host key terverifikasi.'},
  {id:'icmp',label:'ICMP',detail:'Keterjangkauan, latensi dan packet loss yang terukur.'},
  {id:'tcp',label:'TCP',detail:'Ketersediaan satu port. Tidak membaca resource perangkat.'},
  {id:'http',label:'HTTP / HTTPS',detail:'Health check aplikasi; status HTTP dan waktu respons dengan verifikasi TLS.'},
  {id:'dns',label:'DNS',detail:'Jawaban query DNS UDP dengan fallback TCP dan waktu respons.'},
  {id:'',label:'Inventaris saja',detail:'Catat identitas dan URL GUI tanpa menjalankan collector.'},
]

export function integrationGuide(device,poller='alamat server poller NMS') {
  const signature=`${device.vendor||''} ${device.model||''}`.toLowerCase()
  const firmware=device.firmware?`Firmware yang dicatat: ${device.firmware}.`:'Catat versi firmware dari halaman System Information agar panduan dapat dicocokkan.'
  const common={identity:`${device.vendor||device.type||'Perangkat'} ${device.model||''}`.trim(),firmware,poller,steps:[],limits:[]}
  if(device.monitor_method==='snmp') {
    let activation='Buka pengaturan Management/SNMP pada GUI perangkat. Pastikan model dan firmware menyediakan SNMP agent.'
    if(/mikrotik|routeros/.test(signature))activation=`MikroTik Winbox/WebFig: IP → SNMP → Enabled. Di Communities buat user SNMPv3 dengan Security private, Read Access aktif, Write Access mati, Authentication SHA1 (atau SHA256 jika didukung), Encryption AES, dan Addresses ${poller}/32. Nama community di RouterOS menjadi username untuk SNMPv3.`
    else if(/cisco/.test(signature)&&/sf200|sg200/.test(signature))activation='Cisco SF200/SG200: Security → TCP/UDP Services → aktifkan SNMP Service → Apply. SNMP → Communities → Add: pilih User Defined, isi IP poller, Basic, community unik, Read Only dan View Default. Menu SNMP Properties tidak digunakan pada antarmuka SF200 ini.'
    else if(/cisco/.test(signature))activation='Cisco: gunakan panduan model/firmware untuk mengaktifkan SNMP. Smart/Business Switch umumnya memakai Security → TCP/UDP Services dan SNMP → Communities; IOS memakai konfigurasi SNMPv3 group/user read-only. Jangan memakai perintah IOS pada SF200.'
    else if(/tp.?link|tplink/.test(signature))activation='TP-Link: periksa System Tools / SNMP atau System → SNMP sesuai seri. Gunakan read-only/GET dan manager IP poller. Model rumahan TL-WR tertentu tidak menyediakan SNMP; bila menu tidak ada, gunakan ICMP/TCP/HTTP sesuai layanan yang tersedia.'
    else if(/windows|microsoft/.test(signature))activation='Windows: periksa apakah edisi OS menyediakan SNMP Service atau agen SNMPv3 yang disetujui. Untuk layanan SNMP Windows bawaan, set Accepted community names menjadi READ ONLY dan Accept SNMP packets from these hosts ke IP poller. Dukungan v3 tidak diasumsikan pada agen bawaan.'
    else if(/linux|debian|ubuntu|proxmox/.test(signature))activation='Linux/Proxmox: gunakan agen Net-SNMP yang dipasang oleh administrator. Batasi agentAddress ke IP manajemen dan akses read-only ke IP poller, gunakan user authPriv. Proxmox dapat dipantau sebagai host Linux melalui SNMP/SSH; detail cluster/VM API merupakan integrasi tambahan yang memerlukan persetujuan.'
    return {...common,steps:[activation,`IP tujuan NMS adalah IP manajemen perangkat (${device.host||'belum diisi'}). Izinkan UDP ${device.monitor_port||161} dari ${poller}. Management Station/Addresses adalah IP sumber poller, bukan IP switch/router. Jangan membuka port SNMP ke internet.`,
      'Cocokkan versi: v3 mengisi username, protokol autentikasi, auth secret, protokol privasi dan privacy secret; v2c mengisi community read-only yang sama persis, termasuk huruf besar/kecil. THEAZ NMS mensyaratkan community unik minimal 8 karakter.',
      'Simpan konfigurasi perangkat. Pada Cisco klik Save, salin Running Configuration ke Startup Configuration agar tetap aktif setelah reboot.',
      'Isi kredensial di langkah berikutnya lalu Simpan & uji. Discovery membaca OID asli; pilih checkbox kategori yang ditemukan. Bandwidth memerlukan sedikitnya dua sampel counter yang valid.'],
      limits:['Timeout: periksa agent aktif, IP sumber poller/ACL, versi, community atau authPriv, UDP dan rute balasan. Timeout tidak membuktikan perangkat mati.', 'CPU/RAM/storage membutuhkan HOST-RESOURCES-MIB; VLAN membutuhkan Q-BRIDGE-MIB, routing membutuhkan IP-MIB, sensor membutuhkan ENTITY-SENSOR-MIB. OID yang tidak tersedia tidak ditampilkan. Wireless vendor tertentu belum mempunyai adapter MIB.']}
  }
  if(device.monitor_method==='ssh')return {...common,steps:[`Pastikan Linux menyediakan SSH pada TCP ${device.monitor_port||22}, dapat dicapai dari poller ${poller}.`,
    'Buat akun khusus non-root, misalnya nms-monitor. Batasi akun untuk login SSH dan membaca /proc, /proc/net/dev, uname dan df; akun tidak perlu sudo. Password akun bukan password GUI NMS.',
    'Di console tepercaya jalankan ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub lalu cat /etc/ssh/ssh_host_ed25519_key.pub. Cocokkan fingerprint, isi jenis key dan bagian Base64-nya di form. Key tidak boleh dipercaya hanya karena ditemukan melalui jaringan.',
    'Isi kredensial, simpan dan uji. CPU dan bandwidth muncul setelah dua sampel. Mematikan kategori menghentikan pembacaan perintah terkait untuk perangkat itu saja.'],limits:['Adapter SSH ini khusus Linux, termasuk OS Proxmox. SSH Windows/network appliance memerlukan parser yang sesuai dan belum diaktifkan.', 'Akses root ditolak. Host key mismatch harus diperiksa di console; jangan melewati validasi.']}
  const guides={
    icmp:['Izinkan ICMP echo dari IP poller menuju IP manajemen. Tidak ada username/password atau port TCP/UDP.','Data hanya reachability, latency dan packet loss; CPU, RAM, interface dan bandwidth memerlukan SNMP atau SSH yang sesuai.'],
    tcp:[`Tentukan port layanan TCP ${device.monitor_port||'yang aktif'} dan izinkan koneksi dari poller.`,`Port terbuka hanya membuktikan koneksi TCP, bukan autentikasi atau kesehatan aplikasi.`],
    http:['Masukkan URL health HTTP/HTTPS pada host yang diizinkan. HTTPS memerlukan sertifikat yang dipercaya server NMS.','Collector health tidak login atau membaca resource OS. GUI terautentikasi dibuka melalui Portal Access dengan akun perangkat.'],
    dns:[`Masukkan IP resolver, UDP/TCP ${device.monitor_port||53} dan nama domain untuk query. Izinkan resolver menjawab query dari poller.`,`Jawaban DNS dan waktu respons tidak menunjukkan CPU/RAM host DNS.`],
    '':['Simpan nama, alamat, vendor, model, firmware dan URL GUI jika diperlukan.','Tidak ada collector atau status UP yang dibuat hanya karena perangkat tercatat.'],
  }
  const [step,limit]=guides[device.monitor_method]||['Integrasi API lama dipertahankan sebagai adapter opsional.','Penambahan API baru memerlukan alasan metrik yang tidak tersedia melalui protokol standar dan persetujuan administrator.']
  return {...common,steps:[step,'Simpan lalu uji dari server NMS. Periksa waktu sampel dan pesan kesalahan sebelum mengandalkan hasil.'],limits:[limit]}
}
