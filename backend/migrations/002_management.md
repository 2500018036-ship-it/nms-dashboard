# Migrasi aditif 002

Otomatis/idempotent pada `app/management/service.py`: membuat tabel change_plans dan menulis platform_metadata.management_schema=2; rencana APPLYING yang terputus menjadi UNKNOWN, tanpa replay. Payload inventaris/topologi tetap JSON dengan field opsional agar kompatibel. Tidak mengubah tabel monitoring/sesi/insiden lama.

Indeks `checks_target_id` pada app/storage/database.py mempercepat latest-sample tanpa mengubah data. Backup SQLite online dan source/image dibuat sebelum migrasi. Rollback image lama dapat mengabaikan tabel/indeks baru; jangan mengganti database terbaru secara otomatis.
