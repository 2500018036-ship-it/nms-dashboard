# Advanced Unified NMS — tahap fondasi manajemen

Pekerjaan 26–27 Oktober 2026. Frontend Windows `C:/Users/Hype G12/Downloads/nms-dashboard` versi0.6.0; backend Debian `192.168.20.195:/mnt/data/www/nms-bot` versi1.3.0. Template Metis Bootstrap Admin3.6.0, Telegram bot, engine monitoring dan deployment Compose yang ada dipertahankan. Status di bawah membedakan kode, uji mock, dan verifikasi perangkat nyata.

## Hasil audit

- Backend awal sehat, versi1.2.0, restart0. Git branch main, commit3eb98c6; banyak perubahan Phase3/4/Unified belum di-commit. Tidak ada reset atau rewrite. Frontend dan backend berada pada mesin berbeda.
- Inventaris sebelumnya hanya metadata dan topologi belum menghubungkan pendaftaran ke collector. Kini metadata, koneksi monitoring dan identitas node dapat dikaitkan.
- MikroTik login berhasil tetapi gate lama menolak seluruh data karena akun memiliki policy administratif. Permintaan terbaru mengizinkan akun yang mendukung manajemen. Monitoring kini dapat memakai akun tersebut melalui adapter **query baca saja**, dengan opt-in server yang eksplisit. Daftar command AI tetap tidak memiliki operasi konfigurasi.
- API-SSL MikroTik8729 menerima TCP tetapi handshake TLS gagal dengan `SSLV3_ALERT_HANDSHAKE_FAILURE`. Port terbuka tidak disamakan dengan TLS/API yang berfungsi. Operasi tulis diblokir sebelum membuat sesi manajemen plaintext tambahan.
- Cisco `192.168.1.254` tidak merespons koneksi backend pada22,23,80,443. Route host menuju alamat itu memakai gateway192.168.20.1. Tidak ada konfigurasi router/VLAN/firewall yang diubah untuk memaksa akses. Identitas SF200-24 berasal dari pengguna/observasi sebelumnya; firmware dan kemampuan manajemen belum terverifikasi.
- Proxmox TLS dan token monitoring tetap berhasil. Pengguna secara eksplisit memilih **tetap monitoring dahulu**; operasi daya tetap dinonaktifkan.
- Query latest-sample pada database sekitar217MiB terukur15.091,7ms dan memakai temporary sort. Migrasi indeks `checks(target,id DESC)` menurunkannya menjadi0,121ms, tanpa menghapus histori. Pembuatan indeks2,432detik; hanya serviceNMS dihentikan sebentar. Indeks juga dimasukkan pada inisialisasi database agar instalasi baru konsisten.
- Regresi yang ditemukan selama pengembangan telah diperbaiki: pemetaan collector duplikat antara inventaris dan launcher; konsistensi role baru; validasi jenis operasi; perlindungan objek yang masih dirujuk topologi; label status yang membedakan tersimpan dari terintegrasi; encodingUTF-8 pada satu edit UI.

## Implementasi

### Device Connections & Management

Rute baru `/management` memakai sidebar, navbar, card, form, dialog dan tabel template yang sama. Ada pendaftaran/edit perangkat, nama/IP/hostname tambahan, vendor/model, lokasi, peran, grup, interval, metode dan referensi credential backend. Field bersyarat mengikuti protokol. Menyimpan form tidak menghasilkan klaim perangkat sehat.

Metode yang dapat dijalankan: ICMP IPv4, TCP IPv4, DNS A IPv4 dan HTTP/HTTPS. Host harus masuk allowlist System Settings. HTTP menggunakan resolver terkontrol/IP pinning, batas respons, timeout dan validasi TLS. Referensi `routeros-default` dan `proxmox-default` hanya berlaku pada host server yang cocok. SNMP/SSH dapat dicatat sebagai kebutuhan integrasi, tetapi diberi `NOT_CONFIGURED` sampai adapter/akses disiapkan.

