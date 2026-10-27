# Laporan perbaikan koneksi MikroTik — 19 Oktober 2026

## 1. Penyebab yang dibuktikan

Alamat API 192.168.20.1:8728 dapat dijangkau dan kredensial yang sudah tersimpan berhasil login. Akun NMS-HomeServer kini berada di grup khusus NMS-HomeServer, dengan hak aktif read,winbox,api. Hak write,policy,reboot,password,sensitive,sniff dan hak lain tidak aktif. Ini berbeda dengan temuan historis grup bawaan read pada laporan sebelumnya.

Gate bot terlalu ketat: WinBox ikut dianggap izin berlebih. Menurut [dokumentasi policy RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8978504/User), winbox adalah izin login, sedangkan write memberi izin perubahan konfigurasi. Gate dikoreksi tanpa menambah izin atau mengubah konfigurasi router. read,api saja tetap disarankan untuk akun API khusus; login WinBox yang sudah diperlukan pengguna tidak disamakan dengan hak write.

Probe terpisah mengukur pembentukan koneksi TCP sekitar 10 ms, autentikasi beserta koneksi 4,447 detik, pembacaan metadata akun 0,980 detik, dan resource 0,880 detik. Perbedaan ini memisahkan keterjangkauan jaringan dari latensi API.

Login juga lambat dan berubah-ubah: terukur sekitar 2,9–8,7 detik, sehingga batas socket lama 3 detik, lalu 5 detik, kadang terlampaui. Produksi juga menunjukkan metadata akun memerlukan lebih dari 3 detik. Log kini membedakan fase dan mencatat durasi login tanpa password.

Masalah ketiga ada pada scheduler/ringkasan: system dan interface mulai bersama lalu berebut collector serial. Anggaran timeout interface terpakai untuk menunggu system, sehingga interface bisa UNKNOWN walaupun API dapat dibaca. Urutan scheduler diperbaiki menjadi system lalu interface, dengan jendela timeout masing-masing.

## 2. File yang diubah

- app/monitoring/mikrotik.py: gate read-only, klasifikasi fase, batas waktu login/read, deadline termasuk antrean, log durasi aman.
- app/monitoring/mikrotik_catalog.py: petunjuk izin yang sesuai.
- app/services/health.py: urutan collector router dalam ringkasan/scheduler; layanan lain tetap paralel.
- tests/test_mikrotik.py dan tests/test_collectors.py: izin WinBox tanpa write, penolakan hak berbahaya, login lambat, sisa deadline, satu retry timeout, tanpa retry autentikasi/izin, dan urutan pemeriksaan.
- README.md, docs/MIKROTIK.md dan laporan ini.

Tidak ada perubahan compose.yaml, Dockerfile, requirements.txt, .env atau kredensial.

## 3. Perbaikan yang tersedia

Login maksimum 10 detik; setiap pembacaan maksimum 5 detik atau sisa deadline yang lebih kecil. Collector dibatasi 15 detik; request termasuk antrean 19 detik. Timeout login mendapat satu retry setelah 0,2 detik dengan koneksi baru, hanya sebelum query akun/data; percobaan kedua memakai sisa deadline 15 detik yang sama. Error autentikasi/izin dan query data tidak diulang. Tidak ada retry login tanpa batas. Snapshot/pagination/filter/batas hasil dan semua command print read-only tetap dipertahankan. Hak perubahan/sensitif tetap ditolak sebelum pengambilan data.

Command langsung tidak membutuhkan OpenRouter: /mikrotik system, /mikrotik interfaces, /mikrotik dhcp_leases, /mikrotik vlan, dan /mikrotik traffic name=ether1. Halaman interface berikutnya dapat diminta dengan /mikrotik interfaces 10 atau kata lanjutkan sesuai konteks sementara.

## 4. Perintah dan metode pengujian

```sh
docker build --target test -t nms-bot:test .
docker run --rm --network none nms-bot:test
docker compose config --quiet
docker compose build nms-bot
docker compose up -d --no-deps --no-build nms-bot
```

Seluruh source juga dikompilasi menggunakan compile(..., 'exec'). Integrasi live memakai environment yang sudah diproses Compose dari container aktif, SQLite sementara, tanpa menjalankan poller kedua. Baseline layanan lain diperiksa melalui docker inspect, dan byte file konfigurasi dibandingkan dengan checkpoint. Tidak ada scan subnet atau tindakan administratif router.

## 5. Hasil aktual

