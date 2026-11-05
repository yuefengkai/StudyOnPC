# -*- coding: utf-8 -*-
"""Tiny LAN admin HTTP server (stdlib) — polished mobile-friendly parent panel."""
from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("studyonpc.admin")

# Shared CSS — soft StudyOnPC brand, mobile-first cards (inspired by StudyOnTV parent panel layout only)
_CSS = r"""
:root{
  --bg:#f4f1ea; --card:#fff; --ink:#1f2937; --muted:#6b7280; --line:#e7e2d6;
  --brand:#f59e0b; --brand2:#fbbf24; --ok:#059669; --bad:#dc2626; --blue:#2563eb;
  --sky:#0ea5e9; --violet:#7c3aed; --radius:16px; --shadow:0 8px 24px rgba(31,41,55,.08);
}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:var(--bg);color:var(--ink);
  font-family:"Segoe UI","PingFang SC","Microsoft YaHei","Noto Sans SC",system-ui,sans-serif;
  -webkit-font-smoothing:antialiased}
a{color:var(--blue);text-decoration:none}
.wrap{max-width:960px;margin:0 auto;padding:20px 16px 48px}
.top{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:18px}
.brand{display:flex;align-items:center;gap:12px}
.logo{width:44px;height:44px;border-radius:12px;background:linear-gradient(135deg,#fbbf24,#f97316);
  display:grid;place-items:center;font-size:22px;box-shadow:var(--shadow)}
h1{font-size:1.35rem;margin:0;font-weight:750;letter-spacing:.2px}
.sub{color:var(--muted);font-size:.85rem;margin-top:2px}
.nav{display:flex;gap:8px;flex-wrap:wrap}
.btn{appearance:none;border:0;border-radius:12px;padding:10px 16px;font-weight:650;cursor:pointer;
  background:linear-gradient(180deg,var(--brand2),var(--brand));color:#1f2937;box-shadow:0 2px 0 #d97706;
  font-size:.95rem;display:inline-flex;align-items:center;gap:6px}
.btn:active{transform:translateY(1px)}
.btn.ghost{background:#fff;border:1px solid var(--line);box-shadow:none;color:var(--ink)}
.btn.blue{background:linear-gradient(180deg,#60a5fa,#2563eb);color:#fff;box-shadow:0 2px 0 #1d4ed8}
.btn.green{background:linear-gradient(180deg,#34d399,#059669);color:#fff;box-shadow:0 2px 0 #047857}
.btn.danger{background:linear-gradient(180deg,#fca5a5,#ef4444);color:#fff;box-shadow:0 2px 0 #b91c1c}
.btn:disabled{opacity:.55;cursor:not-allowed}
.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:16px 18px;box-shadow:var(--shadow)}
.card h2{margin:0 0 12px;font-size:1.05rem}
.card h3{margin:0 0 8px;font-size:.95rem;color:var(--muted);font-weight:650}
.span-3{grid-column:span 3}.span-4{grid-column:span 4}.span-6{grid-column:span 6}.span-8{grid-column:span 8}.span-12{grid-column:span 12}
@media(max-width:800px){.span-3,.span-4,.span-6,.span-8{grid-column:span 12}}
.stat .label{font-size:.8rem;color:var(--muted);font-weight:600}
.stat .value{font-size:2rem;font-weight:800;line-height:1.15;margin-top:6px;letter-spacing:-.5px}
.stat .hint{font-size:.8rem;color:var(--muted);margin-top:6px}
.pill{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:999px;font-size:.78rem;font-weight:700;background:#f3f4f6}
.pill.ok{background:#d1fae5;color:#065f46}.pill.warn{background:#ffedd5;color:#9a3412}.pill.bad{background:#fee2e2;color:#991b1b}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:640px){.form-grid{grid-template-columns:1fr}}
label{display:block;font-size:.82rem;color:var(--muted);font-weight:650;margin-bottom:6px}
input,textarea,select{width:100%;padding:11px 12px;border:1px solid var(--line);border-radius:12px;font-size:1rem;background:#fff;color:var(--ink)}
input:focus,textarea:focus,select:focus{outline:2px solid #fcd34d;border-color:#f59e0b}
.row-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
.muted{color:var(--muted);font-size:.85rem}
.ok{color:var(--ok)}.err{color:var(--bad)}
.toast{min-height:1.2em;margin-top:10px;font-weight:650}
.table{width:100%;border-collapse:collapse;font-size:.9rem}
.table th,.table td{padding:10px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
.table th{font-size:.78rem;color:var(--muted);font-weight:700}
.bank-list{display:flex;flex-direction:column;gap:8px}
.bank-item{display:flex;justify-content:space-between;gap:10px;align-items:center;padding:10px 12px;border:1px solid var(--line);border-radius:12px;background:#fafafa}
.bank-item strong{font-size:.95rem}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.tab{padding:8px 12px;border-radius:999px;border:1px solid var(--line);background:#fff;cursor:pointer;font-weight:650;font-size:.85rem}
.tab.active{background:#fff7ed;border-color:#fdba74;color:#9a3412}
.bar{height:8px;background:#f3f4f6;border-radius:999px;overflow:hidden;margin-top:10px}
.bar > i{display:block;height:100%;background:linear-gradient(90deg,#fbbf24,#f97316);border-radius:999px}
.login-box{max-width:420px;margin:48px auto}
.footer{margin-top:22px;color:var(--muted);font-size:.8rem;text-align:center}
"""

