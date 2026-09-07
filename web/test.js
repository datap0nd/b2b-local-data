// Acceptance-test panel: drives the server-owned suite, renders each result with the production result view
// (same renderer, options, formatting, and interaction handlers as ordinary answers), runs the sixteen browser
// checks, and records observations. Expected values are recomputed here from the payload with independent
// helpers; renderer diagnostics (plot geometry, recorded drawing operations) are only cross-checked, never trusted alone.
// The user's own question and result in the main page are never touched.
(()=>{
const {ResultView,api,CHART}=window.B2B,$=id=>document.getElementById(id);
const panel=$('test-panel'),view=new ResultView($('test-result'));
let run=null,running=false,cancelled=false,timer=null,startedAt=0,errors=0,suite=null,original=null;
window.addEventListener('error',()=>{errors++;});
const text=(id,value)=>{$(id).textContent=value;};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const frame=()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
function setControls(){$('test-start').disabled=running;$('test-resume').hidden=running||!(run&&run.run.status==='running');$('test-cancel').disabled=!running;$('test-report').disabled=!run;$('test-compare').disabled=!run;$('test-synthetic').disabled=running;}
function tick(){if(startedAt)text('test-elapsed',`${Math.round((Date.now()-startedAt)/1000)} s`);}
function showStatus(status){run=status;const c=status.counts;
  text('test-progress',`Passed ${c.passed} · Failed ${c.failed} · Review ${c.review??0} · Blocked ${c.blocked} · Remaining ${c.remaining} · Browser ${c.browser_passed}/${c.browser_passed+c.browser_failed+c.browser_blocked+c.browser_remaining}`);
  text('test-state',`Run ${status.run.id.slice(0,8)} · ${status.run.status}${status.full_pass?' · qualified':''} · source ${status.run.snapshot.source_name} · ${status.run.snapshot.opportunities.toLocaleString()} opportunities · parity ${status.run.snapshot.canonical_parity?'ok':'FAILED'}`);
  setControls();}
function showStep(step,index,total){text('test-case',`${index+1} of ${total} · ${step.id} ${step.title}`);text('test-prompt',step.prompt||step.error||'');
  text('test-answer',step.clarification?('Clarification: '+step.clarification):step.returned_plan?JSON.stringify(step.returned_plan):(step.error||''));
  const i=step.interpretation,d=step.data_ok??step.data?.ok;
  text('test-checks',`Interpretation: ${i?(i.ok?'pass':'FAIL — '+(i.problems||[]).join('; ')):'—'} · Data: ${d==null?'—':d?'pass':'FAIL'} · Status: ${step.status}${step.recovered?' (recovered after one correction)':''}`);}
function log(kind,id,observation){const line=document.createElement('p');line.className='test-log-line '+observation.status;line.textContent=`${kind} check ${id}: ${observation.status}${observation.notes?' — '+observation.notes:''}`;$('test-browser-log').prepend(line);}
// ----- independent helpers (documented display rules, implemented here without the renderer's code) -----
const LABELS={opportunity_no:'Opportunity no.',opportunity_name:'Opportunity',end_customer:'Customer',opportunity_owner:'Owner',stage:'Stage',stage_group:'Stage group',close_date:'Close date',close_month:'Close month',
  created_date:'Created',last_modified_date:'Last modified',product_code:'Product code',pet_name:'Product',product_codes:'Product codes',product_names:'Product names',quantity:'Quantity',opportunity_amount:'Amount',
  sku_amount:'Amount',amount:'Amount',deal_size:'Deal size (USD)',sku_count:'Product count',opportunity_count:'Opportunity count',opp_amount_converted_currency:'Currency',amount_converted_currency:'Currency',
  has_amount_discrepancy:'Amount check',has_quality_warning:'Data quality',probability:'Probability',type:'Type',first_channel:'First channel',comment:'Comment',age:'Age',subsidiary_subsidiary_code:'Subsidiary',
  gscm_product_group_new:'Product group',biz_focus:'Business focus',business_location:'Location',division:'Division',sales_type_detail:'Sales type',rollout_period_from:'Rollout from',rollout_period_to:'Rollout to',
  source_row_count:'Source rows',exported_opp_amount_min:'Exported amount (min)',exported_opp_amount_max:'Exported amount (max)',exported_opp_amount_value_count:'Exported amount values',deal_size_on_pricing_date_usd:'Deal size (USD)'};
const MEASURE_LABELS={amount:'Amount',quantity:'Quantity',sku_count:'Product count',opportunity_count:'Opportunity count',deal_size:'Deal size (USD)'};
const MONEY=new Set(['amount','opportunity_amount','sku_amount','exported_opp_amount_min','exported_opp_amount_max']);
const STAGE_GROUP={Won:'won','Rollout Started':'won','Rollout Finished':'won',Identified:'open',Qualified:'open',Negotiation:'open',Dropped:'lost',Lost:'lost'};
const COMPACT={opportunity:['opportunity_name','end_customer','opportunity_amount','stage','opportunity_owner','close_date'],opportunity_sku:['opportunity_no','pet_name','sku_amount','quantity','stage','opportunity_owner']};
const CURRENCY_FIELD={opportunity:'opp_amount_converted_currency',opportunity_sku:'amount_converted_currency'};
const sep=(()=>{const parts=new Intl.NumberFormat().formatToParts(1234567.5);return {group:parts.find(p=>p.type==='group')?.value??',',decimal:parts.find(p=>p.type==='decimal')?.value??'.'};})();
function fmtNumber(value,decimals){
  // Exact string arithmetic: no float conversion. decimals=null keeps the value's own digits without trailing zeros.
  if(value==null)return '—';let s=String(value);if(!/^[+-]?\d+(\.\d+)?$/.test(s))return s;
  const neg=s.startsWith('-');s=s.replace(/^[+-]/,'');let [int,frac='']=s.split('.');
  if(decimals!=null){if(frac.length>decimals){const keep=frac.slice(0,decimals),next=frac[decimals];let digits=(int+keep).split('').map(Number);
      if(next>='5'){let i=digits.length-1;while(i>=0){if(digits[i]===9){digits[i]=0;i--;}else{digits[i]++;break;}}if(i<0)digits.unshift(1);}
      const all=digits.join('');int=all.slice(0,all.length-decimals)||'0';frac=all.slice(all.length-decimals);}
    else frac=frac.padEnd(decimals,'0');}
  else frac=frac.replace(/0+$/,'');
  int=int.replace(/^0+(?=\d)/,'').replace(/\B(?=(\d{3})+(?!\d))/g,sep.group);
  const zero=/^0*$/.test(int.replace(/\D/g,''))&&/^0*$/.test(frac);
  return (neg&&!zero?'-':'')+int+(frac?sep.decimal+frac:'');}
function fmtDate(iso,monthOnly){const m=/^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso??''));if(!m)return String(iso??'—');
  return new Intl.DateTimeFormat(undefined,monthOnly?{month:'short',year:'numeric',timeZone:'UTC'}:{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'}).format(new Date(Date.UTC(+m[1],+m[2]-1,+m[3])));}
function fmtPercent(value){if(value==null)return '—';const s=String(value);if(!/^[+-]?\d+(\.\d+)?$/.test(s))return s;let [int,frac='']=s.split('.');frac=frac.padEnd(2,'0');const shifted=int+frac.slice(0,2)+(frac.length>2?'.'+frac.slice(2):'');return fmtNumber(shifted.replace(/\.$/,''),null)+'%';}
function decimalCompare(a,b){const parse=s=>{s=String(s);const neg=s.startsWith('-');s=s.replace(/^[+-]/,'');let [int,frac='']=s.split('.');frac=frac.replace(/0+$/,'');return {neg,int:int.replace(/^0+(?=\d)/,''),frac};};
  const x=parse(a),y=parse(b);const zero=v=>v.int==='0'&&v.frac==='';if(zero(x)&&zero(y))return 0;if(x.neg!==y.neg)return x.neg?-1:1;
  const mag=(p,q)=>p.int.length!==q.int.length?(p.int.length<q.int.length?-1:1):p.int!==q.int?(p.int<q.int?-1:1):p.frac===q.frac?0:(p.frac.padEnd(Math.max(p.frac.length,q.frac.length),'0')<q.frac.padEnd(Math.max(p.frac.length,q.frac.length),'0')?-1:1);
  const m=mag(x,y);return x.neg?-m:m;}
function uniformCurrency(t){const field=CURRENCY_FIELD[t.grain];const codes=new Set(t.rows.map(r=>r[field]).filter(v=>v!=null));if(codes.size===1)return [...codes][0];if(codes.size>1)return 'mixed';
  const f=(t.filters||[]).find(c=>(c.field==='opp_amount_converted_currency'||c.field==='amount_converted_currency')&&(c.operator==='eq'||(c.operator==='in'&&c.value.length===1)));return f?String(Array.isArray(f.value)?f.value[0]:f.value):null;}
function expectedHeader(t,column){let label=LABELS[column]||column;if(MONEY.has(column)){const cur=uniformCurrency(t);if(cur&&cur!=='mixed')label+=` (${cur})`;}return label;}
function expectedCell(t,row,column){const v=row[column],type=t.column_types[column];if(v==null)return '—';
  if(type==='number'){if(column==='probability')return fmtPercent(v);let s=fmtNumber(v,MONEY.has(column)?2:null);if(MONEY.has(column)&&uniformCurrency(t)==='mixed'&&row[CURRENCY_FIELD[t.grain]]!=null)s+=' '+row[CURRENCY_FIELD[t.grain]];return s;}
  if(type==='date')return fmtDate(v,column==='close_month');if(type==='bool'){if(column==='has_quality_warning')return v?'Warning':'OK';if(column==='has_amount_discrepancy')return v?'Mismatch':'Matches';return v?'Yes':'No';}
  return String(v);}
function expectedVisible(t,plan){if(t.intent!=='table'||(plan&&plan.dimensions&&plan.dimensions.length))return t.columns.slice();const compact=COMPACT[t.grain].filter(c=>t.columns.includes(c));(plan?.measures||[]).forEach(m=>{if(t.columns.includes(m)&&!compact.includes(m))compact.push(m);});return compact.length>=2?compact:t.columns.slice();}
const MERGE={opportunity_name:'opportunity_no',pet_name:'product_code'};
function expectedRowText(t,visible,row){return visible.map(c=>{const partner=MERGE[c];if(partner&&t.columns.includes(partner)&&!visible.includes(partner))return expectedCell(t,row,c)+(row[partner]==null?'':String(row[partner]));return expectedCell(t,row,c);});}
function domHeaders(){return [...view.q('.table').tHead.rows[0].cells].map(c=>c.textContent.replace(/ [↕↑↓]$/,''));}
function domRows(){return [...view.q('.table').tBodies[0].rows].filter(r=>!r.classList.contains('detail-row')).map(r=>[...r.cells].map(c=>c.textContent));}
function clone(value){return JSON.parse(JSON.stringify(value));}
function result(status,expected,observed,notes){return {status,expected,observed,notes};}
// ----- table checks -----
function tableChecks(kind){const t=view.table,plan=view.options.plan,visible=expectedVisible(t,plan);
  const headers=domHeaders(),wantHeaders=visible.map(c=>expectedHeader(t,c));const rows=domRows();const mismatches=[];
  t.rows.forEach((row,i)=>{const want=expectedRowText(t,visible,row);want.forEach((cell,j)=>{if(rows[i]?.[j]!==cell&&mismatches.length<20)mismatches.push({row:i,column:visible[j],expected:cell,observed:rows[i]?.[j]});});});
  const merged=visible.map(c=>MERGE[c]).filter(p=>p&&t.columns.includes(p)&&!visible.includes(p));const hidden=t.columns.filter(c=>!visible.includes(c)&&!merged.includes(c));
  let detailsOk=true,detailObserved=null;
  if(hidden.length&&t.rows.length){const toggle=view.q('.row-toggle');toggle.click();const detail=view.q('.detail-row');const terms=[...detail.querySelectorAll('dt')].map(d=>d.textContent);const values=[...detail.querySelectorAll('dd')].map(d=>d.textContent);
    const wantTerms=hidden.map(c=>expectedHeader(t,c)),wantValues=hidden.map(c=>expectedCell(t,t.rows[0],c));detailsOk=JSON.stringify(terms)===JSON.stringify(wantTerms)&&JSON.stringify(values)===JSON.stringify(wantValues);detailObserved={terms,values};toggle.click();}
  const menu=[...view.root.querySelectorAll('.columns-list label')].map(l=>l.textContent);const menuOk=JSON.stringify(menu)===JSON.stringify(t.columns.map(c=>expectedHeader(t,c)));
  const keyOk=kind==='detail'?headers[0]==='Opportunity no.'&&headers[1]==='Product':headers[0]==='Opportunity';
  const ok=JSON.stringify(headers)===JSON.stringify(wantHeaders)&&rows.length===t.rows.length&&!mismatches.length&&detailsOk&&menuOk&&keyOk;
  return result(ok?'pass':'fail',{headers:wantHeaders,rows:t.rows.length,hidden,menu:t.columns.length},{headers,rows:rows.length,mismatches,detailsOk,detail:detailObserved,menuOk,keyOk},`${t.rows.length} displayed rows compared cell by cell against independently formatted values; ${hidden.length} hidden fields checked in row details.`);}
function sortCheck(direction){const t=view.table,plan=view.options.plan,visible=expectedVisible(t,plan);const numeric=visible.filter(c=>t.column_types[c]==='number'&&!MERGE[c]);let column=numeric.find(c=>t.rows.some(r=>r[c]==null))||numeric[0];
  if(!column)return result('blocked',null,null,'No numeric column is visible to sort.');
  const before=original.rows.map(r=>r);const index=visible.indexOf(column);const th=view.q('.table').tHead.rows[0].cells[index];const header=th.querySelector('button');
  // Click the header (as a person would) until it reaches the wanted direction, whatever state an earlier check left.
  const wanted=direction===1?'ascending':'descending';for(let n=0;n<3&&th.getAttribute('aria-sort')!==wanted;n++)header.click();
  const expected=[...before].sort((a,b)=>{if(a[column]==null)return b[column]==null?0:1;if(b[column]==null)return -1;return direction*decimalCompare(a[column],b[column]);});
  const observed=domRows().map(r=>r[index]);const want=expected.map(r=>expectedCell(t,r,column));
  const aria=view.q('.table').tHead.rows[0].cells[index].getAttribute('aria-sort');const withNulls=before.some(r=>r[column]==null);
  const nullsLast=!withNulls||observed.slice(observed.length-observed.filter(v=>v==='—').length).every(v=>v==='—');
  let columnSelection=null;
  if(direction===-1){const hiddenColumn=t.columns.find(c=>!visible.includes(c)&&!Object.values(MERGE).includes(c));
    if(hiddenColumn){const box=[...view.root.querySelectorAll('.columns-list label')].find(l=>l.textContent===expectedHeader(t,hiddenColumn))?.querySelector('input');box.click();
      const headers=domHeaders();const added=headers.includes(expectedHeader(t,hiddenColumn));const stillSorted=view.q('.table').tHead.rows[0].querySelector(`th[data-column="${column}"]`).getAttribute('aria-sort')===(direction===1?'ascending':'descending');
      const newIndex=headers.indexOf(expectedHeader(t,hiddenColumn));const cells=domRows().map(r=>r[newIndex]);const wantCells=expected.map(r=>expectedCell(t,r,hiddenColumn));
      box.click();const removed=!domHeaders().includes(expectedHeader(t,hiddenColumn));columnSelection={column:hiddenColumn,added,stillSorted,cellsOk:JSON.stringify(cells)===JSON.stringify(wantCells),removed};}}
  const ok=JSON.stringify(observed)===JSON.stringify(want)&&aria===(direction===1?'ascending':'descending')&&nullsLast&&(columnSelection===null||(columnSelection.added&&columnSelection.stillSorted&&columnSelection.cellsOk&&columnSelection.removed));
  return result(ok?'pass':'fail',{column,direction,first:want.slice(0,10),nulls:withNulls},{first:observed.slice(0,10),aria,nullsLast,columnSelection},withNulls?'Null witness present; nulls must sort last.':(direction===-1?'No null value in the displayed rows; nulls-last could not be exercised on live data (synthetic checks cover it).':''));}
async function csvCheck(){const t=view.table;const captured=[];const createObjectURL=URL.createObjectURL,revoke=URL.revokeObjectURL;
  URL.createObjectURL=blob=>{captured.push(blob);return 'blob:captured';};URL.revokeObjectURL=()=>{};
  const stopClick=e=>{if(e.target.tagName==='A'&&e.target.href==='blob:captured')e.preventDefault();};document.addEventListener('click',stopClick,true);
  try{const visible=expectedVisible(t,view.options.plan);const sortable=visible.find(c=>t.column_types[c]==='number'&&!MERGE[c]);
    if(sortable){view.q('.table').tHead.rows[0].cells[visible.indexOf(sortable)].querySelector('button').click();view.q('.table').tHead.rows[0].cells[visible.indexOf(sortable)].querySelector('button').click();}
    view.q('.export').click();if(!captured.length)return result('fail',null,null,'The export control produced no file.');const bytes=new Uint8Array(await captured[0].arrayBuffer());const observed=new TextDecoder('utf-8',{ignoreBOM:true}).decode(bytes);
    // Displayed order from the DOM key cells, mapped back to the untouched payload copy.
    const keyText=cells=>cells.join('');const byKey=new Map(original.rows.map(r=>[keyText(expectedRowText(t,visible,r)),r]));const ordered=domRows().map(r=>byKey.get(keyText(r)));
    const quote=v=>{let s=v==null?'':String(v);if(/^[\s]*[=+\-@\t\r]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"';};
    const expected='﻿'+[t.columns.map(quote).join(','),...ordered.map(r=>t.columns.map(c=>quote(r?.[c])).join(','))].join('\r\n');
    const ok=observed===expected&&ordered.every(Boolean);
    return result(ok?'pass':'fail',{length:expected.length,firstLine:expected.split('\r\n')[1]?.slice(0,200),columns:t.columns.length,rows:ordered.length},{length:observed.length,firstLine:observed.split('\r\n')[1]?.slice(0,200),bom:observed.charCodeAt(0)===0xFEFF,crlf:observed.includes('\r\n'),type:captured[0].type},'Export triggered through the Export control; the file must hold every returned column and the displayed rows in the sorted order, every cell quoted, quotes doubled, formula prefixes guarded.');}
  finally{URL.createObjectURL=createObjectURL;URL.revokeObjectURL=revoke;document.removeEventListener('click',stopClick,true);}}
// ----- chart checks -----
function redraw(){view.recordOps=true;view.drawChart();view.recordOps=false;const all=view.ops||[];const start=all.findIndex(o=>o[0]==='save');return {plot:view.plot,ops:all.slice(start+1),allOps:all};}
function measureText(name,value,t){if(value==null)return '—';const s=fmtNumber(value,MONEY.has(name)?2:null);const cur=MONEY.has(name)?uniformCurrency(t):null;return cur&&cur!=='mixed'?`${s} ${cur}`:s;}
function hover(x,y){const c=view.q('.chart'),r=c.getBoundingClientRect();c.dispatchEvent(new PointerEvent('pointermove',{clientX:r.left+x,clientY:r.top+y,bubbles:true}));const tip=view.q('.chart-tip');const shown=!tip.hidden;const content=tip.textContent;c.dispatchEvent(new PointerEvent('pointerleave',{bubbles:true}));return {shown,content};}
function barCheck(){const {plot,ops}=redraw();const t=view.table,rows=original.rows.slice(0,CHART.maxGroups),measure=view.q('.chart-measure').value,dim=t.chart.dimensions[0];
  const groups=rows.map(r=>({label:r[dim]==null?'Unknown':(t.column_types[dim]==='date'?fmtDate(r[dim],dim==='close_month'):String(r[dim])),value:r[measure]})).filter(g=>g.value!=null&&Number.isFinite(Number(g.value)));
  const fills=ops.filter(o=>o[0]==='fillRect').map(o=>o[1]);const texts=ops.filter(o=>o[0]==='fillText').map(o=>o[1][0]);
  const max=Math.max(0,...groups.map(g=>Number(g.value)));const min=Math.min(0,...groups.map(g=>Number(g.value)));
  const orderOk=plot.bars.every((b,i)=>i===0||b.y>plot.bars[i-1].y);const labelsOk=plot.bars.length===groups.length&&plot.bars.every((b,i)=>b.label===groups[i].label);
  const scale=(max-min)?(plot.width-plot.left-plot.right)/(max-min):0;const lengthsOk=plot.bars.every((b,i)=>Math.abs(b.w-Math.max(1,Math.abs(Number(groups[i].value))*scale))<1e-6&&Math.abs(fills[i]?.[2]-b.w)<1e-6);
  const valueLabelsOk=groups.every(g=>texts.includes(measureText(measure,g.value,t)));const categoryLabelsOk=groups.every(g=>texts.some(x=>x===g.label||(x.endsWith('…')&&g.label.startsWith(x.slice(0,-1)))));
  const tip=plot.bars.length?hover(plot.bars[0].x+plot.bars[0].w/2,plot.bars[0].y+plot.bars[0].h/2):{shown:false,content:''};const tipOk=tip.shown&&tip.content.includes(groups[0]?.label)&&tip.content.includes(measureText(measure,groups[0]?.value,t));
  const ok=orderOk&&labelsOk&&lengthsOk&&fills.length===groups.length&&valueLabelsOk&&categoryLabelsOk&&tipOk&&(plot.orientation==='horizontal');
  return result(ok?'pass':'fail',{groups:groups.slice(0,10),orientation:'horizontal',valueLabels:groups.slice(0,10).map(g=>measureText(measure,g.value,t))},{bars:plot.bars.slice(0,10).map(b=>({label:b.label,w:b.w,y:b.y})),fillRect:fills.length,orderOk,labelsOk,lengthsOk,valueLabelsOk,categoryLabelsOk,tooltip:tip,orientation:plot.orientation},`${groups.length} horizontal bars in server order; lengths recomputed from the values and the plot width; value labels and tooltip compared with independently formatted text.`);}
function lineCheck(area){const {plot,ops}=redraw();const t=view.table,rows=original.rows.slice(0,CHART.maxGroups),measure=view.q('.chart-measure').value,dim=t.chart.dimensions[0];
  const labels=rows.map(r=>r[dim]);const ordered=labels.every((l,i)=>i===0||l==null||labels[i-1]==null||String(labels[i-1])<=String(l));
  const values=rows.map(r=>r[measure]).filter(v=>v!=null).map(Number);let min=Math.min(0,...values),max=Math.max(0,...values);if(min===max)max=min+1;
  const {left,right,top,bottom}=plot,w=plot.width-left-right,h=plot.height-top-bottom;const y=v=>top+h-(v-min)/(max-min)*h,step=w/Math.max(1,rows.length);
  const expected=rows.map((r,i)=>r[measure]==null?null:{x:left+step*(i+.5),y:y(Number(r[measure]))});
  const segments=[];let seg=[];expected.forEach(p=>{if(p)seg.push(p);else{if(seg.length)segments.push(seg);seg=[];}});if(seg.length)segments.push(seg);
  const moves=ops.filter(o=>o[0]==='moveTo'),strokes=ops.filter(o=>o[0]==='stroke').length,close=(a,b)=>Math.abs(a-b)<1e-6;
  const pointsOk=expected.length===plot.points.length&&expected.every((p,i)=>p===null?plot.points[i]===null:close(p.x,plot.points[i].x)&&close(p.y,plot.points[i].y));
  const gapsOk=moves.length===segments.length&&segments.every((s,i)=>close(s[0].x,moves[i][1][0])&&close(s[0].y,moves[i][1][1]))&&strokes===segments.length;
  let baselineOk=true;if(area){baselineOk=ops.filter(o=>o[0]==='lineTo'&&close(o[1][1],y(0))).length===segments.length*2&&ops.some(o=>o[0]==='fill');}
  const first=plot.points.find(Boolean);const firstRow=rows[plot.points.indexOf(first)];const tip=first?hover(first.x,first.y):{shown:false,content:''};
  const tipOk=!first||(tip.shown&&tip.content.includes(measureText(measure,firstRow[measure],t))&&tip.content.includes(t.column_types[dim]==='date'?fmtDate(firstRow[dim],dim==='close_month'):String(firstRow[dim])));
  const ok=ordered&&pointsOk&&gapsOk&&baselineOk&&tipOk;
  return result(ok?'pass':'fail',{points:expected.slice(0,10),segments:segments.length,chronological:true,baseline:area?y(0):null},{points:plot.points.slice(0,10),moveTo:moves.length,strokes,chronological:ordered,tooltip:tip},`${segments.length} segment(s); ${expected.filter(p=>p===null).length} gap(s) for missing values; coordinates recomputed from the layout constants.`);}
function scatterCheck(){const {plot,ops}=redraw();const t=view.table,rows=original.rows.slice(0,CHART.maxGroups),[xm,ym]=t.chart.measures;
  const values=rows.map(r=>r[ym]).filter(v=>v!=null).map(Number);let min=Math.min(0,...values),max=Math.max(0,...values);if(min===max)max=min+1;
  const {left,right,top,bottom}=plot,w=plot.width-left-right,h=plot.height-top-bottom;const y=v=>top+h-(v-min)/(max-min)*h;
  const xs=rows.map(r=>r[xm]==null?null:Number(r[xm])),finite=xs.filter(v=>v!=null);let lo=finite.length?Math.min(...finite):0,hi=finite.length?Math.max(...finite):1;if(lo===hi)hi=lo+1;
  const expected=rows.map((r,i)=>r[xm]==null||r[ym]==null?null:{x:left+(xs[i]-lo)/(hi-lo)*w,y:y(Number(r[ym])),row:r}).filter(Boolean);
  const arcs=ops.filter(o=>o[0]==='arc'&&o[1][2]===5).map(o=>o[1]);const close=(a,b)=>Math.abs(a-b)<1e-6;
  const pointsOk=expected.length===plot.scatter.points.length&&expected.length===arcs.length&&expected.every((p,i)=>close(p.x,plot.scatter.points[i].x)&&close(p.y,plot.scatter.points[i].y)&&close(p.x,arcs[i][0])&&close(p.y,arcs[i][1]))&&close(lo,plot.scatter.lo)&&close(hi,plot.scatter.hi);
  const tip=expected.length?hover(expected[0].x,expected[0].y):{shown:false,content:''};const tipOk=!expected.length||(tip.shown&&tip.content.includes(measureText(xm,expected[0].row[xm],t))&&tip.content.includes(measureText(ym,expected[0].row[ym],t)));
  return result(pointsOk&&tipOk?'pass':'fail',{points:expected.slice(0,10).map(p=>({x:p.x,y:p.y})),xRange:[lo,hi],yRange:[min,max]},{points:plot.scatter.points.slice(0,10),arcs:arcs.length,xRange:[plot.scatter.lo,plot.scatter.hi],tooltip:tip},`${expected.length} points recomputed on both axes; tooltip shows both measures.`);}
async function measureCheck(){const t=view.table;const fetchOriginal=window.fetch;let calls=0;window.fetch=(...a)=>{calls++;return fetchOriginal(...a);};
  try{const select=view.q('.chart-measure');const other=[...select.options].map(o=>o.value).find(v=>v!==select.value);if(!other)return result('blocked',null,null,'Only one measure available.');
    const before=redraw().ops.filter(o=>o[0]==='fillText').map(o=>o[1][0]);select.value=other;select.dispatchEvent(new Event('change'));await sleep(50);
    const {plot,ops}=redraw();const texts=ops.filter(o=>o[0]==='fillText').map(o=>o[1][0]);const rows=original.rows.slice(0,CHART.maxGroups);
    const wantLabels=rows.filter(r=>r[other]!=null).map(r=>measureText(other,r[other],t));const labelsOk=wantLabels.every(x=>texts.includes(x));
    const ok=plot.measure===other&&calls===0&&labelsOk&&view.q('.chart-caption').textContent.startsWith(MEASURE_LABELS[other]||other);
    return result(ok?'pass':'fail',{measure:other,fetchCalls:0,valueLabels:wantLabels.slice(0,10)},{measure:plot.measure,fetchCalls:calls,valueLabels:texts.filter(x=>wantLabels.includes(x)).slice(0,10),caption:view.q('.chart-caption').textContent,changed:JSON.stringify(before)!==JSON.stringify(texts)},'Changing the chart measure must redraw locally with the other measure\'s values.');}
  finally{window.fetch=fetchOriginal;}}
function limitCheck(){const t=view.table;const before=redraw().plot;const beforeLabels=(before.bars.length?before.bars:before.points.filter(Boolean)).map(p=>p.label);
  const visible=expectedVisible(t,view.options.plan);const numeric=visible.find(c=>t.column_types[c]==='number');const th=view.q('.table').tHead.rows[0].cells[visible.indexOf(numeric)].querySelector('button');const originalOrder=JSON.stringify(original.rows.map(r=>expectedCell(t,r,numeric)));
  th.click();if(JSON.stringify(domRows().map(r=>r[visible.indexOf(numeric)]))===originalOrder)th.click();
  const after=redraw().plot;const afterLabels=(after.bars.length?after.bars:after.points.filter(Boolean)).map(p=>p.label);const tableOrder=domRows().map(r=>r[visible.indexOf(numeric)]);
  const stable=JSON.stringify(beforeLabels)===JSON.stringify(afterLabels)&&after.displayed===before.displayed;
  const tableReordered=JSON.stringify(tableOrder)!==originalOrder||original.rows.length<2;
  const exercised=t.rows.length>CHART.maxGroups;let limitOk=true,disclosure=view.q('.chart-limit');
  if(exercised){limitOk=after.displayed===CHART.maxGroups&&after.limited&&!disclosure.hidden&&disclosure.textContent.includes('first 30')&&disclosure.textContent.includes(String(t.rows.length));}
  else limitOk=disclosure.hidden&&!after.limited;
  const ok=stable&&limitOk&&tableReordered;
  return result(ok?'pass':'fail',{stableGroups:beforeLabels.slice(0,10),limitExercised:exercised,displayed:exercised?CHART.maxGroups:t.rows.length},{afterSort:afterLabels.slice(0,10),displayed:after.displayed,limited:after.limited,disclosure:disclosure.textContent,tableReordered},exercised?`${t.rows.length} groups: the chart shows the first 30 with its disclosure and keeps them while the table is sorted.`:`Only ${t.rows.length} groups; the 30-group limit is not exercised by this source (synthetic checks cover it). Chart stability while sorting the table is verified.`);}
async function resizeCheck(){const errorsBefore=errors;const host=view.q('.chart').parentElement;const originalWidth=host.style.width;const before=redraw().plot.width;
  host.style.width='620px';const expectedWidth=Math.max(CHART.minWidth,host.clientWidth);window.dispatchEvent(new Event('resize'));await frame();await sleep(30);
  const redrawnWidth=view.plot.width;const {plot,allOps}=redraw();host.style.width=originalWidth;
  const finite=allOps.every(o=>o[1].every(a=>typeof a!=='number'||Number.isFinite(a)));const canvas=view.q('.chart');
  let painted=0;try{const data=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;for(let i=3;i<data.length;i+=4)if(data[i])painted++;}catch{painted=-1;}
  const ok=redrawnWidth===expectedWidth&&plot.width===expectedWidth&&before!==plot.width&&finite&&painted>0&&errors===errorsBefore;window.dispatchEvent(new Event('resize'));await frame();
  return result(ok?'pass':'fail',{width:expectedWidth,finite:true,painted:'> 0',browserErrors:0},{widthBefore:before,widthAfterResizeEvent:redrawnWidth,width:plot.width,finite,painted,browserErrors:errors-errorsBefore,operations:allOps.length},'Resized the chart host to 620px, dispatched a real resize event, waited for the redraw, checked every drawing coordinate is finite, and inspected canvas pixels.');}
// ----- presentation checks -----
function metricCheck(){const t=view.table;const cards=[...view.root.querySelectorAll('.metric')];const measures=t.columns.filter(c=>MEASURE_LABELS[c]);const row=t.rows[0]||{};
  const wantLabels=measures.map(m=>MEASURE_LABELS[m]);const wantValues=measures.map(m=>fmtNumber(row[m],MONEY.has(m)?2:null));
  const labels=cards.map(c=>c.querySelector('.metric-label').textContent),values=cards.map(c=>c.querySelector('.metric-value').childNodes[0].textContent);
  const tableHidden=view.q('.table-wrap').hidden,metricsShown=!view.q('.metrics').hidden;const cur=uniformCurrency(t);const units=cards.map(c=>c.querySelector('.metric-unit')?.textContent||'');const unitsOk=measures.every((m,i)=>MONEY.has(m)?(cur&&cur!=='mixed'?units[i]===cur:units[i]===''):units[i]==='');
  const meta=view.q('.result-meta').textContent;const noteOk=(cur&&cur!=='mixed')?!meta.includes('Currency not provided'):meta.includes('Currency not provided');
  const ok=metricsShown&&tableHidden&&JSON.stringify(labels)===JSON.stringify(wantLabels)&&JSON.stringify(values)===JSON.stringify(wantValues)&&unitsOk&&noteOk;
  return result(ok?'pass':'fail',{labels:wantLabels,values:wantValues,currency:cur},{labels,values,units,tableHidden,metricsShown,meta},'Ungrouped metric rendered as cards with independently formatted values; no table, no fabricated totals.');}
function emptyCheck(){const t=view.table;const empty=view.q('.empty-result');const chips=[...empty.querySelectorAll('.filter-chip')].map(c=>c.textContent);const heading=empty.querySelector('h3')?.textContent;
  const witness=t.filters.map(f=>{const v=Array.isArray(f.value)?f.value[0]:f.value;return typeof v==='number'||(t.column_types[f.field]==='number')?fmtNumber(String(v),null):String(v);});const chipsOk=chips.length===t.filters.length&&witness.every(v=>chips.some(c=>c.includes(v)));
  const ok=t.total_rows===0&&!empty.hidden&&heading==='No results match this question'&&chipsOk&&view.q('.table-wrap').hidden&&view.q('.export-label').textContent.includes('(0)')&&view.q('.result-meta').textContent.includes('No matching');
  return result(ok?'pass':'fail',{heading:'No results match this question',chips:t.filters.length,witness},{heading,chips,tableHidden:view.q('.table-wrap').hidden,exportLabel:view.q('.export-label').textContent},'Zero rows show the empty state with the active filters instead of an empty table.');}
function chipsCheck(){const t=view.table;const chips=[...view.q('.filters').querySelectorAll('.filter-chip')].map(c=>c.textContent);
  const OPS={eq:'is',ne:'is not',gt:'more than',ge:'at least',lt:'less than',le:'at most',contains:'contains',in:'is one of',between:'between'};
  const wantChips=t.filters.map(f=>`${LABELS[f.field]||f.field} ${OPS[f.operator]} ${Array.isArray(f.value)?f.value.join(f.operator==='between'?' and ':', '):f.value}`);
  const chipsOk=JSON.stringify(chips)===JSON.stringify(wantChips)&&![...view.q('.filters').querySelectorAll('button, input')].length;
  const visible=expectedVisible(t,view.options.plan);const stageIndex=visible.indexOf('stage');let badgesOk=true,badges=[];
  if(stageIndex>=0){const rows=[...view.q('.table').tBodies[0].rows].filter(r=>!r.classList.contains('detail-row'));badges=rows.slice(0,10).map(r=>{const b=r.cells[stageIndex].querySelector('.badge');return b?{text:b.textContent,group:[...b.classList].find(c=>['won','open','lost'].includes(c))||null}:null;});
    badgesOk=rows.every((r,i)=>{const b=r.cells[stageIndex].querySelector('.badge');const stage=original.rows[i]?.stage;return stage==null?r.cells[stageIndex].textContent==='—':(b&&b.textContent===stage&&(STAGE_GROUP[stage]||null)===([...b.classList].find(c=>['won','open','lost'].includes(c))||null));});}
  const warnings=[...view.q('.warnings').querySelectorAll('.warning')].map(w=>w.textContent);const warningsOk=JSON.stringify(warnings)===JSON.stringify(t.warnings||[]);
  const flagged=view.root.querySelectorAll('tr.flagged').length,wantFlagged=original.rows.filter(r=>r.has_quality_warning===true).length;
  const ok=chipsOk&&badgesOk&&warningsOk&&flagged===wantFlagged;
  return result(ok?'pass':'fail',{chips:wantChips,warnings:t.warnings,flaggedRows:wantFlagged},{chips,badges,warnings,flaggedRows:flagged,badgesOk},'Read-only filter chips with business labels, exact stage names with their group colour, warnings above the data, and row indicators only where the payload flags rows.');}
function currencyCheck(){const t=view.table;const cur=uniformCurrency(t);if(!cur||cur==='mixed')return result('blocked',{currency:cur},null,'No single currency is established by a returned column or filter.');
  const visible=expectedVisible(t,view.options.plan);const money=visible.find(c=>MONEY.has(c));const headers=domHeaders();const header=money?headers[visible.indexOf(money)]:null;
  const cells=money?domRows().map(r=>r[visible.indexOf(money)]):[];const cellsOk=cells.every((c,i)=>c===expectedCell(t,original.rows[i],money));
  const meta=view.q('.result-meta').textContent;const ok=header===`${LABELS[money]} (${cur})`&&cellsOk&&!meta.includes('Currency not provided')&&!cells.some(c=>c.endsWith(' '+cur));
  return result(ok?'pass':'fail',{header:`${LABELS[money]} (${cur})`,currency:cur},{header,sample:cells.slice(0,5),meta},'The currency named by the filter or the returned column labels the amount header once; cells carry no repeated code and no default currency is assumed.');}
const CHECKS={1:()=>tableChecks('summary'),2:()=>tableChecks('detail'),3:()=>sortCheck(1),4:()=>sortCheck(-1),5:csvCheck,6:barCheck,7:()=>lineCheck(false),8:()=>lineCheck(true),9:scatterCheck,10:measureCheck,11:limitCheck,12:resizeCheck,13:metricCheck,14:emptyCheck,15:chipsCheck,16:currencyCheck};
function renderStep(step,table){original=clone(table);view.render(clone(table),{question:step.prompt||'',plan:step.effective_plan||null,suggestions:[]});view.drawChart();}
async function runBrowserChecks(step){for(const id of step.browser_checks||[]){let observation;
  try{if(step.status==='blocked'||step.status==='error'||step.status==='not_applicable'||!view.table||(id>=6&&id<=12&&!view.table.chart))observation={status:'blocked',notes:`Step ${step.id} produced no rendered ${id>=6&&id<=12?'chart':'result'} (${step.status}).`};
    else observation=await CHECKS[id]();}
  catch(error){observation={status:'fail',notes:'Check threw: '+error.message};}
  log('Live',id,observation);
  try{showStatus(await api(`/api/test/runs/${run.run.id}/browser`,{check:id,status:observation.status,expected:observation.expected??null,observed:observation.observed??null,notes:observation.notes??null}));}
  catch(error){window.B2B.message('Could not record browser check '+id+': '+error.message,'error');}}}
async function drive(){running=true;cancelled=false;setControls();startedAt=startedAt||Date.now();clearInterval(timer);timer=setInterval(tick,1000);
  try{while(!cancelled&&run.run.status==='running'&&run.next_step!==null){const index=run.next_step;
      const result=await api(`/api/test/runs/${run.run.id}/step`,{step:index});const step=result.step;showStatus(result.status);showStep(step,index,result.status.total_steps);
      if(step.status==='blocked'||step.status==='error'||step.status==='not_applicable'||step.clarification){view.clear();}
      else if(result.table){renderStep(step,result.table);}else{view.clear();}
      await runBrowserChecks(step);}
    const status=await api('/api/status');window.B2B.showQualification(status.qualification);
    if(!cancelled){showStatus(await api(`/api/test/runs/${run.run.id}`));text('test-case',run.run.status==='complete'?`Finished: ${run.full_pass?'qualified full pass':'not qualified'}${run.run.unqualified_reasons?.length?' — '+run.run.unqualified_reasons.join('; '):''}`:`Run ${run.run.status}`);}}
  catch(error){window.B2B.message('Acceptance test stopped: '+error.message,'error');text('test-case','Stopped: '+error.message);}
  finally{running=false;clearInterval(timer);tick();setControls();}}
async function start(){if(running)return;$('test-start').disabled=true;try{view.clear();errors=0;startedAt=Date.now();$('test-browser-log').replaceChildren();showStatus(await api('/api/test/runs',{}));await drive();}catch(error){window.B2B.message(error.message,'error');text('test-case',error.message);running=false;setControls();}}
async function resume(){if(running||!run)return;await drive();}
async function cancel(){if(!run)return;cancelled=true;try{showStatus(await api(`/api/test/runs/${run.run.id}/cancel`,{}));text('test-case','Cancelled; the partial report is available.');}catch(error){window.B2B.message(error.message,'error');}}
function download(){if(!run)return;const link=document.createElement('a');link.href=`/api/test/runs/${run.run.id}/report`;link.download='';link.click();}
async function compare(){if(!run)return;const status=await api(`/api/test/runs/${run.run.id}`);const c=status.comparison;
  $('test-comparison').hidden=false;$('test-comparison').textContent=c?JSON.stringify(c,null,2):'No earlier run exists for this user.';}
// ----- synthetic edge cases (development evidence only; never recorded as live coverage) -----
function syntheticTable(columns,rows,extra){const types={};columns.forEach(c=>{types[c]=['quantity','opportunity_amount','sku_amount','amount','sku_count','opportunity_count','probability'].includes(c)?'number':['close_date','close_month'].includes(c)?'date':c.startsWith('has_')?'bool':'text';});
  return {columns,column_types:types,rows,total_rows:rows.length,source_rows:rows.length,truncated:false,result_digest:'digest2:synthetic',totals:null,grain:'opportunity',intent:'table',view:'summary',filters:[],source:'synthetic',source_name:'synthetic fixture',warnings:[],scope:'synthetic',chart:null,snapshot_at:new Date().toISOString(),...extra};}
const SYNTHETIC=[
  {id:'S1',title:'Mixed currencies: header without a code, cells with their own codes; null amount sorts last',checks:[1,3,4],table:()=>syntheticTable(['opportunity_no','opportunity_name','end_customer','opportunity_owner','stage','close_date','quantity','opportunity_amount','sku_count','opp_amount_converted_currency','has_amount_discrepancy','has_quality_warning'],
    [{opportunity_no:'000123',opportunity_name:'Alpha',end_customer:'Zoë Ångström GmbH',opportunity_owner:'Ann',stage:'Won',close_date:'2026-01-02',quantity:'3',opportunity_amount:'12345678901.55',sku_count:2,opp_amount_converted_currency:'EUR',has_amount_discrepancy:false,has_quality_warning:true},
     {opportunity_no:'000124',opportunity_name:'Beta',end_customer:'Contoso',opportunity_owner:'Bo',stage:'Lost',close_date:null,quantity:'1',opportunity_amount:'0.5',sku_count:1,opp_amount_converted_currency:'USD',has_amount_discrepancy:true,has_quality_warning:false},
     {opportunity_no:'000125',opportunity_name:'Gamma',end_customer:null,opportunity_owner:'Cy',stage:'Qualified',close_date:'2026-12-31',quantity:null,opportunity_amount:null,sku_count:0,opp_amount_converted_currency:'EUR',has_amount_discrepancy:false,has_quality_warning:false}],{warnings:['1 matching business rows carry a data-quality warning.']}),plan:{intent:'table',dimensions:[],measures:[]}},
  {id:'S2',title:'Forty groups: chart limited to 30 with its disclosure, stable under table sorting, long labels',checks:[6,10,11],table:()=>syntheticTable(['opportunity_owner','amount','quantity'],Array.from({length:40},(_,i)=>({opportunity_owner:`Owner ${String(i+1).padStart(2,'0')} with a very long descriptive name that needs truncation`,amount:`${(40-i)*1000+0.25}`,quantity:String(i+1)})),{intent:'chart',chart:{type:'bar',dimensions:['opportunity_owner'],measures:['amount','quantity']},filters:[{field:'opp_amount_converted_currency',operator:'eq',value:'EUR'}]}),plan:{intent:'chart',dimensions:['opportunity_owner'],measures:['amount','quantity']}},
  {id:'S3',title:'Empty result with filters',checks:[14],table:()=>syntheticTable(['opportunity_no','opportunity_name','opportunity_amount'],[],{filters:[{field:'stage',operator:'in',value:['Open']},{field:'opportunity_amount',operator:'gt',value:5000000000}]}),plan:{intent:'table',dimensions:[],measures:[]}},
  {id:'S4',title:'Line chart with gaps and a scatter tooltip over synthetic months',checks:[7,8],table:()=>syntheticTable(['close_month','amount'],Array.from({length:12},(_,m)=>({close_month:`2026-${String(m+1).padStart(2,'0')}-01`,amount:m%5===4?null:`${(m+1)*1500}.00`})),{intent:'chart',chart:{type:'area',dimensions:['close_month'],measures:['amount']}}),plan:{intent:'chart',dimensions:['close_month'],measures:['amount']}},
];
async function synthetic(){if(running)return;$('test-synthetic').disabled=true;text('test-case','Synthetic checks (development evidence only)');
  try{for(const fixture of SYNTHETIC){const step={id:fixture.id,prompt:'synthetic: '+fixture.title,effective_plan:fixture.plan,status:'pass'};renderStep(step,fixture.table());await frame();
      for(const id of fixture.checks){let observation;try{observation=await CHECKS[id]();}catch(error){observation={status:'fail',notes:'Check threw: '+error.message};}observation.notes=`[${fixture.id} ${fixture.title}] `+(observation.notes||'');log('Synthetic',id,observation);}}
    text('test-case','Synthetic checks finished; see the log. They are not recorded on the server and are not live-source coverage.');}
  finally{$('test-synthetic').disabled=false;}}
async function open(){panel.hidden=false;document.body.classList.add('testing');
  try{suite=suite||await api('/api/test/suite');text('test-suite',`Suite ${suite.suite_version}: ${suite.steps.length} prompt turns, ${suite.browser_checks.length} browser checks`);window.B2B.showQualification(suite.qualification);
    const runs=await api('/api/test/runs');const active=runs.runs.find(r=>r.status==='running');if(active&&!run){showStatus(await api(`/api/test/runs/${active.id}`));text('test-case','A run is in progress; resume it or cancel it.');}}
  catch(error){text('test-case',error.message);}
  setControls();}
function closePanel(){panel.hidden=true;document.body.classList.remove('testing');}
$('test-open').addEventListener('click',open);$('test-close').addEventListener('click',closePanel);
$('test-start').addEventListener('click',start);$('test-resume').addEventListener('click',resume);$('test-cancel').addEventListener('click',cancel);
$('test-report').addEventListener('click',download);$('test-compare').addEventListener('click',compare);$('test-synthetic').addEventListener('click',synthetic);
})();
