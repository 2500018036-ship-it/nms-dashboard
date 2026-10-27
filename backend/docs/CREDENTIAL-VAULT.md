# Vault kredensial perangkat

Vault menyimpan rahasia secara terpisah dari konfigurasi integrasi dan inventaris. Payload dienkripsi dengan AES-256-GCM menggunakan `NMS_CREDENTIALS_KEY`; nonce acak dan associated data mengikat ciphertext ke jenis serta ID target. Server menolak baca/tulis jika kunci tidak ada atau tidak valid, dan tidak mempunyai jalur penyimpanan plaintext.

## Hak akses dan API

Endpoint memakai sesi dashboard dan perlindungan CSRF yang sama dengan API platform. `credentials.read` dan `credentials.manage` hanya diberikan kepada role Administrator dan Super Administrator. Respons memakai `Cache-Control: no-store`. Endpoint vault tidak termasuk response katalog, perangkat, monitoring, ekspor konfigurasi, atau AI.

| Metode | Endpoint | Izin | Isi |
| --- | --- | --- | --- |
| GET | `/api/platform/credentials/integration/{id}` | `credentials.read` | Mengembalikan payload yang didekripsi setelah target integrasi divalidasi. |
| POST | `/api/platform/credentials/integration/{id}` | `credentials.manage` | Menyimpan payload terenkripsi. |
| GET/POST | `/api/platform/credentials/inventory/{id}` | `credentials.read` / `credentials.manage` | Sama, untuk inventaris perangkat yang tersimpan. |
| GET/POST | `/api/platform/credentials/device/{id}` | `credentials.read` / `credentials.manage` | Sama, untuk perangkat yang masih terlihat pada snapshot collector. |

ID target diverifikasi di server. Payload mempunyai `gui` untuk login aplikasi/perangkat, `wifi_networks` berupa daftar SSID dan password, serta `custom_fields` dan `gui.fields` bertipe. Tipe field yang diterima: `text`, `username`, `password`, `ssid`, `secret`, `url`, `email`, `number`, `boolean`, `textarea`, `token`, dan `api_key`. Batas payload adalah 64 KiB, maksimum 32 SSID dan 32 field per bagian.

Audit hanya menyimpan aktor, target, aksi, serta jumlah field/SSID; bukan nama field, username, password, SSID, atau nilai rahasia. Menghapus integrasi/perangkat dari inventaris menghapus ciphertext terkait. Restore konfigurasi menghapus rekaman vault agar rahasia lama tidak tertinggal tanpa target.

## Penyiapan kunci server

Pada server, buat satu kunci acak 32-byte yang dikodekan base64 URL-safe dan tambahkan ke `.env` dengan permission `0600`. Jangan membuat kunci baru pada setiap deploy: kehilangan kunci membuat ciphertext lama tidak dapat dipulihkan. Simpan backup `.env` dan backup database sesuai kebijakan backup rahasia organisasi. Jangan menyalin nilai ke browser, chat, shell history, atau log.

```sh
python3 -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="))'
```

Kredensial didekripsi hanya ketika administrator membuka vault di UI dan hanya berada di memori halaman sampai ditutup. Kolom password tersembunyi secara default dan dapat diperlihatkan secara eksplisit.