STATUS_HTML = f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"/>
<meta name="theme-color" content="#f59e0b"/>
<title>StudyOnPC · 状态</title>
<style>{_CSS}</style>
</head><body>
<div class="wrap">
  <div class="top">
    <div class="brand">
      <div class="logo">📺</div>
      <div>
        <h1>StudyOnPC 先学再看</h1>
        <div class="sub">局域网状态 · 每 4 秒自动刷新</div>
      </div>
    </div>
    <div class="nav">
      <a class="btn ghost" href="/">刷新</a>
      <a class="btn" href="/admin">家长管理</a>
    </div>
  </div>

  <div class="grid" id="dash">
    <div class="card span-4 stat"><div class="label">可用余额</div><div class="value" id="bal">—</div><div class="hint">分钟 · 看 YouTube 会消耗</div></div>
    <div class="card span-4 stat"><div class="label">今日已看</div><div class="value" id="used">—</div><div class="hint" id="usedHint">—</div><div class="bar"><i id="usedBar" style="width:0%"></i></div></div>
    <div class="card span-4 stat"><div class="label">今日还可看</div><div class="value" id="remain">—</div><div class="hint" id="statusPills"></div></div>
    <div class="card span-12">
      <h2>运行概况</h2>
      <div class="muted" id="meta">加载中…</div>
    </div>
  </div>
  <div class="footer">仅本机 / 同一 WiFi 可访问 · PIN 请家长保管</div>
