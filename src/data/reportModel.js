const csvCell = (value) => { const text = value == null ? '' : String(value); return '"' + (/^[=+@-]/.test(text) ? "'" + text : text).replaceAll('"','""') + '"' }
export function reportCSV(report) {
  const rows = [['target','resource','from_utc','to_utc','sample_availability_percent','coverage_percent','samples'],[report.target,report.resource,new Date(report.from*1000).toISOString(),new Date(report.to*1000).toISOString(),report.sample_availability_percent,report.coverage_percent,report.samples],[],['time_utc','samples','cpu_percent','memory_percent','storage_percent','latency_ms'],...report.points.map((p) => [new Date(p.time*1000).toISOString(),p.samples,p.cpu_percent,p.memory_percent,p.storage_percent,p.latency_ms])]
  return '\uFEFF' + rows.map((r) => r.map(csvCell).join(',')).join('\r\n')
}
