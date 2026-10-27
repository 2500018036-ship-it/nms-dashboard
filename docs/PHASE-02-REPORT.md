# Phase 02 — Core Monitoring & Device Management UI

Tanggal: 21 Oktober 2026. Versi frontend 0.2.0. Scope berhenti pada Phase 02; Phase 03 tidak dikerjakan.

## Hasil dan batas verifikasi

**Selesai dan terverifikasi untuk frontend:** enam halaman inti, komponen reusable, alur form/validasi, pencarian/filter/pagination, modal, grafik, topology interaktif, inventaris dan ACK dalam demonstrasi eksplisit. Semua 13 modul tetap dapat dinavigasi. UI/UX Metis yang disediakan dipertahankan; tidak ada penggantian template atau dependensi tambahan.

**Siap pada lapisan adapter dan diuji dengan mock:** pembacaan tiga kontrak GET lama, normalisasi trafik/interface/host/guest/container/layanan, penanganan timestamp/data hilang, topology neighbor dan buffer RX/TX. Ini belum membuktikan koneksi dengan backend produksi.

**Belum terintegrasi:** API lokal 18765 tidak dapat diakses saat probe. Tidak ada integrasi API live yang diklaim berhasil pada fase ini. CRUD inventaris, uji koneksi, discovery/approval dan ACK aktual menunggu endpoint serta otorisasi backend. Browser tidak melakukan polling langsung ke perangkat.

**Dampak layanan:** hanya proyek frontend lokal yang diubah. Backend Python, Telegram, Docker Compose, router, Proxmox, DNS, dan service homelab tidak diubah/deploy/restart. Dev server tetap berjalan pada loopback 5173; preview produksi sementara dipakai untuk QA lalu dihentikan.

## Audit dan checkpoint

- Memeriksa implementasi Phase 01, routing, template Metis, komponen, client/adapter/context, konfigurasi proxy dan pengujian.
- Membaca source backend mirror secara read-only untuk memeriksa bentuk payload aktual: dashboard/server.py, collector Proxmox, jaringan/ICMP, host collector dan katalog RouterOS.
- Endpoint ditemukan: GET /api/status, /api/events, /api/history?target=...; tidak ditemukan API inventaris, ACK atau discovery. Endpoint history lama tidak memberikan seri RX/TX per interface.
- Proyek tidak memiliki repository Git pada audit; tidak ada branch/commit atau status Git yang dapat dilaporkan.
- Backup sebelum perubahan: `C:\Users\Hype G12\Downloads\nms-dashboard-checkpoints\phase02-20261021T144830\frontend-before-phase02.zip`.
- Perbandingan hash terhadap checkpoint: tidak ada file yang dihapus. Seluruh 159 file template-dashboard dan arsip template-dashboard.zip tetap sama.

## Halaman yang selesai

| Halaman | Hasil UI | Sumber/batas aktual |
| --- | --- | --- |
| Overview | Ringkasan alamat teramati, perhatian collector, alert, freshness, RX/TX, CPU/RAM, resource/aktivitas, dua grafik | Nilai hanya dari snapshot/history valid; angka kosong saat API belum ada |
| Network Monitoring | Pilihan interface, grafik RX/TX, utilisasi, daftar interface/counter/error/drop, pencarian/filter, latency/loss | Rate harus eksplisit; kapasitas/loss tidak ditebak; tidak menjumlah trafik lintas interface |
| Servers & Services | Tab host, VM/LXC, Docker dan layanan; pencarian/filter, CPU/RAM/disk/uptime | Metrik sesuai collector; Docker CPU multi-core dapat >100%; missing health tetap tidak dikonfigurasi |
| Device Management | Form lengkap, detail, CRUD demo, enabled state, search/filter/pagination, import/export, probe/discovery/approval demo | Inventaris berbeda dari collector; mode aktual validasi saja, tanpa klaim penyimpanan |
| Topology | Graph SVG, node keyboard/click, pencarian, detail dan tabel link | Aktual hanya neighbor yang diberikan snapshot; link UNKNOWN; demo graph berlabel ilustrasi |
| Alerts & Incidents | Aktif, severity, waktu WIB, detail/ACK, filter dan recovery timeline | ACK demo hanya memori; riwayat terbatas batch event API, bukan seluruh database |

