# Phase 4 â€” Logs, Alerts & Incident Management

Tanggal: 23 Oktober 2026. Frontend Windows dan backend Debian yang sudah ada tetap dipakai. Template Metis tidak diganti. Fase berikutnya belum dimulai.

## Audit dan keputusan implementasi

Backend memiliki tabel checks, events, alert_state, metadata dan notifications di SQLite, engine Alerts/NetworkEvents/IdleTraffic, serta outbox Telegram persisten. Aturan trafik nol 300 detik, pulih stabil 60 detik, cooldown 600 detik, hysteresis dan kebijakan opt-in client sudah tersedia. Tidak dibuat aturan alert di React atau engine monitoring kedua.

Halaman log sebelumnya menyusun gabungan batch 50 event dan ringkasan snapshot di browser. Tidak ada pagination riwayat server, kategori sumber yang tegas, atau identitas insiden lintas event. Phase 4 mengganti jalur aktif dengan API journal atas record yang benar-benar tersimpan. Hasil pemeriksaan collector dilabeli sebagai record pemeriksaan, bukan log aplikasi palsu.

Log aplikasi saat ini berada pada stdout container, tetapi belum diintegrasikan ke API log. Audit administratif dan penerimaan syslog juga belum tersedia. UI menandai kategori tersebut belum tersedia; tidak mengaktifkan syslog atau menambahkan agen perangkat.

## Implementasi

- Logs: pencarian pesan/target/perangkat, severity, sumber, kategori, waktu WIB, pilihan jumlah baris, pagination dan detail bukti tersanitasi. Pagination membaca backend, bukan hanya batch kecil di browser.
- Alerts & Incidents: aktif/historis, severity tertinggi yang tercatat, perangkat, waktu awal, transisi terakhir, observasi terakhir, waktu penutupan, ID persisten dan kronologi. Kondisi sama yang belum pulih mempertahankan ID; gangguan baru sesudah recovery mendapat ID baru.
- Tabel incidents dan incident_events adalah proyeksi transaksional dari event monitoring; bukan sumber keputusan alert baru. Migrasi membaca riwayat lama tanpa membuat event/notifikasi baru. Cursor proyeksi dapat mengejar event yang ditulis versi lama setelah rollback.
- ACTIVE, RECOVERED, RETIRED dan UNKNOWN dibedakan. RETIRED berarti aturan/inventaris dihentikan, bukan bukti layanan pulih. Riwayat yang tidak lengkap diberi penanda partial_history; tidak mengisi waktu awal atau severity yang hilang dengan angka rekaan.
- Perbaikan first_seen pada konfirmasi perubahan jaringan memastikan awal gejala tetap sama antara ALERT dan RECOVERY, termasuk timestamp nol pada simulasi.
- Metadata severity/default tampilan dibagikan oleh formatter Telegram, outbox dan API. Deduplikasi/cooldown tetap di outbox; hysteresis tetap di engine monitoring. Perubahan halaman/filter tidak membuat notifikasi.
- Status pengiriman per event: sent, pending, failed, suppressed, uncertain atau not_queued. Status ini terpisah dari status layanan. Timeout ambigu tidak dikirim ulang secara buta.
- ACK dan resolusi manual tidak diimplementasikan. API read-only/operator role dipertahankan. UI menjelaskan keterbatasan ini dan tidak membuat ACK lokal semu.

## Endpoint baru

Semua memerlukan sesi dashboard atau Basic auth legacy, memakai perlindungan Host/Origin dan rate limit Phase 3. Query SQLite memakai mode baca saja; tidak ada endpoint mutasi incident atau log.

| Endpoint | Parameter | Hasil |
| --- | --- | --- |
| GET /api/logs | page, page_size, q, severity, device, from, to, category, source | items, total, page, page_size, sources, devices, generated_at, read_only |
| GET /api/incidents | page, page_size, q, severity, device, from, to, status | items, total, summary, devices, acknowledgment_supported:false, resolution_mode:monitoring_only |
| GET /api/incidents/{id} | ID tervalidasi | incident, timeline maksimum 100 event, timeline_truncated, partial_history, delivery |

page: 1â€“10000; page_size: 1â€“100; UI menyediakan 10/25/50/100. q maksimum 120 karakter; device maksimum 180. Filter nilai disiapkan sebagai parameter SQL, bukan interpolasi SQL. Parameter asing/berulang dan ID tidak valid ditolak. Severity: INFO/WARNING/CRITICAL/UNKNOWN. Status: ACTIVE/RECOVERED/RETIRED/UNKNOWN atau all.

