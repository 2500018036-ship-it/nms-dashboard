> Catatan historis Phase 3. Kemampuan role, konfigurasi, ACK, log aplikasi, integrasi dan Proxmox terbaru dijelaskan dalam [kontrak Unified](UNIFIED-PLATFORM-REPORT.md). Transport SSH/same-origin dan endpoint lama tetap dipertahankan.

# Integrasi API Phase 3

Diverifikasi 23 Oktober 2026. Frontend: Windows `C:/Users/Hype G12/Downloads/nms-dashboard`. Backend yang dipertahankan: Debian 13 `192.168.20.195`, `/mnt/data/www/nms-bot`, container `nms-bot`. Bukan dua proyek pada mesin yang sama.

## Arsitektur

```text
Browser React → /nms-api (origin Vite loopback 5173)
 → proxy dengan allowlist metode/path dan pemeriksaan Origin
 → SSH local forward 127.0.0.1:18765
 → server 127.0.0.1:8765 → API Python dalam NMS
 → SQLite cache monitoring bersama Telegram
```

Framework HTTP stdlib yang sudah dipakai backend dipertahankan. Tidak dibuat engine monitoring kedua. Endpoint read-only membuka SQLite `mode=ro`; hanya tabel sesi autentikasi pada file terpisah yang ditulis. Refresh UI membaca cache, bukan menjalankan probe.

## Transport dan konfigurasi

`VITE_NMS_API_ENABLED=true`, `VITE_NMS_API_BASE=/nms-api`, `NMS_API_TARGET=http://127.0.0.1:18765` di `.env.local`. Semua VITE_* publik. Target proxy hanya boleh origin loopback HTTP(S), tanpa credential, path, query, fragment. TLS HTTPS tetap diverifikasi. Tidak ada CORS wildcard atau Authorization yang disisipkan browser/proxy.

Jalankan `powershell -NoProfile -File scripts/start-local.ps1`. Bila Vite sudah aktif, `-TunnelOnly` hanya memastikan tunnel tersedia. Kunci lokal `%USERPROFILE%/.ssh/nms_dashboard_tunnel` terbatas pada forward menuju port NMS loopback; tidak menyediakan shell umum. Pada komputer baru, pengelola harus memasang kunci tunnel khusus/known_hosts dengan pembatasan yang setara, bukan membuka API ke LAN/internet.

`.runtime/tunnel-error.log` dan `tunnel.pid` membantu diagnosis. Bila port 18765 dimiliki proses yang tidak cocok, script berhenti tanpa mematikan proses. Setelah mengubah environment, restart dev server proyek ini. Build `dist/` tidak menyediakan reverse proxy sendiri; deployment produksi belum dilakukan dan memerlukan gateway HTTPS same-origin, cookie Secure, dan fallback SPA.

## Autentikasi

| Endpoint | Request | Respons |
| --- | --- | --- |
| POST /api/auth/login | JSON username (1–80), password (1–512), remember (boolean opsional) | user, expires_at, idle_timeout_seconds; Set-Cookie |
| GET /api/auth/session | Cookie sesi | identitas operator dan masa berlaku; 401 jika tidak valid |
| POST /api/auth/logout | JSON `{}` + cookie | `{ok:true}`; sesi dicabut dan cookie dihapus |

Username operator `nms`; password berasal dari DASHBOARD_PASSWORD di sisi server. File operator privat: `/home/azril/.config/nms/dashboard-login.json`; salinan lokal `%USERPROFILE%/.ssh/nms-dashboard-login.json`. Jangan kirim nilai ke chat/log atau commit file tersebut. Credential dashboard telah dirotasi saat implementasi awal Phase 3 karena konfigurasi frontend sebelumnya pernah memuat secret.

Cookie `nms_session`: HttpOnly, SameSite=Strict, Path=/; tanpa Max-Age pada sesi biasa. Batas absolut 8 jam, idle 30 menit. Remember: absolut 7 hari, idle 1 hari, Max-Age=604800. Request valid memperbarui aktivitas sesi. Token acak tidak tersedia ke JavaScript; server hanya menyimpan hash token dalam `dashboard-auth.sqlite3` permission 600. Sesi tetap ada setelah restart, tetapi habis masa berlaku/logout/rotasi password membuatnya tidak valid.

