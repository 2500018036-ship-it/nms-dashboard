# Laporan Phase 3 — Backend Integration Foundation

Tanggal penutupan verifikasi: 23 Oktober 2026. Scope Phase 3 selesai sejauh akses tersedia; Phase 4 belum dimulai.

## Hasil dan penyebab masalah

Implementasi sebelum perbaikan memakai identitas login browser dan beberapa indikator contoh, sehingga tampilan terkesan terintegrasi tanpa otorisasi/data server yang memadai. API lama memakai Basic auth dan belum memiliki kontrak daftar perangkat/sesi yang cocok untuk React. Solusi mempertahankan HTTP server Python, bot, collector, SQLite, template Metis dan struktur React yang sudah ada.

Masalah tambahan yang ditemukan dan diperbaiki:

- Salah klasifikasi host akibat field CPU null dan array disk kosong.
- Binding observedDevices yang hilang pada halaman Devices.
- Metadata alert legacy tidak selalu menyimpan title/severity; kini proyeksi API mengikuti default formatter Telegram. Pending kosong tidak menutupi last_event.
- Status heartbeat lama tidak lagi dipertahankan sebagai UP saat API gagal/kedaluwarsa.
- Context autentikasi dipisah dari komponen provider agar identitas context stabil pada refresh development; import provider eksplisit menghindari benturan nama resolver Windows.
- ID event log acak dan error lint lainnya diperbaiki; template referensi dikecualikan dari lint aplikasi tanpa mengubah filenya.

## Arsitektur dan fitur yang selesai

React Windows → proxy same-origin → tunnel SSH loopback → API NMS Debian → cache monitoring SQLite yang sama dengan Telegram. Tidak ada engine polling perangkat baru di browser. Pembaruan UI mengikuti interval cache 60 detik saat verifikasi.

Login memvalidasi akun di server, cookie HttpOnly/SameSite=Strict, sesi persisten berisi hash token, expiry absolut/idle, logout mencabut sesi, sinkronisasi tab, penjagaan route dan deep-link return. Password/token tidak dimasukkan bundle atau localStorage. Login contoh/admin lokal dihapus dari alur aktif. Halaman yang belum punya API menampilkan batas kemampuan.

Overview, Network, Servers & Services dan Device Management membaca data nyata. Detail perangkat memakai endpoint cache tanpa probe baru. Alert/event, resource history dan system health juga membaca backend. CRUD/discovery/ACK tidak dibuka. UI/UX Metis tetap digunakan, termasuk sidebar, navbar, login, tema, card, tabel, form, dialog dan breakpoint.

Endpoint yang dipakai/dibuat: GET /api/status, /api/events, /api/history, /api/devices, /api/devices/{id}, /api/metrics, /api/services, /api/health; GET /api/auth/session dan POST /api/auth/login, /api/auth/logout. Schema, parameter, auth, error dan rollback dijelaskan pada API-INTEGRATION.md.

## Verifikasi aktual

| Pemeriksaan | Hasil |
| --- | --- |
| npm test | 50 lulus, 0 gagal |
| npm run lint | Lulus tanpa error/warning |
| npm run build | Lulus; warning ukuran ApexCharts sekitar 748 kB sebelum gzip |
| Backend unittest dalam image test, --network none, filesystem read-only | 204 lulus, 0 gagal |
| py_compile modul API/sesi/proyeksi | Lulus |
| docker compose config --quiet | Lulus |
| Hash source API dalam image vs host saat re-audit | Cocok sebelum revisi final; image final dibangun dari source teruji |
| Login benar / salah / field kosong | Diterima hanya oleh server yang valid / ditolak / validasi tampil |
| Reload sesi, logout antar-tab, Back dan protected deep link | Lulus; sesi tidak dapat dibypass dari browser |
| Kembali ke /servers setelah login dari deep link | Lulus |
| 13 rute pada desktop lebar CSS 1300 px | Heading benar, tidak ada overflow halaman |
| 13 rute pada mobile lebar CSS 381 px | Heading benar, drawer menutup, tidak ada overflow halaman |
| Tema terang/gelap, sidebar desktop/mobile, navbar search | Lulus |
| Form perangkat kosong / valid | Field invalid ditolak; valid diberi keterangan BELUM disimpan |
| Daftar/filter dan detail perangkat | Data nyata terbaca; detail Debian menampilkan collector terkait |
| Tunnel lokal dihentikan untuk simulasi | UI menampilkan API belum dapat dijangkau; jaringan/server tidak dimatikan |
| Tunnel dipulihkan dan dashboard dimuat ulang | Sesi dan data live kembali terbaca |
| Console setelah reload dan pemeriksaan final 13 rute | Tidak ada error runtime baru |
| Template folder vs ZIP | 159/159 file cocok, tidak ada perubahan |
| Scan password operator aktual dan pola token pada source/bundle/dokumen | Tidak ditemukan |
| Telegram getMe pascadeploy | HTTP 200, ok=true, @theaznmsbot |
| Telegram heartbeat | poller_ready=true, scheduler_error=false |
| Restart count NMS setelah deploy | 0; running/healthy |
| Perbandingan ID container layanan lain sebelum/sesudah deploy final | Tidak ada perubahan |

Pengujian backend awal revisi final sempat menemukan dua kegagalan pada default metadata yang masih berisi null; diperbaiki sebelum deployment dan seluruh 204 tes kemudian lulus. Error context development saat pengeditan juga diperbaiki dan diperiksa kembali lewat reload/routing final. Hasil unit test tidak dianggap bukti seluruh integrasi perangkat tersedia.

## Data live yang benar-benar dibaca

