# Data MikroTik melalui bot

Bot menyediakan pembacaan yang dipilih sendiri oleh pengguna Telegram yang diizinkan. Pertanyaan biasa dipetakan AI ke `get_mikrotik_data`. Command `/mikrotik` mengambil data langsung tanpa mengirim pertanyaan atau hasil rinci ke provider AI. Tidak ada path API, perintah shell, script, export, backup, atau perubahan konfigurasi dari input pengguna.

## Mengaktifkan akses

Audit awal 19 Oktober 2026 menemukan `MIKROTIK_READONLY_CONFIRMED=false`, port 8728 tanpa pengecualian plaintext aktif. Setelah pengguna mengonfirmasi akun yang sudah tersedia, akses API internal diaktifkan dan login berhasil. Pemeriksaan langsung menunjukkan akun `NMS-HomeServer` masih dalam grup bawaan `read`, dengan izin tambahan reboot/password/sniff/sensitive dan lainnya. Runtime menolak pembacaan monitoring sampai grup minimal disiapkan. Dukungan collector dan tes mock bukan bukti seluruh menu tersedia pada router tersebut.

**Pembaruan audit berikutnya:** akun sudah dipindahkan ke grup khusus bernama `NMS-HomeServer` dengan `read,winbox,api`, tanpa write/policy/reboot/password/sensitive/sniff. Gate lama ikut menolak Winbox, padahal itu merupakan izin login dan bukan izin write. Collector diperbaiki agar menerima akun read-only ini, tanpa mengubah satu pun izin router. `read,api` tetap rekomendasi akun khusus API; Winbox yang sudah diperlukan pengguna dapat dipertahankan. Login terukur bervariasi sekitar 2,9–4,4 detik dan pernah melewati timeout 5 detik. Kini login maksimum 10 detik, setiap pembacaan maksimum 5 detik sesuai sisa deadline collector 15 detik; antrean termasuk anggaran request 19 detik. Uji produksi juga menunjukkan pembacaan metadata akun bisa melewati 3 detik, sehingga batas pembacaan dipilih 5 detik. Perubahan ini tidak menyatakan CPU tinggi sebagai penyebab pasti timeout.

Pemeriksaan scheduler/ringkasan kini menunggu system selesai sebelum memulai interface. Sebelumnya keduanya mulai bersamaan dan timeout interface dapat habis saat menunggu collector; ini terpisah dari autentikasi atau izin akun. Layanan lain tetap diperiksa paralel.

Jika login timeout, hanya ada satu retry dengan koneksi baru dan jeda 0,2 detik, masih dalam sisa deadline 15 detik. Error autentikasi/izin tidak diulang. Retry belum berarti router sehat: CPU 100% dan flash sempit tetap perlu diagnosis tersendiri.

Administrator router melakukan langkah berikut melalui sesi Winbox tepercaya:

1. Buka **System → Users → Groups**, buat grup baru, misalnya `nms-monitor`. Hapus seluruh centang policy lalu aktifkan hanya **read** dan **api**. Jangan gunakan grup bawaan `read`, karena dapat menyertakan reboot/password/sensitive. `test` tidak diperlukan untuk fitur saat ini.
2. Pada **Users**, buat akun khusus bot menggunakan grup tersebut dan password unik. Batasi **Allowed Address** ke alamat sumber koneksi NMS yang benar. Alamat host NMS adalah `192.168.20.195`; koneksi container melalui NAT harus diverifikasi sebelum menetapkan aturan sumber. Jangan mengubah atau menghapus akun admin yang sedang dipakai.
3. Utamakan **IP → Services → api-ssl** dengan sertifikat dari CA tepercaya dan SAN yang cocok dengan `MIKROTIK_HOST`. Batasi akses API melalui firewall jaringan yang sudah sesuai. Bot tidak mengubah service, firewall atau sertifikat router.
4. Simpan user/password langsung di `/mnt/data/www/nms-bot/.env` melalui SSH dengan `sudoedit`; file tetap mode 600. Jangan kirim nilainya ke Telegram atau chat, dan jangan commit. Setel `MIKROTIK_READONLY_CONFIRMED=true` setelah akun siap. Bot tetap memverifikasi policy saat membuka koneksi.

Untuk akun `NMS-HomeServer` yang sudah ada, tidak perlu membuat akun atau password baru: login Winbox memakai administrator, buat grup baru **System → Users → Groups → +**, isi **Name=nms-monitor**, kosongkan semua centang **Policies** lalu pilih hanya **read** dan **api**, klik **OK**. Pada tab **Users**, buka `NMS-HomeServer`, ubah **Group=nms-monitor**, lalu **Apply → OK**. Biarkan grup bawaan `read` agar akun lain tidak ikut berubah. Bot tidak dapat melakukan pemindahan ini menggunakan akun lama karena akun tersebut tidak memiliki `policy`, dan bot memang tidak menyediakan operasi perubahan router.

