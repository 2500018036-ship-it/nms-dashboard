"use strict";
const $=id=>document.getElementById(id);
const text=(id,value)=>{$(id).textContent=value};
const date=v=>new Date(v*1000).toLocaleString("id-ID",{timeZone:"Asia/Jakarta",hour12:false});
const number=v=>typeof v==="number"&&Number.isFinite(v);
const pct=v=>number(v)?v.toFixed(1)+"%":"Belum tersedia";
const el=(tag,cls,value)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(value!==undefined)e.textContent=value;return e};
async function api(path){const r=await fetch(path,{credentials:"same-origin",cache:"no-store"});if(!r.ok)throw new Error("HTTP "+r.status);return r.json()}
function badge(value){return el("span","badge "+(["UP","DOWN","DEGRADED","UNKNOWN","ALERT","RECOVERY"].includes(value)?value:"UNKNOWN"),value)}
function detail(row){text("detail-title",row.target);text("detail-data",JSON.stringify(row,null,2));$("detail").showModal()}
function render(data){
 const rows=data.checks,counts={UP:0,DOWN:0,DEGRADED:0,UNKNOWN:0};for(const r of rows)counts[r.status]=(counts[r.status]||0)+1;
 text("up",counts.UP);text("issues",counts.DOWN+counts.DEGRADED);text("unknown",counts.UNKNOWN);text("active",data.alerts.length);
 const latest=Math.max(0,...rows.map(r=>r.sample_epoch));text("updated",latest?"Sampel terakhir · "+date(latest):"Belum ada sampel");
 const stale=rows.filter(r=>data.server_time-r.sample_epoch>data.interval+90).length;
 text("connection",stale?stale+" target memiliki data kedaluwarsa":"Terhubung · Refresh tampilan 30 detik · Polling "+data.interval+" detik");
 const host=rows.find(r=>r.target==="debian")||{};text("cpu",pct(host.cpu_percent));text("memory",pct(host.memory_percent));$("cpu-meter").value=host.cpu_percent||0;$("memory-meter").value=host.memory_percent||0;
 text("disk",(host.disks||[]).map(d=>d.path+" · "+pct(d.used_percent)+" terpakai").join("     ")||"Storage belum tersedia.");
 const docker=rows.find(r=>r.target==="docker")||{},containers=docker.containers||[],running=containers.filter(c=>c.state==="running").length,unhealthy=containers.filter(c=>c.expected_running!==false&&(c.health==="unhealthy"||c.state!=="running")).length;
 text("container-count",containers.length?running+" / "+containers.length:"Belum tersedia");text("container-detail",containers.length?"Container running · "+unhealthy+" perlu perhatian · Snapshot "+(docker.age_seconds??"?")+" detik":"Menunggu snapshot host.");
 $("container-tags").replaceChildren(...containers.slice(0,6).map(c=>el("span","tag",c.name)));if(containers.length>6)$("container-tags").append(el("span","tag","+"+(containers.length-6)+" lainnya"));
 const workloads=$("workload-rows");workloads.replaceChildren();const mb=v=>number(v)?(v/1048576).toFixed(0)+" MiB":"—";
 for(const c of containers){const tr=el("tr");tr.append(el("td",null,c.name),el("td",null,(c.state||"UNKNOWN")+" / "+(c.health||"UNKNOWN")+(c.expected_running===false?" (dikecualikan)":"")),el("td",null,pct(c.cpu_percent)),el("td",null,mb(c.memory_bytes)),el("td",null,String(c.restart_count??"—")));workloads.append(tr)}
 const pve=rows.find(r=>r.target==="proxmox_resources")||{};for(const g of pve.guests||[]){const tr=el("tr");tr.append(el("td",null,g.vmid+" · "+(g.name||g.type)),el("td",null,g.status||"UNKNOWN"),el("td",null,pct(number(g.cpu)?g.cpu*100:null)),el("td",null,mb(g.mem)),el("td",null,g.node||"—"));workloads.append(tr)}text("guest-note",pve.status==="UP"?(pve.guests||[]).length+" VM/LXC dipetakan melalui Proxmox API.":"Proxmox: UNKNOWN · "+(pve.error||"data belum tersedia"));
 $("active-alerts").replaceChildren(...data.alerts.map(a=>el("span","tag",a.key+" · aktif")));
 const body=$("targets");body.replaceChildren();for(const row of rows){const tr=el("tr");tr.append(el("td",null,row.target));const status=el("td");status.append(badge(row.status));tr.append(status);const evidence=row.error||((row.http_status?"HTTP "+row.http_status+" · ":"")+row.method);tr.append(el("td",null,evidence));tr.append(el("td",null,date(row.sample_epoch)));const action=el("td");const button=el("button","detail-button","Detail ↗");button.type="button";button.addEventListener("click",()=>detail(row));action.append(button);tr.append(action);body.append(tr)}
}
function svg(tag,attrs){const e=document.createElementNS("http://www.w3.org/2000/svg",tag);for(const [k,v]of Object.entries(attrs))e.setAttribute(k,String(v));return e}
async function history(){
 const target=$("metric-target").value,data=await api("/api/history?target="+encodeURIComponent(target)),points=data.points;
 const traffic=target==="mikrotik_interfaces",latency=target==="technitium_dns",keys=traffic?["rx_bytes","tx_bytes"]:latency?["latency_ms"]:["cpu_percent","memory_percent"];
 const available=points.some(p=>keys.some(k=>number(p[k]))),chart=$("chart");$("chart-empty").hidden=available;chart.style.display=available?"block":"none";chart.replaceChildren();
 text("legend-a",traffic?"● RX bytes (counter)":latency?"● Latensi ms":"● CPU");text("legend-b",traffic?"● TX bytes (counter)":latency?"":"● RAM");
 text("chart-description",traffic?"Counter kumulatif; bukan bitrate. Reset interface dapat menurunkan nilai.":"Sampel nyata dari SQLite, maksimal 120 titik. Nilai kosong tidak digambarkan.");
 text("chart-range",points.length?date(points[0].time)+" — "+date(points[points.length-1].time):"");if(!available)return;
 const max=latency||traffic?Math.max(1,...points.flatMap(p=>keys.map(k=>number(p[k])?p[k]:0))):100;
 for(const y of [15,55,95,135,175])chart.append(svg("line",{x1:15,y1:y,x2:885,y2:y,stroke:"#2a3543","stroke-width":1}));
 keys.forEach((key,index)=>{let d="",previous=false;points.forEach((p,i)=>{if(!number(p[key])){previous=false;return}const x=15+(i/Math.max(1,points.length-1))*870,y=175-(p[key]/max)*160;d+=(previous?" L ":" M ")+x+" "+y;previous=true;if(points.length===1)chart.append(svg("circle",{cx:x,cy:y,r:3,fill:index?"#85b9ec":"#6bd8b0"}))});chart.append(svg("path",{d,fill:"none",stroke:index?"#85b9ec":"#6bd8b0","stroke-width":2.5}))});
}
async function incidents(){const data=await api("/api/events");text("incident-count",data.events.length+" event terakhir");const list=$("event-list");list.replaceChildren();if(!data.events.length){list.append(el("div","empty","Belum ada insiden yang melewati threshold dan debounce."));return}for(const event of data.events){const row=el("div","event");row.append(badge(event.kind),el("span","event-key",event.key),el("time",null,date(event.time)));list.append(row)}}
let loading=false;
async function refresh(){if(loading)return;loading=true;$("refresh").disabled=true;try{const data=await api("/api/status");render(data);await Promise.all([history(),incidents()])}catch(error){text("connection","Gagal memperbarui · "+error.message+" · periksa autentikasi dan collector")}finally{loading=false;$("refresh").disabled=false}}
$("refresh").addEventListener("click",refresh);$("metric-target").addEventListener("change",()=>history().catch(()=>text("chart-description","Riwayat gagal dibaca.")));$("close-detail").addEventListener("click",()=>$("detail").close());refresh();setInterval(refresh,30000);
