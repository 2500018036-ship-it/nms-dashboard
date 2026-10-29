import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'
import { usePlatform } from '../data/platformContext'
import { accessErrors, accessRequest, displayURL } from '../data/accessClient'
import { AccessFiles } from '../components/AccessFiles'
import { Panel, formatTime } from '../components/ui'

function NativeDisplay({ session, onState, onActivity }) {
  const container = useRef(null)
  const rfb = useRef(null)
  const [text, setText] = useState('')
  const [scaled, setScaled] = useState(true)
  useEffect(() => {
    let client; let cancelled = false
    import('@novnc/novnc').then(({ default: RFB }) => {
      if (cancelled) return
      client = new RFB(container.current, displayURL(session.websocket_path, window.location))
      rfb.current = client
      client.scaleViewport = true
      client.resizeSession = false
      client.background = '#101318'
      client.addEventListener('connect', () => { if (!cancelled) onState('connected') })
      client.addEventListener('disconnect', () => { if (!cancelled) { onState('disconnected'); container.current?.replaceChildren() } })
      client.addEventListener('securityfailure', () => { if (!cancelled) onState('failed') })
    }).catch(() => { if (!cancelled) onState('failed') })
    return () => { cancelled = true; client?.disconnect(); rfb.current = null }
  }, [session.id, session.websocket_path, onState])
  const key = (symbol, code) => { rfb.current?.sendKey(symbol, code); onActivity() }
  const paste = () => {
    if (!text || !rfb.current) return
    rfb.current.clipboardPasteFrom(text)
    rfb.current.sendKey(0xffe3, 'ControlLeft', true)
    rfb.current.sendKey(0x76, 'KeyV')
    rfb.current.sendKey(0xffe3, 'ControlLeft', false)
    setText(''); onActivity()
  }
  return <div>
    <div className="d-flex flex-wrap gap-2 mb-2">
      <button className="btn btn-sm btn-outline-secondary" onClick={() => { setScaled(!scaled); if (rfb.current) rfb.current.scaleViewport = !scaled }}>{scaled ? 'Ukuran asli' : 'Sesuaikan layar'}</button>
      <button className="btn btn-sm btn-outline-secondary" onClick={() => container.current?.requestFullscreen()}>Layar penuh</button>
      <button className="btn btn-sm btn-outline-secondary" onClick={() => key(0xff09, 'Tab')}>Tab</button>
      <button className="btn btn-sm btn-outline-secondary" onClick={() => key(0xff0d, 'Enter')}>Enter</button>
      <input className="form-control form-control-sm" style={{ maxWidth: 300 }} type="password" autoComplete="off" aria-label="Teks untuk GUI" placeholder="Teks untuk kolom GUI yang dipilih" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); paste() } }} />
      <button className="btn btn-sm btn-outline-secondary" disabled={!text} onClick={paste}>Kirim teks</button>
    </div>
    <div ref={container} className="border rounded bg-dark overflow-auto" style={{ height: 'max(440px, calc(100dvh - 300px))', minHeight: 440 }}
      onPointerDownCapture={onActivity} onKeyDownCapture={onActivity} onWheelCapture={onActivity} onTouchStartCapture={onActivity} />
    <p className="small text-muted mt-2 mb-0">Login memakai akun asli perangkat. Di HP, pilih kolom di GUI lalu gunakan Kirim teks untuk mengetik. Jangan simpan password di browser sesi.</p>
  </div>
}