Kategori: monitoring, application, audit, syslog atau all. Sumber aktual: monitoring-events dan monitoring-checks. Kategori tanpa integrasi mengembalikan daftar kosong disertai metadata ketersediaan, bukan contoh data. Device pada log mengikuti identitas perangkat/target yang diberikan sumber; bukan inventaris konfigurasi baru.

from/to adalah epoch detik. Log default 24 jam, maksimum rentang 31 hari; data aktual mengikuti retensi 30 hari yang dikonfigurasi. Filter waktu insiden memakai waktu transisi terakhir; default seluruh yang tersimpan agar insiden lama yang masih aktif tetap terlihat. Form waktu khusus berlabel WIB, dan frontend mengonversi ke zona +07:00 secara eksplisit.

API error: 400 query/schema tidak valid, 401 sesi tidak valid, 403 Origin/Host ditolak, 404 insiden tidak ditemukan, 405 mutasi tidak diizinkan, 429 rate limit, 502 proxy tidak terhubung, 503 data belum dapat dibaca. Frontend menampilkan error terpisah dari kondisi tidak ada record. Client terpusat membatasi timeout/ukuran respons seperti Phase 3.

Contoh rute: `/api/logs?source=monitoring-events&page=1&page_size=25`; `/api/incidents?status=ACTIVE`; `/api/incidents/inc_event_21`. ID contoh terakhir merupakan ID dari inspeksi saat pengerjaan, bukan endpoint yang dijamin selamanya ada setelah retensi.

## Penyimpanan dan retensi

incidents: ID, key kondisi, status, waktu awal/pembaruan/penutupan, peak severity, referensi event pembuka/terakhir, perangkat/judul, penanda riwayat parsial. incident_events menghubungkan record event ke siklus incident. Pembaruan event dan proyeksi dilakukan dalam satu transaksi. Tidak menyimpan percakapan AI atau credential baru.

Retensi membersihkan incident nonaktif yang melewati batas; incident aktif tetap dipertahankan. Bila event pembuka sudah melewati retensi, ID incident tetap sama dan UI menunjukkan sebagian kronologi tidak tersedia. Migrasi/index bersifat tambahan; image lama dapat mengabaikan tabel baru saat rollback. Tidak perlu menghapus database untuk rollback.

## Pengujian dan hasil

- Backend: 214 tes lulus dalam image uji terisolasi jaringan, filesystem read-only dan tmpfs 16 MB. Meliputi identitas/restart/recovery/eskalasi, migrasi idempoten tanpa replay Telegram, histori parsial/retensi, penangkapan event versi lama, deduplikasi/hysteresis, sanitasi, filter/pagination, validasi query, autentikasi dan penolakan mutasi.
- Frontend: 56 tes lulus; lint dan build lulus. Tes baru meliputi encoding filter, allowlist endpoint/ID, WIB, rentang waktu tidak valid, anchor pagination, pemetaan status/severity dan pembuangan field rahasia.
- API live: login 200; daftar incident aktif/historis, event log, health dan detail terbaca. Rentang khusus 13.00â€“13.10 WIB menghasilkan 153 record dan seluruh timestamp berada di dalam rentang saat diuji.
- Browser: pencarian DNS, filter severity/perangkat/sumber/kategori, pagination log tanpa ID berulang, pagination recovery, detail bukti, detail incident dan ACK disabled telah diperiksa. Preset waktu 24 jam dan 7 hari terbaca.
- Simulasi kegagalan API dilakukan dengan menghentikan tunnel SSH lokal dashboard saja. UI menampilkan error, lalu daftar pulih sesudah tunnel dijalankan kembali. Monitoring server tidak dimatikan.
- Sempat muncul timeout pemeriksaan sesi selama rangkaian pengujian; halaman menampilkan pesan aman dan tombol hubungkan kembali berhasil memulihkan sesi tanpa login ulang.
- Form datetime-local khusus belum berhasil diisi oleh alat otomasi browser; validasi WIB diuji melalui unit test dan API live, bukan diklaim lulus pengujian pemilih tanggal native.
- Halaman log dan incident diperiksa pada lebar CSS 1300 px dan 381 px tanpa overflow halaman. Tabel memakai scroll internal sesuai template. Bukti visual ada di docs/screenshots/phase04-*.png pada proyek frontend.
- Seluruh 159 file template tetap sama dengan ZIP. Password operator tidak ditemukan dalam source, bundle atau dokumentasi.

