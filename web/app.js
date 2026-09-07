const $ = id => document.getElementById(id);
let sessionId = localStorage.getItem('b2b-session'), busy = false;
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
  localStorage.setItem('b2b-session',sessionId); $('conversation').replaceChildren(); mainView.clear();
  $('rerun').hidden=true; $('question').value=''; $('suggestions').replaceChildren();
  await listSessions(); $('question').focus();
}
async function loadSession(id) {
  const saved=await api('/api/sessions/'+encodeURIComponent(id));
  sessionId=id; localStorage.setItem('b2b-session',id); $('conversation').replaceChildren();
  saved.turns.forEach(turn=>{message(turn.question,'user'); message(turn.response);});
  mainView.clear(); $('rerun').hidden=!saved.active_plan; $('suggestions').replaceChildren();
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
function csvText(table) {
  const cell=value=>{let text=value==null?'':String(value);if(/^[\s]*[=+\-@\t\r]/.test(text))text="'"+text;return '"'+text.replaceAll('"','""')+'"';};
  const rows=[table.columns,...table.rows.map(row=>table.columns.map(c=>row[c]))];
  return '﻿'+rows.map(row=>row.map(cell).join(',')).join('\r\n');
}
// Chart layout constants; the acceptance suite recomputes coordinates from these independently.
const CHART={height:300,left:75,right:25,top:25,bottom:65,minWidth:400,maxGroups:30};
function recording(ctx,ops) {
  return new Proxy(ctx,{get(target,prop){const value=target[prop];if(typeof value!=='function')return value;return (...args)=>{ops.push([prop,args.map(a=>typeof a==='number'?a:String(a))]);return value.apply(target,args);};},
    set(target,prop,value){target[prop]=value;return true;}});
}
class ResultView {
  // One rendered result: a production table, sortable columns, CSV export, and the chart canvas.
  constructor(root) {
    this.root=root; this.table=null; this.sortState={}; this.plot=null; this.ops=null; this.recordOps=false;
    this.q=selector=>root.querySelector(selector);
    this.q('.chart-measure').addEventListener('change',()=>this.drawChart());
    this.q('.export').addEventListener('click',()=>this.export());
    window.addEventListener('resize',()=>requestAnimationFrame(()=>this.drawChart()));
  }
  clear(){this.root.hidden=true;this.table=null;this.plot=null;}
  drawRows() {
    const body=this.q('.table').tBodies[0]; body.replaceChildren();
    this.table.rows.forEach(record=>{const row=body.insertRow(); this.table.columns.forEach(name=>{row.insertCell().textContent=record[name]??'—';});});
  }
  render(table) {
    const q=this.q; this.table=table; this.sortState={}; this.root.hidden=false; q('.table').replaceChildren();
    q('.result-title').textContent=table.intent==='table'?(table.grain==='opportunity'?'Opportunity summary':'Opportunity & product detail'):'Grouped metrics';
    q('.result-meta').textContent=`${table.rows.length.toLocaleString()} of ${table.total_rows.toLocaleString()} rows · ${table.source_rows.toLocaleString()} source lines · ${table.source_name||table.source} · loaded ${new Date(table.snapshot_at).toLocaleTimeString()}${table.truncated?' · Preview limited; CSV includes displayed rows only':''}`;
    q('.scope').textContent=table.scope;
    q('.warnings').replaceChildren(); table.warnings.forEach(text=>{const p=document.createElement('p');p.className='warning';p.textContent=text;q('.warnings').append(p);});
    const head=q('.table').createTHead().insertRow();
    table.columns.forEach(name=>{const th=document.createElement('th');th.scope='col';const button=document.createElement('button');button.className='column-sort';button.textContent=name.replaceAll('_',' ')+' ↕';button.title='Sort displayed rows';
      button.addEventListener('click',()=>this.sortBy(name,th,button,head));th.append(button);head.append(th);});
    q('.table').createTBody();this.drawRows();
    q('.filters').textContent=table.filters.length?JSON.stringify(table.filters,null,2):'No filters.';
    q('.chart-panel').hidden=!table.chart;q('.chart-measure').replaceChildren();this.plot=null;
    if(table.chart){table.chart.measures.forEach(name=>q('.chart-measure').add(new Option(name.replaceAll('_',' '),name)));q('.chart-measure').hidden=table.chart.type==='scatter';requestAnimationFrame(()=>this.drawChart());}
  }
  sortBy(name,th,button,head) {
    const table=this.table,direction=this.sortState[name]===1?-1:1;this.sortState={[name]:direction};
    head.querySelectorAll('th').forEach(cell=>cell.removeAttribute('aria-sort'));th.setAttribute('aria-sort',direction===1?'ascending':'descending');
    head.querySelectorAll('button').forEach(control=>control.textContent=control.textContent.replace(/[↕↑↓]$/,'↕'));button.textContent=name.replaceAll('_',' ')+(direction===1?' ↑':' ↓');
    table.rows.sort((a,b)=>a[name]==null||b[name]==null?compareValues(a[name],b[name],table.column_types[name]):direction*compareValues(a[name],b[name],table.column_types[name]));this.drawRows();this.drawChart();
  }
  sortColumn(name,direction) {
    // Programmatic sort used by the acceptance checks: same code path as a header click.
    const head=this.q('.table').tHead.rows[0];const index=this.table.columns.indexOf(name);const th=head.cells[index],button=th.querySelector('button');
    if(direction===-1&&this.sortState[name]!==1){this.sortState={[name]:1};}
    if(direction===1)this.sortState={};
    this.sortBy(name,th,button,head);
  }
  export() {
    if(!this.table)return;
    const url=URL.createObjectURL(new Blob([csvText(this.table)],{type:'text/csv;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download=`b2b-${this.table.grain}.csv`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  drawChart() {
    const table=this.table; if(!table?.chart||this.root.hidden) return;
    const spec=table.chart,rows=table.rows.slice(0,CHART.maxGroups),canvas=this.q('.chart');
    const ops=[];const ctx=this.recordOps?recording(canvas.getContext('2d'),ops):canvas.getContext('2d');
    const width=Math.max(CHART.minWidth,canvas.parentElement.clientWidth),height=CHART.height;canvas.width=width;canvas.height=height;
    const {left,right,top,bottom}=CHART,w=width-left-right,h=height-top-bottom;
    ctx.clearRect(0,0,width,height);ctx.font='11px Segoe UI';ctx.fillStyle='#617657';ctx.strokeStyle='#d5dfd2';
    const measure=this.q('.chart-measure').value,dimension=spec.dimensions[0],scatter=spec.type==='scatter';
    const values=rows.map(row=>row[scatter?spec.measures[1]:measure]).filter(value=>value!=null).map(Number).filter(Number.isFinite);
    let min=Math.min(0,...values),max=Math.max(0,...values);if(min===max)max=min+1;
    const y=value=>top+h-(value-min)/(max-min)*h;
    const plot={type:spec.type,width,height,left,right,top,bottom,min,max,measure:scatter?spec.measures[1]:measure,dimension,displayed:rows.length,limited:table.rows.length>CHART.maxGroups,bars:[],points:[],scatter:null,zero:y(0)};
    for(let i=0;i<=4;i++){const value=min+(max-min)*i/4,position=y(value);ctx.beginPath();ctx.moveTo(left,position);ctx.lineTo(width-right,position);ctx.stroke();ctx.fillText(new Intl.NumberFormat(undefined,{notation:'compact'}).format(value),5,position+4);}
    ctx.save();ctx.fillStyle='#2c5141';ctx.strokeStyle='#2c5141';ctx.lineWidth=2;
    if(scatter){
      const xs=rows.map(r=>r[spec.measures[0]]==null?null:Number(r[spec.measures[0]])),finite=xs.filter(value=>value!=null&&Number.isFinite(value));let lo=finite.length?Math.min(...finite):0,hi=finite.length?Math.max(...finite):1;if(lo===hi)hi=lo+1;
      plot.scatter={lo,hi,xMeasure:spec.measures[0],points:[]};
      rows.forEach((row,i)=>{if(row[spec.measures[0]]==null||row[spec.measures[1]]==null)return;const x=left+(xs[i]-lo)/(hi-lo)*w,py=y(Number(row[spec.measures[1]]));plot.scatter.points.push({x,y:py,xValue:row[spec.measures[0]],yValue:row[spec.measures[1]],label:String(row[dimension]??'Unknown')});ctx.beginPath();ctx.arc(x,py,5,0,Math.PI*2);ctx.fill();});
      ctx.fillText(spec.measures[0]+': '+lo+' → '+hi,left,height-22);
    } else {
      const step=w/Math.max(1,rows.length),points=[];plot.step=step;
      rows.forEach((row,i)=>{const x=left+step*(i+.5),value=row[measure],label=String(row[dimension]??'Unknown');ctx.save();ctx.translate(x,height-bottom+15);ctx.rotate(-.35);ctx.fillText(label.slice(0,20),-10,0);ctx.restore();
        if(value==null){points.push(null);plot.points.push(null);return;} const point=[x,y(Number(value))];points.push(point);plot.points.push({x:point[0],y:point[1],value,label});
        if(spec.type==='bar'){const zero=y(0);const bar={x:x-step*.3,y:Math.min(zero,point[1]),w:step*.6,h:Math.max(1,Math.abs(zero-point[1])),value,label};plot.bars.push(bar);ctx.fillRect(bar.x,bar.y,bar.w,bar.h);}});
      if(spec.type!=='bar'){
        let segment=[];const flush=()=>{if(!segment.length)return;ctx.beginPath();ctx.moveTo(...segment[0]);segment.slice(1).forEach(p=>ctx.lineTo(...p));ctx.stroke();
          if(spec.type==='area'){ctx.lineTo(segment.at(-1)[0],y(0));ctx.lineTo(segment[0][0],y(0));ctx.closePath();ctx.globalAlpha=.15;ctx.fill();ctx.globalAlpha=1;}segment.forEach(p=>{ctx.beginPath();ctx.arc(...p,3,0,Math.PI*2);ctx.fill();});segment=[];};
        points.forEach(p=>p?segment.push(p):flush());flush();
      }
    }
    ctx.restore();
    const caption=`${scatter?spec.measures.join(' vs '):measure+' by '+dimension} · ${rows.length} displayed groups${plot.limited?` (chart limited to first ${CHART.maxGroups}; table contains the rest)`:''}. Exact values are in the table.`;
    this.q('.chart-caption').textContent=caption;canvas.setAttribute('aria-label',caption);
    plot.caption=caption;this.plot=plot;this.ops=this.recordOps?ops:null;
  }
}
const mainView=new ResultView($('result'));
async function handleResult(result) {
  sessionId=result.session_id;localStorage.setItem('b2b-session',sessionId);
  if(result.kind==='clarify'){message(result.question);$('question').placeholder='Reply to the follow-up question…';}
  else {mainView.render(result.table);$('rerun').hidden=false;message(result.table.total_rows?'Your result is ready.':'No rows matched those filters.');$('question').placeholder='Ask a follow-up, or start a new conversation.';}
  $('suggestions').replaceChildren();
  (result.suggestions||[]).forEach(text=>{const button=document.createElement('button');button.className='quiet data-action';button.textContent=text;button.title='Use this suggested follow-up';button.addEventListener('click',()=>{$('question').value=text;$('question').focus();});$('suggestions').append(button);});
  $('question').value='';await listSessions();
}
async function submit(sample) {
  if(busy)return;const question=$('question').value.trim();if(!sample&&!question)return;
  setBusy(true,sample?'Building result…':'Asking Qwen…');message(sample?`Preview ${sample.intent||'table'} (${sample.view}).`:question,'user');
  try{const body=sample?{...sample,session_id:sessionId}:{question,session_id:sessionId,view:$('view').value};await handleResult(await api(sample?'/api/sample':'/api/ask',body));}
  catch(error){message(error.message,'error');}finally{setBusy(false);}
}
$('ask-form').addEventListener('submit',e=>{e.preventDefault();submit();});
$('question').addEventListener('keydown',e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();submit();}});
document.querySelectorAll('.sample').forEach(b=>b.addEventListener('click',()=>submit({view:b.dataset.view,intent:b.dataset.intent||'table'})));
$('reset').addEventListener('click',async()=>{try{await newSession();}catch(e){message(e.message,'error');}});
$('session-picker').addEventListener('change',async()=>{try{await loadSession($('session-picker').value);}catch(e){message(e.message,'error');}});
$('rerun').addEventListener('click',async()=>{if(busy)return;setBusy(true,'Running saved query…');try{await handleResult(await api('/api/rerun',{session_id:sessionId}));}catch(e){message(e.message,'error');}finally{setBusy(false);}});
$('refresh').addEventListener('click',async()=>{if(busy)return;setBusy(true,'Refreshing data…');try{const result=await api('/api/refresh',{});message(`Data refreshed from ${result.source_name||result.source}: ${result.opportunities.toLocaleString()} opportunities and ${result.skus.toLocaleString()} opportunity/SKU rows. Run the saved query to update its table.`);}catch(e){message(e.message,'error');}finally{setBusy(false);}});
function showQualification(q) {
  const badge=$('readiness');if(!q){badge.hidden=true;return;}
  badge.hidden=false;badge.textContent=q.ready?'Ready for review':`Acceptance: ${q.streak} of ${q.required} passes`;badge.className='readiness'+(q.ready?' ready':'');badge.title=q.reason;
}
window.B2B={ResultView,csvText,compareValues,api,CHART,mainView,showQualification,message};
(async()=>{try{const status=await api('/api/status');$('status').textContent=`${status.source} · Qwen: ${status.model} · v${status.version}`;$('samples').hidden=!status.previews;
  $('samples-label').textContent=status.database==='csv'?'Preview the CSV file without Qwen':'Try the fictional dataset';showQualification(status.qualification);
  if(sessionId){try{await loadSession(sessionId);}catch{sessionId=null;}}if(!sessionId)await newSession();else await listSessions();
}catch(e){$('status').textContent='Could not connect to the app.';message(e.message,'error');}})();