Tujuh modul foundation sebelumnya dipertahankan. Tidak ada chat AI palsu, secret management atau halaman autentikasi produksi yang diklaim aktif.

## Pemisahan data dan keamanan

- Mode aktual adalah bawaan. API tetap nonaktif sesuai konfigurasi awal; saat belum terhubung UI menampilkan belum terintegrasi, bukan angka demo.
- Demonstrasi hanya aktif setelah tombol eksplisit pada npm run dev. Semua halaman mendapat banner BUKAN DATA HOMELAB. Data memakai alamat dokumentasi, snapshot statis dan memori sesi.
- CRUD/approval/ACK DEMO tidak mengubah monitoring homelab. Keluar/reload menghapus state demo. Pergantian mode mereset form, filter dan pesan agar konteks tidak tercampur.
- Fixture DEMO diimpor dinamis di guard import.meta.env.DEV. Build produksi diperiksa: tombol aktivasi dan marker DEMO-CORE-ROUTER tidak tersedia; fixture tidak masuk bundle.
- Service aktual menolak semua operasi tulis/probe yang belum didukung. Client jaringan tetap GET-only same-origin dan dibatasi endpoint.
- Schema import tertutup menolak credential/field asing, tipe salah, duplikasi host/ID, file >256 KiB atau batch >200. Export memproyeksikan field allowlist saja.
- localStorage tetap hanya untuk preferensi tema/sidebar. Tidak menyimpan secret, percakapan, inventaris, ACK atau monitoring.
- Metrik hilang tetap null. Sampel kedaluwarsa menjadi UNKNOWN dan nilai resource/rate/latency/loss/uptime dikosongkan. Status ICMP UP tidak dianggap packet loss nol.
- Buffer RX/TX terbatas 120 titik/interface dan 200 interface, memori saja. Timestamp dideduplikasi; missing rate tetap gap.

## Pengujian aktual

| Pemeriksaan | Hasil |
| --- | --- |
| npm test | 40 lulus, 0 gagal, 0 skipped; 18 tes lama tetap lulus |
| npm run build | Berhasil, Vite 8.3.5, 63 modul |
| Browser 13 rute | Semua judul halaman sesuai navigasi |
| Form aktual | Empty submit ditolak; input valid diberi pesan BELUM tersimpan; inventaris tetap kosong |
| Inventaris demo | Tambah, edit nama, disable dengan konfirmasi, pencarian/filter dan hapus berhasil |
| Uji koneksi demo | Hasil menyatakan simulasi tanpa request ICMP/SNMP/API |
| Discovery demo | Scope 192.0.2.0/24 menghasilkan 2 kandidat statis; approval eksplisit memasukkan kandidat |
| Import | JSON rusak ditolak; JSON valid lolos preview dan import ke memori demo |
| Export | Browser mengunduh nms-inventory.json; diperiksa schemaVersion 1, 9 konfigurasi pada saat export, source demo, field allowlist |
| Pagination/filter | Setelah import QA tambahan, 13 konfigurasi: halaman kedua 3 baris; filter tipe/grup menghasilkan 4 baris |
| Grafik | Overview merender 2 grafik ApexCharts dari fixture development |
| Network/servers | Pilihan interface, filter DOWN, tab VM/LXC dan Docker diperiksa; CPU container 104% dipertahankan |
| Topology | Pemilihan node menampilkan detail; tabel memuat 5 link ilustrasi |
| Alerts | ACK dengan catatan tampil ACK DEMO; filter recovery menghasilkan 1 event |
| Responsif | Enam halaman inti diuji pada lebar CSS aktual 282px; document scrollWidth = clientWidth 271px, tabel/graph memakai scroll dalam panel |
| Modal ponsel | Lebar CSS 282px, tinggi 610px; body modal scrollable, footer pada 581.8px dan tombol tutup bekerja |
| Build produksi di browser | Tidak ada tombol demo atau perangkat contoh; console warning/error kosong |
| Keluar demonstrasi | Inventaris QA/demo hilang; filter/pesan reset; kembali ke mode aktual belum terintegrasi |
| Console akhir development | Tidak ada warning/error pada sesi pemeriksaan akhir |
| Probe API live | Tidak dapat terhubung; integrasi live belum diuji berhasil |

