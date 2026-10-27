import { useEffect, useRef, useState } from 'react'
import { EmptyState } from './ui'
import { categorical, axisInk, gridLine } from '../../template-dashboard/src-modern/scripts/utils/chart-palette.js'
import { formatBps } from '../data/format'
const defaultMetrics = ['cpu', 'memory']
const trafficMetrics = ['rx', 'tx']
export function TrafficChart({ points }) { return <HistoryChart points={points} metrics={trafficMetrics} kind="traffic" /> }
export function HistoryChart({ points, metrics = defaultMetrics, kind = 'resource' }) {
  const host = useRef(null)
  const [failed, setFailed] = useState(false)
  const [theme, setTheme] = useState(() => document.documentElement.dataset.bsTheme || 'dark')
  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(document.documentElement.dataset.bsTheme || 'dark'))
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-bs-theme'] })
    return () => observer.disconnect()
  }, [])
  const valid = points.some((p) => metrics.some((metric) => typeof p[metric] === 'number'))
  useEffect(() => {
    if (!valid) return
    let disposed = false; let chart
    import('../../template-dashboard/src-modern/scripts/utils/apex.js').then(async ({ default: ApexCharts }) => {
      if (disposed || !host.current) return
      chart = new ApexCharts(host.current, {
        chart: { type: 'area', height: 320, background: 'transparent', fontFamily: 'Inter Variable, sans-serif', foreColor: axisInk(), toolbar: { show: false }, animations: { enabled: false } },
        series: metrics.map((metric) => ({ name: { cpu: 'CPU', memory: 'RAM', rx: 'RX', tx: 'TX' }[metric], data: points.map((p) => ({ x: p.time * 1000, y: p[metric] })) })),
        colors: categorical(metrics.length), stroke: { curve: 'straight', width: 2 }, fill: { type: 'solid', opacity: 0.07 }, theme: { mode: theme },
        grid: { borderColor: gridLine(), strokeDashArray: 4 }, dataLabels: { enabled: false },
        xaxis: { type: 'datetime', labels: { datetimeUTC: false, formatter: (value, timestamp) => new Intl.DateTimeFormat('id-ID', { timeZone: 'Asia/Jakarta', hour: '2-digit', minute: '2-digit' }).format(timestamp || Number(value)) }, axisBorder: { show: false }, axisTicks: { show: false } },
        yaxis: { min: 0, ...(kind === 'resource' ? { max: 100 } : {}), labels: { formatter: (v) => kind === 'traffic' ? formatBps(v) : `${v.toFixed(0)}%` } },
        tooltip: { x: { formatter: (v) => new Date(v).toLocaleString('id-ID', { timeZone: 'Asia/Jakarta' }) + ' WIB' } },
        legend: { position: 'top', horizontalAlign: 'left' }, noData: { text: 'Belum ada sampel valid' },
      })
      await chart.render()
    }).catch(() => { if (!disposed) setFailed(true) })
    return () => { disposed = true; chart?.destroy() }
  }, [points, metrics, valid, theme, kind])
  if (!valid || failed) return <EmptyState icon="graph-up" title={failed ? 'Grafik belum dapat dimuat' : 'Belum ada sampel historis'} description="Grafik menunggu sampel valid dari sumber data aktif. Riwayat trafik live dikumpulkan di memori sejak dashboard dibuka." />
  return <div className="nms-chart w-100" ref={host} role="img" aria-label={kind === 'traffic' ? 'Grafik RX dan TX dalam bit per detik' : 'Grafik historis CPU dan RAM'} />
}