- Unit/mock: 134 test lulus dalam 12,266 detik. Jaringan dimatikan; ini berbeda dari pengujian integrasi berikut.
- Produksi: system, interfaces, dhcp_leases, vlan dan traffic semuanya UP pada satu rangkaian pengujian langsung. Router hAP lite, RouterOS 7.19.5 stable; 12 interface, 7 DHCP lease, 3 VLAN. Trafik ether1 dibaca melalui dua sampel counter aktual.
- Alur kelanjutan agent tanpa completion: referensi interface menghasilkan offset 10 dan halaman berikutnya dari data router nyata. Tidak dinyatakan sebagai keberhasilan model OpenRouter.
- Telegram: jalur command/collector/render/pengiriman Bot API ke pemilik berhasil, pesan 85 memiliki entity bold native. Input manusia untuk command baru belum dikonfirmasi; bot sebelumnya sudah dikonfirmasi membalas pesan masuk.
- Scheduler/ringkasan setelah koreksi antrean: uji integrasi ringkasan versi baru berhasil membaca kedua bagian UP dalam 13,81 detik. Setelah deployment terakhir, scheduler produksi juga menyimpan system UP pada 12:45:04 UTC dan interfaces UP pada 12:45:13 UTC, dengan 12 interface. Siklus produksi berakhir 11 UP / 2 UNKNOWN dalam 25,90 detik; kedua UNKNOWN adalah Proxmox TLS dan token VM yang belum tersedia. Login pertama pada startup terakhir berhasil dalam 8,735 detik; retry timeout tervalidasi lewat mock, tidak diklaim terpicu pada startup terakhir.
- Health aplikasi dan verifikasi layanan lain: Selesai dan terverifikasi: hanya service NMS direcreate; container healthy, restart count 0. Pemeriksaan konfigurasi/sintaks lulus. Byte compose.yaml, .env, Dockerfile dan requirements.txt sama dengan checkpoint. Tidak ada perubahan skema DB.
- Uji pertanyaan natural language melalui provider pada tahap ini terhambat HTTP 429 pada openrouter/free dan fallback nvidia/nemotron-3.5-lightning:free. Verifikasi terakhir mengklasifikasikan pesan error provider sebagai batas harian model gratis (daily_free_models), tanpa mencetak body/credential. Batas ini tidak diatasi dengan mengulang request atau mengganti kredensial. Tidak melakukan percobaan berulang untuk menghabiskan kuota. Ini terpisah dari API MikroTik yang berhasil dibaca. Jangan menyatakan uji model terbaru berhasil.

## 6. Deployment dan rollback

Selesai dan terverifikasi: hanya service NMS direcreate; container healthy, restart count 0. Pemeriksaan konfigurasi/sintaks lulus. Byte compose.yaml, .env, Dockerfile dan requirements.txt sama dengan checkpoint. Tidak ada perubahan skema DB

Checkpoint root-only sebelum perubahan: /mnt/data/backups/nms-bot/pre-router-fix-20261019T122210Z.tar.gz, mode 600, mencakup source/.git/.env dan tidak menyertakan DB aktif. Image sebelumnya: nms-bot-pre-router-fix:20261019T122210Z. Baseline: router-fix-baseline-20261019T122210Z.json pada direktori backup yang sama.

Rollback mengikuti prosedur README dengan checkpoint dan tag ini; recreate hanya NMS dan tidak memerlukan restore DB karena skema tidak berubah. Jangan menjalankan compose down atau menghapus volume.

## 7. Dampak terhadap layanan lain

Perbandingan ID, Running dan StartedAt terhadap baseline membuktikan 15 container lain tidak berubah. Port, volume, network, reverse proxy dan dependency tidak berubah. Tidak ada restart router, Proxmox atau host; tidak ada perintah write router. Kredensial tidak diganti dan tidak dicetak ke log/Telegram/provider.

## 8. Risiko dan keterbatasan

CPU router menunjukkan 100% pada beberapa sampel singkat. RAM total 32 MiB, sampel otomatis terakhir RAM bebas 8.024.064 byte. Flash pernah terbaca 86.016 byte (84 KiB), lalu 81.920 byte (80 KiB) dari total 16 MiB pada probe berikutnya. Ini bukti perlunya diagnosis resource, bukan pembuktian tunggal penyebab semua timeout. Tidak ada file router yang dihapus atau perubahan konfigurasi untuk mengatasi angka ini.

API masih memakai pengecualian internal plaintext port 8728 yang sudah dikonfigurasi. API-SSL dengan CA terverifikasi dan pembatasan sumber perlu tahap hardening yang disetujui. Semua 28 menu yang didukung kode belum diuji satu per satu di router ini; menu/paket opsional bisa tidak tersedia. Status interface bukan bukti konektivitas VLAN end-to-end.

Proxmox VM tetap belum disiapkan karena token read-only belum tersedia. Status ini tidak disamakan dengan VM mati. Pertanyaan AI baru bergantung pada ketersediaan/kuota OpenRouter; command langsung tetap tersedia.

## 9. Pekerjaan berikutnya

Selesai dan terverifikasi: perbaikan gate, batas waktu, pembacaan router nyata, format/pengiriman Telegram, serta pemeriksaan regresi yang disebutkan di atas. Pembacaan otomatis setelah perubahan antrean mengikuti bukti pada bagian 5.

Terhambat provider: pengujian completion/tool choice model terbaru, karena kedua model mengembalikan 429. Terhambat kredensial: resource VM Proxmox. Belum dikerjakan: diagnosis penyebab CPU tinggi/flash sempit, uji seluruh menu opsional, dan migrasi API-SSL. Langkah berikut yang masuk akal ialah menilai beban router dari riwayat monitoring dan menyelesaikan pembatasan OpenRouter; perubahan infrastruktur tetap memerlukan otorisasi tersendiri.