Pengujian otomatis mencakup schema/validasi/malformed types, IPv4/IPv6/hostname, duplikasi/import atomik, projection export, penolakan operasi aktual, CRUD memori, scope/approval, simulasi probe/ACK, normalisasi unit, packet loss, missing data, stale resource, trafik bounded/dedup, topology berdasarkan bukti, timeout/cancel, 401/403/429, batas ukuran respons serta allowlist API. Tes tidak mengganggu perangkat produksi.

Bukti rinci: phase02-browser-checks.json. Screenshot: screenshots/phase02-devices-demo.png, phase02-device-form-mobile.png dan phase02-overview-live-unconfigured.png. Dua screenshot pertama berlabel DEMO; yang terakhir menunjukkan keadaan aktual belum terintegrasi.

Lint tidak dijalankan pada fase ini. Tidak ada klaim tes integrasi backend/monitoring jaringan atau persistensi berhasil.

## File yang diubah

| Kelompok | File |
| --- | --- |
| Rute/layout | src/app/router.jsx; src/components/layout/AppLayout.jsx |
| Halaman | src/pages/OverviewPage.jsx; NetworkPage.jsx; ServersPage.jsx; DevicesPage.jsx; TopologyPage.jsx; AlertsPage.jsx; MonitoringPages.jsx; FoundationPages.jsx |
| Komponen | src/components/Modal.jsx; monitoring.jsx; HistoryChart.jsx |
| Data | src/data/adapters.js; coreAdapter.js; format.js; MonitoringProvider.jsx; useMonitoring.js; demo/session.js |
| Inventaris | src/devices/model.js; service.js; DeviceForm.jsx; InventoryModals.jsx |
| Styling | src/styles/app.css, helper dialog/resource/topology sesuai variabel template |
| Versi | package.json dan package-lock.json menjadi 0.2.0; dependensi tidak ditambah/diubah |
| Tes | tests/phase02.test.js; tests/data-layer.test.js sebelumnya dipertahankan |
| Dokumentasi/bukti | README.md; docs/API-INTEGRATION.md; DEVICE-INVENTORY.md; PHASE-02-REPORT.md; phase02-browser-checks.json; tiga screenshot Phase 02 |

Implementasi halaman lama yang digantikan dilepas dari export kumpulan halaman untuk menghindari implementasi ganda. Modul Reports/System Health dan foundation lain tetap dipertahankan. Tidak ada file template diubah dan tidak ada file proyek yang dihapus.

## Menjalankan dan rollback

Dev server aktif di http://127.0.0.1:5173/. Untuk menjalankan lagi:

```powershell
Set-Location 'C:\Users\Hype G12\Downloads\nms-dashboard'
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Gunakan terminal baru hanya jika port belum dipakai server proyek ini. Pada checkout baru jalankan npm ci terlebih dahulu. Validasi: npm test dan npm run build. Produksi lokal: npm run preview -- --host 127.0.0.1 --port 4173; ini preview statis, bukan backend atau deployment produksi.

Rollback aman: hentikan dev server proyek ini, ekstrak checkpoint Phase 02 ke direktori pemulihan terpisah, jalankan npm ci lalu dev dengan port kosong. Jangan menghapus proyek saat ini atau menimpa perubahan tambahan tanpa backup. Tidak perlu menyentuh container atau volume homelab.

## Keterbatasan dan pekerjaan berikutnya

Build menghasilkan warning ApexCharts sekitar 748.49 kB (210.17 kB gzip). Grafik memakai chunk dinamis; CSS template penuh sekitar 483.67 kB (69.95 kB gzip). Warning tidak menggagalkan build. Optimasi template lebih jauh belum dilakukan agar paket UI yang disediakan tetap tersedia.

Langkah berikutnya yang diperlukan adalah gateway same-origin terautentikasi serta endpoint inventaris/ACK/discovery server-side, kemudian tes integrasi dengan data nyata. Itu membutuhkan scope backend tersendiri; tidak dikerjakan pada Phase 02 ini. Detail konfigurasi non-rahasia dan kontrak yang sudah ditemukan ada pada API-INTEGRATION.md; model inventaris pada DEVICE-INVENTORY.md.