POST harus same-origin, JSON dan schema ketat; field role/admin tambahan ditolak. Backend menerima payload autentikasi maksimum 4096 byte. Batas percobaan autentikasi 10 kegagalan/menit per alamat dan 120 request/menit per alamat. Proxy membuat beberapa browser berbagi kuota alamat; bukan sistem multi-user produksi. Basic auth lama dipertahankan untuk pemakai API lama, tidak disisipkan oleh frontend. Cookie Secure belum digunakan khusus transport HTTP loopback lewat SSH; jangan membuka deployment ini ke internet.

Frontend memeriksa sesi saat startup, fokus dan setiap 60 detik, menangani expiry, serta memberi tahu tab lain melalui BroadcastChannel saat login/logout. Data workspace dibuang saat provider dilepas. Gagal logout tidak diberi pesan seolah sesi berhasil dicabut.

## Endpoint monitoring

Semua route berikut GET, memerlukan sesi valid atau Basic auth legacy, dan hanya membaca hasil collector yang sudah ada. Prefix browser: `/nms-api`.

| Route | Parameter | Format ringkas | Batas |
| --- | --- | --- | --- |
| /api/status | tidak ada | checks[], alerts[], server_time, interval, version, source | 100 check terbaru per target, 500 state |
| /api/devices | tidak ada | devices[], server_time, read_only:true | kelompok alamat dari collector; bukan inventaris CRUD |
| /api/devices/{id} | device_[a-f0-9]{12} | device, checks[] | 404 bila tidak ditemukan |
| /api/metrics | target wajib | target, check, read_state | target allowlist konfigurasi/collector; tidak menerima URL |
| /api/services | tidak ada | services[], server_time | check metode HTTP/DNS/TCP/ICMP |
| /api/health | tidak ada | version, status, at, last_cycle, poller_ready, scheduler_error, interval, source, server_time | heartbeat bot; bukan uji AI |
| /api/events | tidak ada | events[{time,key,kind,detail}] | 50 event terbaru |
| /api/history | target opsional, default debian | target, points[{time,status,cpu_percent,memory_percent,latency_ms}] | 120 sampel terbaru, berurutan waktu |

Target history frontend: debian, mikrotik_system, docker, proxmox_resources. Backend juga mengenali target collector yang dikonfigurasi. Unknown parameter, parameter berulang, target tidak diizinkan atau ID salah menghasilkan 400. Endpoint mutasi konfigurasi/discovery/ACK tidak dibuka; 405 untuk metode tulis. Device ID adalah hash alamat, bukan ID inventaris permanen.

Contoh bentuk data (skema ilustratif, bukan pembacaan produksi):

```json
{"target":"debian","check":{"target":"debian","method":"host snapshot","status":"UP","reported_status":"UP","read_state":"up","sample_epoch":1792736811,"stale":false,"cpu_percent":7.3,"memory_percent":41.0}}
```

Field yang tidak tersedia adalah null/array kosong, bukan angka nol. Payload hanya memproyeksikan field metrik yang dikenali; raw logs, comment perangkat, header auth, WireGuard key dan field rahasia tidak diteruskan. Array dibatasi 16 node, 100 guest/container, 200 interface/daftar RouterOS. Detail event hanya berisi judul, perangkat, severity dan waktu; event lama menggunakan default rule yang sama dengan formatter Telegram (`severity_source:rule_default`), bukan diagnosis AI baru.

## Status dan kesegaran

UP/DOWN/DEGRADED/UNKNOWN adalah hasil pemeriksaan relevan. `read_state` membedakan up/degraded, offline (check DOWN), collection_failed, unavailable dan stale. Check DOWN dari ICMP/TCP tidak membuktikan seluruh host offline. Pengelompokan device menampilkan DEGRADED jika salah satu collector gagal, disertai penjelasan lingkup; UNKNOWN jika data belum lengkap.