Target baru bergabung dengan `Monitoring.all()` dan scheduler yang sama dengan Telegram. Endpoint yang sudah mempunyai collector memakai ID collector lama; URL HTTP yang sama dengan launcher menggunakan cache launcher. Tidak ada polling perangkat langsung dari browser. Batas awal20 monitor inventaris baru; alias collector tidak membuat engine tambahan. Status:CONNECTED, WAITING_FOR_SAMPLE, COLLECTION_FAILED, DISABLED atau NOT_CONFIGURED, disertai hasil UP/DOWN/DEGRADED/UNKNOWN dan timestamp bila tersedia.

### Topologi dan identitas

Editor yang sudah ada tetap mendukung drag, pan, zoom, beberapa diagram dan penyimpanan revisi. Tombol **Perangkat baru + node** menyimpan perangkat ke inventaris lalu menambahkan referensinya ke draft diagram. Pengguna tetap harus menyimpan diagram; inventaris yang belum ditempatkan tetap tersimpan. Daftar inventaris/monitoring menandai perangkat yang sudah ditempatkan. Penghapusan inventaris atau layanan ditolak jika masih dirujuk diagram.

Relasi kini menyimpan port sumber/tujuan, VLAN (0=belum diketahui), kecepatan Mbps (0=belum diketahui), serta jenis Physical/Logical/Trunk/Access/LAG-LACP/Routing/Hosts dan jenis lama. Warna relasi dapat mengikuti **port MikroTik bernama yang benar-benar diamati**. Ini bukan bukti bahwa garis manual atau konektivitas end-to-end sudah terverifikasi. Keberhasilan ping tidak dipakai untuk menyimpulkan kabel. Jenis node IoT dan generic ditambahkan tanpa mengubah desain template.

### Pembacaan RouterOS

Panel MikroTik menyediakan katalog bagian yang sudah didukung collector: resource, interface/counter, IP/route, ARP, DHCP, DNS, bridge/VLAN, queue, firewall/NAT/mangle, neighbor, wireless/WiFi, WireGuard, service dan bagian lain sesuai kemampuan RouterOS. Query eksplisit berbentuk job, maksimal10 baris per halaman dengan metadata kelanjutan. Unsupported/permission/error tetap ditampilkan. Password, private key, script, shell dan export konfigurasi sensitif tidak ditambahkan ke katalog.

AI mendapat tool read-only `check_inventory_device`, dengan ID inventaris tervalidasi dan pemetaan ke collector bersama. Tidak ada tool eksekusi administratif bebas. AI belum menjalankan perubahan infrastruktur; administrator memakai form preview/konfirmasi yang terpisah.

### Rencana perubahan dan role

Backend menyimpan rencana perubahan persisten. Aksi terdaftar saat ini hanya `routeros.interface.comment` serta implementasi adapter `proxmox.guest.start/shutdown/reboot`. Operasi Proxmox sengaja nonaktif sesuai pilihan pengguna. Firewall, route, VLAN, bridge, penghapusan VM/disk, Cisco CLI dan shell bukan operasi yang diaktifkan.

Preview memvalidasi parameter, permission role dan kondisi integrasi. Konfirmasi memerlukan nonce sekali pakai, pemilik yang sama, frasa `APPLY plan_...`, umur rencana maksimum180detik, dan sesi yang masih berizin. State diubah atomik menjadi APPLYING sebelum satu kali eksekusi. Pemeriksaan policy pada adapter baca di-cache maksimal60detik, terikat fingerprint credential/host dan dibatalkan saat permission ditolak; write selalu memverifikasi ulang. Subscription listen mengikuti opt-in elevated yang sama dan memeriksa ulang setiap5menit. Adapter memeriksa ulang keadaan perangkat dan permission sebelum menulis, lalu memverifikasi hasil. Timeout tidak diulang otomatis. Setelah restart, operasi APPLYING menjadi UNKNOWN agar tidak terjadi eksekusi ulang tanpa kepastian. Comment RouterOS memerlukan API-SSL terverifikasi dan policy write; tidak ada bypass sertifikat.

