from __future__ import annotations

# A dependency-free first product surface. Keeping this as a static asset makes the
# agent distributable as a single Python package while the product shape is still
# evolving; it can move to a dedicated frontend build when the UI warrants it.
_DASHBOARD_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>justtest Observability</title>
<style>
:root{--bg:#090b10;--panel:#11151d;--panel2:#171c26;--line:#262d3a;--text:#f3f5f7;--muted:#8e98aa;--brand:#8b5cf6;--brand2:#4f46e5;--good:#34d399;--warn:#fbbf24;--bad:#fb7185;--cyan:#22d3ee;--sidebar:224px}
*{box-sizing:border-box}html,body{margin:0;min-height:100%;background:var(--bg);color:var(--text);font:14px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}button,input,select{font:inherit}button{cursor:pointer}
.app{display:grid;grid-template-columns:var(--sidebar) 1fr;min-height:100vh}.side{position:fixed;inset:0 auto 0 0;width:var(--sidebar);padding:18px 14px;background:#0d1017;border-right:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:11px;padding:4px 8px 22px;font-weight:800;letter-spacing:-.02em}.logo{display:grid;place-items:center;width:31px;height:31px;border-radius:9px;background:linear-gradient(135deg,var(--brand),var(--brand2));box-shadow:0 0 26px #7c3aed55}.brand small{display:block;color:var(--muted);font-size:10px;font-weight:600;letter-spacing:.09em;text-transform:uppercase}
.nav{display:grid;gap:4px}.nav button{width:100%;border:0;background:transparent;color:var(--muted);text-align:left;padding:10px 11px;border-radius:8px}.nav button:hover,.nav button.active{background:#191e29;color:#fff}.nav .ico{display:inline-block;width:24px;color:#a78bfa}.side-foot{position:absolute;left:14px;right:14px;bottom:18px;color:var(--muted);font-size:11px}.side-foot strong{color:var(--good);font-weight:600}
.main{grid-column:2;min-width:0}.top{height:66px;display:flex;align-items:center;justify-content:space-between;padding:0 28px;border-bottom:1px solid var(--line);position:sticky;top:0;background:#090b10e8;backdrop-filter:blur(12px);z-index:10}.crumb{color:var(--muted);font-size:12px}.crumb b{color:#fff;font-size:15px}.actions{display:flex;align-items:center;gap:10px}.live{display:flex;align-items:center;gap:7px;color:var(--muted);font-size:12px}.dot{width:8px;height:8px;border-radius:50%;background:var(--good);box-shadow:0 0 10px #34d39988}.ghost{border:1px solid var(--line);background:var(--panel);color:#dbe1ea;padding:7px 11px;border-radius:7px}.ghost:hover{border-color:#4b5568}
.content{padding:26px 28px 48px;max-width:1540px}.view{display:none}.view.active{display:block}.title-row{display:flex;align-items:end;justify-content:space-between;margin-bottom:20px}.title-row h1{margin:0;font-size:24px;letter-spacing:-.03em}.subtitle{color:var(--muted);margin-top:4px}.updated{color:var(--muted);font-size:11px}
.cards{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:12px;margin-bottom:16px}.card,.panel{background:linear-gradient(180deg,#131822,#10141c);border:1px solid var(--line);border-radius:11px}.card{padding:17px}.card-label{color:var(--muted);font-size:12px}.card-value{font-size:28px;font-weight:730;letter-spacing:-.04em;margin-top:7px}.card-foot{margin-top:7px;font-size:11px;color:#697386}.card-foot.good{color:var(--good)}
.two{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(300px,.85fr);gap:14px;margin-bottom:14px}.panel{padding:18px;min-width:0}.panel-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}.panel h2{font-size:14px;margin:0}.panel-note{font-size:11px;color:var(--muted)}
.kind-list{display:grid;gap:10px}.kind-row{display:grid;grid-template-columns:92px 1fr 54px;gap:10px;align-items:center}.kind-name{color:#cbd2dd;font-size:12px}.bar-bg{height:7px;background:#212734;border-radius:99px;overflow:hidden}.bar{height:100%;border-radius:99px;background:linear-gradient(90deg,var(--brand),var(--cyan))}.count{text-align:right;color:var(--muted);font-variant-numeric:tabular-nums;font-size:12px}
.metric-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.metric{background:#0e1219;border:1px solid #222936;border-radius:8px;padding:11px;overflow:hidden}.metric-name{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--muted);font-size:10px}.metric-value{font-size:18px;font-weight:680;margin:3px 0}.spark{height:32px;width:100%;display:block}.spark polyline{fill:none;stroke:#a78bfa;stroke-width:2;vector-effect:non-scaling-stroke}
.toolbar{display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap}.input,.select{background:#0d1118;color:#dce2ec;border:1px solid var(--line);border-radius:7px;padding:7px 9px;outline:none}.input{min-width:220px}.input:focus,.select:focus{border-color:#6d5bd0}.pill-group{display:flex;gap:5px}.pill{border:1px solid var(--line);background:#0d1118;color:var(--muted);border-radius:999px;padding:5px 9px;font-size:11px}.pill.active{border-color:#6d5bd0;color:#ddd6fe;background:#251d40}
.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:9px}.table{width:100%;border-collapse:collapse;min-width:720px}.table th{text-align:left;padding:9px 11px;color:#778196;background:#0d1118;font-size:10px;text-transform:uppercase;letter-spacing:.06em;font-weight:650}.table td{padding:10px 11px;border-top:1px solid #202633;color:#cbd2dd;vertical-align:top}.table tr:hover td{background:#151a23}.mono{font:11px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;color:#9aa5b5}.tag{display:inline-block;margin:1px 3px 1px 0;padding:2px 5px;border-radius:4px;background:#21283a;color:#b9c3d5;font-size:10px}.badge{display:inline-flex;padding:2px 6px;border-radius:5px;background:#262035;color:#c4b5fd;font-size:10px}.empty{padding:28px;color:var(--muted);text-align:center}.error{display:none;margin-bottom:14px;border:1px solid #7f1d2d;background:#2a1118;color:#fecdd3;border-radius:8px;padding:10px 12px}.error.show{display:block}
.auth-backdrop{display:none;position:fixed;inset:0;background:#07090dcc;z-index:50;place-items:center}.auth-backdrop.show{display:grid}.auth{width:min(420px,calc(100vw - 32px));background:#121722;border:1px solid #343b49;border-radius:13px;padding:22px;box-shadow:0 20px 80px #000a}.auth h2{margin:0 0 7px}.auth p{color:var(--muted);margin:0 0 16px}.auth .input{width:100%;margin-bottom:10px}.primary{width:100%;border:0;color:#fff;background:linear-gradient(135deg,var(--brand),var(--brand2));padding:9px 12px;border-radius:8px;font-weight:650}
@media(max-width:950px){:root{--sidebar:64px}.brand span,.nav .label,.side-foot{display:none}.brand{padding-left:2px}.nav button{padding:10px;text-align:center}.nav .ico{width:auto}.cards{grid-template-columns:repeat(2,1fr)}.two{grid-template-columns:1fr}}@media(max-width:620px){.top{padding:0 14px}.content{padding:18px 14px 36px}.cards{grid-template-columns:1fr 1fr}.metric-grid{grid-template-columns:1fr}.updated{display:none}}
</style>
</head>
<body>
<div class="app">
<aside class="side">
  <div class="brand"><div class="logo">J</div><span>justtest<small>Observability</small></span></div>
  <nav class="nav" aria-label="Primary">
    <button class="active" data-view="overview"><span class="ico">◫</span><span class="label">Overview</span></button>
    <button data-view="infrastructure"><span class="ico">⌂</span><span class="label">Infrastructure</span></button>
    <button data-view="services"><span class="ico">◇</span><span class="label">Services</span></button>
    <button data-view="telemetry"><span class="ico">≋</span><span class="label">Telemetry</span></button>
  </nav>
  <div class="side-foot"><strong>● Agent connected</strong><br>Local observability plane</div>
</aside>
<main class="main">
  <header class="top"><div class="crumb"><b id="pageTitle">Overview</b><br><span>Local environment</span></div><div class="actions"><span class="live"><span class="dot"></span>Live</span><button class="ghost" id="refresh">Refresh</button></div></header>
  <div class="content">
    <div class="error" id="error"></div>
    <section class="view active" id="view-overview">
      <div class="title-row"><div><h1>Observability Overview</h1><div class="subtitle">Signals and entities visible to this agent.</div></div><div class="updated" id="updated"></div></div>
      <div class="cards">
        <div class="card"><div class="card-label">Telemetry signals</div><div class="card-value" id="totalSignals">—</div><div class="card-foot good">Durably stored</div></div>
        <div class="card"><div class="card-label">Hosts</div><div class="card-value" id="hostCount">—</div><div class="card-foot">Discovered entities</div></div>
        <div class="card"><div class="card-label">Services</div><div class="card-value" id="serviceCount">—</div><div class="card-foot">Unified service catalog</div></div>
        <div class="card"><div class="card-label">Containers</div><div class="card-value" id="containerCount">—</div><div class="card-foot">Origin-aware telemetry</div></div>
      </div>
      <div class="two">
        <div class="panel"><div class="panel-head"><h2>Signal distribution</h2><span class="panel-note">Stored records by type</span></div><div class="kind-list" id="kindList"></div></div>
        <div class="panel"><div class="panel-head"><h2>Latest host metrics</h2><span class="panel-note">Recent samples</span></div><div class="metric-grid" id="metricGrid"></div></div>
      </div>
      <div class="panel"><div class="panel-head"><h2>Recent telemetry</h2><span class="panel-note">Newest records</span></div><div id="recentTable"></div></div>
    </section>
    <section class="view" id="view-infrastructure"><div class="title-row"><div><h1>Infrastructure</h1><div class="subtitle">Hosts and containers discovered from telemetry.</div></div></div><div class="panel"><div class="toolbar"><div class="pill-group"><button class="pill active" data-entity="all">All</button><button class="pill" data-entity="host">Hosts</button><button class="pill" data-entity="container">Containers</button></div></div><div id="infraTable"></div></div></section>
    <section class="view" id="view-services"><div class="title-row"><div><h1>Services</h1><div class="subtitle">A live catalog derived from service-tagged telemetry.</div></div></div><div class="panel"><div id="serviceTable"></div></div></section>
    <section class="view" id="view-telemetry"><div class="title-row"><div><h1>Telemetry Explorer</h1><div class="subtitle">Inspect the latest metrics, logs, traces, events and checks.</div></div></div><div class="panel"><div class="toolbar"><input class="input" id="search" placeholder="Search name, service, host or tags"><select class="select" id="kindFilter"><option value="">All signal types</option><option>metric</option><option>log</option><option>trace</option><option>event</option><option>service_check</option></select></div><div id="telemetryTable"></div></div></section>
  </div>
</main>
</div>
<div class="auth-backdrop" id="authBackdrop"><form class="auth" id="authForm"><h2>Connect to protected API</h2><p>This observability API requires a bearer token. The token stays in this browser tab.</p><input class="input" id="token" type="password" autocomplete="current-password" placeholder="Bearer token" required><button class="primary" type="submit">Connect</button></form></div>
<script>
const state={overview:null,records:[],entities:[],entityFilter:'all'};
const $=s=>document.querySelector(s), $$=s=>Array.from(document.querySelectorAll(s));
const esc=v=>String(v??'').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));
const fmt=n=>new Intl.NumberFormat().format(Number(n||0));
const ago=t=>{if(!t)return '—';const s=Math.max(0,Date.now()/1000-t);if(s<60)return `${Math.floor(s)}s ago`;if(s<3600)return `${Math.floor(s/60)}m ago`;if(s<86400)return `${Math.floor(s/3600)}h ago`;return `${Math.floor(s/86400)}d ago`};
const token=()=>sessionStorage.getItem('justtestToken')||'';
async function api(path){const headers={};if(token())headers.Authorization=`Bearer ${token()}`;const r=await fetch(path,{headers,cache:'no-store'});if(r.status===401){$('#authBackdrop').classList.add('show');throw new Error('Authentication required');}if(!r.ok)throw new Error(`${r.status} ${r.statusText}`);return r.json()}
function tagsHtml(tags){return Object.entries(tags||{}).slice(0,6).map(([k,v])=>`<span class="tag">${esc(k)}:${esc(v)}</span>`).join('')||'<span class="mono">—</span>'}
function recordsTable(records){if(!records.length)return '<div class="empty">No telemetry collected yet.</div>';return `<div class="table-wrap"><table class="table"><thead><tr><th>Type</th><th>Name</th><th>Service / Host</th><th>Tags</th><th>When</th></tr></thead><tbody>${records.map(r=>`<tr><td><span class="badge">${esc(r.kind)}</span></td><td>${esc(r.name)}</td><td>${esc(r.service||'—')}<div class="mono">${esc(r.host||'')}</div></td><td>${tagsHtml(r.tags)}</td><td class="mono">${ago(r.timestamp)}</td></tr>`).join('')}</tbody></table></div>`}
function entitiesTable(entities){if(!entities.length)return '<div class="empty">No matching entities yet.</div>';return `<div class="table-wrap"><table class="table"><thead><tr><th>Type</th><th>Entity</th><th>Tags</th><th>Last seen</th></tr></thead><tbody>${entities.map(e=>`<tr><td><span class="badge">${esc(e.type)}</span></td><td>${esc(e.id)}</td><td>${tagsHtml(e.tags)}</td><td class="mono">${ago(e.last_seen)}</td></tr>`).join('')}</tbody></table></div>`}
function renderKinds(){const counts=state.overview?.records_by_kind||{};const entries=['metric','log','trace','event','service_check'].map(k=>[k,counts[k]||0]);const max=Math.max(1,...entries.map(x=>x[1]));$('#kindList').innerHTML=entries.map(([k,n])=>`<div class="kind-row"><div class="kind-name">${esc(k)}</div><div class="bar-bg"><div class="bar" style="width:${Math.max(n?3:0,n/max*100)}%"></div></div><div class="count">${fmt(n)}</div></div>`).join('')}
function spark(values){if(values.length<2)return '';const w=180,h=32,min=Math.min(...values),max=Math.max(...values),span=max-min||1;const pts=values.map((v,i)=>`${(i/(values.length-1))*w},${h-((v-min)/span)*(h-4)-2}`).join(' ');return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><polyline points="${pts}"/></svg>`}
function renderMetrics(){const groups=new Map();state.records.filter(r=>r.kind==='metric'&&Number.isFinite(Number(r.payload?.value))).reverse().forEach(r=>{if(!groups.has(r.name))groups.set(r.name,[]);groups.get(r.name).push(Number(r.payload.value))});const items=[...groups.entries()].slice(0,6);$('#metricGrid').innerHTML=items.length?items.map(([name,vals])=>`<div class="metric"><div class="metric-name" title="${esc(name)}">${esc(name)}</div><div class="metric-value">${fmt(vals[vals.length-1])}</div>${spark(vals.slice(-30))}</div>`).join(''):'<div class="empty">Collect metrics to populate charts.</div>'}
function renderOverview(){const o=state.overview||{};$('#totalSignals').textContent=fmt(o.total_records);$('#hostCount').textContent=fmt(o.entities_by_type?.host);$('#serviceCount').textContent=fmt(o.entities_by_type?.service);$('#containerCount').textContent=fmt(o.entities_by_type?.container);$('#updated').textContent=`Updated ${new Date().toLocaleTimeString()}`;renderKinds();renderMetrics();$('#recentTable').innerHTML=recordsTable(state.records.slice(0,12))}
function renderEntities(){const infra=state.entities.filter(e=>['host','container'].includes(e.type)&&(state.entityFilter==='all'||e.type===state.entityFilter));$('#infraTable').innerHTML=entitiesTable(infra);$('#serviceTable').innerHTML=entitiesTable(state.entities.filter(e=>e.type==='service'))}
function renderTelemetry(){const q=$('#search').value.trim().toLowerCase(),kind=$('#kindFilter').value;const rows=state.records.filter(r=>(!kind||r.kind===kind)&&(!q||[r.name,r.service,r.host,JSON.stringify(r.tags||{})].join(' ').toLowerCase().includes(q)));$('#telemetryTable').innerHTML=recordsTable(rows)}
async function refresh(){try{$('#error').classList.remove('show');const [overview,records,entities]=await Promise.all([api('/v1/overview'),api('/v1/query?limit=500'),api('/v1/entities?limit=500')]);state.overview=overview;state.records=records.records||[];state.entities=entities.entities||[];renderOverview();renderEntities();renderTelemetry();$('#authBackdrop').classList.remove('show')}catch(e){if(e.message!=='Authentication required'){const box=$('#error');box.textContent=`Unable to refresh: ${e.message}`;box.classList.add('show')}}}
$$('.nav button').forEach(btn=>btn.addEventListener('click',()=>{$$('.nav button').forEach(x=>x.classList.remove('active'));btn.classList.add('active');$$('.view').forEach(x=>x.classList.remove('active'));$(`#view-${btn.dataset.view}`).classList.add('active');$('#pageTitle').textContent=btn.querySelector('.label')?.textContent||btn.dataset.view}));
$$('[data-entity]').forEach(btn=>btn.addEventListener('click',()=>{$$('[data-entity]').forEach(x=>x.classList.remove('active'));btn.classList.add('active');state.entityFilter=btn.dataset.entity;renderEntities()}));
$('#search').addEventListener('input',renderTelemetry);$('#kindFilter').addEventListener('change',renderTelemetry);$('#refresh').addEventListener('click',refresh);$('#authForm').addEventListener('submit',e=>{e.preventDefault();sessionStorage.setItem('justtestToken',$('#token').value);refresh()});
refresh();setInterval(refresh,15000);
</script>
</body>
</html>'''


def dashboard_html() -> bytes:
    return _DASHBOARD_HTML.encode("utf-8")
