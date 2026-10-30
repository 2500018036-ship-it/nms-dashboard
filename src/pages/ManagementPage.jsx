import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { usePlatform } from '../data/platformContext'
import { Badge, EmptyState, Panel, formatTime, Icon } from '../components/ui'
import { Feedback, Loading } from '../components/PlatformUI'
import { Confirmation, Modal } from '../components/Modal'
import { CredentialEditor } from '../components/CredentialEditor'
import { inventoryValue } from '../devices/serverInventory'
import { newDevice, deviceTypes, validatedDevice } from '../devices/model'
import { RouterOSReadPanel } from './RouterOSReadPanel'
import {SnmpCredentialsForm} from '../components/SnmpCredentialsForm'
import {emptySnmp,snmpErrors,saveSnmpCredentials} from '../devices/snmpEnrollment'

const steps=['Identitas','Metode monitoring','Akses & kredensial','Uji koneksi']
const monitoringMethods=[
  {id:'',label:'Inventaris saja',detail:'Simpan identitas perangkat tanpa membuat collector.'},
  {id:'icmp',label:'ICMP',detail:'Memeriksa keterjangkauan dan latensi. Tidak membaca konfigurasi atau trafik.'},
  {id:'tcp',label:'TCP',detail:'Memeriksa apakah satu port merespons.'},
  {id:'http',label:'HTTP / HTTPS',detail:'Memeriksa URL health yang Anda tentukan.'},
  {id:'dns',label:'DNS',detail:'Mengirim satu query DNS untuk mengukur jawaban dan waktu respons.'},
  {id:'routeros',label:'RouterOS API',detail:'Memakai profil baca-saja yang sudah dikonfigurasi di server.'},
  {id:'proxmox',label:'Proxmox API',detail:'Memakai token baca-saja yang sudah dikonfigurasi di server.'},
  {id:'snmp',label:'SNMPv2c / SNMPv3',detail:'Polling baca-saja atas system identity, uptime, interface dan counter IF-MIB. Bandwidth muncul setelah ada dua sampel counter.'},
  {id:'ssh',label:'SSH Linux (baca-saja)',detail:'Mengambil metrik OS Linux melalui perintah tetap, akun non-root, dan host key yang dipin.'},
]

