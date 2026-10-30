import { newDevice, parseInventory, validatedDevice, validateScope } from './model.js'
export const inventoryValue = (d) => Object.fromEntries(Object.entries(d).filter(([k]) => ['name','host','type','vendor','model','methods','interval','group','tags','profile','enabled','location','role','hostname','credential_ref','monitor_method','monitor_port','monitor_url','dns_query','mac_address','follow_dhcp','monitor_categories'].includes(k)))
export function serverInventory(platform,observed,snapshot) {
  const current = () => platform.inventory.map((d)=>({...inventoryValue(d),id:d.id}))
  const item = (id) => platform.inventory.find((d)=>d.id===id)
  const candidates = () => observed.filter((d)=>/^\d+\.\d+\.\d+\.\d+$/.test(d.host)).map((d)=>({id:d.id,approved:platform.inventory.some((r)=>r.host===d.host),device:{...newDevice(),name:d.name,host:d.host,interval:60,group:'Observed',profile:'custom',methods:['icmp']}}))
  return {
    canWrite:platform.capabilities?.permissions?.includes('inventory.manage') || platform.canManage,
    create:async(value)=>platform.mutate('inventory',{value:inventoryValue(validatedDevice(value,current()))}),
    update:async(id,value)=>platform.mutate(`inventory/${id}`,{revision:item(id)?.revision,value:{...inventoryValue(item(id)),...inventoryValue(validatedDevice(value,current(),id))}}),
    remove:async(id)=>platform.mutate(`inventory/${id}/delete`,{revision:item(id)?.revision}),
    setEnabled:async(id,enabled)=>platform.mutate(`inventory/${id}`,{revision:item(id)?.revision,value:{...inventoryValue(item(id)),enabled}}),
    import:async(text)=>{const values=parseInventory(text,current());await platform.mutate('inventory/import',{devices:values.map(inventoryValue)});return values.length},
    candidates,
    discover:async(scope)=>{
      if(!validateScope(scope))throw Object.assign(new Error(),{code:'validation_failed'})
      const [host,bits]=scope.split('/');const ip=(v)=>v.split('.').reduce((n,b)=>(n*256+Number(b))>>>0,0);const shift=32-Number(bits)
      return candidates().filter((c)=>(ip(c.device.host)>>>shift)===(ip(host)>>>shift))
    },
    approve:async(ids)=>{const devices=candidates().filter((c)=>ids.includes(c.id)&&!c.approved).map((c)=>inventoryValue(c.device));await platform.mutate('inventory/import',{devices});return devices.length},
    testConnection:async(id)=>{const d=item(id);const observedDevice=observed.find((o)=>o.host===d?.host);const checks=snapshot.checks.filter((c)=>observedDevice?.collectors.includes(c.id));return {message:checks.length?checks.map((c)=>`${c.id}: ${c.status}${c.stale?' (kedaluwarsa)':''}`).join(' · ')+' — snapshot collector bersama, tanpa probe baru.':'UNKNOWN — belum ada collector yang terhubung untuk alamat ini. Simpan metadata tidak otomatis mengaktifkan SNMP/API.'}},
  }
}
