# Audit pengembangan platform — 4 November 2026

Basis: `db78294` (perbaikan IP Docker), mencakup rilis produksi `f87174f`.
Worktree terpisah mempertahankan perubahan lokal `access/tests/probe_targets.py`.

## Arsitektur yang dipertahankan

- Frontend React 19/Vite, Bootstrap, maxGraph (dasar draw.io), noVNC. Provider AI dan topologi sudah berada di atas lifecycle halaman, dengan persistensi backend dan request id.
- Backend Python: collector, scheduler, SQLite, incident engine, dashboard HTTP privat dan bot Telegram dalam container `nms-bot`. Tidak ada kebutuhan database pengguna kedua.
- `platform.sqlite3`: inventaris, integrasi, topologi, settings, accounts, audit, AES-GCM credential vault, assistant history, kebijakan dan versi backup perangkat.
- `nms.sqlite3`: checks, alert_state, events, notifications, incidents, incident_events, application_logs, metadata. `dashboard-auth.sqlite3` menyimpan sesi dan revokasi akun.
- Portal: gateway `nms-access`, broker Unix milik root, Chromium terisolasi tanpa network Docker, egress hanya origin terpilih, sesi per login dengan lease, TTL dan cleanup.
- HTTPS publik → Nginx VPS → Nginx Proxy Manager → dashboard/backend/access. Konfigurasi router, WireGuard, firewall dan layanan homelab berada di luar cakupan perubahan ini.

## Temuan

1. Wizard sudah memiliki SNMP/SSH, tetapi API RouterOS/PVE masih menjadi pilihan normal; SSH memerlukan pembukaan vault setelah pendaftaran dan panduan Cisco sebelumnya tidak cocok untuk SF200.
2. SNMP baru membaca identitas dan IF-MIB; tidak boleh mengklaim CPU/RAM/VLAN/sensor tanpa membaca OID terkait. Discovery harus independen dari pilihan kategori agar kategori yang dimatikan bisa diaktifkan kembali.
3. Snapshot global hanya memasukkan empat metode inventaris, menghilangkan SNMP/SSH. Daftar perangkat Overview belum memiliki filter kategori dan relasi induk fisik.
4. Binding target lama bisa mencocokkan host/metode sehingga perangkat baru meminjam jadwal collector lama. Inventaris baru harus memiliki target dan interval sendiri.
5. Portal backend dan broker masih mengandalkan katalog JSON statis. URL baru harus diverifikasi, disimpan dengan alamat koneksi yang divalidasi, diotorisasi, dan dibaca broker dari database yang sama.
6. Startup dashboard/scheduler menunggu koneksi Telegram. Token/allowlist Telegram belum dikelola melalui dashboard dan tidak memakai akun NMS sebagai identitas otoritatif.
7. Incident sudah memiliki waktu/status/ACK, tetapi sebagian nama berasal dari identifier internal. Perlu pemetaan inventaris/induk serta keterangan bila relasi belum diketahui.
8. Reset harus mematikan seeding target lama dan polling konfigurasi lingkungan; mengosongkan tabel saja akan memunculkan perangkat/histori lagi.

## Kondisi server saat audit

Debian `192.168.20.195`: RAM 3921 MiB, tersedia 2273 MiB; disk data 707 GiB tersedia. Container NMS, NPM, Portainer, phpMyAdmin, portfolio dan cloud storage berjalan; tiga container NMS sehat. Database mempunyai 12 perangkat, 11 integrasi, 380815 checks, 902 incidents, 5 credential records. Angka berubah selama polling berjalan.

## Tahapan implementasi dan pengujian

1. Kontrak inventaris, panduan protokol, form SNMP/SSH, discovery nyata, kategori per perangkat dan Overview terfilter.
2. Relasi induk fisik/komponen, penyajian insiden dan Portal Access dinamis dengan otorisasi serta validasi origin di backend dan broker.
3. Integrasi Telegram ke akun, RBAC, konfigurasi token terenkripsi dan lifecycle opsional yang tidak menghalangi monitoring/dashboard.
4. Pengujian regresi/security, pengujian protokol dari poller menggunakan kredensial yang sudah disimpan, uji browser/refresh, build dan rollout terbatas pada NMS jika siap.
5. Backup terakhir, verifikasi SQLite/checksum, rencana reset dengan daftar tabel dan data yang dipertahankan. Reset produksi menunggu persetujuan eksplisit terpisah.

Arsip lama dan backup perangkat tidak dihapus atau digunakan sebagai database pengembangan.