function IntegrationGuide({device}){
  const method=device.monitor_method;const vendor=(device.vendor||'').toLowerCase();const osLike=/linux|debian|ubuntu|windows|microsoft/.test(vendor+' '+(device.model||''))
  if(method==='snmp')return <div className="alert alert-info small mt-3"><strong>Langkah SNMP untuk {device.vendor||device.type} {device.model||''}.</strong><ol className="mb-2 mt-2 ps-3"><li>Aktifkan SNMP pada GUI perangkat dan buat akun/community monitoring <strong>baca-saja</strong>. Utamakan SNMPv3 authPriv SHA/AES. v2c hanya dengan community unik.</li><li>Izinkan hanya alamat poller NMS menuju perangkat melalui <strong>UDP 161</strong>; pastikan perangkat membalas ke alamat poller yang sama. Jangan meneruskan UDP 161 dari internet.</li><li>Di langkah Akses & kredensial, isi versi SNMP, nama pengguna/community dan rahasia yang sama persis seperti di perangkat. Simpan & uji akan menyimpannya terenkripsi.</li><li>Tekan <em>Uji koneksi</em>. Hasil harus menunjukkan UP dan identitas SNMP asli. Interface/trafik hanya muncul jika perangkat mengembalikan IF-MIB; bandwidth baru ada sesudah dua polling.</li></ol>{/mikrotik|routeros/.test(vendor+' '+device.model)?<p className="mb-1">RouterOS: buka <strong>IP → SNMP</strong>, aktifkan SNMP, buat community v2c terbatas ke IP poller atau pengguna SNMPv3 read-only dengan authPriv. Jangan mengubah firewall/router dari wizard ini.</p>:/cisco/.test(vendor)?<p className="mb-1">Cisco Small Business: aktifkan SNMP di halaman administrasi/management sesuai versi firmware, buat view/group read-only dan batasi host manager ke IP poller. Menu SF200 berbeda antarfirmware.</p>:/tp.?link|tplink/.test(vendor)?<p className="mb-1">TP-Link: cari menu SNMP pada System Tools/Management sesuai model/firmware; aktifkan GET/read-only, set manager IP poller dan port 161. Beberapa model rumahan tidak menyediakan SNMP.</p>:osLike?<p className="mb-1">Linux/Windows: pastikan agen SNMP tersedia pada edisi/OS tersebut, bind ke interface manajemen, dan batasi akses inbound UDP 161 ke IP poller. NMS tidak memasang agen jarak jauh.</p>:<p className="mb-1">Pastikan model dan firmware benar-benar mendukung SNMP agent dan IF-MIB. Dukungan CPU, memori, suhu, VLAN atau routing vendor-specific belum diasumsikan bila OID-nya tidak dikembalikan.</p>}<span>Gagal: periksa agent aktif, versi/auth/privacy sama, ACL manager, UDP 161 dan rute pulang. Timeout tidak membuktikan perangkat mati.</span></div>
  if(method==='icmp')return <div className="alert alert-info small mt-3"><strong>Panduan ICMP.</strong> Tidak memerlukan akun atau port TCP/UDP. Pastikan IP manajemen benar, server NMS dapat merutekan paket ke perangkat, dan firewall perangkat mengizinkan ICMP echo dari server NMS. Data yang tersedia hanya status dan latensi jika balasan terukur; tidak ada CPU/interface/trafik.</div>
  if(method==='routeros')return <div className="alert alert-info small mt-3"><strong>RouterOS API.</strong> Adapter NMS memakai profil API baca-saja yang disiapkan di server untuk host {device.host}. Pada MikroTik, aktifkan API-SSL TCP 8729, buat grup read-only dan akun khusus yang hanya perlu `read` + `api`, lalu batasi service/API ke alamat poller. Pilih profil RouterOS yang host-nya cocok. Jangan masukkan kata sandi ke form pendaftaran.</div>
  if(method==='proxmox')return <div className="alert alert-info small mt-3"><strong>Proxmox API.</strong> Endpoint HTTPS TCP 8006. Adapter hanya memakai token yang sudah disiapkan di server, memverifikasi TLS, dan membutuhkan hak audit baca-saja untuk system/node, VM, serta storage. Buat token terpisah di Proxmox dengan privilege audit minimum lalu siapkan CA tepercaya di server; host harus sama dengan profil API.</div>
  if(method==='http')return <div className="alert alert-info small mt-3"><strong>HTTP/HTTPS.</strong> Masukkan URL health-check yang aman pada host terdaftar. NMS mengikuti port URL dan memeriksa status HTTP; ini bukan login dan tidak membaca metrik perangkat. Redirect otomatis dinonaktifkan.</div>
  if(method==='tcp')return <div className="alert alert-info small mt-3"><strong>TCP.</strong> Masukkan port layanan yang memang aktif. Pemeriksaan hanya melakukan koneksi TCP singkat dari NMS; port terbuka bukan bukti aplikasi atau perangkat sehat.</div>
  if(method==='dns')return <div className="alert alert-info small mt-3"><strong>DNS.</strong> Pastikan UDP/TCP port 53 dari NMS diizinkan. Wizard mengirim query DNS yang Anda masukkan dan mengukur jawabannya; hasil tidak membaca metrik host.</div>
  if(method==='ssh')return <div className="alert alert-info small mt-3"><strong>SSH Linux baca-saja.</strong><ol className="mb-2 mt-2 ps-3"><li>Pastikan host Linux dapat dijangkau dari poller dan TCP {device.monitor_port||22} diizinkan hanya dari IP server NMS.</li><li>Buat akun khusus non-root pada Linux, misalnya <code>sudo adduser nms-monitor</code>. Akun hanya perlu login SSH dan baca <code>/proc</code>, <code>/proc/net/dev</code>, serta menjalankan <code>uname</code> dan <code>df</code>. Tidak perlu sudo atau akses tulis.</li><li>Di console tepercaya host, verifikasi fingerprint dengan <code>ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub</code> (atau <code>/etc/ssh/ssh_host_ecdsa_key.pub</code>). Salin algoritma dan bagian Base64 public key ke vault. Pastikan fingerprint cocok dengan console sebelum menyimpan.</li><li>Isi user dan kata sandi akun tersebut di vault. Simpan perangkat, kemudian pilih <em>Uji koneksi</em>. Poller menolak host key yang berubah dan hanya menjalankan pembacaan metrik tetap.</li></ol><p className="mb-1">Didukung: Linux. Windows belum didukung melalui SSH; gunakan SNMP (jika agen/fiturnya tersedia) atau ICMP. CPU dan bandwidth memerlukan dua sampel aktual.</p><span>Gagal: cek TCP {device.monitor_port||22}, user/kata sandi, jenis/Base64 host key, fingerprint, serta izin baca. Host key mismatch berarti key tidak cocok.</span></div>
  return <div className="alert alert-secondary small mt-3">Inventaris saja menyimpan identitas perangkat tanpa koneksi/polling. Pilih metode yang telah dikonfigurasi untuk mulai mengumpulkan data.</div>
}

