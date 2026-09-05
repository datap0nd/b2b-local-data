const $ = id => document.getElementById(id);
let history = [], currentTable = null, busy = false;
function message(text, type = '') {
  $('conversation').querySelector('.empty')?.remove();
  const node = document.createElement('p'); node.className = `message ${type}`; node.textContent = text;
  $('conversation').append(node);
}
async function api(path, body) {
  const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Request failed.'); return result;
}
function renderTable(table) {
  currentTable = table; $('result').hidden = false; $('table').replaceChildren();
  $('result-title').textContent = table.view === 'summary' ? 'Opportunity summary' : 'Opportunity & product detail';
  $('result-meta').textContent = `${table.rows.length.toLocaleString()} of ${table.total_rows.toLocaleString()} rows · ${table.source_rows.toLocaleString()} matching source lines${table.truncated ? ' · Display limit reached; CSV includes the displayed rows only' : ''}`;
  $('scope').textContent = table.product_scope === 'whole_opportunities' ? 'Includes all products belonging to matching opportunities.' : 'Totals include only the source rows that match your filters.';
  const head = $('table').createTHead().insertRow();
  table.columns.forEach(name => { const th = document.createElement('th'); th.scope = 'col'; th.textContent = name.replaceAll('_', ' '); head.append(th); });
  const body = $('table').createTBody();
  table.rows.forEach(record => { const row = body.insertRow(); table.columns.forEach(name => { row.insertCell().textContent = record[name] ?? '—'; }); });
  $('filters').textContent = table.filters.length ? JSON.stringify(table.filters, null, 2) : 'No filters.';
}
async function submit(sampleView) {
  if (busy) return;
  const question = $('question').value.trim();
  if (!sampleView && !question) return;
  busy = true;
  document.querySelectorAll('button').forEach(b => b.disabled = true);
  $('ask').textContent = sampleView ? 'Building table…' : 'Asking Qwen…';
  $('result').hidden = true; currentTable = null;
  message(sampleView ? `Show the fictional ${sampleView} table.` : question, 'user');
  try {
    const result = await api(sampleView ? '/api/sample' : '/api/ask', sampleView ? {view:sampleView} : {question, history, view:$('view').value});
    if (!sampleView) history.push({role:'user', content:question});
    if (result.kind === 'clarify') {
      message(result.question); history.push({role:'assistant',content:result.question});
      $('question').value = ''; $('question').placeholder = 'Reply to the follow-up question…'; $('question').focus();
    } else {
      renderTable(result.table);
      message(result.table.total_rows ? 'Your table is ready. The filters and product scope are shown below.' : 'No rows matched those filters.');
      if (!sampleView) history.push({role:'assistant',content:JSON.stringify(result.plan)});
      $('question').value = ''; $('question').placeholder = 'Ask a follow-up, or start a new question.';
    }
    if (history.length > 16) { history = []; message('Conversation limit reached. The next question will start a new conversation.'); }
  } catch (error) { message(error.message, 'error'); }
  finally { busy = false; document.querySelectorAll('button').forEach(b => b.disabled = false); $('ask').textContent = 'Ask Qwen ↗'; }
}
$('ask-form').addEventListener('submit', e => {e.preventDefault(); submit();});
document.querySelectorAll('.sample').forEach(b => b.addEventListener('click', () => submit(b.dataset.view)));
$('reset').addEventListener('click', () => {history=[]; currentTable=null; $('conversation').replaceChildren(); $('result').hidden=true; $('question').value=''; $('question').placeholder='What would you like to see?'; $('question').focus();});
$('export').addEventListener('click', () => {
  if (!currentTable) return;
  const cell = value => { let text = value == null ? '' : String(value); if (/^[\s]*[=+\-@\t\r]/.test(text)) text="'"+text; return '"'+text.replaceAll('"','""')+'"'; };
  const rows = [currentTable.columns, ...currentTable.rows.map(row => currentTable.columns.map(c => row[c]))];
  const url = URL.createObjectURL(new Blob(['\uFEFF'+rows.map(row => row.map(cell).join(',')).join('\r\n')], {type:'text/csv;charset=utf-8'}));
  const link = document.createElement('a'); link.href=url; link.download=`b2b-${currentTable.view}.csv`; link.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
});
fetch('/api/status').then(r=>r.json()).then(status => { $('status').textContent=`${status.database==='demo'?'Fictional sample data':status.database+' connection configured'} · Qwen: ${status.model} · v${status.version}`; $('samples').hidden=status.database!=='demo'; }).catch(()=>{$('status').textContent='Could not connect to the local app.';});
