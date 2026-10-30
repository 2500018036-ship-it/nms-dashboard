# Pengembangan Topology Builder — 30 Oktober 2026

Basis: `bbe1386`; editor maxGraph, impor/ekspor draw.io, draf per pengguna, undo/redo, dan penyimpanan dengan revision/idempotency dipertahankan. Arsip proyek asli tidak diubah.

## Perubahan

- Canvas lebih tinggi, mode editor diperluas, pustaka bisa disembunyikan, fit diagram, zoom 10–400%, pan dan drag tetap tersedia. Node memakai gambar tanpa card/bingkai; warna label mengikuti kesehatan perangkat.
- `POST /api/platform/topology-verify` membaca inventaris dan snapshot server, memvalidasi diagram terbatas, memerlukan sesi dengan `monitor.read`, lalu mencatat audit. Diagram klien tidak dapat menetapkan status terverifikasi sendiri.
- Bukti yang diterima: IP neighbor sesuai inventaris, protokol LLDP/CDP, port lokal sesuai dan UP, serta kedua perangkat memiliki sampel baru. Port tujuan yang diisi harus didukung observasi balik. Perbedaan MAC yang tersedia, collector, IP, port, sampel lama, atau perangkat nonaktif menghalangi animasi. MNDP/ARP/ping saja tidak membuktikan kabel. VLAN/routing/VPN/wireless memerlukan adapter bukti khusus; belum ditandai terverifikasi.
- Collector neighbor MikroTik menambahkan pembacaan `discovered-by` dan snapshot `mikrotik_neighbors` pada siklus monitoring kontinu yang sudah diaktifkan. Tidak mengaktifkan protokol discovery, mengubah perangkat, jaringan atau firewall.
- Animasi SVG mengikuti titik/jalur kabel maxGraph, hanya untuk link dengan bukti yang belum kedaluwarsa. Perubahan binding/port/jenis koneksi membatalkan hasil lama. Perubahan posisi dan zoom tidak mengubah bukti hubungan. Animasi adalah ilustrasi hubungan, bukan packet capture atau bukti laju trafik khusus pasangan perangkat. Rate/counter diberi scope interface lokal.
- Klik kanan membuka panel yang dibatasi viewport: informasi inventaris, waktu sampel, status, CPU/RAM/interface/rate jika tersedia, edit/binding perangkat, dan launcher GUI melalui portal yang sudah ada. Data tidak tersedia tidak diganti angka dummy.
- Draf tetap disimpan lokal; autosave server berjalan dari workspace di luar lifecycle halaman, memakai revision dan request ID yang sama saat retry. Posisi, waypoint dan view x/y/zoom dipersistenkan. Mode editor/pustaka tersimpan per draf di browser. Autosave hanya aktif untuk role yang boleh mengelola topologi.
- Sinkronisasi canvas memperbarui cell yang ada; pan/zoom tidak membangun ulang graph. Animasi memakai SVG SMIL tanpa loop JavaScript per frame dan dihentikan secara visual untuk reduced motion/tab tersembunyi. Batas kompatibilitas tetap 100 node/200 koneksi; performa visual skala tersebut belum diukur.

## Pengujian dan batas bukti

- Regresi lokal: 302 tes backend lulus; 89 tes frontend lulus; lint dan build lulus. Setelah penanganan resource virtual ditambahkan, delapan tes khusus verifikasi lulus. Build masih melaporkan warning maxGraph eval dan ukuran chunk yang sudah ada.
- Tes HTTP nyata dengan server dan SQLite sementara memeriksa autentikasi, penolakan origin lain, audit, kontrak input, serta node manual. Tes persistence memeriksa waypoint/view dan autosave saat subscriber halaman dilepas. Fixture tes tidak dipasang ke produksi.
- Probe baca saja pada server homelab: RouterOS neighbors UP, empat neighbor, protokol `cdp,lldp` dan `cdp,mndp`; interface UP. Uji pasangan inventaris dengan port gabungan yang tidak cocok ditolak dengan `MISMATCH`, tanpa animasi. Belum ada uji positif link fisik dengan seluruh syarat terpenuhi yang dapat dilaporkan.
- Diagram produksi `Homelab - observasi Proxmox` memiliki dua resource virtual tanpa link. Keduanya dikenali melalui data Proxmox tetapi belum siap untuk verifikasi konektivitas: IP manajemen guest perlu ditautkan melalui inventaris. IP host Proxmox tidak dipakai sebagai IP guest.
- Pengujian UI browser dimulai tetapi Computer Use berhenti karena URL Windows tidak dapat dipastikan untuk enforcement kebijakan. Tidak ada klaim bahwa drag, context menu, animasi visual atau responsivitas skala besar telah lulus pengujian browser. Verifikasi tersebut masih diperlukan sebelum rollout fitur ini.
- Produksi tetap pada rilis `bbe1386` selama peninjauan fitur topologi. Pekerjaan topologi disiapkan sebagai perubahan terpisah; layanan homelab dan konfigurasi jaringan tidak diubah.

Referensi protokol: [RouterOS Neighbor Discovery](https://help.mikrotik.com/docs/spaces/ROS/pages/24805517/Neighbor%2Bdiscovery).
