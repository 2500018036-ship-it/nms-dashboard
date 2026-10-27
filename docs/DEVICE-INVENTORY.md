# Inventaris perangkat — kontrak UI Phase 02

> Status Phase 3 (23 Oktober 2026): workspace memakai data aktual saja. Demo memori Phase 2 tidak diaktifkan. Daftar perangkat teramati/detail sudah membaca API read-only; penyimpanan/discovery/ACK tetap belum tersedia. Tabel demo di bawah adalah dokumentasi historis adapter Phase 2.

Inventaris konfigurasi dibedakan dari snapshot hasil collector. Perangkat yang muncul pada collector tidak otomatis menjadi konfigurasi tersimpan. Memilih metode atau profil tidak membuktikan kemampuan perangkat, tidak membuat collector, dan tidak memulai polling.

## Model

| Field | Validasi |
| --- | --- |
| id | Opsional saat tambah, ID unik 1–80 huruf/angka/underscore/hyphen |
| name | Wajib, maksimum 80 karakter |
| host | IPv4, IPv6 atau hostname; tanpa URL, port, credential atau path |
| type | router, switch, server, hypervisor, container-host, dns, vpn, service, other |
| vendor / model | Opsional, teks maksimum 80 karakter masing-masing |
| methods | Minimal satu dari icmp, snmp, api, agent, http, dns |
| interval | Bilangan bulat 15–86400 detik |
| group | Opsional, maksimum 48 karakter |
| tags | Maksimum 10 tag; masing-masing 1–32 huruf/angka/underscore/hyphen |
| profile | connectivity, network, host, virtualization, services, custom |
| enabled | Boolean, bawaan true |

Duplikasi alamat setelah normalisasi ditolak. Field asing, password, token dan credential tidak diterima. Profil hanya menjelaskan metrik yang diharapkan; tampilan data tetap mengikuti kemampuan collector aktual.

## Format import/export

JSON UTF-8, maksimum 256 KiB dan 1–200 perangkat per import. Semua entri divalidasi sebelum perubahan dilakukan. ID/alamat duplikat terhadap batch atau inventaris ditolak tanpa import sebagian.

```json
{
  "schemaVersion": 1,
  "source": "development-demonstration",
  "devices": [
    {
      "name": "EXAMPLE-SWITCH",
      "host": "192.0.2.20",
      "type": "switch",
      "vendor": "",
      "model": "",
      "methods": ["icmp", "snmp"],
      "interval": 30,
      "group": "Lab",
      "tags": ["example"],
      "profile": "network",
      "enabled": true
    }
  ]
}
```

Alamat contoh adalah alamat dokumentasi, bukan target jaringan pengguna. Export hanya memuat field konfigurasi allowlist; tidak berisi credential, log atau metrik. `source` adalah metadata asal, bukan verifikasi integrasi. Form import menyediakan preview/validasi dan tombol terpisah untuk import DEMO.

## Perilaku operasi

| Operasi | Mode aktual | Demonstrasi development |
| --- | --- | --- |
| Tambah/edit | Form dapat divalidasi; pesan jelas BELUM disimpan | Tersimpan di memori sesi |
| Aktif/nonaktif/hapus | Menunggu API inventaris | Dialog konfirmasi dan perubahan memori |
| Uji koneksi | Tidak melakukan probe; backend belum tersedia | Hasil simulasi berlabel, tanpa request jaringan |
| Discovery | Rancangan scope/penjelasan, tanpa pemindaian | Memfilter kandidat statis pada IPv4 /24–/32 |
| Approval | Menunggu backend | Hanya kandidat yang telah ditemukan dan dipilih yang masuk inventaris |
| Import | Validasi format; tidak menulis backend | Import atomik ke memori |
| Export | Memerlukan inventaris tersedia | Download JSON konfigurasi sesi |
| ACK alert | Menunggu endpoint/otorisasi | Note maksimum 300 karakter, memori sesi saja |

Keluar demonstrasi atau reload menghapus inventaris/ACK DEMO. Snapshot monitoring contoh tidak mengikuti perubahan inventaris. Tidak ada localStorage untuk perangkat, ACK, secret maupun data monitoring.

## Lapisan service

- `model.js`: schema tertutup dan validator import/form/export.
- `service.js`: `unavailableDeviceService` menolak operasi aktual dengan backend_not_integrated; `createMemoryDeviceService` hanya dipakai sesi DEMO.
- `DeviceForm.jsx`: form dan ringkasan validasi.
- `InventoryModals.jsx`: import/preview/export, scope discovery dan approval.
- `DevicesPage.jsx`: pencarian/filter/pagination, detail dan operasi UI.

Integrasi mendatang mengganti adapter aktual di provider sesudah backend benar-benar tersedia. Browser tidak boleh membuka SNMP, RouterOS, Proxmox, Docker, atau IP target secara langsung. Validasi frontend adalah bantuan UX; backend tetap harus memvalidasi/otorisasi dan membatasi target sebelum menjalankan collector.