| Role | Hak |
| --- | --- |
| Viewer / Read-only operator | Monitoring dan AI read-only |
| Operator | Baca dan pengelolaan ACK insiden |
| Network Administrator | Inventaris/topologi, preview/aksi jaringan terdaftar, ACK dan audit |
| Server Administrator | Inventaris/topologi, operasi server terdaftar bila diaktifkan, ACK dan audit |
| Super Administrator | Hak konfigurasi NMS, akun, kebijakan dan operasi terdaftar |
| Administrator lama | Alias kompatibel hak administratif; akun lama tidak dihapus/dirotasi |

Role tidak menggantikan permission perangkat. Tidak ada penambahan hak pada akun RouterOS, Cisco atau token Proxmox. Credential profil saat ini mereferensikan konfigurasi server yang sudah ada; vault dinamis lintas perangkat belum tersedia.

## API tambahan

Prefix browser tetap `/nms-api`. Semua POST memerlukan cookie sesi, Origin same-origin, JSON dan skema ketat. GET lama dipertahankan. Error400=validasi/policy,401=sesi,403=permission,404=ID/pemilik tidak cocok,409=konflik/replay/expiry,429=rate limit.

| Route | Kontrak |
| --- | --- |
| GET `/api/platform/management` | Permissions, operasi, policy tulis, metadata credential reference, status inventaris, histori rencana; tanpa secret/nonce lama |
| POST `/api/platform/management/read` | `{section,offset?}` RouterOS; mengembalikan job ID;5 permintaan/menit dan satu job per pengguna |
| GET `/api/platform/jobs/{id}` | Hasil job hanya untuk pemilik; TTL10 menit |
| POST `/api/platform/management/preview` | `{operation,params}`;3 preview/menit/pengguna; before, risiko, blocker, expiry, nonce |
| POST `/api/platform/management/{plan_id}/confirm` | `{confirmation,phrase}`; satu kali; mengembalikan APPLYING; hasil ada di histori |
| POST `/api/platform/inventory/{id}/test` | `{}`; probe/cache sesuai metode yang terdaftar, maksimal5/menit, timeout terkontrol |
| POST `/api/platform/inventory` dan `/{id}` | CRUD lama diperluas field koneksi/lokasi/peran; edit memakai revision |
| POST `/api/platform/topologies` dan `/{id}` | Identitas inventory pada node dan metadata port/VLAN/kecepatan pada relasi |

Field inventaris baru: `location`, `role`, `hostname`, `credential_ref`, `monitor_method`, `monitor_port`, `monitor_url`, `dns_query`. Field `methods`/`profile` lama tetap kompatibel. Mengaktifkan SNMP pada metadata tidak memasang SNMP pada perangkat.

## Konfigurasi dan migrasi

- `MIKROTIK_MONITOR_ALLOW_ELEVATED=true` pada deployment ini: mengizinkan akun yang lebih luas dipakai oleh adapter baca. Default instalasi baru false. Tidak memberi AI hak set/add/remove.
- `NMS_DEVICE_WRITES_ENABLED=true`: hanya mengizinkan alur aksi terdaftar setelah seluruh gate per-perangkat lolos. Saat verifikasi, RouterOS tetap terblokir TLS.
- `PROXMOX_MANAGEMENT_ENABLED=false`: keputusan pengguna; monitoring tetap aktif.
- `PROXMOX_MANAGEMENT_TOKEN_ID/SECRET`: hanya disediakan sebagai opsi server untuk pengembangan berikutnya, tidak dikonfigurasi/diaktifkan pada pekerjaan ini.
- `network.json.switch.management_host` dicatat sebagai192.168.1.254; tidak mengubah IP atau route switch/router.

Migrasi aditif versi2 membuat tabel `change_plans` di `platform.sqlite3`, menyimpan marker `management_schema=2`, dan memperluas payload JSON. Tidak menghapus tabel monitoring/sesi/insiden. Inisialisasi idempotent ada di `app/management/service.py`. Retensi rencana365hari, respons histori dibatasi100. Snapshot SQLite online dibuat sebelum deployment. Backup konfigurasi UI tetap tidak berisi credential, akun atau histori monitoring.