export function DeviceRegistration({item,inventory=[],enrollment,onClose,onSaved}) {
  const p=usePlatform();const [step,setStep]=useState(0)
  const [f,setF]=useState(()=>({...newDevice(),location:'',role:'',hostname:'',credential_ref:'',monitor_method:'icmp',monitor_port:443,monitor_url:'',dns_query:'example.com',mac_address:'',follow_dhcp:false,...(item?inventoryValue(item):{} )}))
  const [error,setError]=useState(null);const [busy,setBusy]=useState(false);const [fieldErrors,setFieldErrors]=useState({});const [savedDeviceId,setSavedDeviceId]=useState(item?.id||'');const [testResult,setTestResult]=useState(null)
  const [authorize,setAuthorize]=useState(true)
  const [savedRecord,setSavedRecord]=useState(item||null)
  const [snmp,setSnmp]=useState(emptySnmp)
  const [snmpLoaded,setSnmpLoaded]=useState(!item)
  const [snmpLoading,setSnmpLoading]=useState(false)
  const [snmpLoadError,setSnmpLoadError]=useState(null)
  const [snmpValidation,setSnmpValidation]=useState({})
  const saving=useRef(false)
  useEffect(()=>{
    if(f.monitor_method!=='snmp'||!item?.id||snmpLoaded||!p.canReadCredentials||step<2)return
    const controller=new AbortController()
    const start=setTimeout(()=>{
      setSnmpLoading(true)
      p.client.credentials('inventory',item.id,{signal:controller.signal}).then((value)=>{
        if(!controller.signal.aborted){setSnmp(value.credentials.snmp?.version?value.credentials.snmp:emptySnmp());setSnmpLoading(false);setSnmpLoaded(true);setSnmpLoadError(null)}
      }).catch((e)=>{if(!controller.signal.aborted)setSnmpLoadError(e.code||'unavailable')}).finally(()=>{if(!controller.signal.aborted)setSnmpLoading(false)})
    },0)
    return()=>{clearTimeout(start);controller.abort()}
  },[f.monitor_method,item?.id,p.client,p.canReadCredentials,snmpLoaded,step])
  const needsAuthorization=Boolean(f.monitor_method&&!p.settings?.value?.allowed_hosts?.includes(f.host.trim().toLowerCase()))
  const canAuthorize=p.capabilities.permissions?.includes('config.manage')
  const set=(k,v)=>{setF((old)=>({...old,[k]:v}));setTestResult(null)}
  const profile=enrollment?.credential_profiles?.find((v)=>v.id===(f.monitor_method==='routeros'?'routeros-default':'proxmox-default'))
  const chooseMethod=(method)=>{
    const methods={icmp:['icmp'],tcp:['tcp'],http:['http'],dns:['dns'],snmp:['snmp'],ssh:['ssh'],routeros:['api'],proxmox:['api'],'':['icmp']}
    setF((old)=>({...old,monitor_method:method,methods:methods[method]||old.methods,follow_dhcp:method==='icmp'?old.follow_dhcp:false,
      monitor_categories:method==='snmp'?['network_status','system_information','interfaces','traffic','bandwidth']:method==='ssh'?['network_status','system_information','cpu','memory','storage','interfaces','traffic','bandwidth']:['network_status'],
      credential_ref:method==='routeros'?'routeros-default':method==='proxmox'?'proxmox-default':'',monitor_url:'',monitor_port:method==='dns'?53:method==='snmp'?161:method==='ssh'?22:443}))
    setTestResult(null)
  }
  const normalized=()=>validatedDevice(f,inventory,savedRecord?.id||item?.id)
  const validateStep=(target)=>{
    try{const value=normalized();setFieldErrors({});return value}catch(e){
      const relevant=target===0?['name','host','type']:target===1?['monitor_method','methods','profile','interval']:target===2?['host','credential_ref','monitor_url','monitor_port','dns_query','mac_address']:['form']
      const errors=Object.fromEntries(Object.entries(e.errors||{}).filter(([key])=>relevant.includes(key)))
      if(!Object.keys(errors).length&&target===3)Object.assign(errors,e.errors||{})
      setFieldErrors(errors);return null
    }
  }
  const testDevice=async identity=>{
    setBusy(true);setError(null);setTestResult(null)
    try{const result=await p.client.platform(`inventory/${identity}/test`,{body:{}});setTestResult(result);return result}
    catch(e){setError(e.code||'unavailable');return null}
    finally{setBusy(false)}
  }
  const saveAndTest=async()=>{
    if(busy||saving.current)return
    const value=validateStep(3);if(!value)return
    if(f.monitor_method==='snmp') {
      const errors=snmpErrors(snmp);setSnmpValidation(errors)
      if(Object.keys(errors).length||!snmpLoaded||snmpLoading||snmpLoadError){setStep(2);return}
      if(!p.canManageCredentials){setError('permission_denied');return}
    }
    if(needsAuthorization&&(!authorize||!canAuthorize)){setError('host_not_allowed');return}
    saving.current=true
    setBusy(true);setError(null);setTestResult(null)
    try{
      if(savedRecord?.id&&f.monitor_method==='snmp')await saveSnmpCredentials(p.client,savedRecord.id,snmp)
      const saved=await p.mutate(`inventory${savedRecord?'/'+savedRecord.id:''}`,{value:inventoryValue(value),...(needsAuthorization&&authorize&&canAuthorize?{authorize_host:true}:{}),...(savedRecord?{revision:savedRecord.revision}:{})})
      const record=saved?.item||saved
      const identity=record?.id||savedRecord?.id
      if(!identity)throw Object.assign(new Error(),{code:'invalid_response'})
      setSavedRecord(record)
      setSavedDeviceId(identity);setStep(3)
      if(!savedRecord&&f.monitor_method==='snmp')await saveSnmpCredentials(p.client,identity,snmp)
      try{const result=await p.client.platform(`inventory/${identity}/test`,{body:{}});setTestResult(result)}catch(e){setError(e.code||'unavailable')}
      onSaved?.()
    }catch(e){setError(e.code||'validation_failed');setFieldErrors(e.errors||{})}
    finally{setBusy(false);saving.current=false}
  }
  const next=()=>{if(step===2&&f.monitor_method==='snmp'){const errors=snmpErrors(snmp);setSnmpValidation(errors);if(Object.keys(errors).length||!snmpLoaded||snmpLoading||snmpLoadError)return}if(validateStep(step))setStep((v)=>Math.min(3,v+1))}
  const field=(key,label,type='text',required=false)=><div className="col-md-6"><label className="form-label" htmlFor={'register-'+key}>{label}</label><input className={`form-control ${fieldErrors[key]?'is-invalid':''}`} id={'register-'+key} type={type} required={required} value={f[key]??''} maxLength={key==='monitor_url'?500:253} min={key==='interval'?15:1} max={key==='interval'?86400:65535} onChange={(e)=>set(key,type==='number'?Number(e.target.value):e.target.value)}/>{fieldErrors[key]&&<div className="invalid-feedback">{fieldErrors[key]}</div>}</div>
  const methodReady=!['routeros','proxmox'].includes(f.monitor_method)||(profile?.configured&&profile.host===f.host.trim())
  return <Modal title={item?'Perbarui perangkat':'Wizard penambahan perangkat'} onClose={busy?()=>{}:onClose} footer={<>
    <button type="button" className="btn btn-secondary" disabled={busy} onClick={onClose}>Tutup</button>
    {step>0&&<button type="button" className="btn btn-outline-secondary" disabled={busy} onClick={()=>setStep((v)=>v-1)}>Kembali</button>}
    {step<3&&<button type="button" className="btn btn-primary" disabled={busy} onClick={next}>Lanjut</button>}
    {step===3&&<button type="button" className="btn btn-primary" disabled={busy} onClick={saveAndTest}>{busy?'Menyimpan & menguji…':'Simpan & uji koneksi'}</button>}
    {step===3&&savedDeviceId&&<button type="button" className="btn btn-outline-primary" disabled={busy} onClick={()=>testDevice(savedDeviceId)}>{busy?'Menguji…':'Uji data tersimpan'}</button>}
  </>}>
    <ol className="nms-device-wizard-steps" aria-label="Langkah pendaftaran">{steps.map((label,index)=><li key={label} className={index===step?'active':index<step?'complete':''} aria-current={index===step?'step':undefined}><span>{index+1}</span>{label}</li>)}</ol>
    <Feedback error={error}/>
    {Object.keys(fieldErrors).length>0&&<div className="alert alert-danger" role="alert">Periksa field yang ditandai sebelum melanjutkan.</div>}
    {step===0&&<section aria-labelledby="wizard-identity"><h3 id="wizard-identity" className="h6">Identitas dan alamat manajemen</h3><p className="small text-muted">Masukkan alamat IP atau hostname yang dapat dijangkau dari server NMS. Alamat ini dipakai sebagai target collector.</p><div className="row g-3">
      {field('name','Nama perangkat','text',true)}{field('host','IP manajemen / hostname','text',true)}
      <div className="col-md-6"><label className="form-label" htmlFor="register-type">Tipe perangkat</label><select id="register-type" className="form-select" value={f.type} onChange={(e)=>set('type',e.target.value)}>{deviceTypes.map((t)=><option key={t}>{t}</option>)}</select></div>
      {field('vendor','Vendor')}{field('model','Model')}{field('location','Lokasi')}{field('role','Peran perangkat')}{field('hostname','Hostname tambahan')}{field('group','Grup')}
    </div></section>}
    {step===1&&<section aria-labelledby="wizard-method"><h3 id="wizard-method" className="h6">Pilih cara monitoring</h3><p className="small text-muted">Pilihan menjelaskan data yang benar-benar dapat dikumpulkan oleh adapter saat ini.</p><div className="row g-2">{monitoringMethods.map((method)=><div className="col-12" key={method.id}><label className={`nms-monitor-method ${f.monitor_method===method.id?'selected':''} ${method.disabled?'disabled':''}`}><input type="radio" name="monitor-method" value={method.id} checked={f.monitor_method===method.id} disabled={method.disabled} onChange={()=>chooseMethod(method.id)}/><span><strong>{method.label}</strong><small className="d-block text-muted">{method.detail}</small></span></label></div>)}<div className="col-12"><label className="form-label" htmlFor="register-profile">Profil tampilan metrik</label><select id="register-profile" className="form-select" value={f.profile} onChange={(e)=>set('profile',e.target.value)}><option value="connectivity">Keterjangkauan</option><option value="network">Interface dan trafik (jika adapter menyediakannya)</option><option value="host">Resource server</option><option value="virtualization">Virtualisasi Proxmox</option><option value="services">Kondisi layanan</option><option value="custom">Sesuai kemampuan adapter</option></select></div>{field('interval','Interval polling (detik)','number',true)}
    {['tcp','ssh'].includes(f.monitor_method)&&field('monitor_port',f.monitor_method==='ssh'?'Port SSH TCP':'Port TCP','number',true)}{f.monitor_method==='http'&&field('monitor_url','URL pemeriksaan HTTP/HTTPS','url',true)}{f.monitor_method==='dns'&&<>{field('monitor_port','Port DNS','number',true)}{field('dns_query','Nama domain untuk query','text',true)}</>}</div>
    {f.monitor_method==='icmp'&&<div className="border rounded p-3 mt-3"><label className="form-label" htmlFor="register-mac">MAC untuk pencocokan DHCP (opsional)</label><input id="register-mac" className="form-control" maxLength={17} value={f.mac_address} onChange={(e)=>set('mac_address',e.target.value)}/><label className="form-check mt-2"><input className="form-check-input" type="checkbox" checked={f.follow_dhcp} onChange={(e)=>set('follow_dhcp',e.target.checked)}/><span className="form-check-label">Ikuti alamat DHCP berdasarkan MAC</span></label><small className="text-muted">Alamat baru harus berasal dari lease aktif router yang dikonfigurasi dan membalas ping.</small></div>}
    {['routeros','proxmox'].includes(f.monitor_method)&&<div className={`alert ${methodReady?'alert-info':'alert-warning'} small mt-3`}>{profile?.configured?`Target API di server: ${profile.host}.`: 'Profil API belum disiapkan pada server.'} {profile?.configured&&profile.host!==f.host.trim()?'IP perangkat harus sama dengan target profil server.':''} Kredensial tidak dikirim atau disimpan dari browser.</div>}
    <IntegrationGuide device={f}/>
    </section>}
    {step===2&&<section aria-labelledby="wizard-access"><h3 id="wizard-access" className="h6">Akses, protokol, dan kredensial</h3><dl className="row small mb-3"><dt className="col-sm-4">Protokol</dt><dd className="col-sm-8">{monitoringMethods.find((m)=>m.id===f.monitor_method)?.label||'Inventaris saja'}</dd><dt className="col-sm-4">Port / endpoint</dt><dd className="col-sm-8">{f.monitor_method==='icmp'?'ICMP echo':f.monitor_method==='dns'?`UDP/TCP ${f.monitor_port}`:['tcp','ssh'].includes(f.monitor_method)?`TCP ${f.monitor_port}`:f.monitor_method==='snmp'?`UDP ${f.monitor_port}`:f.monitor_method==='http'?f.monitor_url||'URL belum diisi':profile?.configured?profile.host:'Belum dikonfigurasi'}</dd></dl>
      {f.monitor_method==='routeros'&&<div className="alert alert-info small">Gunakan API-SSL pada RouterOS. Akun monitoring di server harus read-only dan hanya mengizinkan read + api. NMS menolak kredensial dengan izin berlebih.</div>}
      {f.monitor_method==='proxmox'&&<div className="alert alert-info small">Gunakan token API Proxmox baca-saja dan CA TLS tepercaya. Token dikelola di server, bukan dimasukkan ke form ini.</div>}
      {f.monitor_method==='snmp'&&<><p className="small">Isi koneksi SNMP langsung di bawah. Pada MikroTik: aktifkan SNMP, gunakan read-only, security private untuk v3, serta Addresses 192.168.20.195/32.</p><div className="row g-3 mb-3">{field('monitor_port','Port SNMP UDP','number',true)}</div>{snmpLoading&&<p role="status">Memuat kredensial SNMP tersimpan…</p>}{snmpLoadError&&<Feedback error={snmpLoadError}/>}<SnmpCredentialsForm value={snmp} onChange={(value)=>{setSnmp(value);setSnmpValidation({});setTestResult(null)}} disabled={!p.canManageCredentials||snmpLoading||!snmpLoaded||Boolean(snmpLoadError)} errors={snmpValidation}/>{!p.canManageCredentials&&<div className="alert alert-warning">Diperlukan izin pengelolaan kredensial untuk menyimpan koneksi SNMP.</div>}</>}
      {f.monitor_method==='ssh'&&<div className="alert alert-warning small">Daftarkan perangkat dahulu. Di vault, isi akun Linux non-root, kata sandi, jenis host key dan Base64 key yang fingerprint-nya diverifikasi dari console. Simpan vault, lalu pilih <em>Uji koneksi</em>. Kredensial SSH disimpan terenkripsi per perangkat.</div>}
      <div className="alert alert-secondary small">Kredensial GUI asli dan kredensial monitoring disimpan terenkripsi dan terpisah dari inventaris. Konfigurasi perangkat tetap dilakukan melalui GUI aslinya.</div>
      {savedDeviceId&&f.monitor_method!=='snmp'&&<CredentialEditor targetType="inventory" targetId={savedDeviceId} title="Vault kredensial perangkat"/>}
      {!savedDeviceId&&f.monitor_method!=='snmp'&&<p className="small text-muted">Simpan pendaftaran pada langkah terakhir terlebih dahulu; setelah tersimpan, vault kredensial GUI dapat dibuka dengan izin yang sesuai.</p>}
      {needsAuthorization&&<div className="alert alert-warning"><label className="form-check mb-0"><input className="form-check-input" type="checkbox" checked={authorize} disabled={!canAuthorize} onChange={(e)=>setAuthorize(e.target.checked)}/><span className="form-check-label">Izinkan {f.host||'alamat ini'} pada allowlist monitoring saat menyimpan.</span></label>{!canAuthorize&&<small className="d-block mt-1">Minta Administrator mengizinkan alamat ini di Pengaturan Sistem.</small>}</div>}
    </section>}
    {step===3&&<section aria-labelledby="wizard-test"><h3 id="wizard-test" className="h6">Simpan dan uji dari server</h3><p className="small text-muted">NMS menguji metode yang dipilih dari server. Menyimpan inventaris tidak menandakan perangkat berhasil terhubung.</p><div className="border rounded p-3"><div><strong>{f.name||'Perangkat baru'}</strong><span className="text-muted"> · {f.host||'IP belum diisi'}</span></div><div className="small mt-1">{monitoringMethods.find((m)=>m.id===f.monitor_method)?.label||'Inventaris saja'} · setiap {f.interval} detik</div></div>
      {needsAuthorization&&<div className="alert alert-warning mt-3"><label className="form-check mb-0"><input className="form-check-input" type="checkbox" checked={authorize} disabled={!canAuthorize} onChange={(e)=>setAuthorize(e.target.checked)}/><span className="form-check-label">Izinkan alamat target pada allowlist saat menyimpan.</span></label></div>}
      {!methodReady&&<div className="alert alert-warning mt-3">Profil API belum cocok dengan host target. Ubah ke ICMP/inventaris atau siapkan profil di server sebelum uji API.</div>}
      {testResult&&<div className={`alert ${testResult.status==='UP'?'alert-success':'alert-warning'} mt-3`} role="status"><strong>Hasil uji: {testResult.status||testResult.integration_state||'UNKNOWN'}</strong><div>{testResult.error||testResult.method||testResult.read_state||'Collector belum menyediakan data.'}</div><small>Hasil pada {formatTime(testResult.sample_epoch||testResult.timestamp)}. Status tetap mengikuti polling berikutnya.</small>{testResult.supported_categories?.length>0&&<div className="mt-2">Kemampuan terdeteksi dari sampel asli: {testResult.supported_categories.map((id)=>id.replaceAll('_',' ')).join(', ')}.</div>}</div>}
      {testResult?.status!=='UP'&&<details className="mt-3"><summary>Pemecahan masalah</summary><ul className="small mt-2"><li>Pastikan IP adalah alamat manajemen dan server NMS dapat mencapainya; periksa allowlist tujuan.</li><li>Periksa protokol, port/ACL, TLS dan kredensial baca-saja. Timeout dapat berarti paket diblokir atau respons tidak kembali.</li><li>Untuk RouterOS/Proxmox, pastikan IP cocok dengan profil API yang disiapkan di server.</li><li>SNMP: cocokkan versi serta auth/privacy, pastikan UDP 161 dan view baca-saja; hanya OID yang dibalas akan ditawarkan.</li><li>SSH Linux: periksa TCP, akun non-root, fingerprint/jenis/Base64 host key, dan hak baca. Host key yang berubah harus diverifikasi di console dan dimasukkan ulang.</li></ul></details>}
      {savedDeviceId&&f.monitor_method!=='snmp'&&<CredentialEditor targetType="inventory" targetId={savedDeviceId} title="Vault kredensial perangkat"/>}
    </section>}
    <div className="small text-muted mt-3">Tidak ada perubahan konfigurasi atau pemindaian aktif pada perangkat. Collector hanya menjalankan metode yang dipilih dan diizinkan.</div>
  </Modal>
}

