# Monitoring perubahan otomatis — 20 Oktober 2026

## 1. Temuan audit dan penyebab kekurangan sebelumnya

Baseline proyek main/402a10a bersih, container sehat dan koneksi MikroTik stabil. Polling berjalan 180 detik; alert interface hanya mengevaluasi MIKROTIK_INTERFACES, tetapi daftar tersebut kosong. Karena itu, port fisik tidak menghasilkan alert kabel. Trafik belum mempunyai baseline/delta berkala untuk deteksi anomali. Pengiriman lama hanya menyimpan satu pending event per key sehingga DOWN dan RECOVERY yang terjadi sebelum pengiriman dapat saling menimpa, dan cooldown insiden lama dapat menunda insiden baru.

Audit RouterOS menemukan ether1 sebagai uplink, ether3/ether4 pada bond-switch mode 802.3ad menuju satu Cisco SF200-24, ether2 tidak running, tiga VLAN, dan wg-azure. Dua entri LLDP berasal dari dua link ke switch yang sama; tidak dihitung sebagai dua switch. LLDP tidak memberikan IP manajemen Cisco. Pengguna juga belum mengetahui alamatnya; tidak dilakukan pemindaian subnet atau mencoba alamat/credential bawaan.

WireGuard memiliki peer dengan keepalive 25 detik dan handshake baru. Tabel ARP/DHCP/route mengidentifikasi sembilan alamat inventaris yang kemudian di-allowlist pada network.json. Snapshot terakhir sebelum perubahan memperlihatkan flash MikroTik bebas 0 byte; tidak ada penghapusan file, reboot atau perubahan konfigurasi router.

Perluasan jumlah target membuat hasil lengkap mencapai 27.391 karakter, melewati batas tool 22.000 karakter. Tool ringkasan diperbaiki agar mempertahankan seluruh 26 status dengan detail terbatas; uji produksi menghasilkan 13.748 karakter tanpa error result_too_large. Data rinci tetap dapat diminta melalui tool khusus.

Uji AI juga menunjukkan openrouter/free sempat memilih nvidia/nemotron-3.5-content-safety:free untuk pertanyaan umum. Model itu merupakan classifier moderasi, sehingga respons nonkosong/HTTP 200 saja tidak cukup. Client sekarang menolak actual_model khusus moderasi yang teridentifikasi dan beralih ke fallback yang sudah dikonfigurasi. Model dan kredensial tidak diganti. Hasil uji final dicatat di bagian 5.

Pengaman deployment mendeteksi perubahan lokal Proxmox selama pekerjaan. Dukungan PROXMOX_HOST/PORT dari perubahan tersebut dipertahankan. Opsi menonaktifkan verifikasi TLS ditolak oleh aplikasi sesuai persyaratan keamanan; tidak mengirim token lewat koneksi tanpa verifikasi.

Perbandingan runtime juga menangkap alur prefetch Proxmox yang belum tercakup image pengujian. Percobaan hotfix AI pertama otomatis di-rollback ke versi monitoring sehat. Alur tersebut dipertahankan, dimasukkan ke image test dan diberi regresi untuk kegagalan provider setelah bukti PVE diambil. Bukti yang sudah dibaca tetap dapat ditampilkan saat AI timeout.

## 2. File yang diubah

```text
.env.example
Dockerfile
README.md
network.json
app/__init__.py
app/config.py
app/main.py
app/ai/agent.py
app/ai/client.py
app/ai/evidence.py
app/ai/prompts.py
app/alerts/engine.py
app/alerts/network.py
app/alerts/outbox.py
app/dashboard/server.py
app/monitoring/icmp.py
app/monitoring/interface_events.py
app/monitoring/mikrotik.py
app/monitoring/mikrotik_catalog.py
app/monitoring/proxmox.py
app/services/health.py
app/services/network.py
app/services/scheduler.py
app/storage/database.py
app/telegram/formatting.py
app/telegram/handlers.py
deploy/host_collector.py
tests/test_ai.py
tests/test_bandwidth.py
tests/test_collectors.py
tests/test_continuous.py
tests/test_lifecycle.py
tests/test_state_telegram.py
docs/MONITORING-OTOMATIS-2026-10-20.md
```

