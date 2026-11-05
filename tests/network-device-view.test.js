import test from 'node:test'
import assert from 'node:assert/strict'
import {networkDeviceView} from '../src/data/networkDeviceView.js'
test('network filter separates devices and uses readable names instead of internal IDs',()=>{
 const core={interfaces:[{sourceId:'inventory_inv_a',name:'ether1'},{sourceId:'inventory_inv_b',name:'port1'}],traffic:[{sourceId:'inventory_inv_a',name:'ether1',rx:9},{sourceId:'inventory_inv_b',name:'port1',rx:20}],services:[]}
 const inventory=[{id:'inv_a',host:'192.168.20.1',name:'Router utama',enabled:true,monitor_method:'snmp'},{id:'inv_b',host:'192.168.10.26',name:'Switch Cisco',enabled:true,monitor_method:'snmp'}]
 const view=networkDeviceView(core,inventory,[],'inv_b')
 assert.equal(view.interfaces.length,1);assert.equal(view.traffic[0].rx,20);assert.equal(view.interfaces[0].sourceName,'Switch Cisco')
 assert.equal(networkDeviceView(core,[],[],'').traffic.length,0)
})
