# Perbaikan keterbacaan Telegram — 19 Oktober 2026

1. **Penyebab:** AI mengeluarkan Markdown, sementara pengiriman bot tidak memakai parse mode. Heading `###`, penanda `**`, backtick dan tabel pipe tampil sebagai teks mentah. Tabel lebar juga tidak nyaman pada layar ponsel.
2. **File:** `app/telegram/formatting.py`, `app/telegram/delivery.py`, `app/telegram/handlers.py`, `app/services/scheduler.py`, `app/alerts/engine.py`, `app/ai/prompts.py`, `requirements.txt`, `tests/test_formatting.py`, README dan laporan ini.
3. **Implementasi:** renderer AST Mistune 3.3.4 mengubah heading/emphasis menjadi HTML Telegram yang terbatas dan aman. Tabel menjadi daftar per target; raw HTML selalu di-escape. Poin dan spasi dipertahankan. Pesan panjang dipisah pada batas paragraf/baris/kata dengan tag lengkap dan batas UTF-16. Penolakan entity mendapat satu fallback teks bersih, sedangkan timeout send tetap tidak diulang. Format juga dipakai `/status`, alert, dan daily summary. Alert tidak lagi menampilkan dictionary Python mentah. Prompt meminta Bahasa Indonesia baku, jawaban ringkas dan tanpa tabel, serta melarang tanggal/URL yang tidak didukung tool. Konfigurasi monitoring, kredensial, permission, model, port dan volume dipertahankan.
4. **Pengujian:** kompilasi sumber Python, build image test, `docker run --rm --network none nms-bot:test`, integrasi AI/tool read-only dan API Telegram untuk send/edit HTML. Pengujian tambahan mencakup screenshot-style Markdown, tabel, HTML tidak tepercaya, kode, nested emphasis, emoji, pesan panjang, JSON literal dan fallback entity.
5. **Hasil aktual:** seluruh **76 tes lulus** pada suite akhir, dalam 62,973 detik. Telegram menerima entity native bold/code/italic dari hasil renderer. Pesan contoh ID 57 kemudian diperbarui memakai status nyata dengan nama layanan yang lebih jelas; edit diterima dengan 17 entity. Unit test fallback parse dan timeout lulus; tidak melakukan eksperimen destruktif pada layanan.
6. **Deployment:** recreate dibatasi pada service `nms-bot` dengan `up -d --no-deps --no-build`; health dan jumlah restart diperiksa setelahnya. Hasil verifikasi akhir dicatat di bawah.
7. **Dampak:** Compose tidak diubah. Tidak ada perubahan router/PVE, container aplikasi lain, atau aturan alert; hanya tampilan alert diperbaiki.
8. **Batasan:** renderer mendukung subset Markdown yang relevan; HTML dari AI diperlakukan sebagai teks. JSON command admin tetap literal. Ketersediaan model gratis dan akurasi analisis tetap bergantung pada provider serta bukti tool; formatter tidak menambahkan metrik atau status sendiri. Tanggal/alamat yang tidak didukung pada satu sampel AI menyebabkan prompt diperketat dan pesan contoh diganti dengan ringkasan deterministik dari collector.
9. **Rollback/berikutnya:** checkpoint source di `/mnt/data/backups/nms-bot/pre-format-20261019T064101Z.tar.gz`, image `nms-bot-pre-format:20261019T064101Z`. Pengguna dapat mengirim pertanyaan baru untuk menilai tampilan pada ponselnya; sesuaikan kepadatan jawaban jika perlu tanpa mengubah collector.

## Verifikasi produksi

- Rollout 13:49 WIB: container `healthy`, restart count **0**; Mistune 3.3.4 termuat di image produksi.
- API Telegram produksi berhasil mengedit pesan ID **57** dengan **17 entity** dan seluruh **13 target**. Tidak ada penanda `###` atau `**` mentah pada teks hasil. Pesan berjudul “Format baru bot NMS sudah aktif” memakai data collector aktual.
- Kondisi pemeriksaan saat verifikasi: **9 UP, 4 UNKNOWN**. Data/akses yang belum tersedia tetap ditandai UNKNOWN.
- Seluruh **15 container non-NMS** mempunyai ID, status running/exited dan waktu mulai yang sama dengan baseline sebelum perubahan.
- Hanya service NMS direcreate. Tidak ada perubahan Compose, credential, permission, router, PVE, reverse proxy atau aturan alert.
