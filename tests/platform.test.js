import { answerBlocks } from '../src/data/answerModel.js'
import test from 'node:test'
import assert from 'node:assert/strict'
import { createApiClient } from '../src/data/apiClient.js'
import { adaptSession } from '../src/data/authModel.js'
import { isGatewayRequest, sameOriginRequest } from '../config/devProxy.js'
import { recordValue } from '../src/data/platformContext.js'
import { reportCSV } from '../src/data/reportModel.js'
import { serverInventory } from '../src/devices/serverInventory.js'
import { adaptIncident } from '../src/data/journalModel.js'
import { adaptStatus, ageSnapshot } from '../src/data/adapters.js'
const json=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}})
test('platform client restricts paths, query fields and device mutations',async()=>{
  const calls=[];const client=createApiClient({enabled:true,base:'/nms-api'},async(url,options)=>{calls.push({url,options});return json({ok:true})})
  await client.platform('topologies',{body:{value:{name:'LAN',nodes:[],links:[]}}})
  assert.equal(calls[0].options.method,'POST');assert.equal(calls[0].options.credentials,'same-origin')
  for(const path of ['../auth','integrations/x/exec','http://evil.test','settings?password=x','integrations//delete'])await assert.rejects(client.platform(path),{code:'target_not_allowed'})
  await assert.rejects(client.platform('report',{params:{host:'169.254.169.254'}}),{code:'target_not_allowed'})
  assert.equal(calls.length,1)
})
test('credential client uses an explicit same-origin route and validates target identities',async()=>{
  const calls=[];const client=createApiClient({enabled:true,base:'/nms-api'},async(url,options)=>{calls.push({url,options});return json({credentials:{gui:{username:'admin',password:'secret',fields:[]},wifi_networks:[],custom_fields:[]}})})
  const id='int_'+'a'.repeat(24)
  await client.credentials('integration',id)
  assert.equal(calls[0].url,`/nms-api/api/platform/credentials/integration/${id}`);assert.equal(calls[0].options.method,'GET');assert.equal(calls[0].options.cache,'no-store')
  const payload={gui:{username:'admin',password:'secret',fields:[]},wifi_networks:[],custom_fields:[]}
  await client.credentials('integration',id,{credentials:payload})
  assert.equal(calls[1].options.method,'POST');assert.deepEqual(JSON.parse(calls[1].options.body),{credentials:payload});assert.equal(calls[1].options.credentials,'same-origin')
  await assert.rejects(client.credentials('integration','int_bad'),{code:'target_not_allowed'})
  assert.equal(calls.length,2)
})
test('403 is permission denial and does not turn into successful local login',async()=>{
  const client=createApiClient({enabled:true,base:'/nms-api'},async()=>json({},403))
  await assert.rejects(client.platform('settings',{body:{}}),{code:'permission_denied'})
  const session=adaptSession({user:{username:'admin',name:'Admin',role:'Administrator'},expires_at:Date.now()/1000+60,idle_timeout_seconds:1800})
  assert.equal(session.user.role,'Administrator')
  assert.throws(()=>adaptSession({user:{username:'admin',role:'root'},expires_at:Date.now()/1000+60,idle_timeout_seconds:1800}))
})
test('development proxy exposes only explicit NMS configuration actions',()=>{
  for(const path of ['/api/platform','/api/platform/report?target=debian','/api/platform/jobs/job_'+'a'.repeat(24)])assert.equal(isGatewayRequest('GET','/nms-api'+path,'/nms-api'),true)
  for(const path of ['/api/platform/topologies','/api/platform/integrations/int_123/test','/api/platform/acknowledge/inc_event_1'])assert.equal(isGatewayRequest('POST','/nms-api'+path,'/nms-api'),true)
  for(const path of ['/api/platform/credentials/integration/int_'+'a'.repeat(24),'/api/platform/credentials/inventory/inv_'+'b'.repeat(24),'/api/platform/credentials/device/device_'+'c'.repeat(12)]){assert.equal(isGatewayRequest('GET','/nms-api'+path,'/nms-api'),true);assert.equal(isGatewayRequest('POST','/nms-api'+path,'/nms-api'),true)}
  assert.equal(isGatewayRequest('POST','/nms-api/api/platform/credentials/device/device_bad','/nms-api'),false)
  for(const path of ['/api/platform/integrations/x/exec','/api/proxmox/start','/api/platform/users/delete-all'])assert.equal(isGatewayRequest('POST','/nms-api'+path,'/nms-api'),false)
  assert.equal(sameOriginRequest({origin:'http://evil.test',host:'localhost:5173'}),false)
})
test('record value excludes server metadata and health',()=>{
  assert.deepEqual(recordValue({id:'int_1',revision:2,name:'DNS',health:{status:'UP'},monitor_target:'dns',created_at:1,updated_at:2,capabilities:['launcher']}),{name:'DNS'})
})
test('CSV preserves missing values and neutralizes spreadsheet formulas',()=>{
  const csv=reportCSV({target:'=WEBSERVICE("https://evil.test")',resource:null,from:1,to:2,samples:1,sample_availability_percent:null,coverage_percent:0,points:[{time:1,samples:1,cpu_percent:null,memory_percent:0,storage_percent:null,latency_ms:2}]})
  assert.ok(csv.includes("'=WEBSERVICE"));assert.ok(csv.includes('"","0","","2"'));assert.ok(csv.includes('1970-01-01T00:00:01.000Z'))
})
test('inventory adapter writes validated server metadata without claiming collector enrollment',async()=>{
  const calls=[];const value={id:'inv_1',revision:3,created_at:1,updated_at:2,name:'Router',host:'192.168.20.1',type:'router',vendor:'',model:'',methods:['api'],interval:60,group:'LAN',tags:[],profile:'network',enabled:true}
  const platform={canManage:true,inventory:[value],mutate:async(path,body)=>{calls.push({path,body});return {ok:true}}}
  const service=serverInventory(platform,[{id:'device_1',name:'Router',host:value.host,collectors:['mikrotik_system']}],{checks:[{id:'mikrotik_system',status:'UP',stale:false}]})
  await service.setEnabled(value.id,false);assert.equal(calls[0].body.revision,3);assert.equal(calls[0].body.value.enabled,false);assert.equal(calls[0].body.value.created_at,undefined)
  const result=await service.testConnection(value.id);assert.match(result.message,/snapshot collector bersama/);assert.equal(calls.length,1)
  assert.equal((await service.discover('192.168.20.0/24')).length,1);assert.equal((await service.discover('192.168.30.0/24')).length,0)
})
test('acknowledgment remains separate from incident status and filters secret fields',()=>{
  const value=adaptIncident({id:'inc_event_1',status:'ACTIVE',acknowledgment:{supported:true,actor:'operator1',at:123,note:'Investigating',token:'secret'}})
  assert.equal(value.status,'ACTIVE');assert.equal(value.acknowledgment.actor,'operator1');assert.equal(value.acknowledgmentSupported,true);assert.equal(value.acknowledgment.token,undefined)
})
test('Proxmox storage and permission metadata age without a fabricated zero',()=>{
  const now=Date.now()/1000;const value=adaptStatus({checks:[{target:'proxmox_resources',method:'API',status:'UP',sample_epoch:now,readonly_verified:true,version:{version:'9.2'},storage:[{id:'storage/pve/local',storage:'local',node:'pve',status:'available',disk:50,maxdisk:100}]}],alerts:[],interval:60},now)
  assert.equal(value.core.storage[0].percent,50);assert.equal(value.core.virtualization.readonlyVerified,true)
  const stale=ageSnapshot(value,now+300);assert.equal(stale.core.storage[0].status,'UNKNOWN');assert.equal(stale.core.storage[0].percent,null);assert.equal(stale.core.virtualization.status,'UNKNOWN')
})

test('per-collector freshness follows the configured service polling interval',()=>{
  const now=Date.now()/1000;const snapshot=adaptStatus({checks:[{target:'service_test',status:'UP',sample_epoch:now-300,stale_after_seconds:2700}],alerts:[],interval:60},now)
  assert.equal(snapshot.checks[0].status,'UP');assert.equal(ageSnapshot(snapshot,now+200).checks[0].status,'UP');assert.equal(ageSnapshot(snapshot,now+3000).checks[0].status,'UNKNOWN')
})

test('AI response headings and tables are formatted as text blocks without executing HTML',()=>{
  const blocks=answerBlocks('## VM\n| Nama | Status |\n| --- | --- |\n| DNS | UP |\n\n<script>alert(1)</script>')
  assert.equal(blocks[0].kind,'heading');assert.deepEqual(blocks[1].headers,['Nama','Status']);assert.deepEqual(blocks[1].rows,[['DNS','UP']]);assert.equal(blocks.at(-1).text,'<script>alert(1)</script>')
})
