import test from 'node:test'
import assert from 'node:assert/strict'
import {topologySignature,verifiedLink} from '../src/data/topologyVerification.js'
import {createTopologyWorkspace} from '../src/data/topologyWorkspace.js'
import {isGatewayRequest} from '../config/devProxy.js'

test('packet permission expires, rejects changed bindings and never trusts diagram evidence',()=>{
  const graph={nodes:[{id:'a',device_id:'inv_a'},{id:'b',device_id:'inv_b'}],links:[{id:'e',source:'a',target:'b',type:'Ethernet',evidence:'verified'}]}
  const edge=graph.links[0],signature=topologySignature(graph)
  assert.equal(verifiedLink(edge,null,signature,graph,100),null)
  const report={links:[{id:'e',verified:true,animate:true,expires_at:120}]}
  assert.ok(verifiedLink(edge,report,signature,graph,100))
  assert.equal(verifiedLink(edge,report,signature,graph,120),null)
  graph.nodes[0].x=500;edge.points=[{x:200,y:100}]
  assert.ok(verifiedLink(edge,report,signature,graph,100))
  graph.nodes[0].device_id='other'
  assert.equal(verifiedLink(edge,report,signature,graph,100),null)
})

test('autosave continues after page unsubscribe and restores view and edge route after refresh',async()=>{
  const values=new Map(),bodies=[];const storage={getItem:(key)=>values.get(key),setItem:(key,value)=>values.set(key,value)}
  const client={async platform(path,{body}){bodies.push(body);return {id:'top_test',revision:bodies.length,...body.value}}}
  const a=createTopologyWorkspace({client,username:'tester',storage,autoSave:true,saveDelay:5,makeId:()=> 'a'.repeat(32)})
  const stop=a.start();a.create('LAN');const off=a.subscribe(()=>{})
  a.change({name:'LAN',nodes:[{id:'a',x:100,y:50},{id:'b',x:900,y:250}],links:[{id:'e',source:'a',target:'b',points:[{x:300,y:50}]}]})
  a.setView({x:-50,y:30,zoom:.5});off()
  await new Promise((resolve)=>setTimeout(resolve,30))
  assert.equal(bodies.length,1);assert.equal(bodies[0].value.view.zoom,.5);stop()
  const b=createTopologyWorkspace({client,username:'tester',storage,autoSave:true})
  const doc=b.getSnapshot().documents[b.getSnapshot().selected]
  assert.equal(doc.dirty,false);assert.deepEqual(doc.graph.links[0].points,[{x:300,y:50}]);assert.deepEqual(doc.view,{x:-50,y:30,zoom:.5})
  assert.equal(isGatewayRequest('POST','/nms-api/api/platform/topology-verify','/nms-api'),true)
  assert.equal(isGatewayRequest('DELETE','/nms-api/api/platform/topology-verify','/nms-api'),false)
})
