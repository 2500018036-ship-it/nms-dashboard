export const accessErrors = {
  portal_not_verified:'URL belum diuji dari server NMS. Klik Uji akses.',portal_verification_expired:'Hasil verifikasi sudah kedaluwarsa; uji ulang sebelum membuka.',
  tls_verification_failed:'Sertifikat TLS tidak dipercaya. Pasang CA yang benar atau minta administrator meninjau pin sertifikat.',certificate_pin_mismatch:'Sertifikat berbeda dari pin yang disetujui; akses dihentikan.',
  timeout:'Server tidak menerima balasan. Periksa alamat, port, jalur jaringan dan firewall tujuan.',dns_resolution_failed:'Hostname GUI tidak dapat diresolusikan dari server NMS.',dashboard_connection_failed:'Koneksi atau respons HTTP GUI gagal.',
  redirect_origin_not_approved:'GUI mengarahkan ke origin lain yang belum diizinkan. Administrator perlu meninjau origin tujuan.',dashboard_http_error:'GUI merespons kesalahan HTTP. Periksa layanan perangkat.',disabled:'Target dinonaktifkan.',
  access_not_activated: 'Portal akses belum diaktifkan pada server.',
  access_denied: 'Akun Anda belum mendapat izin untuk GUI ini.',
  authentication_required: 'Sesi NMS berakhir. Silakan masuk kembali.',
  authentication_unavailable: 'Sesi NMS belum dapat diverifikasi.',
  access_capacity_reached: 'Sesi GUI sedang digunakan. Tutup sesi aktif sebelum membuka perangkat lain.',
  browser_runtime_unavailable: 'Runtime GUI belum tersedia atau sedang memulai.',
  session_not_found: 'Sesi GUI sudah berakhir.',
  session_expired: 'Sesi GUI telah kedaluwarsa.',
  session_owner_mismatch: 'Sesi GUI ini dimiliki sesi login lain.',
  display_not_ready: 'Tampilan GUI belum siap.',
  unavailable: 'Portal akses belum dapat dijangkau.',
  upload_quota_reached: 'Kuota unggah sesi 32 MiB telah terpakai. Mulai sesi baru untuk melanjutkan.',
}

export async function accessRequest(path, method = 'GET', body) {
  if (!/^\/(?:catalog|audit|sessions(?:\/[a-f0-9]{32}(?:\/(?:activity|downloads))?)?)$/.test(path)) throw new Error('unavailable')
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 45000)
  try {
    const response = await fetch('/access-api' + path, {
      method, credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: controller.signal,
      headers: { Accept: 'application/json', ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    })
    if (!response.ok) {
      const message = (await response.text()).slice(0, 120).trim()
      throw new Error(Object.hasOwn(accessErrors, message) ? message : 'unavailable')
    }
    return await response.json()
  } finally { clearTimeout(timer) }
}

export function displayURL(path, location) {
  if (!/^\/access-api\/sessions\/[a-f0-9]{32}\/display$/.test(path) || location.protocol !== 'https:') throw new Error('unavailable')
  return `wss://${location.host}${path}`
}