Compose dan requirements.txt tidak diubah. Dockerfile hanya menambah COPY network.json. .env hanya diperbarui untuk continuous monitoring, interval, serta tujuh parameter ambang/cooldown; seluruh nilai credential/model dan konfigurasi lain dipertahankan. Collector host tetap menggunakan daftar endpoint Docker GET yang dibatasi, tanpa akses socket Docker bagi bot. Versi aplikasi 1.1.0.

## 3. Fitur yang tersedia

- Perubahan UP/DOWN Ethernet dengan baseline awal diam, event RouterOS /interface/listen dan polling cadangan 15 detik. Uplink Cisco diamati dari sisi MikroTik. Counter link-downs membantu mendeteksi gangguan singkat di antara polling; waktu persisnya tidak dikarang.
- Trafik RX/TX bit/detik dari delta counter dan selang aktual untuk Ethernet, bonding, VLAN dan WireGuard. Lonjakan >2× median baseline selama 60 detik setelah pemanasan 5 sampel, baseline minimal 100 kbit/detik dan spike minimal 1 Mbit/detik. Penurunan <=10% baseline dikonfirmasi dua sampel. Baseline dibekukan ketika terjadi anomali; recovery memakai hysteresis. Reset counter/gap/collector gagal tidak dianggap trafik nol.
- Utilisasi Ethernet berdasarkan rate link ternegosiasi dari monitor once, bukan advertised speed. Full duplex menggunakan maksimum RX/TX, half duplex jumlah RX+TX. >85% selama 30 detik WARNING; >95% selama 30 detik CRITICAL. Eskalasi dan recovery dikonfirmasi, hysteresis 5 poin. Timer dan state disimpan di SQLite. Ether3/ether4 benar-benar terbaca 100 Mbps full duplex. Persentase tidak dibuat untuk link DOWN, virtual, atau kapasitas yang belum diketahui; kapasitas port bukan kapasitas paket ISP.
- Perubahan tabel route lengkap dan perubahan usia handshake WireGuard; key VPN tidak dibaca. Handshake lama belum membuktikan peer mati, khususnya bila tunnel idle.
- Status ICMP sembilan alamat hasil audit; Debian CPU/RAM/disk, Docker health/restart/CPU/RAM, DNS query, dan HTTP/TLS tetap diperiksa. Nama klien mengikuti data DHCP saat audit, bukan jaminan alamat DHCP tidak berubah.
- Event SQLite dan antrean pengiriman terpisah. ALERT dan RECOVERY tetap tersimpan sebagai event berbeda. Retry transport maksimum lima kali dengan backoff/cooldown 5–300 detik dan penghormatan RetryAfter Telegram. Timeout pengiriman ditandai uncertain dan tidak dikirim ulang otomatis; pesan mungkin sudah sampai.
- Pesan memuat perangkat, kejadian, keparahan, waktu WIB, status pemulihan dan bukti. Deduplikasi transisi dan cooldown 600 detik per key/kondisi mencegah pengulangan. Eskalasi, recovery, insiden baru setelah recovery dan gangguan perangkat lain tetap dikirim. Perubahan route yang berbeda juga tetap diproses; duplikat diberi status suppressed. Semua gate bertahan setelah restart.
- /status, /alerts, /history, /devices, /help, /ask serta /events dan /mikrotik tersedia dengan guard allowlist/private chat. /history tanpa argumen menampilkan kejadian; dengan target menampilkan dua sampel. Tool get_incidents memungkinkan AI membaca riwayat. Notifier tidak memanggil AI; key AI boleh kosong. Error kuota harian model gratis diberi penjelasan khusus tanpa mencoba model gratis lain dari akun yang sama berulang kali.
- Retensi tidak mereset ID event, sehingga cursor notifikasi tetap bekerja setelah pembersihan. Incident container yang sudah hilang hanya diarsipkan setelah snapshot Docker lengkap; tidak diklaim sebagai layanan pulih.

