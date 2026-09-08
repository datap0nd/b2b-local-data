// Record the shipped frontend with isolated fictional responses. No backend runs.
const {createRequire} = require('module');
const path = require('path');
const fs = require('fs');
const http = require('http');
const req = process.env.PLAYWRIGHT_PACKAGE ? createRequire(process.env.PLAYWRIGHT_PACKAGE) : require;
const {chromium} = req('playwright');
const root = __dirname, dist = path.resolve(root, '../web/dist');
const out = path.join(root, 'captures'); fs.mkdirSync(out, {recursive:true});
const delay = ms => new Promise(r=>setTimeout(r,ms));
const rows = [35000,25000,22000,18000,12000,8000].map((amount,i)=>({
  opportunity_no:`DEMO-${i+1}`, opportunity_name:`Demo project ${String.fromCharCode(65+i)}`,
  end_customer:`Example customer ${i+1}`, opportunity_amount:String(amount),
  stage:['Negotiation','Negotiation','Qualified','Qualified','Identified','Identified'][i],
  opportunity_owner:'Demo owner', close_date:'2026-12-15',opp_amount_converted_currency:'EUR'
}));
function table(overrides={}) {
 return {columns:['amount'],column_types:{amount:'number'},rows:[{amount:'120000'}],total_rows:1,
 source_rows:6,truncated:false,result_digest:'fictional-video',totals:null,grain:'opportunity',
 intent:'metric',view:'summary',result_kind:'aggregate',presentation:'cards',columns_mode:'default',
 filters:[{field:'stage_group',operator:'eq',value:'Open'}],source:'synthetic',source_name:'Fictional video demo',
 warnings:[],scope:'',chart:null,plan_version:2,views:{current:'summary',available:['summary'],scope:null,scope_label:null,product_filtered:false},
 metadata:{version:2,calculation_version:3,currency:{code:'EUR',mixed:false,codes:{EUR:6},source:'column'},complete:{rows:1,opportunities:6},warnings:[],freshness:null,fingerprint:'fictional-video',explicit_columns:false},...overrides};
}
function records(data=rows) { return table({columns:Object.keys(rows[0]).filter(k=>k!=='close_date'),column_types:Object.fromEntries(Object.keys(rows[0]).map(k=>[k,k==='opportunity_amount'?'number':k==='close_date'?'date':'text'])),rows:data,total_rows:data.length,result_kind:'rows',intent:'rows',presentation:'table'}); }
function answer(i) {
 const data=records(i===2?rows.slice(0,2):rows);
 const t=i===0?table():i===1?table({columns:['stage','amount'],column_types:{stage:'text',amount:'number'},rows:[{stage:'Negotiation',amount:'60000'},{stage:'Qualified',amount:'40000'},{stage:'Identified',amount:'20000'}],total_rows:3,intent:'chart',presentation:'chart',chart:{type:'bar',dimensions:['stage'],measures:['amount']}}):data;
 if(i===2) {t.filters=[{field:'stage',operator:'eq',value:'Negotiation'}];t.metadata.complete={rows:2,opportunities:2};t.metadata.currency.codes={EUR:2};}
 return {kind:'table',turn_id:1,session_id:'video-demo',table:t,variants:{},answer:{title:['Open pipeline value','Open pipeline by stage','Opportunities in negotiation'][i],context:i===2?'2 opportunities · EUR':'6 open opportunities · EUR',sentence:'',metrics:i===0?[{label:'Amount',value:'€120,000',raw:'120000',currency:'EUR'}]:[]},suggestions:[],supporting:i<2?{version:1,available:true,default_view:'summary',views:{summary:data}}:undefined};
}
const server=http.createServer((q,r)=>{
 const pathname=new URL(q.url,'http://localhost').pathname;
 const p=path.resolve(dist,'.'+(pathname==='/'?'/index.html':pathname));
 if(!p.startsWith(dist+path.sep)||!fs.existsSync(p)){r.writeHead(404);r.end();return;}
 const type={'.html':'text/html','.js':'text/javascript','.css':'text/css','.woff2':'font/woff2'}[path.extname(p)]||'application/octet-stream';
 r.writeHead(200,{'Content-Type':type});fs.createReadStream(p).pipe(r);
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const url=`http://127.0.0.1:${server.address().port}`;
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_EXE||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 const prompts=['What is the total value of open opportunities?','Show open pipeline value by stage','Show opportunities in negotiation'];
 const manifest=[];
 try {
 for(let i=0;i<3;i++) {
  const context=await browser.newContext({viewport:{width:1440,height:810},deviceScaleFactor:1,recordVideo:{dir:out,size:{width:1440,height:810}}});
  await context.addInitScript(()=>localStorage.setItem('b2b-sidebar','collapsed'));
  let calls=0; const errors=[];
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/**',async route=>{
   const p=new URL(route.request().url()).pathname;
   let body;
   if(p==='/api/bootstrap') body={identity:{login_required:false,name:'Demo user',mode:'local'},capabilities:{acceptance_ui:false,samples:false,saved_results:true,contract_version:2,views:['summary'],presentations:['cards','chart','table']}};
   else if(p==='/api/freshness') body={freshness:null};
   else if(p==='/api/sessions') body={sessions:[]};
   else if(p==='/api/ask'){calls++;await delay(1450);body=answer(i);}
   else throw new Error('Unexpected API request: '+p);
   await route.fulfill({json:body});
  });
  await page.goto(url);await page.getByRole('textbox',{name:'Your question'}).waitFor();
  await page.waitForTimeout(700);
  const started=Date.now();
  await page.getByRole('textbox',{name:'Your question'}).pressSequentially(prompts[i],{delay:38});
  await page.waitForTimeout(450);
  const sent=Date.now();await page.getByRole('button',{name:'Send',exact:true}).click();
  await page.getByTestId('result-card').waitFor();
  const elapsed=Date.now()-sent;
  await page.waitForTimeout(1200);await page.screenshot({path:path.join(out,`result-${i}.png`)});
  if(i===1){await page.waitForTimeout(1800);await page.getByRole('button',{name:'Data',exact:true}).click();await page.waitForTimeout(1500);await page.getByRole('button',{name:'Chart',exact:true}).click();}
  if(i===2){await page.waitForTimeout(2000);const download=page.waitForEvent('download');await page.getByTestId('export').click();const file=await download;await file.saveAs(path.join(out,'fictional-result.csv'));}
  await page.waitForTimeout(Math.max(0,15500-(Date.now()-started)));
  if(errors.length||calls!==1)throw new Error(JSON.stringify({errors,calls}));
  const video=page.video();await context.close();const raw=await video.path();
  fs.renameSync(raw,path.join(out,`ui-${i}.webm`));
  manifest.push({clip:i,prompt:prompts[i],scriptedResponseDelayMs:1450,observedUiResponseMs:elapsed,apiCalls:calls});
  console.log(`Captured ${i+1}/3: UI result appeared in ${elapsed} ms`);
 }
 fs.writeFileSync(path.join(out,'manifest.json'),JSON.stringify(manifest,null,2));
 } finally {await browser.close();server.close();}
})().catch(e=>{console.error(e);process.exit(1)});
