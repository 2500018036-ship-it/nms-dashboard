import test from 'node:test'
import assert from 'node:assert/strict'
import { createApiClient } from '../src/data/apiClient.js'
import { newDevice, validateDevice } from '../src/devices/model.js'
import { inventoryValue } from '../src/devices/serverInventory.js'

test('API preserves a specific safe validation code and rejects unknown error text', async () => {
  const client = (code) => createApiClient({ enabled: true, base: '/nms-api' }, async () => new Response(JSON.stringify({ code }), { status: 400, headers: { 'Content-Type': 'application/json' } }))
  await assert.rejects(client('host_not_allowed').platform('inventory', { body: {} }), { code: 'host_not_allowed' })
  await assert.rejects(client('private-password-message').platform('inventory', { body: {} }), { code: 'validation_failed' })
})

test('registration retains DHCP identity while excluding server revisions and credentials', () => {
  const form = { ...newDevice(), name: 'TLWR', host: '192.168.10.194', monitor_method: 'icmp', mac_address: '20:E1:5D:91:53:DC', follow_dhcp: true }
  const validated = validateDevice(form)
  assert.deepEqual(validated.errors, {})
  assert.equal(inventoryValue({ ...validated.value, revision: 3, password: 'never-send' }).mac_address, form.mac_address)
  assert.equal(inventoryValue(validated.value).follow_dhcp, true)
  assert.equal(inventoryValue({ ...validated.value, revision: 3 }).revision, undefined)
  assert.equal(validateDevice({ ...form, mac_address: '' }).value, null)
  assert.equal(validateDevice({ ...form, monitor_method: 'http' }).value, null)
})

test('per-device monitoring category choices persist in inventory without admitting unknown capabilities',()=>{
  const value={...newDevice(),name:'SNMP switch',host:'192.168.10.26',type:'switch',vendor:'Cisco',methods:['snmp'],monitor_method:'snmp',monitor_port:161,
    monitor_categories:['network_status','system_information','interfaces','traffic']}
  const validated=validateDevice(value)
  assert.deepEqual(validated.errors,{})
  assert.deepEqual(inventoryValue(validated.value).monitor_categories,value.monitor_categories)
  assert.equal(validateDevice({...value,monitor_categories:['shell_access']}).value,null)
})
