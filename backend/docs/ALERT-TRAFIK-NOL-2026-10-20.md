# Perbaikan spam alert — 20 Oktober 2026

## Penyebab yang terverifikasi

Aturan lama menandai penurunan sampai 10% baseline setelah dua sampel, sekitar 15 detik. Riwayat ether4 RX menunjukkan baseline 121–127 kbit/detik, turun ke 2–4 kbit/detik lalu naik kembali. Itu cukup untuk menghasilkan ALERT/RECOVERY berulang walaupun link tetap running. Cooldown lama membandingkan jenis event terakhir; recovery membuat ALERT berikutnya lolos sebelum 10 menit. Ini kelemahan implementasi sebelumnya, bukan bukti gangguan kabel atau serangan.

iPhone juga dimasukkan ke aturan perangkat yang diharapkan selalu online. Riwayat menunjukkan transisi ping UP/DOWN berulang, termasuk 14:36, 14:38, 14:40, 14:50, 14:54, 15:05 dan 15:18 WIB. Tidak membalas ICMP tidak membuktikan ponsel mati; tidur, perpindahan jaringan, firewall atau perubahan IP belum dibedakan oleh pemeriksaan tersebut.

## Kebijakan yang disetujui dan diimplementasikan

- RX dan TX harus sama-sama nol selama 300 detik pada sampel valid dan link running sebelum satu WARNING dikirim.
- Trafik positif pada salah satu arah harus bertahan 60 detik sebelum satu RECOVERY dikirim. Putusnya sampel atau kembalinya trafik ke nol memutus timer pemulihan.
- Nol trafik dilabeli sebagai tidak ada trafik teramati, bukan internet/perangkat terputus. Counter reset, link DOWN dan data gagal tidak dianggap nol atau pulih.
- Aturan spike/drop relatif baseline lama dinonaktifkan pada deployment ini. Metrik RX/TX, histori dan analisis AI tetap tersedia.
- Cooldown trafik 600 detik tetap dihitung dari ALERT sebelumnya meskipun ada recovery. Recovery untuk siklus yang ALERT-nya ditahan juga ditahan. Recovery menunggu pengiriman ALERT terkait jika masih retry.
- Alert link fisik DOWN/UP, bandwidth tinggi 85%/95%, resource, layanan penting, routing dan WireGuard dipertahankan.
- Sembilan alamat tetap dipantau. Enam infrastruktur mengirim alert: MikroTik, Debian, Proxmox host, DNS, gateway upstream dan TLWR820N. iPhone, ajilll dan laptop THEAZ hanya observasi; hasil dan kebijakan terlihat di /devices dan /status.
- Aturan lama yang dinonaktifkan ditutup sebagai RETIRED, bukan RECOVERY. Pending notifikasi aturan tersebut dibatalkan; riwayat yang sudah terkirim/tidak pasti tidak dihapus.

## File dan konfigurasi

Perubahan pada app/config.py, app/alerts/traffic_idle.py, app/alerts/network.py, app/alerts/outbox.py, app/alerts/engine.py, app/services/scheduler.py, app/services/health.py, app/storage/database.py, handler/formatting Telegram, app/__init__.py, network.json, .env.example, README.md, tests/test_continuous.py dan tests/test_quiet_alerts.py. Versi aplikasi 1.1.1.

```dotenv
TRAFFIC_ZERO_SECONDS=300
TRAFFIC_RESUME_SECONDS=60
TRAFFIC_BASELINE_ALERTS_ENABLED=false
```

network.json memakai boolean alert_on_unreachable; default false untuk perangkat baru. Kredensial tetap disimpan di .env mode 600. Compose, dependensi, port dan konfigurasi jaringan tidak diubah.

## Pengujian

Suite lengkap 193 unit/mock test lulus dalam 9,981 detik dengan jaringan container dimatikan dan database uji sementara. Cakupan baru meliputi nol 5 menit, pemulihan stabil 1 menit, RX/TX hanya satu arah, fluktuasi biasa, data hilang/reset/gap, timer/state lintas restart, link DOWN langsung, cooldown lintas recovery, recovery siklus yang ditahan, urutan retry, pembatalan pending lama, klien pribadi tanpa alert, perangkat infrastruktur tetap mengirim alert, serta validasi konfigurasi.

Uji pembacaan langsung menggunakan image pengujian, akun read-only dan database sementara. Pengiriman Telegram pada pengujian perbaikan ini memakai mock; tidak mengirim pesan uji baru ke Telegram pengguna. Durasi gangguan diuji dengan waktu simulasi, bukan memutus jaringan atau menunggu link produksi sepi selama 5 menit.

Pembacaan live berhasil: ether3, ether4 dan wg-azure mempunyai trafik positif; link yang tidak running tetap UNKNOWN untuk trafik. iPhone merespons ICMP pada sampel pengujian dengan notifikasi false; Debian merespons dengan notifikasi true. Pergantian status ponsel di masa depan tidak perlu menunggu ponsel offline untuk membuktikan keputusan kebijakan, karena jalur tersebut sudah diuji dengan rangkaian UP/DOWN simulasi.

## Deployment dan rollback

Checkpoint sebelum perubahan: /mnt/data/backups/nms-bot/pre-zero-traffic-20261020. Tersedia source.tar.gz, env.before_deploy, backup SQLite online nms.sqlite3, dan baseline container lain; direktori mode 700, file rahasia mode 600. Image rollback nms-bot-pre-zero-traffic:20261020.

Deployment hanya build/recreate service nms-bot dengan --no-deps. Jika gagal, source/konfigurasi dan image dari checkpoint dipakai kembali tanpa menghapus volume atau me-restore DB aktif secara sembarangan. Perubahan kebijakan pada state/riwayat bersifat observasional, bukan perubahan perangkat.

Deployment selesai dan terverifikasi: versi 1.1.1 healthy, restart count 0. Event stream terhubung dan polling berjalan 15 detik. Tidak ada ALERT/RECOVERY/CHANGE baru dari baseline lama atau tiga klien pribadi sejak container baru dimulai. Tidak ada pending notification dari aturan yang dimatikan; incident lama sudah tidak aktif. Terdapat satu event RETIRED pada cutover, tanpa mengirim recovery palsu. Seluruh 34 berkas runtime/config di image sesuai source. Lima belas container selain NMS mempertahankan ID, Running dan StartedAt. Compose/dependensi tidak berubah dan .env tetap mode 600. Riwayat pengiriman lama tetap utuh, termasuk failed/uncertain; tidak diubah menjadi klaim terkirim.

## Batas yang tetap ada

Perangkat DHCP tidak dijamin mempunyai identitas/IP tetap. Status UNKNOWN/ICMP tidak membuktikan seluruh layanan sehat atau mati. Cisco SNMP dan resource VM/LXC Proxmox tetap mempunyai keterbatasan akses/TLS dari laporan sebelumnya. Pengiriman Telegram bisa gagal atau belum pasti ketika konektivitas bermasalah; itu tidak diubah menjadi klaim terkirim.
