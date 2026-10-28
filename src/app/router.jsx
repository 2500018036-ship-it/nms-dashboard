import { Component } from 'react'
import { Link, Navigate, Outlet, Route, Routes, useLocation } from 'react-router'
import { useAuth } from '../data/authSessionContext'
import { PlatformProvider } from '../data/PlatformProvider'
import { MonitoringProvider } from '../data/MonitoringProvider'
import { errorMessages } from '../data/apiClient'
import { AppLayout } from '../components/layout/AppLayout'
import { LoginPage } from '../pages/LoginPage'
import { OverviewPage } from '../pages/OverviewPage'
import { ReportsPage, HealthPage } from '../pages/MonitoringPages'
import { NetworkPage } from '../pages/NetworkPage'
import { ServersPage } from '../pages/ServersPage'
import { DevicesPage } from '../pages/DevicesPage'
import { AlertsPage } from '../pages/AlertsPage'
import { AccessPortalPage } from '../pages/AccessPortalPage'
import { ManagementPage } from '../pages/ManagementPage'
import { TopologyEditor } from '../pages/TopologyEditor'
import { IntegrationsPage, ServiceDetailPage } from '../pages/IntegrationsPage'
import { ProxmoxPage, DeviceDetailPage } from '../pages/ResourcePages'
import { PlatformSettings } from '../pages/PlatformSettings'
import { UnifiedLogsPage } from '../pages/UnifiedLogsPage'
import { AssistantPage, UsersPage } from '../pages/FoundationPages'
import { EmptyState } from '../components/ui'

class PageBoundary extends Component {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() {
    if (this.state.failed) return <div className="container py-5"><div className="alert alert-danger"><h1 className="h4">Halaman belum dapat ditampilkan</h1><p>Terjadi kesalahan pada antarmuka. Data infrastruktur tidak diubah.</p><button className="btn btn-primary" onClick={() => window.location.reload()}>Muat ulang dashboard</button></div></div>
    return this.props.children
  }
}
export function AppRouter() {
  return (
    <PageBoundary>
      <Routes>
        <Route path="login" element={<LoginPage />} />
        <Route element={<ProtectedWorkspace />}>
        <Route element={<AppLayout />}>
          <Route index element={<OverviewPage />} />
          <Route path="network" element={<NetworkPage />} />
          <Route path="servers" element={<ServersPage />} />
          <Route path="topology" element={<TopologyEditor />} />
          <Route path="devices" element={<DevicesPage />} />
          <Route path="access" element={<AccessPortalPage />} />
          <Route path="management" element={<ManagementPage />} />
          <Route path="alerts" element={<AlertsPage />} />
          <Route path="assistant" element={<AssistantPage />} />
          <Route path="settings" element={<PlatformSettings />} />
          <Route path="virtualization" element={<ProxmoxPage />} />
          <Route path="devices/:id" element={<DeviceDetailPage />} />
          <Route path="integrations/:id" element={<ServiceDetailPage />} />
          <Route path="integrations" element={<IntegrationsPage />} />
          <Route path="logs" element={<UnifiedLogsPage />} />
          <Route path="reports" element={<ReportsPage />} />
          <Route path="users" element={<UsersPage />} />
          <Route path="system-health" element={<HealthPage />} />
          <Route path="*" element={<div className="card text-center p-4"><EmptyState icon="signpost-split" title="Rute tidak ditemukan" description="Gunakan sidebar atau pencarian untuk membuka modul NMS." action={false} /><Link className="btn btn-primary align-self-center" to="/">Kembali ke Overview</Link></div>} />
        </Route>
        </Route>
      </Routes>
    </PageBoundary>
  )
}

function ProtectedWorkspace() {
  const { status, error, check } = useAuth(); const location = useLocation()
  if (status === 'checking') return <main className="container py-5 text-center" aria-live="polite"><span className="spinner-border text-primary mb-3" /><p>Memeriksa sesi dashboardÃ¢â‚¬Â¦</p></main>
  if (status === 'error') return <main className="container py-5"><div className="card mx-auto p-4" style={{ maxWidth: 520 }}><h1 className="h4">Sesi belum dapat diverifikasi</h1><p className="text-muted">{errorMessages[error] || 'Backend belum dapat diakses'}. Data monitoring memerlukan sesi yang valid.</p><button className="btn btn-primary" onClick={check}>Coba hubungkan kembali</button><Link className="btn btn-link mt-2" to="/login" state={{ from: location.pathname }}>Ke halaman masuk</Link></div></main>
  if (status !== 'authenticated') return <Navigate to="/login" replace state={{ from: location.pathname, expired: error === 'session_expired' }} />
  return <MonitoringProvider><PlatformProvider><Outlet /></PlatformProvider></MonitoringProvider>
}
