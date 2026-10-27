# Laporan AI sesuai konteks dan kelengkapan data — 19 Oktober 2026

## 1. Penyebab/temuan

Agent sebelumnya memproses setiap pertanyaan tanpa rujukan topik, sehingga “RAMnya?” dapat berpindah ke perangkat lain. Instruksi jawaban ringkas juga tidak menjamin seluruh baris yang diminta muncul. UNKNOWN pada sebagian collector dapat tertutup oleh ringkasan komponen yang berhasil.

Uji nyata menemukan model `nvidia/nemotron-3-ultra-550b-a55b:free` yang dipilih `openrouter/free` mengabaikan tool yang diwajibkan meskipun HTTP sukses. Pengaman baru menolak respons itu dan fallback `nvidia/nemotron-3.5-lightning:free` benar-benar memanggil tool Docker. Uji berikutnya menemukan model sempat memindahkan pertanyaan RAM Docker ke Debian; alur metrik lanjutan kemudian dipindahkan ke pemilihan tool berbasis rujukan aplikasi, bukan tebakan model.

## 2. File diubah

Baru `app/ai/context.py`, `app/ai/evidence.py`, dan `tests/test_context_evidence.py`. Perubahan pada `app/ai/agent.py`, `client.py`, `prompts.py`, `app/telegram/handlers.py`, `app/main.py`, `app/services/health.py`, `app/monitoring/proxmox.py`, `tests/test_ai.py`, `tests/test_state_telegram.py`, README dan laporan ini.

## 3. Hasil implementasi

- Rujukan per user privat: maksimal empat tool/target/filter/cursor, TTL 10 menit, 64 user. Tidak menyimpan teks chat, jawaban AI atau angka hasil monitoring sebagai memori percakapan. `/reset`, restart, isolasi antar-user dan reset ketika request masih berjalan diuji.
- Pertanyaan metrik singkat mengikuti komponen sebelumnya secara langsung. Bila ada beberapa komponen, bot meminta target. Pertanyaan konseptual tetap boleh tanpa tool; target baru tidak dipaksa mengikuti topik lama.
- Permintaan semua/daftar/lengkap/rinci/detail menambahkan fakta dari collector secara deterministik, termasuk field bertingkat. Maksimal lima halaman MikroTik tambahan diambil dengan section/filter sama, dibatasi ukuran data. Sisa halaman/scan/field yang dipotong selalu diberi penanda. “Lanjutkan” memakai cursor sebenarnya, tanpa completion AI baru.
- Collector belum disiapkan dipisahkan dari layanan DOWN. Proxmox tanpa token tidak dapat diklaim mempunyai VM sehat berdasarkan HTTP/TCP. Kegagalan/hasil parsial tidak hilang dari jawaban campuran.
- Respons tanpa tool saat diwajibkan ditolak dan memakai fallback eksplisit. Bila tool sudah menghasilkan fakta tetapi ringkasan AI gagal atau deadline tercapai, fakta tetap dikirim dengan penjelasan. Kegagalan sebelum ada fakta tidak diisi data buatan.

## 4. Pengujian

Image test dibangun, lalu dijalankan dengan `docker run --rm --network none nms-bot:test`. Sintaks seluruh app/test diperiksa melalui `compile`; Compose divalidasi dengan `docker compose config --quiet`. Uji integrasi memakai DB sementara dan snapshot host read-only, tanpa poller/scheduler kedua.

## 5. Hasil aktual

**125 unit/mock test lulus**, suite akhir **10,996 detik**, tanpa jaringan/secret. Termasuk pagination otomatis dan batasnya, cursor tidak mundur ketika halaman awal diulang, semua baris tetap ada melewati 2500 karakter, format field bersarang, data campuran, token PVE belum ada, HTTP bukan status VM, isolasi/TTL/reset/context, scope RAM Docker, ambiguitas, provider mengabaikan required tool, dan fakta dipertahankan saat timeout/provider gagal.

