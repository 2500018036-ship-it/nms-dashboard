> Branch pemulihan lokal `codex/theaz-recovery-20261029` sedang memperbarui baseline historis di bawah. Produksi tetap memakai LibreNMS pada `nms.azrilachdi.web.id`; branch ini belum dipasang ke server atau proxy. Rincian yang sudah diterapkan dan batas dukungan ada di [laporan pemulihan 29 Oktober](docs/THEAZ-RECOVERY-2026-10-29.md).

# Unified NMS Homelab Dashboard

React 0.5.0 menggunakan template pengguna **Metis Bootstrap Admin 3.6.0**. Frontend Windows terhubung ke backend Python NMS 1.2.0 di Debian melalui tunnel SSH privat. Dashboard dan Telegram menggunakan collector, cache, histori dan engine alert yang sama.

Fitur yang telah diterapkan: monitoring aktual, Proxmox node/VM/storage, detail perangkat/layanan, katalog dan launcher dinamis, editor topologi persisten, metadata inventaris, System Settings/maintenance/backup konfigurasi, role/ACK/audit, log NMS, laporan histori/CSV/print PDF, dan AI Assistant dengan tool read-only.

Status lengkap, endpoint, batas keamanan, rollback dan pekerjaan yang masih terhambat tersedia pada [laporan implementasi 24 Oktober](docs/UNIFIED-PLATFORM-REPORT.md). Tidak semua target sehat: MikroTik menunggu perbaikan group read-only, Cisco menunggu IP/SNMP, dan statistik Technitium menunggu token khusus. Tidak ada dummy sebagai data produksi.

## Menjalankan

```powershell
Set-Location 'C:\Users\Hype G12\Downloads\nms-dashboard'
# npm ci hanya jika dependensi belum tersedia
powershell -NoProfile -File scripts/start-local.ps1
```

Buka http://127.0.0.1:5173/. Script memeriksa port milik proyek, memastikan tunnel loopback18765 ke Debian8765, kemudian menjalankan Vite. Tidak menghentikan proyek lain. Untuk Vite yang sudah berjalan, gunakan `-TunnelOnly`.

Login `admin` menggunakan file privat `%USERPROFILE%/.ssh/nms-dashboard-admin-login.json`; operator `nms` memakai `%USERPROFILE%/.ssh/nms-dashboard-login.json`. Nilai password tidak berada di source atau browser storage. User/role baru dikelola oleh Administrator, dengan audit dan pencabutan sesi saat hak akses berubah. Credential perangkat hanya di backend.

Konfigurasi publik `.env.local`:

```dotenv
VITE_NMS_API_ENABLED=true
VITE_NMS_API_BASE=/nms-api
NMS_API_TARGET=http://127.0.0.1:18765
```

Produksi: https://nms.azrilachdi.web.id. Push ke `main` menjalankan lint, tes, build image Docker dan deployment otomatis ke server `192.168.20.195` melalui rilis GitHub. Gateway publik `20.194.8.143` menangani HTTPS. Lihat [panduan deployment produksi](docs/PRODUCTION-DEPLOYMENT.md) untuk arsitektur, pemeriksaan kesehatan, log dan rollback.

## Verifikasi

```powershell
npm run lint
npm test
npm run build
```

Verifikasi24 Oktober:66 tes frontend,244 tes backend, lint dan build lulus. Peringatan ukuran chunk ApexCharts tetap ada. Bukti API/browser dan keterbatasan berada di docs; pengujian mock tidak dinyatakan sebagai uji gangguan fisik.

## Struktur utama

- `src/data`: API client, sesi/auth, monitoring adapter dan PlatformProvider.
- `src/pages`: modul UI dan detail, editor topologi, pengaturan, integrasi, AI dan laporan.
- `src/components`: UI template reusable, modal, chart, tabel dan kontrol jurnal.
- `src/devices`: metadata inventaris server dan alur persetujuan observasi pasif.
- `src/styles`: style template dan penyesuaian NMS terbatas.
- `scripts/start-local.ps1`: peluncur development/tunnel privat.
- `tests`:66 tes otomatis.
- `template-dashboard` dan `template-dashboard.zip`: referensi asli yang dipertahankan.
- `docs`: laporan fase sebelumnya (historis), kontrak integrasi dan laporan Unified terbaru.

Panduan transport awal: [API-INTEGRATION.md](docs/API-INTEGRATION.md). Dokumen Phase3/4 adalah catatan historis; endpoint dan kemampuan yang kini aktif mengikuti laporan Unified terbaru. Inventaris metadata tidak otomatis memasang collector API/SNMP dan tidak mengubah perangkat fisik.

Perbaikan pendaftaran, kelengkapan Device Management, penghapusan dan pelacakan DHCP: [catatan stabilitas perangkat](docs/DEVICE-STABILITY-2026-10-27.md). Backend ikut diuji dan di-deploy dari direktori `backend/`.
