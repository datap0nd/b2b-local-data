const $ = id => document.getElementById(id);
let sessionId = localStorage.getItem('b2b-session'), currentTable = null, busy = false, sortState = {};
function message(text, type = '') {
  $('conversation').querySelector('.empty')?.remove();
  const node = document.createElement('p'); node.className = `message ${type}`; node.textContent = text;
  $('conversation').append(node);
}
async function api(path, body) {
  const options = body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)};
  const response = await fetch(path, options), result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Request failed.'); return result;
}
function setBusy(value, label='Asking Qwen…') {
  busy=value; $('ask').disabled=value; $('session-picker').disabled=value;
  document.querySelectorAll('.data-action').forEach(b=>b.disabled=value);
  $('ask').textContent=value?label:'Ask Qwen ↗';
}
async function listSessions() {
  const data=await api('/api/sessions'); $('session-picker').replaceChildren();
  data.sessions.forEach(session=> {const option=new Option(session.title,session.id); $('session-picker').add(option);});
  if (sessionId) $('session-picker').value=sessionId;
}
async function newSession() {
  const result=await api('/api/sessions',{}); sessionId=result.session_id;
  localStorage.setItem('b2b-session',sessionId); $('conversation').replaceChildren(); $('result').hidden=true;
  currentTable=null; $('rerun').hidden=true; $('question').value=''; $('suggestions').replaceChildren();
  await listSessions(); $('question').focus();
}
async function loadSession(id) {
  const saved=await api('/api/sessions/'+encodeURIComponent(id));
  sessionId=id; localStorage.setItem('b2b-session',id); $('conversation').replaceChildren();
  saved.turns.forEach(turn=>{message(turn.question,'user'); message(turn.response);});
  $('result').hidden=true; currentTable=null; $('rerun').hidden=!saved.active_plan; $('suggestions').replaceChildren();
  if(saved.active_plan) message('Saved query ready. Run it to show a table from the current data.');
}
function decimalParts(value) {
  const [base,exp='0']=String(value).toLowerCase().split('e');
  const [integer,fraction='']=base.replace(/^[+-]/,'').split('.');
  return {digits:BigInt((base.startsWith('-')?'-':'')+(integer+fraction)),scale:fraction.length-Number(exp)};
}
function compareValues(a,b,type) {
  if(a==null) return b==null?0:1; if(b==null) return -1;
  if(type==='number') {
    const x=decimalParts(a),y=decimalParts(b),scale=Math.max(x.scale,y.scale);
    const left=x.digits*10n**BigInt(scale-x.scale),right=y.digits*10n**BigInt(scale-y.scale);
    return left<right?-1:left>right?1:0;
  }
  return String(a).localeCompare(String(b));
}
function drawRows() {
  const body=$('table').tBodies[0]; body.replaceChildren();
  currentTable.rows.forEach(record=>{const row=body.insertRow(); currentTable.columns.forEach(name=>{row.insertCell().textContent=record[name]??'—';});});
}
function renderTable(table) {
  currentTable=table; sortState={}; $('result').hidden=false; $('table').replaceChildren(); $('rerun').hidden=false;
  $('result-title').textContent=table.intent==='table'?(table.grain==='opportunity'?'Opportunity summary':'Opportunity & product detail'):'Grouped metrics';
  $('result-meta').textContent=`${table.rows.length.toLocaleString()} of ${table.total_rows.toLocaleString()} rows · ${table.source_rows.toLocaleString()} source lines · loaded ${new Date(table.snapshot_at).toLocaleTimeString()}${table.truncated?' · Preview limited; CSV includes displayed rows only':''}`;
  $('scope').textContent=table.scope;
  $('warnings').replaceChildren(); table.warnings.forEach(text=>{const p=document.createElement('p');p.className='warning';p.textContent=text;$('warnings').append(p);});
  const head=$('table').createTHead().insertRow();
  table.columns.forEach(name=>{const th=document.createElement('th');th.scope='col';const button=document.createElement('button');button.className='column-sort';button.textContent=name.replaceAll('_',' ')+' ↕';button.title='Sort displayed rows';
    button.addEventListener('click',()=>{const direction=sortState[name]===1?-1:1;sortState={[name]:direction};
      head.querySelectorAll('th').forEach(cell=>cell.removeAttribute('aria-sort'));th.setAttribute('aria-sort',direction===1?'ascending':'descending');
      head.querySelectorAll('button').forEach(control=>control.textContent=control.textContent.replace(/[↕↑↓]$/,'↕'));button.textContent=name.replaceAll('_',' ')+(direction===1?' ↑':' ↓');
      table.rows.sort((a,b)=>a[name]==null||b[name]==null?compareValues(a[name],b[name],table.column_types[name]):direction*compareValues(a[name],b[name],table.column_types[name]));drawRows();drawChart();});th.append(button);head.append(th);});
  $('table').createTBody();drawRows();
  $('filters').textContent=table.filters.length?JSON.stringify(table.filters,null,2):'No filters.';
  $('chart-panel').hidden=!table.chart;$('chart-measure').replaceChildren();
  if(table.chart){table.chart.measures.forEach(name=>$('chart-measure').add(new Option(name.replaceAll('_',' '),name)));$('chart-measure').hidden=table.chart.type==='scatter';requestAnimationFrame(drawChart);}
}
function drawChart() {
  if(!currentTable?.chart) return;
  const spec=currentTable.chart,rows=currentTable.rows.slice(0,30),canvas=$('chart'),ctx=canvas.getContext('2d');
  const width=Math.max(400,canvas.parentElement.clientWidth),height=300;canvas.width=width;canvas.height=height;
  const left=75,right=25,top=25,bottom=65,w=width-left-right,h=height-top-bottom;
  ctx.clearRect(0,0,width,height);ctx.font='11px Segoe UI';ctx.fillStyle='#617657';ctx.strokeStyle='#d5dfd2';
  const measure=$('chart-measure').value,dimension=spec.dimensions[0],scatter=spec.type==='scatter';
  const values=rows.map(row=>row[scatter?spec.measures[1]:measure]).filter(value=>value!=null).map(Number).filter(Number.isFinite);
  let min=Math.min(0,...values),max=Math.max(0,...values);if(min===max)max=min+1;
  const y=value=>top+h-(value-min)/(max-min)*h;
  for(let i=0;i<=4;i++){const value=min+(max-min)*i/4,position=y(value);ctx.beginPath();ctx.moveTo(left,position);ctx.lineTo(width-right,position);ctx.stroke();ctx.fillText(new Intl.NumberFormat(undefined,{notation:'compact'}).format(value),5,position+4);}
  ctx.save();ctx.fillStyle='#2c5141';ctx.strokeStyle='#2c5141';ctx.lineWidth=2;
  if(scatter){
    const xs=rows.map(r=>r[spec.measures[0]]==null?null:Number(r[spec.measures[0]])),finite=xs.filter(value=>value!=null&&Number.isFinite(value));let lo=finite.length?Math.min(...finite):0,hi=finite.length?Math.max(...finite):1;if(lo===hi)hi=lo+1;
    rows.forEach((row,i)=>{if(row[spec.measures[0]]==null||row[spec.measures[1]]==null)return;const x=left+(xs[i]-lo)/(hi-lo)*w;ctx.beginPath();ctx.arc(x,y(Number(row[spec.measures[1]])),5,0,Math.PI*2);ctx.fill();});
    ctx.fillText(spec.measures[0]+': '+lo+' → '+hi,left,height-22);
  } else {
    const step=w/Math.max(1,rows.length),points=[];
    rows.forEach((row,i)=>{const x=left+step*(i+.5),value=row[measure],label=String(row[dimension]??'Unknown');ctx.save();ctx.translate(x,height-bottom+15);ctx.rotate(-.35);ctx.fillText(label.slice(0,20),-10,0);ctx.restore();
      if(value==null){points.push(null);return;} const point=[x,y(Number(value))];points.push(point);
      if(spec.type==='bar'){const zero=y(0);ctx.fillRect(x-step*.3,Math.min(zero,point[1]),step*.6,Math.max(1,Math.abs(zero-point[1])));}});
    if(spec.type!=='bar'){
      let segment=[];const flush=()=>{if(!segment.length)return;ctx.beginPath();ctx.moveTo(...segment[0]);segment.slice(1).forEach(p=>ctx.lineTo(...p));ctx.stroke();
        if(spec.type==='area'){ctx.lineTo(segment.at(-1)[0],y(0));ctx.lineTo(segment[0][0],y(0));ctx.closePath();ctx.globalAlpha=.15;ctx.fill();ctx.globalAlpha=1;}segment.forEach(p=>{ctx.beginPath();ctx.arc(...p,3,0,Math.PI*2);ctx.fill();});segment=[];};
      points.forEach(p=>p?segment.push(p):flush());flush();
    }
  }
  ctx.restore();
  $('chart-caption').textContent=`${scatter?spec.measures.join(' vs '):measure+' by '+dimension} · ${rows.length} displayed groups${currentTable.rows.length>30?' (chart limited to first 30; table contains the rest)':''}. Exact values are in the table.`;
  canvas.setAttribute('aria-label',$('chart-caption').textContent);
}
async function handleResult(result) {
  sessionId=result.session_id;localStorage.setItem('b2b-session',sessionId);
  if(result.kind==='clarify'){message(result.question);$('question').placeholder='Reply to the follow-up question…';}
  else {renderTable(result.table);message(result.table.total_rows?'Your result is ready.':'No rows matched those filters.');$('question').placeholder='Ask a follow-up, or start a new conversation.';}
  $('suggestions').replaceChildren();
  (result.suggestions||[]).forEach(text=>{const button=document.createElement('button');button.className='quiet data-action';button.textContent=text;button.title='Use this suggested follow-up';button.addEventListener('click',()=>{$('question').value=text;$('question').focus();});$('suggestions').append(button);});
  $('question').value='';await listSessions();
}
async function submit(sample) {
  if(busy)return;const question=$('question').value.trim();if(!sample&&!question)return;
  setBusy(true,sample?'Building result…':'Asking Qwen…');message(sample?`Show fictional ${sample.intent||'table'} (${sample.view}).`:question,'user');
  try{const body=sample?{...sample,session_id:sessionId}:{question,session_id:sessionId,view:$('view').value};await handleResult(await api(sample?'/api/sample':'/api/ask',body));}
  catch(error){message(error.message,'error');}finally{setBusy(false);}
}
$('ask-form').addEventListener('submit',e=>{e.preventDefault();submit();});
$('question').addEventListener('keydown',e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();submit();}});
$('chart-measure').addEventListener('change',drawChart);window.addEventListener('resize',()=>requestAnimationFrame(drawChart));
document.querySelectorAll('.sample').forEach(b=>b.addEventListener('click',()=>submit({view:b.dataset.view,intent:b.dataset.intent||'table'})));
$('reset').addEventListener('click',async()=>{try{await newSession();}catch(e){message(e.message,'error');}});
$('session-picker').addEventListener('change',async()=>{try{await loadSession($('session-picker').value);}catch(e){message(e.message,'error');}});
$('rerun').addEventListener('click',async()=>{if(busy)return;setBusy(true,'Running saved query…');try{await handleResult(await api('/api/rerun',{session_id:sessionId}));}catch(e){message(e.message,'error');}finally{setBusy(false);}});
$('refresh').addEventListener('click',async()=>{if(busy)return;setBusy(true,'Refreshing data…');try{const result=await api('/api/refresh',{});message(`Data refreshed: ${result.opportunities.toLocaleString()} opportunities and ${result.skus.toLocaleString()} opportunity/SKU rows. Run the saved query to update its table.`);}catch(e){message(e.message,'error');}finally{setBusy(false);}});
$('export').addEventListener('click',()=>{
  if(!currentTable)return;
  const cell=value=>{let text=value==null?'':String(value);if(/^[\s]*[=+\-@\t\r]/.test(text))text="'"+text;return '"'+text.replaceAll('"','""')+'"';};
  const rows=[currentTable.columns,...currentTable.rows.map(row=>currentTable.columns.map(c=>row[c]))];
  const url=URL.createObjectURL(new Blob(['\uFEFF'+rows.map(row=>row.map(cell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}));
  const link=document.createElement('a');link.href=url;link.download=`b2b-${currentTable.grain}.csv`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
(async()=>{try{const status=await api('/api/status');$('status').textContent=`${status.database==='demo'?'Fictional sample data':'PostgreSQL configured'} · Qwen: ${status.model} · v${status.version}`;$('samples').hidden=status.database!=='demo';
  if(sessionId){try{await loadSession(sessionId);}catch{sessionId=null;}}if(!sessionId)await newSession();else await listSessions();
}catch(e){$('status').textContent='Could not connect to the app.';message(e.message,'error');}})();