Waktu sampel memakai yang lebih awal antara waktu simpan dan timestamp observasi. Lebih lama dari max(120 detik, 3 interval), dibatasi 1 jam, menjadi UNKNOWN. Frontend mengevaluasi usia ulang tiap 15 detik; resource lama dikosongkan. Heartbeat yang gagal dibaca/kedaluwarsa tidak ditampilkan sebagai bot sehat. Timestamp UI menggunakan Asia/Jakarta/WIB.

## Client, loading dan error

Satu `src/data/apiClient.js`: same-origin cookie, timeout 8 detik, batas streaming JSON 2 MiB, tidak mengikuti redirect, tanpa mencetak respons error mentah/credential. `MonitoringProvider` membaca status/events/devices/health sebagai satu siklus, berbagi state antarhalaman. Interval mengikuti API (60 detik saat diuji), dibatasi 30–300 detik. Error konektivitas dicoba kembali setelah 60 detik; autentikasi/rate limit menghentikan retry terkait. Tidak ada fallback demo otomatis. Chart RX/TX menyimpan 120 sampel/interface, maksimum 200 interface dalam memori browser; bukan database trafik historis.

| HTTP | Makna |
| --- | --- |
| 400 | query/schema/target tidak valid |
| 401 | login salah atau sesi tidak valid |
| 403 | Origin/Host tidak diizinkan |
| 404 | endpoint/perangkat tidak ditemukan |
| 405 | endpoint baca saja/metode tidak didukung |
| 413/414/415 | ukuran/path/content type tidak valid |
| 429 | rate limit, Retry-After 60 detik |
| 502 | proxy dev tidak dapat menjangkau backend |
| 503 | data cache belum dapat dibaca |

## Operasi dan rollback

Source/test backend diubah hanya pada app/dashboard dan pengujiannya. Compose, Dockerfile, bot.py, collector dan konfigurasi jaringan dipertahankan. Backup awal `backups/phase3-20261022T002919Z`, backup final `backups/phase3-20261023-final`. Tag rollback final `nms-bot:phase3-rollback-20261023`.

Perintah final yang telah dijalankan di server:

```sh
python3 -m py_compile app/dashboard/server.py app/dashboard/projection.py app/dashboard/sessions.py
docker compose config --quiet
docker build --target test -t nms-bot:phase3-test .
docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m nms-bot:phase3-test
docker build --target production -t nms-bot:phase3-candidate .
docker image tag nms-bot:phase3-candidate nms-bot:local
docker compose up -d --no-deps --no-build nms-bot
```

Rollback image, dari direktori backend setelah memeriksa backup/tag:

```sh
docker image tag nms-bot:phase3-rollback-20261023 nms-bot:local
docker compose up -d --no-deps --no-build nms-bot
```

Untuk memulihkan source, ekstrak arsip dashboard-before.tar.gz ke direktori terpisah dan bandingkan dahulu; jangan menimpa perubahan pengguna berikutnya. Pertahankan data/ dan credential terbaru. Tidak perlu compose down, volume prune atau restart host.

## Batas integrasi

MikroTik/traffic/WireGuard, Debian/Docker, DNS dan layanan web tampil dari collector aktual. Proxmox token sudah tersedia menurut pemeriksaan keberadaan, tetapi API resource masih tertahan validasi TLS; sertifikat/CA harus disiapkan sebelum menyatakan VM/LXC dapat dipantau. Cisco IP manajemen/SNMP belum dikonfigurasi. Tidak ada pemindaian baru atau bypass TLS.

Belum tersedia: konfigurasi inventaris tersimpan, uji koneksi/discovery/approval dari UI, ACK persisten, AI chat web, log mentah, user/RBAC dan audit administratif. Modul tersebut menampilkan batas kemampuan; tidak mengklaim operasi sudah dilakukan. Dokumen Phase 00–02 adalah catatan historis dan bukan status konektivitas Phase 3.


## Tambahan Phase 4

GET /api/logs, /api/incidents dan /api/incidents/{id} menambahkan filter/pagination log serta kronologi incident dari penyimpanan bersama. Kontrak, validasi, retensi, migrasi, status kanal notifikasi, pengujian dan rollback dijelaskan pada [PHASE-04-REPORT.md](PHASE-04-REPORT.md). Tidak ada endpoint ACK/resolusi manual atau remote syslog yang diaktifkan.