export function AccessPortalPage() {
  const platform = usePlatform()
  const [params] = useSearchParams()
  const autoOpened = useRef('')
  const mounted = useRef(false)
  const [catalog, setCatalog] = useState(null)
  const [session, setSession] = useState(null)
  const [state, setState] = useState('idle')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [audit, setAudit] = useState(null)
  const [displayAttempt, setDisplayAttempt] = useState(0)
  const current = useRef(null)
  const lastActivity = useRef(0)
  useEffect(() => {
    const controller = new AbortController()
    platform.client.platform('access', { signal: controller.signal }).then(setCatalog).catch((e) => { if (!controller.signal.aborted) setError(e.code || 'unavailable') })
    return () => controller.abort()
  }, [platform.client])
  useEffect(() => {
    const identity=session?.id
    if (!identity || session.state !== 'starting') return
    let active=true;let timer
    const poll=async()=>{
      try {
        const value=await accessRequest('/sessions/'+identity)
        if(!active)return
        setSession(value)
        if(value.state==='starting')timer=setTimeout(poll,2000)
      } catch(e) {
        if(!active)return
        setError(e.message)
        if(['session_not_found','session_expired'].includes(e.message)) {current.current=null;setSession(null);setState('idle')}
        else timer=setTimeout(poll,3000)
      }
    }
    timer=setTimeout(poll,1000)
    return ()=>{active=false;clearTimeout(timer)}
  }, [session?.id,session?.state])
  useEffect(() => { mounted.current = true; return () => {
    mounted.current = false
    if (current.current) fetch('/access-api/sessions/' + current.current, { method: 'DELETE', credentials: 'same-origin', keepalive: true }).catch(() => {})
  } }, [])
  const activity = useCallback(() => {
    if (!current.current || Date.now() - lastActivity.current < 15000) return
    lastActivity.current = Date.now()
    accessRequest('/sessions/' + current.current + '/activity', 'POST', {}).catch((e) => setError(e.message))
  }, [])
  const open = useCallback(async (target) => {
    setBusy(true); setError(''); setState('starting')
    try {
      const value = await accessRequest('/sessions', 'POST', { target })
      if (!mounted.current) { accessRequest('/sessions/' + value.id, 'DELETE').catch(() => {}); return }
      current.current = value.id; setSession(value)
    } catch (e) { setError(e.message); setState('failed') } finally { setBusy(false) }
  }, [])
  const requested = params.get('target') || ''
  useEffect(() => {
    if (!catalog?.enabled || !requested || session || busy || autoOpened.current === requested) return
    if (!catalog.targets.some((target) => target.id === requested && target.allowed)) return
    const timer = setTimeout(() => { autoOpened.current = requested; open(requested) }, 0)
    return () => clearTimeout(timer)
  }, [catalog, requested, session, busy, open])
  const close = async () => {
    if (!session) return
    setBusy(true)
    try { await accessRequest('/sessions/' + session.id, 'DELETE'); current.current = null; setSession(null); setState('idle') }
    catch (e) {
      if (['session_not_found', 'session_expired'].includes(e.message)) { current.current = null; setSession(null); setState('idle') }
      else setError(e.message)
    } finally { setBusy(false) }
  }
  const selected = catalog?.targets.find((t) => t.id === session?.target)
  const admin = platform.capabilities.permissions?.includes('config.manage')
  return <>
    <Panel title="THEAZ Portal Akses" subtitle="GUI asli perangkat dan layanan melalui koneksi privat homelab">
      <p className="text-muted">Pilih perangkat untuk menampilkan GUI aslinya di ruang kerja ini. HP/laptop cukup mengakses domain NMS melalui HTTPS.</p>
      {error && <div className="alert alert-danger" role="alert">{accessErrors[error] || 'Portal belum dapat menyelesaikan permintaan.'}</div>}
      {catalog && !catalog.enabled && <div className="alert alert-info">Runtime akses belum diaktifkan. Aktivasi perubahan NMS dan reverse proxy menunggu persetujuan pengelola.</div>}
      <div className="d-flex flex-wrap gap-2">{catalog?.targets.map((target) => <button key={target.id} className={`btn ${session?.target === target.id ? 'btn-primary' : 'btn-outline-primary'}`} disabled={!catalog.enabled || !target.allowed || busy} title={target.allowed ? target.url : 'Belum diizinkan untuk akun atau perangkat ini'} onClick={() => open(target.id)}>{target.name}</button>)}</div>
    </Panel>
    {session && <Panel title={selected?.name || 'GUI perangkat'} subtitle={`Sesi ${state === 'connected' ? 'terhubung' : session.state === 'starting' ? 'sedang disiapkan' : state} · Berakhir ${formatTime(session.expires_at)}`} action={<div className="d-flex gap-2">{session.state==='ready'&&['disconnected','failed'].includes(state)&&<button className="btn btn-sm btn-outline-primary" onClick={()=>{setState('connecting');setDisplayAttempt((value)=>value+1)}}>Sambungkan layar ulang</button>}<button className="btn btn-sm btn-outline-danger" disabled={busy} onClick={close}>Tutup sesi</button></div>}>
      {session.state === 'ready' ? <NativeDisplay key={`${session.id}-${displayAttempt}`} session={session} onState={setState} onActivity={activity} /> : <div className="py-5 text-center" role="status">{session.state === 'failed' ? 'Browser sesi gagal dimulai. Tutup sesi lalu periksa runtime.' : <><span className="spinner-border text-primary" /><p className="mt-3">Menyiapkan GUI asli…</p></>}</div>}
      {session.state === 'ready' && <AccessFiles session={session} />}
    </Panel>}
    {!session && <div className="alert alert-secondary">Sesi GUI dipisahkan per login dan berakhir otomatis saat tidak digunakan. Hak di dalam perangkat mengikuti akun asli perangkat tersebut.</div>}
    {admin && <Panel title="Audit akses GUI" action={<button className="btn btn-sm btn-outline-secondary" disabled={!catalog?.enabled} onClick={() => accessRequest('/audit').then((v) => setAudit(v.items)).catch((e) => setError(e.message))}>Muat log akses</button>}>
      {audit ? <div className="table-responsive"><table className="table table-sm"><thead><tr><th>Waktu</th><th>Pengguna</th><th>Perangkat</th><th>Kejadian</th><th>Alasan</th></tr></thead><tbody>{audit.map((r, i) => <tr key={i}><td>{formatTime(r.at)}</td><td>{r.actor}</td><td>{r.target}</td><td>{r.event}</td><td>{r.reason || '—'}</td></tr>)}</tbody></table></div> : <p className="small text-muted mb-0">Log mencatat pembukaan, penutupan dan penolakan akses. Password, input dan isi tampilan GUI tidak dicatat.</p>}
    </Panel>}
  </>
}