</div>
<script>
async function load(){{
  try{{
    const r=await fetch('/api/status'); const j=await r.json();
    const bal=Number(j.balance_minutes||0).toFixed(1);
    const used=Number(j.daily_used_minutes||0).toFixed(1);
    const max=Number(j.daily_max_watch_minutes||60);
    const rem=Number(j.daily_remaining_minutes||0).toFixed(1);
    document.getElementById('bal').textContent=bal;
    document.getElementById('used').textContent=used;
    document.getElementById('remain').textContent=rem;
    document.getElementById('usedHint').textContent=`上限 ${{max}} 分钟 · ${{j.daily_date||''}}`;
    const pct=Math.max(0,Math.min(100, max? (Number(used)/max*100):0));
    document.getElementById('usedBar').style.width=pct+'%';
    const pills=[];
    pills.push(`<span class="pill ${{j.needs_quiz?'warn':'ok'}}">${{j.needs_quiz?'需要答题':'可观看'}}</span>`);
    pills.push(`<span class="pill ${{j.quiz_active||j.in_quiz?'warn':'ok'}}">${{j.quiz_active||j.in_quiz?'答题中':'空闲'}}</span>`);
    pills.push(`<span class="pill ${{j.running?'ok':'bad'}}">${{j.running?'守护运行中':'未运行'}}</span>`);
    document.getElementById('statusPills').innerHTML=pills.join(' ');
    document.getElementById('meta').innerHTML =
      `补题 pending=<b>${{j.pending_extra||0}}</b> · 连错 streak=<b>${{j.wrong_streak||0}}</b> · 题组正确率门槛见管理页<br/>
       运行起始：${{j.running_since||'—'}}`;
  }}catch(e){{
    document.getElementById('meta').textContent='无法连接状态接口';
  }}
}}
load(); setInterval(load,4000);
</script>
</body></html>
"""

ADMIN_HTML = f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"/>
<meta name="theme-color" content="#f59e0b"/>
<title>StudyOnPC · 家长管理</title>
<style>{_CSS}</style>
</head><body>
<div class="wrap">
  <div class="top">
    <div class="brand">
      <div class="logo">🔐</div>
      <div>
        <h1>家长管理面板</h1>
        <div class="sub">规则 · 题库 · 强制出题 · 答题记录</div>
      </div>
    </div>
    <div class="nav">
      <a class="btn ghost" href="/">← 状态页</a>
    </div>
  </div>

  <div class="card login-box" id="login">
    <h2>登录</h2>
    <p class="muted">管理密码默认与家长 PIN 相同，装好请立刻修改。</p>
    <label>管理密码</label>
    <input id="pw" type="password" placeholder="输入管理密码" autocomplete="current-password"/>
    <div class="row-actions">
      <button class="btn" onclick="doLogin()">进入管理</button>
    </div>
    <div id="loginMsg" class="toast err"></div>
  </div>

  <div id="panel" style="display:none">
    <div class="grid" style="margin-bottom:14px" id="dashCards"></div>

    <div class="tabs">
      <button class="tab active" data-tab="rules" onclick="showTab('rules')">规则设置</button>
      <button class="tab" data-tab="banks" onclick="showTab('banks')">题库管理</button>
      <button class="tab" data-tab="ops" onclick="showTab('ops')">快捷操作</button>
      <button class="tab" data-tab="logs" onclick="showTab('logs')">答题记录</button>
    </div>

    <div class="card tabpane" id="tab-rules">
      <h2>规则</h2>
      <div class="form-grid" id="rules"></div>
      <div class="row-actions">
        <button class="btn green" onclick="saveRules()">保存规则</button>
      </div>
      <div id="msg-rules" class="toast"></div>
    </div>

    <div class="card tabpane" id="tab-banks" style="display:none">
      <h2>题库管理</h2>
      <p class="muted" id="bankMeta">加载中…</p>
      <div class="bank-list" id="banks" style="margin-bottom:12px"></div>
      <div class="form-grid" style="margin-bottom:12px">
        <div>
          <label>科目筛选</label>
          <select id="qSubject" onchange="loadQuestions(1)"><option value="">全部科目</option></select>
        </div>
        <div>
          <label>搜索题干 / 选项 / 单元 / ID</label>
          <input id="qSearch" placeholder="例如：加法、猴子、book、21" onkeydown="if(event.key==='Enter'){{event.preventDefault();loadQuestions(1);}}"/>
        </div>
      </div>
      <div class="row-actions">
        <button class="btn" onclick="loadQuestions(1)">查询</button>
        <button class="btn green" onclick="openEditor()">＋ 新增题目</button>
        <button class="btn ghost" onclick="exportBank()">导出 JSON</button>
        <button class="btn blue" onclick="document.getElementById('importBox').style.display='block'">导入到当前题库</button>
      </div>
      <div style="overflow:auto;margin-top:12px">
        <table class="table" id="qTable">
          <thead><tr><th>ID</th><th>科目</th><th>单元</th><th>题干</th><th>选项</th><th>图</th><th>操作</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
      <div class="row-actions" id="qPager"></div>
      <div id="importBox" style="display:none;margin-top:16px;padding-top:12px;border-top:1px solid var(--line)">
        <h3>导入 JSON 到当前题库</h3>
        <p class="muted">支持题目数组或含 questions 的对象。可合并或覆盖当前题库。</p>
        <label>JSON</label>
        <textarea id="import" rows="7" placeholder='[{{"q":"1+1=?","a":"2","choices":["1","2","3"],"type":"single","subject":"数学"}}]'></textarea>
        <div class="row-actions">
          <button class="btn blue" onclick="importActive(false)">覆盖导入</button>
          <button class="btn" onclick="importActive(true)">合并导入</button>
          <button class="btn ghost" onclick="doImport()">另存为新文件</button>
        </div>
        <label style="margin-top:8px">另存文件名</label>
        <input id="importName" value="imported.json"/>
      </div>
      <div id="editorBox" style="display:none;margin-top:16px;padding-top:12px;border-top:1px solid var(--line)">
        <h3 id="editorTitle">编辑题目</h3>
        <div class="form-grid">
          <div><label>ID（留空自动）</label><input id="e_id"/></div>
          <div><label>类型</label>
            <select id="e_type"><option value="single">单选</option><option value="multiple">多选</option><option value="boolean">判断</option><option value="text">填空</option></select>
          </div>
          <div><label>科目</label><input id="e_subject" placeholder="语文 / 数学 / 英语"/></div>
          <div><label>单元</label><input id="e_unit"/></div>
          <div style="grid-column:1/-1"><label>题干</label><input id="e_q"/></div>
          <div style="grid-column:1/-1"><label>选项（每行一个）</label><textarea id="e_choices" rows="4"></textarea></div>
          <div><label>正确答案</label><input id="e_a" placeholder="与某一选项完全一致"/></div>
          <div><label>图片路径</label><input id="e_image" placeholder="assets/images/xxx.png"/></div>
        </div>
        <div class="row-actions">
          <button class="btn green" onclick="saveQuestion()">保存题目</button>
          <button class="btn ghost" onclick="closeEditor()">取消</button>
        </div>
      </div>
      <div id="msg-banks" class="toast"></div>
    </div>

    <div class="card tabpane" id="tab-ops" style="display:none">
      <h2>快捷操作</h2>
      <p class="muted">强制出题会立刻全屏弹出一组题（会静音并最小化 YouTube）。</p>
      <div class="row-actions">
        <button class="btn" onclick="forceQuiz()">⚡ 立即出题一组</button>
        <button class="btn danger" onclick="doQuit()">退出守护（需 PIN）</button>
      </div>
      <div id="msg-ops" class="toast"></div>
    </div>

    <div class="card tabpane" id="tab-logs" style="display:none">
      <h2>最近答题</h2>
      <p class="muted">来自本机 answers.log（最多显示最近 80 条）</p>
      <div style="overflow:auto">
        <table class="table" id="logTable">
          <thead><tr><th>时间</th><th>科目</th><th>结果</th><th>选择</th><th>答案</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
      <div class="row-actions">
        <button class="btn ghost" onclick="loadLogs()">刷新记录</button>
      </div>
      <div id="msg-logs" class="toast"></div>
    </div>
  </div>
  <div class="footer">StudyOnPC · 家庭本地使用 · 勿把管理页暴露到公网</div>
</div>
<script>
let token='';
const fieldGroups=[
  {{title:'解锁与题组', items:[
    ['unlock_minutes_per_set','每组解锁分钟'],
    ['questions_per_set','每组题数'],
    ['pass_ratio','及格比例（如 0.67）'],
    ['answer_delay_seconds','看题等待秒数'],
  ]}},
  {{title:'每日与加练', items:[
    ['daily_max_watch_minutes','每日上限分钟'],
    ['wrong_streak_to_extra','连错几次加补题'],
    ['extra_questions','每次补题数'],
    ['poll_ms','轮询毫秒'],
  ]}},
  {{title:'安全与题库', items:[
    ['parent_pin','家长 PIN'],
    ['admin_password','管理密码'],
    ['bank_file','题库路径'],
  ]}},
];
function headers(){{return token?{{'Authorization':'Bearer '+token,'Content-Type':'application/json'}}:{{'Content-Type':'application/json'}};}}
function showTab(name){{
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active', t.dataset.tab===name));
  document.querySelectorAll('.tabpane').forEach(p=>p.style.display='none');
  document.getElementById('tab-'+name).style.display='block';
  if(name==='logs') loadLogs();
  if(name==='banks') loadQuestions(qPage||1);
}}
async function doLogin(){{
  const r=await fetch('/api/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{password:document.getElementById('pw').value}})}});
  const j=await r.json();
  if(!r.ok){{document.getElementById('loginMsg').textContent=j.error||'失败';return;}}
  token=j.token; localStorage.setItem('studyonpc_token', token);
  document.getElementById('login').style.display='none';
  document.getElementById('panel').style.display='block';
  loadAdmin(); loadDash(); loadLogs(); loadQuestions(1);
  setInterval(loadDash, 5000);
}}
async function loadDash(){{
  try{{
    const r=await fetch('/api/status'); const j=await r.json();
    const unlocks=Number(j.today_unlock_minutes||0).toFixed(1);
    document.getElementById('dashCards').innerHTML=`
      <div class="card span-3 stat"><div class="label">余额</div><div class="value">${{Number(j.balance_minutes||0).toFixed(1)}}</div><div class="hint">分钟</div></div>
      <div class="card span-3 stat"><div class="label">今日已看</div><div class="value">${{Number(j.daily_used_minutes||0).toFixed(1)}}</div><div class="hint">/ ${{j.daily_max_watch_minutes||60}}</div></div>
      <div class="card span-3 stat"><div class="label">今日解锁累计</div><div class="value">${{unlocks}}</div><div class="hint">答题获得</div></div>
      <div class="card span-3 stat"><div class="label">状态</div><div class="value" style="font-size:1.2rem;margin-top:12px">${{j.needs_quiz?'需答题':'可观看'}}</div><div class="hint">${{j.quiz_active||j.in_quiz?'答题进行中':'空闲'}}</div></div>`;
  }}catch(e){{}}
}}
async function loadAdmin(){{
  const r=await fetch('/api/admin/config',{{headers:headers()}});
  if(r.status===401){{localStorage.removeItem('studyonpc_token'); location.reload();return;}}
  const j=await r.json();
  let html='';
  for(const g of fieldGroups){{
    html+=`<div style="grid-column:1/-1"><h3>${{g.title}}</h3></div>`;
    for(const [k,label] of g.items){{
      html+=`<div><label>${{label}}</label><input data-k="${{k}}" value="${{j[k]??''}}"/></div>`;
    }}
  }}
  document.getElementById('rules').innerHTML=html;
  const b=await fetch('/api/admin/banks',{{headers:headers()}});
  const bj=await b.json();
  const banks=bj.banks||[];
  document.getElementById('banks').innerHTML = banks.length? banks.map(x=>`
    <div class="bank-item"><div><strong>${{x.name}}</strong><div class="muted">${{x.path}}${{x.count!=null?(' · '+x.count+' 题'):''}}</div></div>
    <span class="pill">${{ (j.bank_file||'').replace(/\\\\/g,'/')===x.path || (j.bank_file||'').endsWith(x.name) ? '当前' : '可选' }}</span>
  </div>`).join('') : '<div class="muted">暂无题库文件</div>';
}}
async function saveRules(){{
  const body={{}};
  document.querySelectorAll('#rules input').forEach(el=>{{body[el.dataset.k]=el.value;}});
  for(const k of ['unlock_minutes_per_set','questions_per_set','pass_ratio','daily_max_watch_minutes','wrong_streak_to_extra','extra_questions','poll_ms','answer_delay_seconds']){{
    if(body[k]!==undefined && body[k]!=='') body[k]=Number(body[k]);
  }}
  const r=await fetch('/api/admin/config',{{method:'POST',headers:headers(),body:JSON.stringify(body)}});
  const j=await r.json();
  document.getElementById('msg-rules').innerHTML=r.ok?'<span class="ok">已保存</span>':'<span class="err">'+(j.error||'失败')+'</span>';
  if(r.ok) loadDash();
}}
async function doImport(){{
  const r=await fetch('/api/admin/import',{{method:'POST',headers:headers(),
    body:JSON.stringify({{filename:document.getElementById('importName').value,json:document.getElementById('import').value}})}});
  const j=await r.json();
  document.getElementById('msg-banks').innerHTML=r.ok?'<span class="ok">已导入 '+j.path+'</span>':'<span class="err">'+(j.error||'失败')+'</span>';
  if(r.ok) loadAdmin();
}}
async function forceQuiz(){{
  const r=await fetch('/api/admin/force_quiz',{{method:'POST',headers:headers(),body:'{{}}'}});
  const j=await r.json();
  document.getElementById('msg-ops').innerHTML=r.ok?'<span class="ok">已请求出题</span>':'<span class="err">'+(j.error||'失败')+'</span>';
}}
async function doQuit(){{
  const pin=prompt('输入家长 PIN 退出守护');
  if(pin===null) return;
  const r=await fetch('/api/admin/quit',{{method:'POST',headers:headers(),body:JSON.stringify({{pin}})}});
  const j=await r.json();
  document.getElementById('msg-ops').innerHTML=r.ok?'<span class="ok">正在退出…</span>':'<span class="err">'+(j.error||'失败')+'</span>';
}}
async function loadLogs(){{
  try{{
    const r=await fetch('/api/admin/answers',{{headers:headers()}});
    if(r.status===401) return;
    const j=await r.json();
    const rows=j.lines||[];
    const tb=document.querySelector('#logTable tbody');
    if(!rows.length){{ tb.innerHTML='<tr><td colspan="5" class="muted">暂无记录</td></tr>'; return; }}
    tb.innerHTML=rows.map(x=>`<tr>
      <td>${{x.time||''}}</td><td>${{x.subject||''}}</td>
      <td><span class="pill ${{x.ok?'ok':'bad'}}">${{x.ok?'答对':'答错'}}</span></td>
      <td>${{esc(x.chose||'')}}</td><td>${{esc(x.expect||'')}}</td>
    </tr>`).join('');
  }}catch(e){{ document.getElementById('msg-logs').textContent='读取失败'; }}
}}
function esc(s){{return String(s).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[c]);}}

let qPage=1;
async function loadQuestions(page){{
  qPage=page||1;
  const subject=document.getElementById('qSubject').value;
  const search=document.getElementById('qSearch').value.trim();
  const u=new URL('/api/admin/questions', location.origin);
  u.searchParams.set('page', String(qPage));
  u.searchParams.set('page_size','20');
  // Always send filters so parents can see query string / debug
  u.searchParams.set('subject', subject || '');
  u.searchParams.set('q', search || '');
  let r;
  try {{
    r=await fetch(u.toString(), {{headers:headers()}});
  }} catch(err) {{
    document.getElementById('bankMeta').textContent='查询失败：网络错误';
    document.getElementById('msg-banks').innerHTML='<span class="err">查询失败：'+esc(String(err))+'</span>';
    return;
  }}
  if(r.status===401){{location.reload();return;}}
  let j={{}};
  try {{ j=await r.json(); }} catch(err) {{
    document.getElementById('bankMeta').textContent='查询失败：无效响应';
    return;
  }}
  if(!r.ok){{
    document.getElementById('bankMeta').textContent='查询失败';
    document.getElementById('msg-banks').innerHTML='<span class="err">'+(j.error||('HTTP '+r.status))+'</span>';
    return;
  }}
  const filterBits=[];
  if(subject) filterBits.push('科目='+subject);
  if(search) filterBits.push('关键词='+search);
  document.getElementById('bankMeta').textContent =
    `当前题库 ${{j.bank_file||''}} · 筛选后 ${{j.total||0}} 题 · 第 ${{j.page}}/${{j.pages}} 页` +
    (filterBits.length?(' · '+filterBits.join(' · ')):'');
  const sel=document.getElementById('qSubject');
  const cur=subject;
  sel.innerHTML='<option value="">全部科目</option>'+((j.subjects||[]).map(s=>`<option value="${{esc(s)}}">${{esc(s)}}</option>`).join(''));
  sel.value=cur;
  const tb=document.querySelector('#qTable tbody');
  const items=j.items||[];
  if(!items.length){{
    tb.innerHTML='<tr><td colspan="7" class="muted">没有匹配的题目'+(search||subject?'（请清空筛选再试）':'')+'</td></tr>';
  }} else {{
    tb.innerHTML=items.map(it=>`<tr>
      <td>${{it.id}}</td><td>${{esc(it.subject||'')}}</td><td>${{esc(it.unit||'')}}</td>
      <td>${{esc(it.q_preview||it.q||'')}}</td>
      <td>${{it.choices_count||0}}</td>
      <td>${{it.has_image?'🖼':'—'}}</td>
      <td>
        <button class="btn ghost" style="padding:6px 10px" onclick='editQuestion(${{JSON.stringify(String(it.id))}})'>编辑</button>
        <button class="btn danger" style="padding:6px 10px" onclick='removeQuestion(${{JSON.stringify(String(it.id))}})'>删</button>
      </td>
    </tr>`).join('');
  }}
  const pager=document.getElementById('qPager');
  const pages=j.pages||1;
  pager.innerHTML=`
    <button class="btn ghost" ${{j.page<=1?'disabled':''}} onclick="loadQuestions(${{Math.max(1,(j.page||1)-1)}})">上一页</button>
    <span class="muted">第 ${{j.page}} / ${{pages}} 页（共 ${{j.total}} 题）</span>
    <button class="btn ghost" ${{j.page>=pages?'disabled':''}} onclick="loadQuestions(${{(j.page||1)+1}})">下一页</button>
    <button class="btn ghost" onclick="document.getElementById('qSearch').value='';document.getElementById('qSubject').value='';loadQuestions(1);">清空筛选</button>`;
}}
function openEditor(item){{
  document.getElementById('editorBox').style.display='block';
  document.getElementById('editorTitle').textContent=item?'编辑题目 #'+item.id:'新增题目';
  document.getElementById('e_id').value=item&&item.id!=null?item.id:'';
  document.getElementById('e_type').value=(item&&item.type)||'single';
  document.getElementById('e_subject').value=(item&&item.subject)||'';
  document.getElementById('e_unit').value=(item&&item.unit)||'';
  document.getElementById('e_q').value=(item&&item.q)||'';
  document.getElementById('e_a').value=(item&&item.a!=null)?(Array.isArray(item.a)?item.a.join('|'):item.a):'';
  document.getElementById('e_image').value=(item&&item.image)||'';
  document.getElementById('e_choices').value=((item&&item.choices)||[]).join('\\n');
  document.getElementById('editorBox').scrollIntoView({{behavior:'smooth'}});
}}
function closeEditor(){{ document.getElementById('editorBox').style.display='none'; }}
async function editQuestion(id){{
  try{{
    const r=await fetch('/api/admin/questions/'+encodeURIComponent(id),{{headers:headers()}});
    const j=await r.json();
    if(!r.ok){{ document.getElementById('msg-banks').innerHTML='<span class="err">'+(j.error||'读取失败')+'</span>'; return; }}
    if(!j.item){{ document.getElementById('msg-banks').innerHTML='<span class="err">题目数据为空</span>'; return; }}
    openEditor(j.item);
  }}catch(e){{
    document.getElementById('msg-banks').innerHTML='<span class="err">读取失败：'+(e&&e.message?e.message:e)+'</span>';
  }}
}}
async function saveQuestion(){{
  const idRaw=document.getElementById('e_id').value.trim();
  const choices=document.getElementById('e_choices').value.split(/\\n/).map(s=>s.trim()).filter(Boolean);
  const body={{
    type:document.getElementById('e_type').value,
    subject:document.getElementById('e_subject').value.trim(),
    unit:document.getElementById('e_unit').value.trim(),
    q:document.getElementById('e_q').value.trim(),
    a:document.getElementById('e_a').value.trim(),
    choices:choices,
    image:document.getElementById('e_image').value.trim()||undefined,
  }};
  if(idRaw!=='') body.id=Number(idRaw)||idRaw;
  const url=idRaw!==''?('/api/admin/questions/'+encodeURIComponent(idRaw)):'/api/admin/questions';
  const r=await fetch(url,{{method:'POST',headers:headers(),body:JSON.stringify(body)}});
  const j=await r.json();
  document.getElementById('msg-banks').innerHTML=r.ok?'<span class="ok">已保存 #'+(j.item&&j.item.id)+'</span>':'<span class="err">'+(j.error||'失败')+'</span>';
  if(r.ok){{ closeEditor(); loadQuestions(qPage); loadAdmin(); }}
}}
async function removeQuestion(id){{
  if(!confirm('确定删除题目 #'+id+'？')) return;
  const r=await fetch('/api/admin/questions/'+encodeURIComponent(id),{{method:'DELETE',headers:headers()}});
  const j=await r.json();
  document.getElementById('msg-banks').innerHTML=r.ok?'<span class="ok">已删除</span>':'<span class="err">'+(j.error||'失败')+'</span>';
  if(r.ok){{ loadQuestions(qPage); loadAdmin(); }}
}}
async function exportBank(){{
  const r=await fetch('/api/admin/export',{{headers:headers()}});
  if(!r.ok){{ const j=await r.json(); document.getElementById('msg-banks').innerHTML='<span class="err">'+(j.error||'导出失败')+'</span>'; return; }}
  const blob=await r.blob();
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  a.download='bank-export.json';
  a.click();
}}
async function importActive(merge){{
  const r=await fetch('/api/admin/import_active',{{method:'POST',headers:headers(),
    body:JSON.stringify({{json:document.getElementById('import').value, merge:!!merge}})}});
  const j=await r.json();
  document.getElementById('msg-banks').innerHTML=r.ok?'<span class="ok">已导入 '+j.count+' 题 → '+j.path+'</span>':'<span class="err">'+(j.error||'失败')+'</span>';
  if(r.ok){{ loadQuestions(1); loadAdmin(); }}
}}

// auto resume session
(async function(){{
  const t=localStorage.getItem('studyonpc_token');
  if(!t) return;
  token=t;
  const r=await fetch('/api/admin/config',{{headers:headers()}});
  if(r.ok){{
    document.getElementById('login').style.display='none';
    document.getElementById('panel').style.display='block';
    loadAdmin(); loadDash(); loadQuestions(1); setInterval(loadDash,5000);
  }} else {{
    localStorage.removeItem('studyonpc_token');
  }}
}})();
document.getElementById('pw').addEventListener('keydown',e=>{{ if(e.key==='Enter') doLogin(); }});
document.getElementById('qSearch').addEventListener('keydown',e=>{{ if(e.key==='Enter'){{ e.preventDefault(); loadQuestions(1); }} }});
</script>
</body></html>
"""