## 4. Pengujian yang dijalankan

```sh
docker build --target test -t nms-bot:continuous-test .
docker run --rm --network none nms-bot:continuous-test
docker run --rm --network none --entrypoint python nms-bot:continuous-test -m unittest discover -s tests -p test_ai.py -v
docker compose config --quiet
docker compose build nms-bot
docker compose up -d --no-deps --no-build nms-bot
```

Source juga diperiksa sintaksnya dan hash runtime image test dibandingkan dengan file yang akan dideploy. Integrasi awal dijalankan sebagai UID 10001 dengan cap-drop ALL, no-new-privileges, filesystem read-only, CPU 0.75 dan memory 256 MiB, tanpa poller Telegram kedua. Database pengujian terpisah dari database produksi.

## 5. Hasil pengujian aktual

- Selesai dan terverifikasi: suite lengkap 180 unit/mock test lulus dalam 59,246 detik, jaringan dimatikan. Setelah penggabungan alur PVE dan guard classifier, 25 tes AI/agent lulus dalam 5,097 detik dan 26 tes context/evidence lulus dalam 0,104 detik. Ketiga run memiliki tes yang tumpang tindih; tidak diklaim sebagai 231 tes berbeda atau full suite 183 pada versi terakhir. Cakupan meliputi transisi/pemulihan, baseline port kosong, partial event ID, stale polling, rate/reset/gap, threshold 85/95 dengan durasi, full/half duplex, spike 2×/60 detik, konfirmasi lintas restart, gagal sampel, cooldown persisten, eskalasi/perangkat lain, route parsial, WireGuard handshake, WIB, outbox/retry/uncertain, retensi/cursor, otorisasi seluruh command, SSRF, dan AI tanpa key/kuota harian/TLS.
- Integrasi jaringan awal: sembilan host membalas ICMP tanpa NET_RAW. Sistem/interface MikroTik, WireGuard, DNS, Debian, Docker dan HTTP dapat dibaca. Trafik ether1 pada salah satu sampel sekitar RX 1,10 Mbit/detik dan TX 81,4 kbit/detik, dari selang 15,014 detik. Nilai ini sampel sesaat, bukan rata-rata jangka panjang.
- Event stream RouterOS benar-benar tersambung selama pengujian; fallback polling tetap berjalan ketika stream terputus. Riwayat produksi berisi event link ether1 dari RouterOS /interface/listen dan polling. Pengiriman dua event itu berstatus uncertain akibat timeout, sehingga tidak diklaim sudah diterima. Kami tidak melakukan perubahan kabel fisik; ini bukan uji cabut kabel terkontrol.
- Simulasi DOWN/UP: pesan Telegram 116, kedua event berstatus sent dalam DB sementara. Simulasi bandwidth: pesan Telegram 221, tiga event WARNING–CRITICAL–RECOVERY sent, satu duplikat suppressed; tidak ada pengiriman tambahan pada flush berikutnya. Pesan memiliki entity bold native, waktu WIB dan label SIMULASI. AI key kosong pada kedua pengujian; tidak ada data palsu dalam DB produksi.
- AI umum final: satu jawaban Bahasa Indonesia yang relevan dari dots-studio/dots-3-note-preview:free, tanpa tool; respons diperiksa isinya, bukan hanya HTTP/nonkosong. Uji live riwayat sebelumnya benar-benar menjalankan get_incidents, check_service dan get_mikrotik_data dengan hasil UP, lalu menghasilkan penjelasan 4.118 karakter. Guard model classifier dan fallback dibuktikan dengan mock; tidak diklaim ada percobaan live memaksa classifier pada run terakhir. Ketersediaan/kuota provider tetap dapat berubah.
- Verifikasi produksi: 26 target terwakili pada ringkasan AI; 9 alamat ICMP diperiksa, 7 merespons dan 2 tidak merespons pada snapshot akhir pengujian. Ether1 dan ether2 DOWN, ether3/ether4 UP. Sampel ether3 RX 156.778,54 bit/detik, TX 758,41 bit/detik, utilisasi 0,157%; ether4 RX 1.698,43 bit/detik, TX 845.911,37 bit/detik, utilisasi 0,846%, selang 15,285 detik. Ini sampel sesaat. 17 container terbaca, 13 running; status masing-masing dipertahankan. Router flash tetap 0 byte bebas. NMS healthy, restart count 0. .env mode 600, hash Compose/dependensi tetap sama.

