import {test} from 'node:test'
import assert from 'node:assert/strict'
import {integrationGuide,standardMethods} from '../src/devices/integrationGuide.js'
import {emptySsh,sshErrors} from '../src/devices/sshEnrollment.js'
import {newDevice,validateDevice} from '../src/devices/model.js'
import {inventoryValue} from '../src/devices/serverInventory.js'
import {createApiClient} from '../src/data/apiClient.js'

test('SF200 instructions name the actual service activation menu and distinguish poller IP from switch IP',()=>{
  const guide=integrationGuide({vendor:'Cisco',model:'SF200-24',firmware:'1.3',host:'192.168.10.26',monitor_method:'snmp'},'192.168.20.195')
  assert.match(guide.steps[0],/Security → TCP\/UDP Services/);assert.match(guide.steps[1],/192\.168\.20\.195/)
  assert.match(guide.steps[1],/192\.168\.10\.26/);assert.match(guide.steps.join(' '),/Startup Configuration/)
  assert.ok(!standardMethods.some((m)=>['routeros','proxmox','api'].includes(m.id)))
})
test('Linux SSH guide uses non-root credentials and trusted host key; unsupported appliance data remains explicit',()=>{
  assert.match(integrationGuide({monitor_method:'ssh',vendor:'Proxmox'}).steps.join(' '),/non-root/)
  assert.match(integrationGuide({monitor_method:'snmp',vendor:'TP-Link',model:'TL-WR820N'}).steps[0],/tidak menyediakan SNMP/)
  assert.match(integrationGuide({monitor_method:'icmp'}).limits.join(' '),/CPU/)
  assert.ok(sshErrors({...emptySsh(),username:'root',password:'test',host_key_data:'AAAA'}).username)
})
test('inventory forwards firmware, GUI and physical-parent relationship while keeping credentials separate',()=>{
  const value={...newDevice(),name:'DNS',host:'192.168.20.199',parent_id:'inv_'+'a'.repeat(24),component_kind:'service',component_ref:'dns',firmware:'12',dashboard_url:'http://192.168.20.199:5380/'}
  const valid=validateDevice(value,[{id:'parent',host:value.host}]);assert.ok(valid.value)
  assert.equal(inventoryValue(valid.value).parent_id,value.parent_id);assert.equal(inventoryValue(valid.value).firmware,'12')
  assert.ok(!('password' in inventoryValue({...valid.value,password:'secret'})))
})
test('new control paths remain exact and history accepts only enrolled device identifiers',async()=>{
  const requests=[];const fetcher=async(url)=>{requests.push(url);return new Response('{}',{headers:{'content-type':'application/json'}})}
  const client=createApiClient({enabled:true,base:'/nms-api'},fetcher)
  for(const path of ['telegram','telegram/bindings','portal/test','server-hierarchy','reset-plan','optional-api-approval','users/delete'])await client.platform(path)
  await client.history('inventory_inv_'+'b'.repeat(24));assert.equal(requests.length,8)
  await assert.rejects(client.platform('reset/apply'));await assert.rejects(client.history('../../etc/passwd'))
})
