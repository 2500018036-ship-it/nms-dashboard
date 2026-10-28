import { BrandLogo } from '../BrandLogo'
import { FloatingMenu } from '../FloatingMenu'
import { Fragment, useEffect, useRef, useState } from 'react'

import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router'

import { modules, searchModules } from '../../app/modules'

import { useMonitoring } from '../../data/useMonitoring'

import { usePlatform } from '../../data/platformContext'

import { useAuth } from '../../data/authSessionContext'

import { errorMessages } from '../../data/apiClient'

import { Badge, Icon, formatTime } from '../ui'



const stored = (key, fallback) => { try { return localStorage.getItem(key) || fallback } catch { return fallback } }

const remember = (key, value) => { try { localStorage.setItem(key, value) } catch { /* UI preference is optional. */ } }



export function AppLayout() {

  const location = useLocation()

  const navigateHook = useNavigate()

  const platform = usePlatform()

  const parent = location.pathname.startsWith('/devices/') ? '/devices' : location.pathname.startsWith('/integrations/') ? '/integrations' : location.pathname === '/virtualization' ? '/servers' : location.pathname

  const current = modules.find((m) => m.path === parent)

  const detailName = location.pathname.startsWith('/integrations/') ? platform.integrations.find((s) => location.pathname.endsWith('/'+s.id))?.name : location.pathname.startsWith('/devices/') ? 'Detail perangkat' : location.pathname === '/virtualization' ? 'Proxmox VE' : null

  const { snapshot, observedDevices, connection, config, refresh } = useMonitoring()

  const { user, logout } = useAuth()

  const [theme, setTheme] = useState(() => stored('nms.ui.theme', 'dark') === 'light' ? 'light' : 'dark')

  const [collapsed, setCollapsed] = useState(() => stored('nms.ui.sidebarCollapsed', 'false') === 'true')

  const [mobile, setMobile] = useState(() => window.matchMedia('(max-width: 991.98px)').matches)

  const [drawer, setDrawer] = useState(false)

  const [query, setQuery] = useState('')

  const [searchOpen, setSearchOpen] = useState(false)

  const [menu, setMenu] = useState(null)

  const [notice, setNotice] = useState('')

  const [loggingOut, setLoggingOut] = useState(false)

  const notificationButton = useRef(null); const accountButton = useRef(null)
  const sidebar = useRef(null); const search = useRef(null); const toggle = useRef(null); const main = useRef(null)

  const header = useRef(null); const lastPath = useRef(location.pathname)

  useEffect(() => {

    document.documentElement.dataset.bsTheme = theme

    remember('nms.ui.theme', theme)

  }, [theme])

  useEffect(() => { remember('nms.ui.sidebarCollapsed', String(collapsed)) }, [collapsed])

  useEffect(() => {

    const media = window.matchMedia('(max-width: 991.98px)')

    const update = () => { setMobile(media.matches); setDrawer(false) }

    media.addEventListener('change', update)

    return () => media.removeEventListener('change', update)

  }, [])

  useEffect(() => {

    const keys = (e) => {

      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); search.current?.focus() }

      if (e.key === 'Escape') { setMenu(null); setSearchOpen(false); setDrawer(false) }

    }

    const outside = (e) => { if (!header.current?.contains(e.target) && !e.target.closest('[data-nms-floating-menu]')) { setMenu(null); setSearchOpen(false) } }

    document.addEventListener('keydown', keys); document.addEventListener('click', outside)

    return () => { document.removeEventListener('keydown', keys); document.removeEventListener('click', outside) }

  }, [])

  useEffect(() => {

    document.title = `${current?.title || 'Halaman tidak ditemukan'} · THEAZ NMS`

    if (lastPath.current !== location.pathname) {

      main.current?.focus({ preventScroll: true }); window.scrollTo({ top: 0, left: 0 })

      lastPath.current = location.pathname

    }

  }, [location.pathname, current?.title])

  useEffect(() => {

    if (!mobile || !drawer) return

    const previous = document.body.style.overflow

    document.body.style.overflow = 'hidden'

    const elements = () => [...sidebar.current.querySelectorAll('a, button')]

    elements()[0]?.focus()

    const trap = (e) => {

      if (e.key === 'Escape') toggle.current?.focus()

      if (e.key === 'Tab') {

        const first = elements()[0]; const last = elements().at(-1)

        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus() }

        if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus() }

      }

    }

    document.addEventListener('keydown', trap)

    return () => { document.body.style.overflow = previous; document.removeEventListener('keydown', trap) }

  }, [mobile, drawer])

  const closeDrawer = () => { setDrawer(false); toggle.current?.focus() }

  const navigate = () => { setDrawer(false); setMenu(null); setSearchOpen(false); setQuery(''); window.scrollTo({ top: 0, left: 0 }) }

  const fullscreen = async () => {

    try {

      if (document.fullscreenElement) await document.exitFullscreen()

      else if (document.documentElement.requestFullscreen) await document.documentElement.requestFullscreen()

      else setNotice('Browser ini belum mendukung mode layar penuh.')

    } catch { setNotice('Mode layar penuh tidak tersedia pada browser ini.') }

  }

  const connected = connection.status === 'connected'

  const matches = query.trim() ? [...searchModules(query), ...observedDevices.filter((d)=>`${d.name} ${d.host}`.toLowerCase().includes(query.toLowerCase())).map((d)=>({id:d.id,path:'/devices/'+d.id,title:d.name+' · '+d.host,icon:'router'})), ...platform.integrations.filter((d)=>`${d.name} ${d.url}`.toLowerCase().includes(query.toLowerCase())).map((d)=>({id:d.id,path:'/integrations/'+d.id,title:d.name,icon:'plug'})), ...snapshot.core.guests.filter((g)=>`${g.name} ${g.vmid}`.toLowerCase().includes(query.toLowerCase())).map((g)=>({id:g.id,path:'/virtualization?resource='+encodeURIComponent(g.id),title:g.name+' · '+g.vmid,icon:'pc-display'}))].slice(0,18) : []

  const [workspaceTitle, setWorkspaceTitle] = useState('THEAZ NMS')

  useEffect(() => {

    const sync = () => {

      try { const name = JSON.parse(localStorage.getItem('nms.workspace_settings') || '{}').workspaceName; setWorkspaceTitle(typeof name === 'string' && name.trim() ? name.slice(0, 60) : 'THEAZ NMS'); setTheme(stored('nms.ui.theme', 'dark') === 'light' ? 'light' : 'dark') } catch { setWorkspaceTitle('THEAZ NMS') }

    }

    sync(); window.addEventListener('nms:preferences', sync)

    return () => window.removeEventListener('nms:preferences', sync)

  }, [])

  return <div className="admin-app"><a className="skip-link" href="#main-content">Lewati ke konten utama</a><div className={`admin-wrapper ${collapsed ? 'sidebar-collapsed' : ''}`} id="admin-wrapper">

    <header ref={header} className="admin-header"><nav className="navbar navbar-expand-lg navbar-light bg-white border-bottom"><div className="container-fluid">

      <Link className="navbar-brand d-flex align-items-center" to="/" aria-label="THEAZ NMS" onClick={navigate}><BrandLogo /></Link>

      <button ref={toggle} className={`hamburger-menu ${collapsed && !mobile ? 'is-active' : ''}`} type="button" data-sidebar-toggle aria-label={mobile ? 'Buka navigasi' : collapsed ? 'Perluas sidebar' : 'Ringkas sidebar'} aria-controls="admin-sidebar" aria-expanded={mobile ? drawer : !collapsed} onClick={() => mobile ? setDrawer(!drawer) : setCollapsed(!collapsed)}><Icon name="list" /></button>

      <div className="search-container flex-grow-1 mx-4"><div className="position-relative"><input ref={search} type="search" className="form-control" placeholder="Cari modul… (Ctrl+K)" aria-label="Cari modul" value={query} onFocus={() => { setMenu(null); setSearchOpen(true) }} onChange={(e) => { setQuery(e.target.value); setSearchOpen(true) }} /><Icon name="search" className="position-absolute top-50 end-0 translate-middle-y me-3" />

        {searchOpen && query.trim() && <FloatingMenu as="div" anchorRef={search} open onClose={() => setSearchOpen(false)} matchAnchorWidth autoFocus={false} className="nms-search-results">{matches.map((item) => <Link className="dropdown-item d-flex align-items-center py-2" key={item.id} to={item.path} onClick={navigate}><Icon name={item.icon} className="me-2 text-muted" /><span>{item.title}</span></Link>)}{!matches.length && <p className="text-muted px-3 py-2 mb-0">Tidak ada modul, perangkat atau layanan yang sesuai.</p>}</FloatingMenu>}

      </div></div>

      <div className="navbar-nav flex-row">

        <button className="btn btn-outline-secondary me-2" type="button" title="Ganti tema" aria-label="Ganti tema" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}><Icon name={theme === 'dark' ? 'moon-fill' : 'sun-fill'} /></button>

        <button className="btn btn-outline-secondary me-2 d-none d-lg-inline-block" type="button" title="Layar penuh" aria-label="Layar penuh" onClick={fullscreen}><Icon name="arrows-fullscreen" className="icon-hover" /></button>

        <div className="dropdown me-2"><button ref={notificationButton} className="btn btn-outline-secondary position-relative" type="button" aria-label="Notifikasi" aria-expanded={menu === 'notifications'} onClick={() => { setSearchOpen(false); setMenu(menu === 'notifications' ? null : 'notifications') }}><Icon name="bell" />{connected && snapshot.alerts.length > 0 && <span className="position-absolute top-0 start-100 translate-middle badge rounded-pill bg-danger">{snapshot.alerts.length}</span>}</button><FloatingMenu anchorRef={notificationButton} open={menu === 'notifications'} onClose={() => setMenu(null)}>

          <li><h6 className="dropdown-header">Notifikasi NMS</h6></li><li><span className="dropdown-item-text text-muted small">{connected ? `${snapshot.alerts.length} alert aktif pada snapshot` : 'Data notifikasi belum terintegrasi'}</span></li><li><hr className="dropdown-divider" /></li><li><Link className="dropdown-item text-center" to="/alerts" onClick={navigate}>Lihat Peringatan dan Insiden</Link></li></FloatingMenu></div>

        <div className="dropdown">

          <button ref={accountButton} className="btn btn-outline-secondary d-flex align-items-center" type="button" aria-label="Menu akun pengguna" aria-expanded={menu === 'workspace'} onClick={() => { setSearchOpen(false); setMenu(menu === 'workspace' ? null : 'workspace') }}>

            <img src={user?.avatar || '/metis/avatar-placeholder.svg'} alt="" width="24" height="24" className="rounded-circle me-2" />

            <span className="d-none d-md-inline">{user ? user.username : 'Masuk'}</span>

            <Icon name="chevron-down" className="ms-1" />

          </button>

          <FloatingMenu anchorRef={accountButton} open={menu === 'workspace'} onClose={() => setMenu(null)}>

            {user ? (

              <>

                <li>

                  <div className="px-3 py-1">

                    <div className="fw-semibold small">{user.name || user.username}</div>

                    <small className="text-muted d-block">{user.role || 'Operator'}</small>

                  </div>

                </li>

                <li><hr className="dropdown-divider" /></li>

                <li><Link className="dropdown-item" to="/users" onClick={navigate}><Icon name="person" className="me-2" />Pengguna dan Log Audit</Link></li>

                <li><Link className="dropdown-item" to="/settings" onClick={navigate}><Icon name="gear" className="me-2" />Pengaturan Sistem</Link></li>

                <li><Link className="dropdown-item" to="/integrations" onClick={navigate}><Icon name="plug" className="me-2" />Integrasi</Link></li>

                <li><hr className="dropdown-divider" /></li>

                <li>

                  <button

                    type="button"

                    className="dropdown-item text-danger d-flex align-items-center"

                    disabled={loggingOut}

                    onClick={async () => {

                      setLoggingOut(true)

                      try { await logout(); navigate(); navigateHook('/login', { replace: true }) }

                      catch (e) { setNotice(`Proses keluar belum selesai: ${errorMessages[e.code] || 'server belum merespons'}. Coba kembali agar sesi dicabut di server.`); setMenu(null) }

                      finally { setLoggingOut(false) }

                    }}

                  >

                    <Icon name="box-arrow-right" className="me-2" />

                    <span>{loggingOut ? 'Mengakhiri sesi…' : 'Keluar'}</span>

                  </button>

                </li>

              </>

            ) : (

              <li>

                <Link className="dropdown-item d-flex align-items-center" to="/login" onClick={navigate}>

                  <Icon name="box-arrow-in-right" className="me-2 text-primary" />

                  <span>Masuk ke Dashboard</span>

                </Link>

              </li>

            )}

          </FloatingMenu>

        </div>

      </div>

    </div></nav></header>

    <div className={`sidebar-backdrop ${drawer && mobile ? 'show' : ''}`} onClick={closeDrawer} aria-hidden="true" />

    <aside ref={sidebar} className={`admin-sidebar ${drawer ? 'show' : ''}`} id="admin-sidebar" aria-label="Navigasi utama" inert={mobile && !drawer ? true : undefined}><div className="sidebar-content"><Link to="/" onClick={navigate}><BrandLogo className="theaz-brand-sidebar" /></Link><nav className="sidebar-nav"><ul className="nav flex-column">{['Workspace', 'Observability', 'Administration'].map((group, index) => <Fragment key={group}>{index > 0 && <li className="nav-item mt-3"><small className="text-muted text-uppercase">{({Workspace:'Ruang Kerja',Observability:'Pemantauan',Administration:'Administrasi'})[group]}</small></li>}{modules.filter((m) => m.group === group).map((item) => <li className="nav-item" key={item.id}><NavLink end={item.path === '/'} to={item.path} title={item.title} className={({ isActive }) => `nav-link ${isActive || current?.id===item.id ? 'active' : ''}`} onClick={navigate}><Icon name={item.icon} /><span className="nms-nav-label">{item.navTitle || item.title}</span></NavLink></li>)}</Fragment>)}{platform.integrations.some((s)=>s.enabled) && <><li className="nav-item mt-3"><small className="text-muted text-uppercase">Layanan dan Portal</small></li>{platform.integrations.filter((s)=>s.enabled).slice(0,10).map((s)=><li className="nav-item" key={s.id}><NavLink className={({isActive})=>`nav-link ${isActive?'active':''}`} to={'/integrations/'+s.id} onClick={navigate}><Icon name="box-arrow-up-right"/><span className="nms-nav-label">{s.name}</span></NavLink></li>)}</>}</ul><button className="btn btn-sm btn-outline-secondary d-lg-none mt-3 w-100" onClick={closeDrawer}>Tutup navigasi</button></nav></div></aside>

    <main ref={main} id="main-content" className="admin-main" tabIndex={-1} inert={mobile && drawer ? true : undefined}><div className="container-fluid p-4 p-lg-4">

      <div className="d-flex flex-column flex-md-row justify-content-between align-items-start align-items-md-center gap-3 mb-4"><div><h1 className="h3 mb-0">{detailName || current?.title || 'Halaman tidak ditemukan'}</h1><p className="text-muted mb-0">{current?.description || 'Gunakan navigasi untuk membuka modul NMS.'}</p></div><div className="d-flex gap-2 flex-shrink-0"><Link className="btn btn-primary" to="/integrations"><Icon name="plug" className="me-2" /><span>Integrasi API</span></Link><button className="btn btn-outline-secondary" title={config.enabled ? 'Perbarui data' : 'Aktifkan integrasi API terlebih dahulu'} aria-label="Perbarui data" disabled={!config.enabled || connection.status === 'loading'} onClick={refresh}><Icon name="arrow-clockwise" className="icon-hover" /></button><Link className="btn btn-outline-secondary d-none d-sm-inline-block" title="Pengaturan" aria-label="Pengaturan" to="/settings"><Icon name="gear" className="icon-hover" /></Link></div></div>

      <nav aria-label="Jejak navigasi"><ol className="breadcrumb small mb-4"><li className="breadcrumb-item"><Link to="/">Ruang Kerja</Link></li>{current && <li className={detailName ? 'breadcrumb-item' : 'breadcrumb-item active'}>{detailName ? <Link to={current.path}>{current.title}</Link> : current.title}</li>}{detailName && <li className="breadcrumb-item active" aria-current="page">{detailName}</li>}</ol></nav>

      {notice && <div className="alert alert-info d-flex align-items-center justify-content-between" role="status">{notice}<button className="btn-close ms-3" aria-label="Tutup informasi" onClick={() => setNotice('')} /></div>}

      <div className={`alert ${connected ? 'alert-success' : 'alert-warning'} d-flex flex-wrap align-items-center gap-2 mb-4`} role="status"><Icon name={connected ? 'check-circle' : 'info-circle'} className="me-1" /><div className="flex-grow-1"><strong>{connected ? 'API monitoring terhubung' : connection.status === 'loading' ? 'Membaca data monitoring…' : errorMessages[connection.error] || 'API belum dihubungkan'}</strong><div className="small">{connected ? `Snapshot terakhir: ${formatTime(snapshot.receivedAt)}` : 'Status perangkat belum dapat dipastikan. Silakan periksa koneksi backend.'}</div></div><Badge status={connected ? 'UP' : 'UNKNOWN'}>{connected ? 'Terhubung' : 'Belum terintegrasi'}</Badge></div>

      <Outlet />

    </div></main>

    <footer className="admin-footer"><div className="container-fluid px-4"><div className="d-flex flex-wrap justify-content-between gap-2 small text-muted"><span className="d-flex align-items-center gap-2"><BrandLogo className="theaz-brand-footer" />{platform.settings?.value.identity && platform.settings.value.identity !== 'NMS Homelab' ? platform.settings.value.identity : workspaceTitle} · v0.6.0</span><span>UI Metis · <Link to="/system-health">Status sistem</Link> · Asia/Jakarta</span></div></div></footer>

  </div></div>

}