## 6. Deployment dan rollback

Continuous monitoring, perbaikan ukuran ringkasan, dan ambang/cooldown sudah dideploy menggunakan build image serta recreate hanya service NMS. Backup tambahan ambang tersedia di /mnt/data/backups/nms-bot/pre-thresholds-20261020T0810Z, termasuk source, .env dan backup SQLite online; image rollback nms-bot-pre-thresholds:20261020T0810Z. Runtime source dibandingkan dengan image pengujian sebelum deployment. Hotfix guard AI dan penggabungan prefetch PVE juga selesai; checkpoint /mnt/data/backups/nms-bot/pre-ai-model-guard-20261020-final, image nms-bot-pre-ai-model-guard:20261020-final. Verifikasi akhir memastikan 32 file Python runtime sama dengan source aktif, .env/Compose/requirements tidak berubah selama hotfix, collector timer active dan NMS healthy dengan restart count 0. Handler /alerts serta /devices diuji terhadap data produksi dan menghasilkan format Telegram valid tanpa memanggil AI. Ini uji handler, bukan klaim pengguna telah mengetik kedua command setelah deployment terakhir.

Checkpoint sebelum perubahan: /mnt/data/backups/nms-bot/pre-continuous-20261020T033751Z/source.tar.gz dan backup SQLite online nms.sqlite3, mode 600 dalam direktori root-only. Image rollback: nms-bot-pre-continuous:20261020T033751Z. env.before_deploy dan host_collector.before.py menyimpan konfigurasi/collector sebelum penerapan. containers.json hanya menyimpan ID, nama, Running dan StartedAt yang diperlukan untuk perbandingan; environment aplikasi lain tidak dipertahankan pada baseline ini.

Untuk rollback, gunakan image dan source lama serta env.before_deploy; interval 60 detik dari versi baru tidak kompatibel dengan batas minimum 120 detik pada versi sebelumnya. Pulihkan collector NMS bila perlu, lalu recreate hanya service NMS dengan override image tersebut. Jangan compose down, menghapus volume atau memulihkan DB aktif secara sembarangan. Skema tambahan tidak mengubah tabel lama, sehingga backup DB tidak perlu dipulihkan untuk rollback kode normal. Status uncertain perlu diperiksa sebelum pengiriman ulang manual.

## 7. Dampak terhadap layanan lain

Lima belas container baseline selain NMS memiliki ID, StartedAt dan Running yang sama setelah deployment. Tidak ada restart/perubahan container tersebut. Collector systemd milik NMS sendiri diperbarui; port, network, volume dan reverse proxy Compose tidak diubah.

Tidak ada perubahan RouterOS/Cisco/Proxmox, restart host, pemutusan kabel, pembukaan trap/API publik atau pemberian Docker socket/capability administratif kepada bot. Akun router tetap diverifikasi sebagai read-only. Konfigurasi port, volume, network dan reverse proxy aplikasi lain dipertahankan.

## 8. Belum tersedia dan risiko