class AdminContext:
    def __init__(
        self,
        get_status,
        get_config,
        save_config,
        force_quiz,
        request_quit,
        list_banks,
        import_bank,
        password: str,
        get_answers=None,
        list_questions=None,
        get_question=None,
        upsert_question=None,
        delete_question=None,
        export_bank=None,
        import_active=None,
    ):
        self.get_status = get_status
        self.get_config = get_config
        self.save_config = save_config
        self.force_quiz = force_quiz
        self.request_quit = request_quit
        self.list_banks = list_banks
        self.import_bank = import_bank
        self.get_answers = get_answers or (lambda: [])
        self.list_questions = list_questions or (
            lambda **kw: {"items": [], "total": 0, "page": 1, "pages": 1, "subjects": [], "page_size": 20}
        )
        self.get_question = get_question or (lambda _id: None)
        self.upsert_question = upsert_question or (lambda data: data)
        self.delete_question = delete_question or (lambda _id: False)
        self.export_bank = export_bank or (lambda: "{}\n")
        self.import_active = import_active
        self.password = password
        self.tokens: dict[str, float] = {}
        self.lock = threading.Lock()

    def issue_token(self) -> str:
        tok = secrets.token_urlsafe(24)
        with self.lock:
            self.tokens[tok] = time.time() + 86400
        return tok

    def valid_token(self, tok: str | None) -> bool:
        if not tok:
            return False
        with self.lock:
            exp = self.tokens.get(tok)
            if not exp:
                return False
            if exp < time.time():
                self.tokens.pop(tok, None)
                return False
            return True


