import test from 'node:test'
import assert from 'node:assert/strict'
import {createApiClient} from '../src/data/apiClient.js'
import {emptySnmp,snmpErrors,saveSnmpCredentials} from '../src/devices/snmpEnrollment.js'
import {isGatewayRequest} from '../config/devProxy.js'
import {ageDeviceSummary} from '../src/devices/deviceSummary.js'

test('enrollment route reaches the server and unrelated monitoring paths stay blocked',async()=>{
 const calls=[]
 const client=createApiClient({enabled:true,base:'/nms-api'},async(url,options)=>{calls.push({url,options});return new Response(JSON.stringify({inventory:[]}),{headers:{'Content-Type':'application/json'}})})
 assert.deepEqual(await client.platform('monitoring/enrollment'),{inventory:[]})
 assert.equal(calls[0].url,'/nms-api/api/platform/monitoring/enrollment');assert.equal(calls[0].options.method,'GET')
 await assert.rejects(client.platform('monitoring/enrollment/exec'),{code:'target_not_allowed'})
 assert.equal(isGatewayRequest('GET','/nms-api/api/platform/monitoring/enrollment','/nms-api'),true)
 assert.equal(isGatewayRequest('POST','/nms-api/api/platform/monitoring/enrollment','/nms-api'),false)
})

test('collector outages age metrics independently without retaining a green stale device',()=>{
 const state={health:{status:'UP',sample_epoch:100,stale_after_seconds:120},collectors:[{target:'snmp',status:'UP',sample_epoch:100,stale_after_seconds:120},{target:'api',status:'UP',sample_epoch:200,stale_after_seconds:120}],telemetry:{cpu_percent:15,interfaces:[{name:'ether1',collector:'snmp',rx_bps:30}]},metric_sources:{cpu_percent:{collector:'api'}},integration_state:'CONNECTED'}
 const partial=ageDeviceSummary(state,250)
 assert.equal(partial.health.status,'UNKNOWN');assert.equal(partial.integration_state,'PARTIAL')
 assert.equal(partial.telemetry.cpu_percent,15);assert.deepEqual(partial.telemetry.interfaces,[])
 const stale=ageDeviceSummary(state,400);assert.equal(stale.integration_state,'STALE');assert.equal(stale.telemetry.cpu_percent,undefined)
 assert.equal(state.health.status,'UP')
})

test('SNMP is validated before transmission and preserving a fresh vault keeps GUI, SSH and Wi-Fi intact',async()=>{
 const current={gui:{username:'owner',password:'existing-gui',fields:[]},ssh:{username:'ro'},wifi_networks:[{ssid:'office',password:'existing-wifi'}],custom_fields:[],snmp:{version:''}}
 const calls=[];const client={async credentials(type,id,options){calls.push({type,id,options});return {credentials:current}}}
 await assert.rejects(saveSnmpCredentials(client,'inv_test',emptySnmp()),{code:'invalid_credentials'});assert.equal(calls.length,0)
 const snmp={...emptySnmp(),username:'nms',auth_secret:'fixture-auth-password',privacy_secret:'fixture-privacy-password'}
 await saveSnmpCredentials(client,'inv_test',snmp)
 assert.equal(calls.length,2);assert.equal(calls[0].options,undefined)
 assert.deepEqual(calls[1].options.credentials.gui,current.gui);assert.deepEqual(calls[1].options.credentials.wifi_networks,current.wifi_networks)
 assert.deepEqual(calls[1].options.credentials.snmp,snmp);assert.equal(current.snmp.version,'')
 assert.ok(snmpErrors({...emptySnmp(),version:'v2c',community:'public'}).community)
 assert.deepEqual(snmpErrors({...emptySnmp(),version:'v2c',community:'fixture-unique-community'}),{})
})