- Cisco: uplink LACP dan LLDP dapat diamati. IP/kredensial manajemen belum diketahui; data 24 port internal, resource switch, SNMP polling dan traps belum diimplementasikan/diaktifkan pada perangkat. Panduan Cisco mendokumentasikan SNMP dan traps, tetapi ketersediaan kode bukan bukti layanan tersebut aktif di switch ini.
- Proxmox: host merespons ICMP. Saat verifikasi terakhir konfigurasi token sudah terisi, tetapi PROXMOX_SSL_VERIFY=false dan CA belum tersedia. Aplikasi menolak bypass dan menghasilkan tls_verification_required; HTTPS juga belum dipercaya. Validitas token/role PVEAuditor, resource node dan VM/LXC belum terverifikasi. Tidak mengklaim VM sehat/mati.
- Uji kabel fisik: belum dilakukan karena pengguna tidak mempunyai port cadangan aman dan memilih simulasi berlabel. Simulasi tidak mengubah data/alert produksi.
- API MikroTik tetap menggunakan pengecualian LAN plaintext 8728 yang sudah dikonfigurasi. Migrasi API-SSL memerlukan CA/sertifikat dan perubahan administratif tersendiri.
- Inventaris IP adalah hasil audit pasif saat ini; tidak menjamin menemukan semua perangkat atau mengikuti perpindahan DHCP secara otomatis. ICMP tidak membuktikan semua layanan sehat. Link fisik tidak membuktikan routing/VLAN end-to-end.
- Event stream dapat terputus; koneksi dicoba ulang dengan backoff dan diverifikasi ulang setiap lima menit. Polling tetap berjalan. Antrean masuk dibatasi; overflow tercatat dan polling menjadi cadangan.
- Flash router penuh perlu penanganan administrator. Tidak ada klaim bahwa hal tersebut sudah diperbaiki atau penyebab tunggal gangguan telah terbukti.
- Sebagian notifikasi produksi sebelumnya berstatus failed atau uncertain ketika transport bermasalah. Catatan tersebut tidak dihapus atau diklaim terkirim. Uji simulasi terbaru berhasil; hal itu tidak menjamin Telegram selalu tersedia. Periksa /alerts dan /events bila diperlukan. Secret yang pernah dibagikan dalam chat sebaiknya dirotasi oleh administrator.

## 9. Langkah berikut yang masuk akal

Sediakan IP manajemen Cisco serta akses monitoring read-only untuk uji SNMP/traps dan seluruh port. Sediakan CA Proxmox dari sumber tepercaya yang dapat dibaca di dalam container, set PROXMOX_CA_FILE dan PROXMOX_SSL_VERIFY=true, lalu verifikasi token PVEAuditor dengan hak minimum. Lakukan uji kabel fisik hanya pada port cadangan setelah tersedia. Periksa jalur ether1 dan flash router penuh secara administratif tanpa menganggap penyebabnya sudah pasti. Sesuaikan baseline trafik dengan pola homelab, lalu lanjutkan API-SSL dan pembaruan inventaris DHCP. Tidak ada auto-remediation jaringan.

Referensi primer: [RouterOS API listen](https://manual.mikrotik.com/docs/developer-guides/api/), [counter interface](https://manual.mikrotik.com/docs/cli-reference/interface/), [rate Ethernet aktual](https://help.mikrotik.com/docs/spaces/ROS/pages/8323191/Ethernet), [usia handshake WireGuard](https://manual.mikrotik.com/docs/cli-reference/interface/wireguard/peers/), [Cisco 200 Series 1.3.0.x](https://www.cisco.com/c/dam/en/us/td/docs/switches/lan/csbss/sf20x_sg20x/administration_guide/78-21139.pdf), [model moderasi Content Safety](https://openrouter.ai/nvidia/nemotron-3.5-content-safety%3Afree/providers), [fallback Lightning dan tools](https://openrouter.ai/nvidia/nemotron-3.5-lightning%3Afree).