## Verifikasi dan batas klaim

Frontend: lint,70 tes dan build produksi PASS. Warning ukuran chunk ApexCharts masih ada. Backend kandidat akhir:266 tes PASS dalam container `--network none --read-only`; ini mencakup mock eksekusi sekali pakai, replay/expiry/owner/role denial, restart recovery, penolakan plaintext, credential-host binding, target bersama, dependensi topologi dan batas API. Tidak ada eksperimen cabut kabel, start/stop/reboot VM, perubahan komentar router, atau konfigurasi jaringan produksi.

Hasil API live dan pengujian browser akhir dicatat terpisah di `advanced-live-api-checks.json` dan `advanced-browser-checks.json`. Jangan menganggap uji mock sebagai bukti perubahan perangkat nyata. Implementasi write adapter belum dinyatakan teruji pada perangkat produksi karena gate akses/TLS belum terpenuhi.

## Pekerjaan yang belum selesai

1. **BLOCKED — Cisco:** konektivitas ke192.168.1.254, firmware/model aktual dan akses SNMP/SSH perlu disiapkan/diverifikasi. Belum ada pembacaan24port, VLAN/STP/LACP atau penulisan konfigurasi Cisco.
2. **BLOCKED — RouterOS write:** API-SSL gagal handshake. Administrator perlu memeriksa sertifikat/serviceTLS dan jalur ke perangkat; verifikasi CA/hostname tetap wajib. Tidak dilakukan perubahan router otomatis. Pembacaan yang sudah diizinkan sebelumnya tetap melalui API internal plaintext; risikonya tercatat.
3. **NONAKTIF SESUAI PILIHAN — Proxmox:** tetap monitoring. Token baru VM.PowerMgmt tidak diminta lagi dan tidak dibuat.
4. **Belum diimplementasikan:** CRUD firewall/route/VLAN/bridge/queue dengan validasi dependensi dan pemulihan spesifik perangkat, SNMP/SSH collector dinamis, subnet scanning aktif dengan kebijakan approval, credential vault dinamis, incident assignment/komentar/korelasi perubahan, widget per-user, PDF server, SSO/MFA dan console proxy. Fitur tersebut tidak diberi tombol seolah berfungsi.
5. **Akses tambahan:** statistik API Technitium dan administrasi aplikasi lain menunggu metode/credential khusus. Health DNS/HTTP yang ada tetap berfungsi. Embedding mengikuti kebijakan aplikasi; launcher aman tetap menjadi fallback.

## Menjalankan dan rollback

```powershell
Set-Location 'C:\Users\Hype G12\Downloads\nms-dashboard'
powershell -NoProfile -File scripts/start-local.ps1
```

Buka `http://127.0.0.1:5173/management`. Akun admin memakai file privat `%USERPROFILE%/.ssh/nms-dashboard-admin-login.json`. Password/token tidak dicantumkan dalam dokumentasi. Build dist belum dipublikasikan ke internet.

Checkpoint awal: server `backups/advanced-20261026` dan frontend `nms-dashboard-checkpoints/advanced-20261026/frontend-source-before.zip`. Checkpoint sebelum patch akhir: server `backups/advanced-final-20261027`. Image rollback `nms-bot:advanced-final-rollback-20261027` atau `nms-bot:advanced-rollback-20261026`. Pulihkan source dan tag image yang sesuai, validasi Compose, lalu recreate hanya `nms-bot` dengan `docker compose up -d --no-deps --no-build nms-bot`. Pertahankan database terbaru; restore DB hanya setelah backup kondisi terkini dan keputusan administrator. Jangan compose down atau hapus volume.

Referensi primer: [RouterOS API](https://manual.mikrotik.com/docs/developer-guides/api/), [Proxmox permission/token](https://github.com/proxmox/pve-docs/blob/master/pveum.adoc).