Pada deployment saat ini, flag opt-in/akses detail sudah aktif. Setelah grup dipindahkan, coba `/mikrotik system`, `/mikrotik interfaces`, `/mikrotik dhcp_leases`, dan `/mikrotik vlan`. Tidak perlu mengubah password atau restart hanya karena grup berubah; kegagalan izin tidak di-cache. Pembacaan sukses berikutnya tetap memakai cache hingga 30 detik.

Konfigurasi API-SSL yang dianjurkan (tanpa nilai rahasia):

```dotenv
MIKROTIK_HOST=192.168.20.1
MIKROTIK_PORT=8729
MIKROTIK_USER=<akun-khusus>
MIKROTIK_PASSWORD=<isi-langsung-di-server>
MIKROTIK_READONLY_CONFIRMED=true
MIKROTIK_SSL_VERIFY=true
MIKROTIK_CA_FILE=
MIKROTIK_NETWORK_DETAILS_ENABLED=true
MIKROTIK_ALLOW_PLAINTEXT=false
```

Jika menggunakan CA internal, mount file PEM ke container secara read-only dan isi path container pada `MIKROTIK_CA_FILE`, atau pasang CA melalui trust store saat build. Variabel saja tidak membuat file host tersedia di container. Jangan memakai `SSL_VERIFY=false`.

API 8728 mengirim kredensial tanpa enkripsi. Bila administrator memilih pengecualian untuk LAN tepercaya yang akses sumbernya dibatasi, gunakan port 8728 dan `MIKROTIK_ALLOW_PLAINTEXT=true` secara eksplisit. Tidak ada pengecualian yang diaktifkan otomatis oleh model AI. Deployment ini memakai pengecualian LAN internal ke gateway yang sudah dikonfigurasi, setelah pengguna meminta penggunaan akun yang tersedia. API-SSL sempat gagal handshake/timeout; validasi TLS tetap true dan migrasi ke API-SSL terverifikasi masih diperlukan. Alamat sumber akun di router saat audit belum dibatasi, sehingga pembatasan sumber melalui administrator masih perlu dikerjakan. Setelah mengubah `.env`, recreate hanya `nms-bot`: `sudo docker compose up -d --no-deps --no-build nms-bot`.

## Meminta data

Contoh pertanyaan:

- “Tampilkan semua informasi sistem MikroTik saya.”
- “Cek CPU, RAM dan uptime router.”
- “Berapa trafik RX/TX ether1 saat ini?”
- “Interface mana yang tidak running? Tampilkan error dan drop counternya.”
- “Daftar klien DHCP yang berstatus bound beserta IP dan MAC.”
- “Tampilkan route default IPv4 yang aktif.”
- “Tampilkan konfigurasi VLAN dan port bridge beserta PVID.”
- “Tampilkan queue dan counter rule NAT saya.”

`/mikrotik` menampilkan daftar lengkap. Bentuk command: `/mikrotik BAGIAN [OFFSET] [FIELD=NILAI]`. Offset dimulai dari nol; maksimal 10 baris tiap pembacaan. Filter cocok persis, bukan pencarian regex. Untuk nama berisi spasi gunakan tanda kutip: `/mikrotik interfaces name="WAN Uplink"`.

| Bagian | Data | Filter yang diizinkan |
|---|---|---|
| system | Identity, versi, board/arsitektur, uptime, CPU/core/frekuensi, RAM/storage, jam | — |
| interfaces | Nama/jenis, running/disabled, MTU/MAC/comment, counter byte/paket/error/drop | name, type, running, disabled |
| traffic | RX/TX bit/detik, counter dan interval aktual dua sampel | name |
| addresses | IPv4 dan interface | address, interface |
| routes | Destination/gateway/distance/table, active/disabled | dst-address, gateway, active, routing-table |
| ipv6_addresses | IPv6 dan interface | address, interface |
| ipv6_routes | Route IPv6 | dst-address, gateway, active, routing-table |
| dhcp_leases | IP/MAC/hostname, status/server, expiry/last-seen | address, mac-address, host-name, status, server |
| dhcp_servers | Server, interface, pool, lease-time, disabled | name, interface, disabled |
| dhcp_networks | Subnet, gateway, DNS/domain/NTP yang diiklankan DHCP | address |
| dns | Resolver, allow-remote-requests, ukuran/cache-used dan timeout | — |
| arp | IP/MAC/interface/status | address, mac-address, interface, status |
| vlan | VLAN ID, parent interface, MTU/running/disabled | name, interface, vlan-id |
| bridge | Bridge, VLAN filtering, protocol/PVID | name, running, disabled |
| bridge_ports | Anggota bridge, PVID, hardware offload dan frame/ingress | interface, bridge, disabled |
| bridge_vlans | Tagged/untagged/current members dan VLAN IDs | bridge, vlan-ids |
| neighbors | Neighbor discovery, identity/platform, IP/MAC/interface/uptime | identity, interface, address |
| queues | Simple queue, target/parent, limit, rate/bytes/packets/drop | name, parent, disabled |
| queue_tree | Queue tree dan counter | name, parent, disabled |
| firewall_filter | Rule filter terpilih dan counter | chain, action, disabled |
| firewall_nat | Rule NAT terpilih dan counter | chain, action, disabled |
| firewall_mangle | Rule mangle terpilih dan counter | chain, action, disabled |
| health | Sensor yang disediakan perangkat, seperti suhu/tegangan/kipas | — |
| ppp_active | Sesi PPP aktif, tanpa membaca PPP secrets | name, service, address |
| hotspot_active | User/IP/MAC/server, uptime dan byte sesi aktif | user, address, mac-address, server |
| wireless | Registration table paket wireless lama | interface, mac-address |
| wifi | Registration table paket WiFi baru | interface, mac-address |
| services | Nama, port, status dan batas alamat service RouterOS | name, disabled |