**Integrasi OpenRouter berhasil mengambil Docker aktual:** seluruh nama dari **16 container** muncul dalam jawaban 10.957 karakter, tiga bagian Telegram. Fallback benar-benar digunakan sesudah primary mengabaikan tool. Ini bukan sekadar test mock atau HTTP 200.

**Integrasi konteks dengan collector aktual berhasil:** versi yang diperbaiki mengambil RAM dari **16 container Docker**, menghasilkan 2.298 karakter dalam satu bagian, tanpa beralih ke Debian dan tanpa completion model untuk follow-up singkat. Pengujian ini menggunakan source nyata dengan registry produksi dan snapshot collector, bukan nilai RAM dummy.

## 6. Deployment/rollback

Recreate hanya `nms-bot`. Checkpoint awal `/mnt/data/backups/nms-bot/pre-context-20261019T072441Z.tar.gz`; checkpoint segar tepat sebelum deploy `/mnt/data/backups/nms-bot/pre-context-deploy-20261019T115221Z.tar.gz` dan image `nms-bot-pre-context-deploy:20261019T115221Z`. Gunakan prosedur rollback README dengan tag ini bila diperlukan. Tidak ada migrasi atau restore DB aktif.

Verifikasi produksi akhir: **healthy, restart count 0**. Follow-up RAM mengambil seluruh **16 container** pada snapshot aktual dan mengirim satu pesan Telegram nomor **77** dengan **83 entity HTML native**. Ini memverifikasi pengiriman API dan controller dengan source nyata; bukan klaim pengujian input manusia untuk seluruh variasi pertanyaan baru.

## 7. Dampak layanan lain

Compose, `.env`, Dockerfile, dependensi, port, volume dan network dibandingkan byte/hash sebelum-sesudah patch dan tetap sama. Nilai kredensial/model tidak diubah. Tidak ada perubahan router/VM atau administrasi aplikasi lain. Verifikasi container lain memakai baseline segar sebelum deploy.

Hasil perbandingan **15 container lain**: ID, Running dan StartedAt sama; tidak ada yang direstart atau diganti oleh deployment ini. Siklus monitoring dasar tetap **9 UP / 4 UNKNOWN**.

## 8. Batas/risiko

Memori adalah rujukan terbatas, bukan ingatan seluruh percakapan. Data dapat memakai cache collector yang waktunya ditampilkan; perubahan tabel setelah cache kedaluwarsa tetap mungkin. Batas 500 baris/160 karakter per field dan timeout tool tetap berlaku. Angka yang belum tersedia tetap null/UNKNOWN; daftar belum lengkap tidak disebut lengkap. Analisis sebab yang kompleks tetap bergantung pada kemampuan/kuota/latensi model; pengaman ini tidak menjamin setiap interpretasi bahasa model selalu benar.

Proxmox belum mempunyai token read-only. Audit akun MikroTik sebelumnya menunjukkan grup bawaan read dengan izin tambahan; pemindahan ke grup read,api belum dikonfirmasi. Probe API produksi paling akhir menghasilkan **UNKNOWN timeout**, sehingga data router tetap belum terverifikasi. Jangan menyimpulkan bahwa kondisi izin terbaru sudah berhasil diperiksa dari probe yang timeout. Tidak ada bypass permission atau perubahan kredensial untuk melewati batas tersebut. Secret/file/script/shell/perubahan infrastruktur tetap tidak tersedia.

## 9. Berikutnya

Pengguna dapat mencoba “Tampilkan semua container Docker saya”, lalu “RAMnya berapa?”, “Cek DNS saya”, dan `/reset`. Selesaikan pemindahan grup MikroTik sesuai panduan, lalu lakukan uji data router nyata. Proxmox baru diaktifkan setelah token minimum dan CA terverifikasi tersedia; tidak menjadi prasyarat laporan komponen lain yang sudah berfungsi.