Uji data nyata menemukan batas temp SQLite 16 MB: kueri awal menyortir payload/pesan besar sehingga API menghasilkan 503. Diperbaiki dengan pagination identitas ringkas terlebih dahulu dan pengambilan payload hanya untuk halaman terpilih; tidak menaikkan limit container. Pengujian mencakup halaman awal dan riwayat jauh dengan puluhan ribu record pada container read-only ber-tmpfs 16 MB. Hasil final pada 79.042 record: halaman 1/1000/3000/10000 berhasil dalam 1,08–1,19 detik pada uji read-only ber-tmpfs 16 MB. Uji HTTP melalui proxy frontend pada sekitar 79.119 record: halaman 1 HTTP 200 dalam 2,095 detik dan halaman 3000 HTTP 200 dalam 2,235 detik, masing-masing 25 baris.

Pengujian gangguan/deduplikasi menggunakan database sementara dan mock Telegram; tidak mencabut kabel, menyalakan syslog, membuat gangguan produksi, atau mengirim alarm palsu. getMe dan heartbeat memverifikasi identitas/kesiapan bot; pesan masuk dari akun manusia tidak diuji ulang pada penutupan fase.

## Hasil audit kanal notifikasi

Saat inspeksi akhir: 2 incident ACTIVE, 370 RECOVERED, 8 RETIRED; angka dapat berubah mengikuti monitoring. Outbox berisi 666 sent, 70 failed, 16 uncertain dan 2 suppressed. Semua 70 failed tercatat sebagai NetworkError, terakhir 23 Oktober 2026 02.43 WIB; uncertain terakhir 20 Oktober 2026 21.44 WIB. Riwayat lama ini dipertahankan dan tidak dikirim ulang massal. getMe pascadeploy berhasil dan poller_ready=true; itu tidak dianggap bukti setiap notifikasi historis pernah sampai.

## File dan deployment

Frontend ditambah: src/data/journalModel.js, src/data/useJournal.js, src/components/JournalControls.jsx, tests/phase04.test.js. Diubah: src/pages/LogsPage.jsx, src/pages/AlertsPage.jsx, src/data/apiClient.js, config/devProxy.js dan dokumentasi. Layout/template, backend credentials, reverse proxy dan perangkat tidak diubah.

Backend ditambah: app/alerts/presentation.py, app/storage/incidents.py, app/dashboard/journal.py, tests/test_journal.py. Diubah: app/alerts/engine.py, app/alerts/network.py, app/alerts/outbox.py, app/storage/database.py, app/dashboard/projection.py, app/dashboard/server.py serta dokumentasi. Compose, Dockerfile, scheduler, bot.py, protokol collector, permission perangkat dan konfigurasi jaringan tetap dipertahankan.

Backup frontend: direktori saudara nms-dashboard-checkpoints/phase04-20261023/frontend-before.zip. Backup backend: /mnt/data/www/nms-bot/backups/phase4-20261023, termasuk source-before.tar.gz, backup SQLite konsisten, env-before permission terbatas dan image-before. Image rollback: nms-bot:phase4-rollback-20261023.

Deployment hanya menggunakan `docker compose up -d --no-deps --no-build nms-bot`. Tidak ada compose down, penghapusan volume, restart host, perubahan perangkat, atau restart service lain. ID container selain NMS sama sebelum/sesudah pemeriksaan.

Rollback: tag image nms-bot:phase4-rollback-20261023 menjadi nms-bot:local dan recreate hanya nms-bot. Pertahankan database terkini agar event baru tidak hilang. Pemulihan source dilakukan ke direktori terpisah untuk perbandingan, bukan menimpa perubahan pengguna. Tabel incident tambahan dapat dibiarkan ketika image lama dijalankan.

## Batas yang masih ada

Log mentah aplikasi, audit administratif, remote syslog, ACK persisten dan resolusi manual belum diintegrasikan. Proxmox VM/API tetap tertahan TLS dan Cisco SNMP menunggu konfigurasi; Phase 4 tidak mengubah batas tersebut. Dashboard tetap lokal melalui SSH; deployment publik belum dilakukan. Build masih memperingatkan ukuran chunk ApexCharts. Fase selanjutnya tidak dimulai otomatis.