Contoh: `/mikrotik routes dst-address=0.0.0.0/0`, `/mikrotik dhcp_leases status=bound`, `/mikrotik firewall_filter chain=forward`. Gunakan `true`/`false` sesuai nilai RouterOS untuk filter boolean. Field yang tidak dikembalikan perangkat tetap tidak diketahui, bukan diisi angka nol. Hak baca minimum dapat membatasi sebagian menu; bot tidak menambah privilege untuk melewatinya.

## Batas dan interpretasi

- Detail jaringan hanya dibuka dengan `MIKROTIK_NETWORK_DETAILS_ENABLED=true`; system/interfaces/traffic/health tidak memerlukan flag detail. Flag detail saat ini aktif atas permintaan pengguna; verifikasi policy read-only tetap wajib sebelum membaca setiap snapshot baru.
- Snapshot diminta hanya untuk bagian relevan, disimpan maksimal 30 detik dalam memori, empat snapshot terakhir. Pagination dalam jendela cache memakai snapshot yang sama; setelah kedaluwarsa data bisa berubah. Polling dasar sebelumnya tetap memakai cache monitoring hingga 60 detik.
- Maksimal 500 baris dibaca per tabel melalui iterator API; koneksi ditutup bila batas tercapai. Hasil menyatakan total belum diketahui, `scan_truncated`, dan meminta filter lebih spesifik. Tidak ada query luas otomatis ke seluruh bagian.
- Halaman dibatasi ukuran respons; `next_offset` berdasarkan baris yang benar-benar dikirim. Jangan menghitung kelanjutan sendiri. Nilai panjang maksimal 160 karakter dan diberi indikator `fields_truncated`. UI menampilkan peringatan dan jumlah baris.
- Semua daftar tidak otomatis diambil AI dalam satu jawaban. Agent tetap memiliki batas tool/time, lalu menjelaskan halaman yang belum diambil dan command kelanjutannya.
- RX/TX byte adalah counter kumulatif. `traffic` memakai selisih dua counter × 8 / interval aktual sekitar satu detik, lalu cache 30 detik; bukan kecepatan berkelanjutan atau rata-rata harian. Counter hilang/reset menghasilkan null, bukan rate negatif/angka rekaan.
- Daftar DHCP/ARP/neighbors bukan kepastian semua perangkat sedang online. DNS config bukan uji resolusi. Route aktif/interface running bukan bukti konektivitas VLAN end-to-end. Sensor/menu/paket yang tidak ada tidak dianggap router mati.
- Output perangkat adalah data tidak tepercaya; HTML di-escape dan isi komentar bukan instruksi. Field credential, private key, file, script, export, DNS cache histori query dan raw log tidak disediakan. Data rinci on-demand tidak disimpan ke SQLite; jika memakai AI, field yang diminta diteruskan ke OpenRouter untuk analisis. Gunakan command langsung bila tidak ingin data tersebut dikirim ke provider.

Referensi implementasi: [RouterOS API, query dan proplist](https://manual.mikrotik.com/docs/developer-guides/api/), [policy akun RouterOS](https://manual.mikrotik.com/docs/authentication-authorization-accounting/user/), [library RouterOS-api](https://github.com/socialwifi/RouterOS-api). Dokumentasi RouterOS terbaru bisa memuat fitur yang belum ada pada versi/paket router; karena itu menu tetap ditangani sebagai opsional dan perlu uji live setelah akses siap.