export function ManagementPage(){
  const p=usePlatform();const [params]=useSearchParams();const [data,setData]=useState(null);const [error,setError]=useState(null);const [message,setMessage]=useState('');const [busy,setBusy]=useState(false);const [modal,setModal]=useState(null);const [query,setQuery]=useState('')
  const refresh=useCallback(async()=>{try{const v=await p.client.platform('monitoring/enrollment');setData(v);setError(null)}catch(e){setError(e.code)}},[p.client])
  useEffect(()=>{const start=setTimeout(refresh,0);const timer=setInterval(refresh,30000);return()=>{clearTimeout(start);clearInterval(timer)}},[refresh])
  const canInventory=!p.error&&p.capabilities.permissions?.includes('inventory.manage')
  const inventory=(data?.inventory||p.inventory).filter((d)=>`${d.name} ${d.host} ${d.vendor} ${d.location||''}`.toLowerCase().includes(query.toLowerCase()))
  const test=async(d)=>{setBusy(true);try{const r=await p.client.platform(`inventory/${d.id}/test`,{body:{}});setMessage(`${d.name}: ${r.status||'UNKNOWN'} · ${r.error||r.method||'Pemeriksaan selesai'}. Ini hasil uji saat ini.`);await refresh()}catch(e){setError(e.code)}finally{setBusy(false)}}
  const remove=async()=>{setBusy(true);setError(null);try{await p.mutate(`inventory/${modal.item.id}/delete`,{revision:modal.item.revision,...(p.capabilities.permissions?.includes('topology.manage')?{detach_topology:true}:{})});setModal(null);setMessage('Pendaftaran perangkat dihapus dari NMS. Riwayat monitoring dipertahankan.');await refresh()}catch(e){setError(e.code);setModal(null)}finally{setBusy(false)}}
  const selectedId=params.get('device')
  return <><Feedback error={error||p.error} message={message}/><Loading loading={!data}/><Panel title="Perangkat dan Inventaris" subtitle="Monitoring terpusat, penemuan pasif, dan tautan GUI asli" action={<button className="btn btn-primary btn-sm" disabled={!canInventory} onClick={()=>setModal({kind:'register'})}><Icon name="plus-lg" className="me-1"/>Daftarkan perangkat</button>}>
    <div className="d-flex gap-2 mb-3 flex-wrap"><input className="form-control" style={{maxWidth:400}} aria-label="Cari perangkat" placeholder="Nama, alamat, lokasi, vendor…" value={query} onChange={(e)=>setQuery(e.target.value)}/><Link className="btn btn-outline-secondary" to="/devices">Inventaris & penemuan pasif</Link><Link className="btn btn-outline-secondary" to="/topology">Topologi</Link><Link className="btn btn-outline-secondary" to="/backups">Backup & Restore</Link><button className="btn btn-outline-secondary" onClick={refresh}>Perbarui</button></div>
    {!inventory.length?<EmptyState action={false} title="Belum ada inventaris" description="Daftarkan perangkat atau tautkan collector yang sudah tersedia."/>:<div className="table-responsive"><table className="table table-hover align-middle"><thead><tr><th>Perangkat</th><th>Metode</th><th>Status polling</th><th>Aksi</th></tr></thead><tbody>{inventory.map((d)=>{const state=data?.inventory.find((i)=>i.id===d.id);return <tr key={d.id} className={selectedId===d.id?'table-active':''}><td><strong>{d.name}</strong><small className="d-block text-muted">{d.host} · {d.location||'Lokasi belum diisi'}</small></td><td>{d.monitor_method||'Inventaris saja'}<small className="d-block text-muted">{state?.monitor_target||'Collector belum terhubung'}</small></td><td><Badge status={state?.health?.status||'UNKNOWN'}/><small className="d-block">{{CONNECTED:'Terhubung',UNREACHABLE:'Tidak ada respons',WAITING_FOR_SAMPLE:'Menunggu pemeriksaan',STALE:'Sampel kedaluwarsa',DISABLED:'Nonaktif',NOT_CONFIGURED:'Monitoring belum diaktifkan',COLLECTION_FAILED:'Collector gagal'}[state?.integration_state]||state?.integration_state||'Memuat…'}</small><small className="text-muted">{formatTime(state?.health?.sample_epoch)}</small></td><td><div className="d-flex gap-2 flex-wrap"><button className="btn btn-sm btn-outline-primary" disabled={!canInventory||busy} onClick={()=>setModal({kind:'register',item:d})}>Wizard / Edit</button><button className="btn btn-sm btn-outline-secondary" disabled={!canInventory||busy||!state?.monitor_target} onClick={()=>test(d)}>Uji koneksi</button><Link className="btn btn-sm btn-outline-secondary" to="/topology">Topologi</Link><button className="btn btn-sm btn-outline-danger" disabled={!canInventory||busy} onClick={()=>setModal({kind:'remove',item:d})}>Hapus</button></div></td></tr>})}</tbody></table></div>}
  </Panel>
  <RouterOSReadPanel sections={data?.routeros_sections}/>
  <Panel title="Akses perangkat" subtitle="Kredensial dan konfigurasi tetap dikelola melalui GUI asli"><p className="mb-0">Pilih perangkat dari menu <Link to="/access">Akses perangkat</Link> untuk membuka sesi browser terisolasi di dalam NMS. NMS tidak menyediakan editor konfigurasi router atau Proxmox. Status monitoring berasal dari collector dan menampilkan waktu sampel serta kegagalan secara eksplisit.</p></Panel>
  {modal?.kind==='remove'&&<Confirmation title="Hapus pendaftaran perangkat?" danger busy={busy} onClose={()=>setModal(null)} onConfirm={remove} confirmLabel="Hapus dari NMS"><p><strong>{modal.item.name}</strong> · {modal.item.host}</p><p>Hanya metadata inventaris yang dihapus. Riwayat monitoring dan konfigurasi perangkat di GUI asli tetap ada.</p></Confirmation>}
  {modal?.kind==='register'&&<DeviceRegistration item={modal.item} inventory={inventory} enrollment={data} onClose={()=>setModal(null)} onSaved={()=>{setMessage('Pendaftaran tersimpan; periksa hasil uji aktual sebelum mengandalkan collector.');refresh()}}/>}
  </>
}
