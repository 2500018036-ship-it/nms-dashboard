// Only a current server verification can authorize packet illustrations.
export const topologySignature = (graph) => JSON.stringify({
  nodes:(graph?.nodes||[]).map(({id,device_id='',collector='',resource_id=''})=>({id,device_id,collector,resource_id})),
  links:(graph?.links||[]).map(({id,source,target,type,source_port='',target_port='',vlan=0})=>({id,source,target,type,source_port,target_port,vlan})),
})
export function verifiedLink(edge, report, signature, graph, now) {
  if (!edge || !report || signature!==topologySignature(graph)) return null
  const row=report.links.find((item)=>item.id===edge.id)
  return row?.verified && row.animate && row.expires_at>now ? row : null
}
