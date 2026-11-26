const BRANCHES = ['A', 'B', 'C'];
let branchState = {};
let transactions = [];
let refreshing = false;

const money = cents => Number.isFinite(Number(cents))
  ? (Number(cents) / 100).toLocaleString('en-CA', {style:'currency',currency:'CAD'}) : '—';
const el = id => document.getElementById(id);

async function api(branch, endpoint) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 3500);
  try {
    const response = await fetch(`/api/branches/${branch}/${endpoint}`, {signal:controller.signal,cache:'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } finally { clearTimeout(timeout); }
}
function text(tag, content, className) {
  const node = document.createElement(tag);
  node.textContent = content;
  if (className) node.className = className;
  return node;
}
function line(label, value, cls='') {
  const node = document.createElement('div'); node.className='detail-line';
  node.append(text('span',label),text('strong',value,cls));return node;
}
function renderBranches() {
  const container = el('branchCards'); container.replaceChildren();
  BRANCHES.forEach(id => {
    const data = branchState[id];
    const online = Boolean(data);
    const card = document.createElement('article');card.className='branch-card';
    const head=document.createElement('div');head.className='branch-head';
    const title=document.createElement('div');title.className='branch-title';
    title.append(text('span',id,'branch-icon'));
    const name=document.createElement('div');name.append(text('h3',`Branch ${id}`),text('small',`Node ${id} · Port ${5000+BRANCHES.indexOf(id)+1}`));title.append(name);
    head.append(title,text('span',online?'● Online':'● Offline',`status ${online?'online':'offline'}`));
    card.append(head,text('p','AVAILABLE CASH','branch-balance-label'),text('p',online?money(data.cash):'Unavailable','branch-balance'));
    const details=document.createElement('div');details.className='branch-details';
    details.append(line('Employees',online?String(data.employees):'—'),line('Minimum reserve',online?money(data.minimum_reserve):'—'));
    const reserve=online?(data.reserve_warning?'⚠ Below minimum reserve':'✓ Reserve compliant'):'Unknown while offline';
    details.append(line('Reserve status',reserve,online?(data.reserve_warning?'danger':'safe'):'unknown'));
    card.append(details);container.append(card);
  });
}
function renderMetrics() {
  const online=BRANCHES.map(id=>branchState[id]).filter(Boolean);
  el('totalCash').textContent=money(online.reduce((sum,b)=>sum+Number(b.cash||0),0));
  el('onlineCount').textContent=`${online.length} / 3`;
  el('employeeCount').textContent=String(online.reduce((sum,b)=>sum+Number(b.employees||0),0));
  el('alertCount').textContent=String(online.filter(b=>b.reserve_warning).length);
}
function renderHealth() {
  const list=el('healthList');list.replaceChildren();
  BRANCHES.forEach(id=>{
    const data=branchState[id];const item=document.createElement('div');item.className='health-item';
    const left=document.createElement('div');left.className='left';left.append(text('span','',`dot ${data?'':'red'}`));
    const labels=document.createElement('div');labels.append(text('strong',`Branch ${id}`),text('small',!data?'Connection unavailable':data.reserve_warning?'Reserve alert':'Reserve compliant'));left.append(labels);
    item.append(left,text('span',data?'Online':'Offline',data?'safe':'danger'));list.append(item);
  });
}
function renderTransactions() {
  const query=el('search').value.trim().toLowerCase();
  const branch=el('branchFilter').value;const type=el('typeFilter').value;
  const visible=transactions.filter(t=>{
    if(branch!=='all'&&t.branch!==branch)return false;
    if(type!=='all'&&!String(t.tx_type||'').toLowerCase().includes(type))return false;
    return [t.branch,t.tx_type,t.tx_id,t.status,t.note,t.created_at,String(t.amount)].join(' ').toLowerCase().includes(query);
  });
  el('txCount').textContent=`${visible.length} record${visible.length===1?'':'s'}`;
  const body=el('transactionRows');body.replaceChildren();
  if(!visible.length){const row=document.createElement('tr');const cell=text('td',transactions.length?'No matching transactions.':'No transactions found yet.','empty');cell.colSpan=5;row.append(cell);body.append(row);return;}
  visible.slice(0,100).forEach(t=>{
    const row=document.createElement('tr');
    const status=String(t.status||'Unknown');
    const date=t.created_at?String(t.created_at).replace('T',' ').replace(/\..*$/,''):'—';
    row.append(text('td',`Branch ${t.branch}`),text('td',String(t.tx_type||'Unknown').replaceAll('_',' '),'tx-type'),text('td',money(t.amount),'tx-amount'));
    const statusCell=document.createElement('td');statusCell.append(text('span',status,`tx-status ${/fail|reject|cancel/i.test(status)?'failed':''}`));row.append(statusCell,text('td',date));body.append(row);
  });
}
async function refresh() {
  if(refreshing)return;
  refreshing=true;el('refresh').disabled=true;el('refresh').textContent='↻ Updating…';
  try {
    const results=await Promise.all(BRANCHES.map(async id=>{
      try {return {id,status:await api(id,'status')};}catch{return {id,status:null};}
    }));
    branchState=Object.fromEntries(results.map(({id,status})=>[id,status]));
    const txResults=await Promise.all(BRANCHES.map(async id=>{
      if(!branchState[id])return [];
      try {const data=await api(id,'transactions');return Array.isArray(data.transactions)?data.transactions.map(t=>({...t,branch:id})):[];}
      catch{return [];}
    }));
    transactions=txResults.flat().sort((a,b)=>String(b.created_at||'').localeCompare(String(a.created_at||'')));
    renderMetrics();renderBranches();renderHealth();renderTransactions();
    el('updated').textContent=`Last updated ${new Date().toLocaleTimeString()} · ${results.filter(r=>r.status).length}/3 online`;
  } finally {refreshing=false;el('refresh').disabled=false;el('refresh').textContent='↻ Refresh data';}
}
['search','branchFilter','typeFilter'].forEach(id=>el(id).addEventListener(id==='search'?'input':'change',renderTransactions));
el('refresh').addEventListener('click',refresh);
document.querySelectorAll('.nav-link').forEach(link=>link.addEventListener('click',()=>{document.querySelectorAll('.nav-link').forEach(x=>x.classList.remove('active'));link.classList.add('active');}));
refresh();setInterval(refresh,5000);