def _make_handler(ctx: AdminContext):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            log.debug("admin %s - %s", self.address_string(), fmt % args)

        def _json(self, code: int, obj: dict):
            raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _html(self, code: int, html: str):
            raw = html.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _body(self) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if n else b""

        def _auth(self) -> bool:
            auth = self.headers.get("Authorization") or ""
            tok = ""
            if auth.lower().startswith("bearer "):
                tok = auth[7:].strip()
            return ctx.valid_token(tok)

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)
            if path in ("/", "/status"):
                return self._html(200, STATUS_HTML)
            if path == "/admin":
                return self._html(200, ADMIN_HTML)
            if path == "/api/status":
                return self._json(200, ctx.get_status())
            if path == "/api/admin/config":
                if not self._auth():
                    return self._json(401, {"error": "未登录"})
                return self._json(200, ctx.get_config())
            if path == "/api/admin/banks":
                if not self._auth():
                    return self._json(401, {"error": "未登录"})
                return self._json(200, {"banks": ctx.list_banks()})
            if path == "/api/admin/answers":
                if not self._auth():
                    return self._json(401, {"error": "未登录"})
                return self._json(200, {"lines": ctx.get_answers()})
            if path in ("/api/admin/questions", "/api/questions"):
                if not self._auth():
                    return self._json(401, {"error": "未登录"})
                subject = (qs.get("subject") or [""])[0]
                search = (qs.get("q") or qs.get("search") or [""])[0]
                subject = (subject or "").strip() or None
                search = (search or "").strip() or None
                page = int((qs.get("page") or ["1"])[0] or 1)
                page_size = int((qs.get("page_size") or ["20"])[0] or 20)
                return self._json(
                    200,
                    ctx.list_questions(
                        subject=subject,
                        search=search,
                        page=page,
                        page_size=page_size,
                    ),
                )
            if path in ("/api/admin/export", "/api/questions/export"):
                if not self._auth():
                    return self._json(401, {"error": "未登录"})
                raw = ctx.export_bank().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header(
                    "Content-Disposition", 'attachment; filename="bank-export.json"'
                )
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            if path.startswith("/api/admin/questions/") or path.startswith("/api/questions/"):
                if not self._auth():
                    return self._json(401, {"error": "未登录"})
                qid = path.rstrip("/").split("/")[-1]
                item = ctx.get_question(qid)
                if not item:
                    return self._json(404, {"error": "题目不存在"})
                return self._json(200, {"item": item})
            return self._json(404, {"error": "not found"})

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                data = json.loads(self._body().decode("utf-8") or "{}")
            except Exception:
                return self._json(400, {"error": "无效 JSON"})
            if path == "/api/login":
                pw = str(data.get("password") or "")
                if pw != str(ctx.password):
                    return self._json(403, {"error": "密码错误"})
                return self._json(200, {"token": ctx.issue_token()})
            if not self._auth():
                return self._json(401, {"error": "未登录"})
            if path == "/api/admin/config":
                try:
                    ctx.save_config(data)
                    if "admin_password" in data:
                        ctx.password = str(data["admin_password"])
                    return self._json(200, {"ok": True})
                except Exception as e:
                    return self._json(400, {"error": str(e)})
            if path == "/api/admin/import":
                try:
                    p = ctx.import_bank(
                        str(data.get("json") or ""),
                        str(data.get("filename") or "imported.json"),
                    )
                    return self._json(200, {"ok": True, "path": p})
                except Exception as e:
                    return self._json(400, {"error": str(e)})
            if path in ("/api/admin/import_active", "/api/questions/import"):
                try:
                    if ctx.import_active is None:
                        return self._json(400, {"error": "未启用活动题库导入"})
                    result = ctx.import_active(
                        str(data.get("json") or ""), merge=bool(data.get("merge"))
                    )
                    return self._json(200, {"ok": True, **result})
                except Exception as e:
                    return self._json(400, {"error": str(e)})
            if path == "/api/admin/force_quiz":
                ctx.force_quiz()
                return self._json(200, {"ok": True})
            if path == "/api/admin/quit":
                ok, msg = ctx.request_quit(str(data.get("pin") or ""))
                return self._json(200 if ok else 403, {"ok": ok, "error": None if ok else msg})
            if path in ("/api/admin/questions", "/api/questions"):
                try:
                    item = ctx.upsert_question(data)
                    return self._json(200, {"ok": True, "item": item})
                except Exception as e:
                    return self._json(400, {"error": str(e)})
            if path.startswith("/api/admin/questions/") or path.startswith("/api/questions/"):
                qid = path.rstrip("/").split("/")[-1]
                try:
                    payload = dict(data)
                    payload["id"] = int(qid) if str(qid).isdigit() else qid
                    item = ctx.upsert_question(payload)
                    return self._json(200, {"ok": True, "item": item})
                except Exception as e:
                    return self._json(400, {"error": str(e)})
            return self._json(404, {"error": "not found"})

        def do_DELETE(self):
            path = urlparse(self.path).path
            if not self._auth():
                return self._json(401, {"error": "未登录"})
            if path.startswith("/api/admin/questions/") or path.startswith("/api/questions/"):
                qid = path.rstrip("/").split("/")[-1]
                ok = ctx.delete_question(qid)
                return self._json(
                    200 if ok else 404,
                    {"ok": ok, "error": None if ok else "题目不存在"},
                )
            return self._json(404, {"error": "not found"})

        def do_PUT(self):
            return self.do_POST()

    return Handler


def start_admin_server(
    ctx: AdminContext,
    host: str = "0.0.0.0",
    port: int = 8099,
) -> ThreadingHTTPServer:
    handler = _make_handler(ctx)
    httpd = ThreadingHTTPServer((host, port), handler)
    t = threading.Thread(target=httpd.serve_forever, name="studyonpc-admin", daemon=True)
    t.start()
    log.info("admin server on http://%s:%s/", host, port)
    return httpd
