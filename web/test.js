// Acceptance-test panel: drives the server-owned suite, renders each result with the production
// renderers, runs the twelve browser checks, and records observations. The user's own question and
// result in the main page are never touched.
(()=>{
const {ResultView,csvText,api,CHART}=window.B2B,$=id=>document.getElementById(id);
const panel=$('test-panel'),view=new ResultView($('test-result'));
let run=null,running=false,cancelled=false,timer=null,startedAt=0,errors=0,suite=null;
window.addEventListener('error',()=>{errors++;});
const text=(id,value)=>{$(id).textContent=value;};
function setControls(){$('test-start').disabled=running;$('test-resume').hidden=running||!(run&&run.run.status==='running');$('test-cancel').disabled=!running;$('test-report').disabled=!run;$('test-compare').disabled=!run;}
function tick(){if(startedAt)text('test-elapsed',`${Math.round((Date.now()-startedAt)/1000)} s`);}
function showStatus(status){run=status;const c=status.counts;
  text('test-progress',`Passed ${c.passed} · Failed ${c.failed} · Blocked ${c.blocked} · Remaining ${c.remaining} · Browser ${c.browser_passed}/${c.browser_passed+c.browser_failed+c.browser_blocked+c.browser_remaining}`);
  text('test-state',`Run ${status.run.id.slice(0,8)} · ${status.run.status}${status.full_pass?' · full pass':''} · source ${status.run.snapshot.source_name} · ${status.run.snapshot.opportunities.toLocaleString()} opportunities`);
  setControls();}
function showStep(step,index,total){text('test-case',`${index+1} of ${total} · ${step.id} ${step.title}`);text('test-prompt',step.prompt||step.error||'');
  text('test-answer',step.clarification?('Clarification: '+step.clarification):step.returned_plan?JSON.stringify(step.returned_plan):(step.error||''));
  const i=step.interpretation,d=step.data_ok??step.data?.ok;
  text('test-checks',`Interpretation: ${i?(i.ok?'pass':'FAIL — '+(i.problems||[]).join('; ')):'—'} · Data: ${d==null?'—':d?'pass':'FAIL'} · Status: ${step.status}`);}
// ----- independent helpers for the browser checks (they do not reuse the renderer's own comparator) -----
function decimalCompare(a,b){const parse=s=>{s=String(s);const neg=s.startsWith('-');s=s.replace(/^[+-]/,'');let [int,frac='']=s.split('.');frac=frac.replace(/0+$/,'');return {neg,int:int.replace(/^0+(?=\d)/,''),frac};};
  const x=parse(a),y=parse(b);const zero=v=>v.int==='0'&&v.frac==='';if(zero(x)&&zero(y))return 0;if(x.neg!==y.neg)return x.neg?-1:1;
  const mag=(p,q)=>p.int.length!==q.int.length?(p.int.length<q.int.length?-1:1):p.int!==q.int?(p.int<q.int?-1:1):p.frac===q.frac?0:(p.frac.padEnd(Math.max(p.frac.length,q.frac.length),'0')<q.frac.padEnd(Math.max(p.frac.length,q.frac.length),'0')?-1:1);
  const m=mag(x,y);return x.neg?-m:m;}
const close=(a,b)=>Math.abs(a-b)<1e-6;
function expectedLayout(rows,measure,width){const {left,right,top,bottom,height}=CHART,w=width-left-right,h=height-top-bottom;
  const values=rows.map(r=>r[measure]).filter(v=>v!=null).map(Number);let min=Math.min(0,...values),max=Math.max(0,...values);if(min===max)max=min+1;
  const y=v=>top+h-(v-min)/(max-min)*h;const step=w/Math.max(1,rows.length);return {w,h,min,max,y,step,x:i=>left+step*(i+.5),zero:y(0)};}
function cellsOf(){return [...view.q('.table').tBodies[0].rows].map(r=>[...r.cells].map(c=>c.textContent));}
function tableChecks(kind){const t=view.table;const headers=[...view.q('.table').tHead.rows[0].cells].map(c=>c.textContent.replace(/ [↕↑↓]$/,''));
  const expectedHeaders=t.columns.map(c=>c.replaceAll('_',' '));const cells=cellsOf();const mismatches=[];
  t.rows.forEach((row,i)=>t.columns.forEach((c,j)=>{const want=row[c]==null?'—':String(row[c]);if(cells[i]?.[j]!==want&&mismatches.length<20)mismatches.push({row:i,column:c,expected:want,observed:cells[i]?.[j]});}));
  const keys=kind==='detail'?['opportunity no','product code']:['opportunity no'];const keysOk=keys.every((k,i)=>headers[i]===k);
  const ok=JSON.stringify(headers)===JSON.stringify(expectedHeaders)&&cells.length===t.rows.length&&!mismatches.length&&keysOk;
  return {status:ok?'pass':'fail',expected:{headers:expectedHeaders,rows:t.rows.length,keys},observed:{headers,rows:cells.length,mismatches,keysOk},notes:`${t.rows.length} displayed rows compared cell by cell.`};}
function sortCheck(direction){const t=view.table;const numeric=t.columns.filter(c=>t.column_types[c]==='number');let column=numeric.find(c=>t.rows.some(r=>r[c]==null))||numeric[0];
  if(!column)return {status:'blocked',notes:'No numeric column to sort.'};
  const withNulls=t.rows.some(r=>r[column]==null);
  const before=t.rows.map(r=>r);view.sortColumn(column,direction);
  const expected=[...before].sort((a,b)=>{if(a[column]==null)return b[column]==null?0:1;if(b[column]==null)return -1;return direction*decimalCompare(a[column],b[column]);});
  const keyIndex=t.columns.indexOf(column);const observed=cellsOf().map(r=>r[keyIndex]);const want=expected.map(r=>r[column]==null?'—':String(r[column]));
  const ok=JSON.stringify(observed)===JSON.stringify(want)&&view.q('.table').tHead.rows[0].cells[keyIndex].getAttribute('aria-sort')===(direction===1?'ascending':'descending');
  const nullsLast=!withNulls||observed.slice(observed.length-observed.filter(v=>v==='—').length).every(v=>v==='—');
  return {status:ok&&nullsLast?'pass':'fail',expected:{column,direction,first:want.slice(0,10),nulls:withNulls},observed:{first:observed.slice(0,10),nullsLast},notes:withNulls?'Null witness present; nulls must sort last.':(direction===-1?'No null value in the displayed rows; nulls-last could not be exercised on live data.':'')};}
function csvCheck(){const t=view.table;const quote=v=>{let s=v==null?'':String(v);if(/^[\s]*[=+\-@\t\r]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"';};
  const expected='﻿'+[t.columns.map(quote).join(','),...t.rows.map(r=>t.columns.map(c=>quote(r[c])).join(','))].join('\r\n');
  const observed=csvText(t);const ok=observed===expected;
  const sample={columns:t.columns.length,rows:t.rows.length,bom:observed.charCodeAt(0)===0xFEFF,crlf:observed.includes('\r\n'),quotedQuote:t.rows.some(r=>t.columns.some(c=>String(r[c]??'').includes('"')))};
  return {status:ok?'pass':'fail',expected:{length:expected.length,firstLine:expected.split('\r\n')[1]?.slice(0,200)},observed:{length:observed.length,firstLine:observed.split('\r\n')[1]?.slice(0,200),...sample},notes:'CSV covers the displayed rows in displayed order; every cell quoted, quotes doubled, formula prefixes guarded.'};}
function redraw(){view.recordOps=true;view.drawChart();view.recordOps=false;const all=view.ops||[];const start=all.findIndex(o=>o[0]==='save');
  // Drawing operations after the axis grid: the plotted marks only.
  return {plot:view.plot,ops:all.slice(start+1),allOps:all};}
function barCheck(){const {plot,ops}=redraw();const t=view.table,rows=t.rows.slice(0,CHART.maxGroups),measure=view.q('.chart-measure').value,L=expectedLayout(rows,measure,plot.width);
  const expected=rows.map((r,i)=>r[measure]==null?null:{x:L.x(i)-L.step*.3,y:Math.min(L.zero,L.y(Number(r[measure]))),w:L.step*.6,h:Math.max(1,Math.abs(L.zero-L.y(Number(r[measure])))),value:r[measure]}).filter(Boolean);
  const fills=ops.filter(o=>o[0]==='fillRect').map(o=>o[1]);
  const ok=expected.length===plot.bars.length&&expected.length===fills.length&&expected.every((b,i)=>close(b.x,plot.bars[i].x)&&close(b.y,plot.bars[i].y)&&close(b.w,plot.bars[i].w)&&close(b.h,plot.bars[i].h)&&close(b.x,fills[i][0])&&close(b.y,fills[i][1])&&close(b.h,fills[i][3]));
  return {status:ok?'pass':'fail',expected:{bars:expected.slice(0,10),min:L.min,max:L.max},observed:{bars:plot.bars.slice(0,10),fillRect:fills.slice(0,10),min:plot.min,max:plot.max},notes:`${expected.length} bars recomputed from the layout constants and compared with plotted rectangles and fillRect calls.`};}
function lineCheck(area){const {plot,ops}=redraw();const t=view.table,rows=t.rows.slice(0,CHART.maxGroups),measure=view.q('.chart-measure').value,L=expectedLayout(rows,measure,plot.width),dim=t.chart.dimensions[0];
  const labels=rows.map(r=>r[dim]);const ordered=labels.every((l,i)=>i===0||l==null||labels[i-1]==null||String(labels[i-1])<=String(l));
  const expected=rows.map((r,i)=>r[measure]==null?null:{x:L.x(i),y:L.y(Number(r[measure])),value:r[measure]});
  const segments=[];let seg=[];expected.forEach(p=>{if(p)seg.push(p);else{if(seg.length)segments.push(seg);seg=[];}});if(seg.length)segments.push(seg);
  const moves=ops.filter(o=>o[0]==='moveTo');const strokes=ops.filter(o=>o[0]==='stroke').length;
  const pointsOk=expected.length===plot.points.length&&expected.every((p,i)=>p===null?plot.points[i]===null:close(p.x,plot.points[i].x)&&close(p.y,plot.points[i].y));
  const gapsOk=moves.length===segments.length&&segments.every((s,i)=>close(s[0].x,moves[i][1][0])&&close(s[0].y,moves[i][1][1]))&&strokes===segments.length;
  let baselineOk=true;if(area){const baseline=ops.filter(o=>o[0]==='lineTo'&&close(o[1][1],L.zero));baselineOk=baseline.length===segments.length*2&&ops.some(o=>o[0]==='fill');}
  const ok=ordered&&pointsOk&&gapsOk&&baselineOk;
  return {status:ok?'pass':'fail',expected:{points:expected.slice(0,10),segments:segments.length,chronological:true,baseline:area?L.zero:null},observed:{points:plot.points.slice(0,10),moveTo:moves.length,strokes,chronological:ordered,baselineLineTo:area?ops.filter(o=>o[0]==='lineTo'&&close(o[1][1],L.zero)).length:null},notes:`${segments.length} segment(s); ${expected.filter(p=>p===null).length} gap(s) for missing values.`};}
function scatterCheck(){const {plot,ops}=redraw();const t=view.table,rows=t.rows.slice(0,CHART.maxGroups),[xm,ym]=t.chart.measures,L=expectedLayout(rows,ym,plot.width);
  const xs=rows.map(r=>r[xm]==null?null:Number(r[xm])),finite=xs.filter(v=>v!=null);let lo=finite.length?Math.min(...finite):0,hi=finite.length?Math.max(...finite):1;if(lo===hi)hi=lo+1;
  const expected=rows.map((r,i)=>r[xm]==null||r[ym]==null?null:{x:CHART.left+(xs[i]-lo)/(hi-lo)*L.w,y:L.y(Number(r[ym]))}).filter(Boolean);
  const arcs=ops.filter(o=>o[0]==='arc'&&o[1][2]===5).map(o=>o[1]);
  const ok=expected.length===plot.scatter.points.length&&expected.length===arcs.length&&expected.every((p,i)=>close(p.x,plot.scatter.points[i].x)&&close(p.y,plot.scatter.points[i].y)&&close(p.x,arcs[i][0])&&close(p.y,arcs[i][1]))&&close(lo,plot.scatter.lo)&&close(hi,plot.scatter.hi);
  return {status:ok?'pass':'fail',expected:{points:expected.slice(0,10),xRange:[lo,hi],yRange:[L.min,L.max]},observed:{points:plot.scatter.points.slice(0,10),arcs:arcs.length,xRange:[plot.scatter.lo,plot.scatter.hi],yRange:[plot.min,plot.max]},notes:`${expected.length} points recomputed on both axes.`};}
async function measureCheck(){const original=window.fetch;let calls=0;window.fetch=(...a)=>{calls++;return original(...a);};
  try{const select=view.q('.chart-measure');const other=[...select.options].map(o=>o.value).find(v=>v!==select.value);if(!other)return {status:'blocked',notes:'Only one measure available.'};
    select.value=other;view.recordOps=true;select.dispatchEvent(new Event('change'));view.recordOps=false;await new Promise(r=>setTimeout(r,50));
    const ok=view.plot.measure===other&&calls===0&&view.q('.chart-caption').textContent.startsWith(other);
    return {status:ok?'pass':'fail',expected:{measure:other,fetchCalls:0},observed:{measure:view.plot.measure,fetchCalls:calls,caption:view.q('.chart-caption').textContent},notes:'Changing the chart measure must redraw locally.'};}
  finally{window.fetch=original;}}
function limitCheck(){const t=view.table;if(t.rows.length<=CHART.maxGroups)return {status:'blocked',expected:{groups:'> 30'},observed:{groups:t.rows.length},notes:`Only ${t.rows.length} groups; the 30-group limit is not exercised by this source.`};
  const {plot}=redraw();const caption=view.q('.chart-caption').textContent;const ok=plot.displayed===CHART.maxGroups&&plot.limited&&caption.includes('chart limited to first 30')&&caption.includes('table contains the rest');
  return {status:ok?'pass':'fail',expected:{displayed:30,explanation:'chart limited to first 30; table contains the rest'},observed:{displayed:plot.displayed,caption},notes:`${t.rows.length} groups in the result.`};}
function resizeCheck(){const errorsBefore=errors;const host=view.q('.chart').parentElement;const originalWidth=host.style.width;const before=redraw().plot.width;
  host.style.width='620px';const expectedWidth=Math.max(CHART.minWidth,host.clientWidth);window.dispatchEvent(new Event('resize'));const {plot,allOps}=redraw();host.style.width=originalWidth;
  const finite=allOps.every(o=>o[1].every(a=>typeof a!=='number'||Number.isFinite(a)));const canvas=view.q('.chart');
  let painted=0;try{const data=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;for(let i=3;i<data.length;i+=4)if(data[i])painted++;}catch{painted=-1;}
  const ok=plot.width===expectedWidth&&before!==plot.width&&finite&&painted>0&&errors===errorsBefore;window.dispatchEvent(new Event('resize'));
  return {status:ok?'pass':'fail',expected:{width:expectedWidth,finite:true,painted:'> 0',browserErrors:0},observed:{widthBefore:before,width:plot.width,finite,painted,browserErrors:errors-errorsBefore,operations:allOps.length},notes:'Resized the chart host to 620px, redrew, checked every drawing coordinate is finite, and inspected canvas pixels.'};}
const CHECKS={1:()=>tableChecks('summary'),2:()=>tableChecks('detail'),3:()=>sortCheck(1),4:()=>sortCheck(-1),5:csvCheck,6:barCheck,7:()=>lineCheck(false),8:()=>lineCheck(true),9:scatterCheck,10:measureCheck,11:limitCheck,12:resizeCheck};
async function runBrowserChecks(step){for(const id of step.browser_checks||[]){let observation;
  try{if(step.status==='blocked'||step.status==='error'||!view.table||(id>=6&&!view.table.chart))observation={status:'blocked',notes:`Step ${step.id} produced no rendered ${id>=6?'chart':'table'} (${step.status}).`};
    else observation=await CHECKS[id]();}
  catch(error){observation={status:'fail',notes:'Check threw: '+error.message};}
  try{showStatus(await api(`/api/test/runs/${run.run.id}/browser`,{check:id,status:observation.status,expected:observation.expected??null,observed:observation.observed??null,notes:observation.notes??null}));}
  catch(error){window.B2B.message('Could not record browser check '+id+': '+error.message,'error');}}}
async function drive(){running=true;cancelled=false;setControls();startedAt=startedAt||Date.now();clearInterval(timer);timer=setInterval(tick,1000);
  try{while(!cancelled&&run.run.status==='running'&&run.next_step!==null){const index=run.next_step;
      const result=await api(`/api/test/runs/${run.run.id}/step`,{step:index});const step=result.step;showStatus(result.status);showStep(step,index,result.status.total_steps);
      if(step.status==='blocked'||step.status==='error'||step.clarification){view.clear();}
      else if(result.table){view.render(result.table);}else{view.clear();}
      await runBrowserChecks(step);}
    const status=await api('/api/status');window.B2B.showQualification(status.qualification);
    if(!cancelled){showStatus(await api(`/api/test/runs/${run.run.id}`));text('test-case',run.run.status==='complete'?`Finished: ${run.full_pass?'full pass':'not a full pass'}`:`Run ${run.run.status}`);}}
  catch(error){window.B2B.message('Acceptance test stopped: '+error.message,'error');text('test-case','Stopped: '+error.message);}
  finally{running=false;clearInterval(timer);tick();setControls();}}
async function start(){if(running)return;$('test-start').disabled=true;try{view.clear();errors=0;startedAt=Date.now();showStatus(await api('/api/test/runs',{}));await drive();}catch(error){window.B2B.message(error.message,'error');text('test-case',error.message);running=false;setControls();}}
async function resume(){if(running||!run)return;await drive();}
async function cancel(){if(!run)return;cancelled=true;try{showStatus(await api(`/api/test/runs/${run.run.id}/cancel`,{}));text('test-case','Cancelled; the partial report is available.');}catch(error){window.B2B.message(error.message,'error');}}
function download(){if(!run)return;const link=document.createElement('a');link.href=`/api/test/runs/${run.run.id}/report`;link.download='';link.click();}
async function compare(){if(!run)return;const status=await api(`/api/test/runs/${run.run.id}`);const c=status.comparison;
  $('test-comparison').hidden=false;$('test-comparison').textContent=c?JSON.stringify(c,null,2):'No earlier run exists for this user.';}
async function open(){panel.hidden=false;document.body.classList.add('testing');
  try{suite=suite||await api('/api/test/suite');text('test-suite',`Suite ${suite.suite_version}: ${suite.steps.length} prompt turns, ${suite.browser_checks.length} browser checks`);window.B2B.showQualification(suite.qualification);
    const runs=await api('/api/test/runs');const active=runs.runs.find(r=>r.status==='running');if(active&&!run){showStatus(await api(`/api/test/runs/${active.id}`));text('test-case','A run is in progress; resume it or cancel it.');}}
  catch(error){text('test-case',error.message);}
  setControls();}
function closePanel(){panel.hidden=true;document.body.classList.remove('testing');}
$('test-open').addEventListener('click',open);$('test-close').addEventListener('click',closePanel);
$('test-start').addEventListener('click',start);$('test-resume').addEventListener('click',resume);$('test-cancel').addEventListener('click',cancel);
$('test-report').addEventListener('click',download);$('test-compare').addEventListener('click',compare);
})();
