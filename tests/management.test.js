import test from 'node:test'
import assert from 'node:assert/strict'
import { createApiClient } from '../src/data/apiClient.js'
import { adaptSession } from '../src/data/authModel.js'
import { isGatewayRequest } from '../config/devProxy.js'
import { connectedTopologyDevices, knownTopologyDeviceIds, linkedLegacyServices, portObservation, topologyDeviceNodes, topologyHostSummary } from '../src/data/topologyModel.js'
import { adaptStatus } from '../src/data/adapters.js'
import { inventoryValue } from '../src/devices/serverInventory.js'
import { validateDevice } from '../src/devices/model.js'

test('management client only exposes preview read and exact confirmation endpoints',async()=>{
 const calls=[];const client=createApiClient({enabled:true,base:'/nms-api'},async(url)=>{calls.push(url);return new Response('{}',{headers:{'content-type':'application/json'}})})
 for(const path of ['management','management/read','management/preview','management/plan_'+'a'.repeat(24)+'/confirm']){
  await client.platform(path,path==='management'?{}:{body:{}})
  assert.ok(isGatewayRequest(path==='management'?'GET':'POST','/nms-api/api/platform/'+path,'/nms-api'))
 }
 for(const path of ['management/exec','management/shell','management/plan_x/confirm','management/preview/../../shell'])await assert.rejects(client.platform(path),{code:'target_not_allowed'})
 assert.equal(calls.length,4)
})
test('role contract accepts granular roles and rejects invented privilege',()=>{
 for(const role of ['Viewer','Operator','Network Administrator','Server Administrator','Super Administrator'])assert.equal(adaptSession({user:{username:'test',role},expires_at:Date.now()/1000+60,idle_timeout_seconds:1800}).user.role,role)
 assert.throws(()=>adaptSession({user:{username:'test',role:'root'},expires_at:Date.now()/1000+60,idle_timeout_seconds:1800}))
})
test('topology never infers a cable from host UP and uses only named fresh port',()=>{
 const edge={source:'a',target:'b',source_port:'ether3'};const nodes=[{id:'a',name:'Router',collector:'mikrotik_system'},{id:'b',collector:'host_proxmox'}]
 assert.equal(portObservation(edge,nodes,[]).status,'UNKNOWN')
 const ports=[{sourceId:'mikrotik_interfaces',name:'ether3',status:'DOWN',stale:false}]
 assert.equal(portObservation(edge,nodes,ports).status,'DOWN')
 assert.equal(portObservation(edge,nodes,[{...ports[0],stale:true}]).status,'UNKNOWN')
 assert.match(portObservation(edge,nodes,ports).scope,/bukan verifikasi relasi fisik/)
})
test('topology candidates require a fresh UP device collector and exclude service inventory',()=>{
 const now=1_800_000_000
 const inventory=[
  {id:'inv_router',name:'Router',host:'192.168.20.1',type:'router',enabled:true,interval:60},
  {id:'inv_switch',name:'Switch',host:'192.168.20.2',type:'switch',enabled:true,interval:60},
  {id:'inv_dns',name:'DNS check',host:'192.168.20.199',type:'service',enabled:true,interval:60},
 ]
 const states=[
  {id:'inv_router',integration_state:'CONNECTED',monitor_target:'inventory_inv_router',health:{status:'UP',sample_epoch:now-5,stale:false}},
  {id:'inv_switch',integration_state:'CONNECTED',monitor_target:'inventory_inv_switch',health:{status:'UP',sample_epoch:now-500,stale:true}},
  {id:'inv_dns',integration_state:'CONNECTED',monitor_target:'inventory_inv_dns',health:{status:'UP',sample_epoch:now-5,stale:false}},
 ]
 const observed=[{id:'device_mikrotik',name:'192.168.20.1',host:'192.168.20.1',status:'UP',sampled:now-5,staleAfter:120,collectors:['mikrotik_system']}]
 const rows=connectedTopologyDevices({inventory,inventoryStates:states,observedDevices:observed,now})
 assert.equal(rows.length,1)
 assert.equal(rows[0].device_id,'inv_router')
 assert.equal(rows[0].kind,'router')
 assert.equal(knownTopologyDeviceIds(inventory,observed).has('inv_dns'),false)
})
test('topology canvas filters services and old virtual guests but keeps linked service labels for hover',()=>{
 const graph={nodes:[{id:'router',name:'MikroTik',kind:'router',device_id:'inv_router'},{id:'dns',name:'Technitium DNS',kind:'application'},{id:'vm',name:'Web server',kind:'vm'}],links:[{id:'r-dns',source:'router',target:'dns'},{id:'r-vm',source:'router',target:'vm'}]}
 const visible=topologyDeviceNodes(graph,new Set(['inv_router']))
 assert.deepEqual(visible.nodes.map((node)=>node.id),['router'])
 assert.equal(visible.links.length,0)
 assert.deepEqual(linkedLegacyServices(visible.nodes[0],graph).map((row)=>row.name),['Technitium DNS','Web server'])
 assert.equal(visible.hiddenCount,2)
})
test('host summary distinguishes the Debian Docker server from Proxmox nodes',()=>{
 assert.equal(topologyHostSummary([{sourceId:'debian'},{sourceId:'proxmox_resources'}]),'1 server Debian/Docker · 1 node Proxmox')
})
test('resource rows keep distinct Debian and Proxmox endpoint identities',()=>{
 const now=Date.now()/1000
 const result=adaptStatus({checks:[
  {target:'debian',method:'host /proc snapshot',status:'UP',sample_epoch:now,host:'192.168.20.195',cpu_percent:5,memory_percent:40,disks:[]},
  {target:'proxmox_resources',method:'PVE API',status:'UP',sample_epoch:now,host:'192.168.20.200',nodes:[{id:'node/pve',node:'pve',status:'online',cpu:.1,mem:40,maxmem:100}]},
 ],alerts:[],interval:60},now)
 assert.equal(result.core.hosts.length,2)
 assert.equal(result.core.hosts[0].name,'Debian Docker server')
 assert.equal(result.core.hosts[0].host,'192.168.20.195')
 assert.equal(result.core.hosts[1].host,'192.168.20.200')
})
test('inventory connection metadata round trips without credentials',()=>{
 const d={name:'DNS',host:'192.168.20.199',type:'dns',methods:['dns'],interval:60,group:'LAN',tags:[],profile:'connectivity',enabled:true,monitor_method:'dns',monitor_port:53,location:'Rack',credential_ref:''}
 const result=validateDevice(d);assert.equal(result.value.monitor_method,'dns');assert.equal(result.value.location,'Rack')
 assert.equal(inventoryValue({...d,password:'never',revision:1}).password,undefined)
 assert.equal(validateDevice({...d,password:'never'}).value,null)
})
