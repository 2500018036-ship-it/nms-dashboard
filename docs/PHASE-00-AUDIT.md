# Phase 00 — Audit proyek frontend

Tanggal: 21 Oktober 2026. Scope: frontend lokal saja.

## Bukti awal

- Root merupakan React 19.3.1 + Vite 8.3.4; App.jsx masih starter counter Vite. Tidak ada router, data layer, atau integrasi API dalam source awal.
- Node 22.18.0 dan npm 10.9.3 tersedia. Tidak ada repository Git pada root ini. Tidak ada AGENTS.md pada root/ancestor yang diperiksa.
- Template tersedia sebagai template-dashboard.zip dan folder template-dashboard. Seluruh 159 file hasil ekstraksi sesuai byte dengan arsip. Folder/arsip dipertahankan tanpa modifikasi.
- Template Metis 3.6.0 adalah HTML, Bootstrap 5.3.8, SCSS, Alpine; bukan template React. Layout header/sidebar, kartu, tema gelap, ApexCharts, Bootstrap Icons, dan Inter relevan untuk dipakai kembali. Script Alpine/Bootstrap DOM tidak dipasang bersama React agar kontrol DOM tidak bertabrakan.
- Dokumentasi template diperiksa bersama SCSS aktual. Sebagian contoh dokumentasi masih menggambarkan desain lama (shadow/spacing/font eksternal), sehingga source SCSS menjadi acuan utama.
- Dependensi React/Vite dan script dev/build/preview dipertahankan. Ditambah React Router untuk rute, komponen/style Metis yang dipakai, dan Sass untuk kompilasi SCSS; tidak menyalin dependensi demo yang tidak diperlukan.
- Dev server proyek yang sama sudah ditemukan pada localhost:5173. Tidak ada service homelab yang diubah.

## Kontrak API yang ditemukan

Inspeksi baca-saja terhadap mirror kode backend sebelumnya (app/dashboard/server.py), bukan klaim integrasi langsung:

| Endpoint | Data | Batas |
| --- | --- | --- |
| GET /api/status | checks, alerts, server_time, interval | hasil collector dan alert aktif |
| GET /api/history?target=debian | target, points | CPU/RAM/latensi; tidak ada seri trafik bps per-interface |
| GET /api/events | events | riwayat kejadian terbaru |

API lama dilindungi Basic auth, pemeriksaan loopback/Host/Origin, dan rate limit. Probe tanpa kredensial ke http://127.0.0.1:18765/api/status tidak terjangkau saat audit. Tidak ada dokumentasi/konfigurasi integrasi pada starter React. Endpoint untuk konfigurasi, discovery, topology, AI chat web, log mentah, user/RBAC belum ditemukan. Tidak ada secret dibaca atau dimasukkan frontend.

## Keputusan struktur Phase 01

Pertahankan root React/Vite dan template asli. Pisahkan app (rute/registry), components (layout/UI/chart), pages (13 modul), data (client/adapters/provider), styles, dan tests. Sesuai arahan lanjutan pengguna, gunakan UI/UX Metis asli: import lengkap SCSS dan adaptasi markup ke React. Pertahankan ukuran, palet, layout, serta mode terang/gelap template; hanya konten dan menu disesuaikan untuk NMS. Data tidak tersedia ditampilkan sebagai belum terintegrasi/UNKNOWN, bukan angka dummy. Adapter hanya memproyeksikan data dari endpoint yang terverifikasi pada source; fitur tulis tetap tidak aktif.

## Checkpoint

Backup sebelum perubahan: `../nms-dashboard-checkpoints/phase00-20261021T141341/original-project.zip`. Arsip telah diuji tanpa error. Hash SHA-256 template dicatat pada template.sha256 di folder checkpoint yang sama. Backup berada di luar root agar tidak masuk bundle.

Tidak ada perubahan backend Python, bot Telegram, Docker Compose, router, ataupun service homelab.