Snapshot verifikasi: 26 collector (21 UP, 3 UNKNOWN, 2 DOWN), 11 kelompok alamat/perangkat teramati, 17 service check dan 120 titik riwayat Debian. Angka berubah mengikuti pemeriksaan nyata; bukan fixture.

| Sumber | Status verifikasi |
| --- | --- |
| MikroTik | System/resource, 12 interface teramati, RX/TX, kapasitas/utilisasi bila tersedia, route dan WireGuard dari API backend; terbaca |
| Debian | CPU, RAM, disk, uptime dan SSH; terbaca |
| Docker | Daftar/status/health/restart dan resource yang disediakan collector terbatas; terbaca |
| Technitium | Resolusi DNS A melalui collector DNS; terbaca |
| HTTP/HTTPS | Web, cloud storage, portfolio sesuai target yang dikonfigurasi; terbaca |
| Proxmox | Host ICMP merespons; HTTP/API resource UNKNOWN akibat TLS. Token hadir, izin/kegunaan token belum dapat diverifikasi sebelum TLS diperbaiki |
| Cisco SF200-24 | Neighbor teramati dari MikroTik; IP manajemen/SNMP belum tersedia, metrik port belum aktif |
| Dua client DHCP | ICMP tidak merespons; ditampilkan sebagai check gagal, tidak menyimpulkan host pasti mati |

MikroTik masih menggunakan API internal tanpa TLS menurut metadata collector; Phase 3 tidak mengubah transport atau konfigurasi router tersebut. Upgrade API-SSL memerlukan sertifikat/config terpisah. Tidak ada bypass TLS Proxmox atau perubahan jaringan.

## Deployment dan backup

Hanya service nms-bot dibangun/recreate dengan --no-deps --no-build. Compose, Dockerfile, bot.py, engine monitoring dan konfigurasi jaringan tidak diubah dalam Phase 3. Tidak ada compose down, penghapusan volume, restart host atau perubahan aplikasi lain.

Backend: `/mnt/data/www/nms-bot/backups/phase3-20261022T002919Z` dan `backups/phase3-20261023-final`; rollback image final `nms-bot:phase3-rollback-20261023`. Frontend: direktori saudara `nms-dashboard-checkpoints/phase03-20261022/frontend-before.zip` dan `phase03-20261023/frontend-before-final.zip`. Backend .env hanya berubah pada credential dashboard dalam implementasi awal; nilai tidak dipublikasikan.

Frontend berjalan lokal pada http://127.0.0.1:5173/ melalui scripts/start-local.ps1. Build dist berhasil tetapi belum di-host publik. Akses memerlukan akun operator dan tunnel privat yang tersedia pada komputer ini.

## Batas dan langkah manual

- Siapkan CA/sertifikat Proxmox yang terpercaya; lalu validasi token PVEAuditor melalui collector. Data VM/LXC tetap UNKNOWN sampai pembacaan berhasil.
- Temukan IP manajemen Cisco dan siapkan akses SNMP read-only; belum ada scanning luas atau perubahan switch.
- CRUD inventaris, discovery/approval, ACK persisten, credential UI, AI chat web, raw logs dan multi-user/RBAC tetap menunggu fase/API selanjutnya.
- Riwayat resource berasal dari SQLite; grafik trafik browser hanya buffer sesi, belum seri trafik persisten melalui endpoint history.
- Pengujian pascadeploy Telegram menggunakan getMe dan heartbeat; pesan masuk dari akun manusia tidak diuji ulang pada penutupan fase. Collector dan alur bot tidak diubah.
- Akses produksi melalui domain/HTTPS dan hardening multi-user belum dideploy. API tetap loopback; Vite bukan server publik produksi.

## File backend

Diubah: app/dashboard/server.py, tests/test_dashboard.py. Ditambah: app/dashboard/sessions.py, app/dashboard/projection.py, tests/test_dashboard_sessions.py, docs/DASHBOARD-API-PHASE3.md. Dokumentasi README backend mendapat tautan integrasi. Tidak mengubah collector/Compose/bot Telegram.

## File frontend terhadap checkpoint awal Phase 3

- .gitignore
- README.md
- config/devProxy.js
- docs/API-INTEGRATION.md
- docs/phase03-browser-checks.json
- docs/screenshots/phase03-devices-mobile.png
- docs/screenshots/phase03-overview-live.png
- docs/screenshots/phase03-overview-mobile.png
- eslint.config.js
- package.json
- scripts/start-local.ps1
- src/App.jsx
- src/app/router.jsx
- src/components/layout/AppLayout.jsx
- src/data/AuthContext.jsx
- src/data/MonitoringProvider.jsx
- src/data/adapters.js
- src/data/apiClient.js
- src/data/authModel.js
- src/data/authSessionContext.js
- src/data/capabilities.js
- src/data/coreAdapter.js
- src/data/useMonitoring.js
- src/devices/DeviceForm.jsx
- src/devices/ObservedDevices.jsx
- src/devices/model.js
- src/pages/AlertsPage.jsx
- src/pages/AssistantPage.jsx
- src/pages/DevicesPage.jsx
- src/pages/FoundationPages.jsx
- src/pages/HealthPage.jsx
- src/pages/LoginPage.jsx
- src/pages/LogsPage.jsx
- src/pages/NetworkPage.jsx
- src/pages/OverviewPage.jsx
- src/pages/SettingsPage.jsx
- src/pages/UsersPage.jsx
- src/styles/app.css
- tests/phase03.test.js
- vite.config.js
- docs/PHASE-03-REPORT.md
- docs/DEVICE-INVENTORY.md (penanda status dokumentasi historis)
