# Audit dan perubahan ruang kerja THEAZ NMS

## Audit sebelum perubahan

AssistantPage menyimpan percakapan dan polling pada komponen halaman. Backend menjalankan job async tetapi hasil job hanya di memori selama 600 detik. TopologyEditor mempunyai CRUD backend dengan optimistic revision, namun draf dan viewport hanya di state halaman. Canvas SVG menyembunyikan node manual/virtual dan hanya menyediakan perangkat UP. Dropdown header berada di container halaman dan terpotong. Sebagian label menggunakan bahasa Inggris dan beberapa string mengalami mojibake. Integrasi masih memakai launcher tab baru walaupun portal privat sudah diaktifkan.

## Implementasi

- Provider asisten dan topologi hidup di protected workspace, di atas Outlet. Navigasi tidak menghentikan controller. Pertanyaan memakai request_id dan backend async independen dari UI; SQLite menyimpan maksimal 100 pertanyaan per akun selama 90 hari. Riwayat hanya dapat dibaca pemilik sesi. Audit hanya mencatat metadata. Restart server menandai job yang terputus sebagai gagal, tanpa mengirim ulang otomatis.
- Draf topologi, posisi, koneksi, viewport, dan pending save disimpan per akun di localStorage. Tombol Simpan menyinkronkan JSON tervalidasi ke SQLite. Receipt request_id atomik mencegah duplikasi jika respons hilang. Revision conflict tetap ditolak; pengguna dapat mengekspor draf lalu memuat versi server. Perubahan selama save tidak ditimpa respons lama.
- maxGraph 0.25.1 (Apache-2.0), penerus mxGraph, menjalankan canvas lokal. Pustaka 27 simbol generik jaringan, VM, container, dan infrastruktur dari Bootstrap Icons (MIT). Drag node, koneksi/reconnect, resize, pan, zoom, seleksi, undo/redo canvas, dan hapus tersedia. Form metadata dan binding monitoring tetap digunakan. Node manual berstatus UNKNOWN.
- Impor/ekspor struktur .drawio/mxGraphModel, termasuk kompresi deflate, halaman pertama, posisi/ukuran/koneksi/waypoint, dan metadata NMS. Ini bukan seluruh editor draw.io atau pelestarian seluruh style/stencil draw.io. Impor dibatasi 2 MB, 100 node/200 koneksi; entity/doctype, HTML aktif, style/script, dan gambar eksternal tidak dijalankan. Tidak ada diagram dikirim ke diagrams.net.
- Dropdown dipindahkan ke portal body dengan posisi fixed, batas viewport, scroll, navigasi keyboard, Escape, dan penutupan klik luar. Bahasa UI diperbaiki; enum/protokol/nama layanan asli dipertahankan sebagai data teknis.
- Logo pemilik diperjelas melalui imagegen; tagline dihapus. Asset transparan dipakai konsisten; prompt dicatat di public/brand/README.md.
- Tombol GUI layanan terdaftar menuju sesi browser privat pada area utama NMS. Target tetap diautorisasi server; tidak ada URL klien yang diteruskan bebas. WireGuard, routing, firewall, dan konfigurasi perangkat tidak diubah.

## Referensi primer

- https://maxgraph.github.io/maxGraph/docs/intro/
- https://maxgraph.github.io/maxGraph/docs/tutorials/editor-input-output/
- https://github.com/maxGraph/maxGraph
- https://www.drawio.com/docs/reference/embed-mode/

## Pengujian

Lihat hasil CI untuk regresi JS/Python, build, keamanan portal dan Chromium nyata. Pengujian UI memakai backend lokal terisolasi dengan akun dan respons AI sintetis; tidak memanggil AI berbayar atau mengubah infrastruktur produksi. Bukti GUI native terpisah memverifikasi render ketujuh halaman masuk. Login administratif asli dan seluruh operasi setelah login belum diverifikasi tanpa akun perangkat tersebut.


## Perluasan katalog layanan

Audit katalog produksi menemukan empat tujuan tambahan: phpMyAdmin pada 192.168.20.195:8088, halaman HTTP internal pada 192.168.20.195:80, portfolio azrilachdi.web.id, dan cloud.azrilachdi.web.id. Dua entri portfolio menunjuk origin yang sama sehingga berbagi satu target. Total 11 target unik.

phpMyAdmin/HTTP memakai origin internal yang tepat. Dua virtual host HTTPS sudah tersedia melalui gateway publik; pemeriksaan melalui alamat internal 192.168.20.195:443 menghasilkan penolakan SNI, dan jalur 10.10.0.1:443 tidak merespons. Tanpa mengubah jaringan atau proxy layanan itu, sesi browser menggunakan hostname HTTPS asli dengan koneksi dipatok ke gateway 20.194.8.143:443 yang sudah ada. Sertifikat dan SNI tetap diverifikasi browser. Pemetaan hanya berasal dari konfigurasi root, tanpa DNS dinamis atau URL tujuan dari klien. Tidak ada port GUI baru dibuka.

Regresi kebijakan memverifikasi origin/port persis dan menolak hostname lain, loopback, link-local/metadata, multicast, serta alamat tak ditentukan. Hak GUI tambahan dibatasi pada Administrator, Super Administrator, dan Server Administrator. Pembaruan package broker/config root tetap memerlukan aktivasi terkontrol sesuai deploy/access/ACTIVATION.md; image gateway/worker mengikuti CI.

Visual portfolio awal tanpa CSS menunjukkan dependensi eksternal. Audit HTML sumber menetapkan tiga origin aset hanya untuk target portfolio: cdn.tailwindcss.com, fonts.googleapis.com, dan fonts.gstatic.com. Ketiganya dipatok ke alamat IPv4 publik hasil audit, memakai TLS asli, tanpa wildcard. Origin aset ini tidak diizinkan untuk GUI lain.


## Regresi runtime yang ditemukan pada verifikasi publik

Penghapusan kontainer sesi kadang selesai di Docker setelah CLI melewati timeout. Broker sebelumnya mempertahankan slot meskipun kontainer telah hilang. Stop kini mengonfirmasi keberadaan kontainer dengan nama dan label persis, melepas slot hanya ketika penghapusan terkonfirmasi, dan aman dipanggil bersamaan oleh penutupan sesi dan lease cleanup. Kegagalan daemon yang belum dapat dipastikan tetap mempertahankan slot.

Worker kini menerbitkan status ready setelah benar-benar menerima greeting RFB dari server tampilan. CI menunda x11vnc secara sengaja untuk memverifikasi status ready tidak muncul hanya karena pathname socket sudah ada. Tidak ada perubahan jaringan atau konfigurasi perangkat.

Unit broker mempertahankan direktori socket saat restart otomatis. Selector image dibaca melalui direktori read-only, sehingga pembaruan selector secara atomic rename terlihat tanpa mempertahankan inode file lama. Direktori tetap tidak dapat ditulis oleh broker.
