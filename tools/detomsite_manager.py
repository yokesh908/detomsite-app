#!/usr/bin/env python3
"""
DETOMSITE MANAGER — local control panel for the DETOMSITE backend.

Standalone tool (stdlib only). Start it, open http://127.0.0.1:8765 and you can:

  * Browse every table (shops, products, orders, payments, users, SMS logs).
  * Create / edit shops, products, orders, payment settings, users.
  * See EVERY API URL of the backend (auto-read from /openapi.json) and call
    any endpoint with a payload from the browser.
  * Simulate the shopkeeper's bank SMS (UTR / YES / NO) to test confirmation.
  * Export any response as JSON / download it.

Usage
-----
    python tools/detomsite_manager.py                # start on http://127.0.0.1:8765
    python tools/detomsite_manager.py 9000           # custom port

It can also be driven from the terminal for quick data calls:

    python tools/detomsite_manager.py --base https://detomsite.onrender.com/api/v1 \
        --login admin you@example.com 'yourpassword'
    python tools/detomsite_manager.py --call "GET /local/shops"
    python tools/detomsite_manager.py --call "PATCH /local/payment-settings" '{"upi_id":"detomsite@ybl"}'

The login token is cached in ~/.detomsite-manager-token.json so later --call usage
reuses it. No third-party packages are required.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_BASE = "https://detomsite.onrender.com/api/v1"
TOKEN_FILE = os.path.expanduser("~/.detomsite-manager-token.json")

MANAGER_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>DETOMSITE Manager</title>
<style>
  :root{--bg:#0c0f14;--panel:#141a22;--panel2:#1b232e;--line:#26303d;--txt:#e7edf3;--mut:#8aa0b5;
        --acc:#38bdf8;--ok:#34d399;--warn:#fbbf24;--bad:#f87171;}
  *{box-sizing:border-box}
  body{margin:0;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:var(--bg);color:var(--txt);font-size:13px}
  header{display:flex;align-items:center;gap:10px;padding:8px 14px;background:var(--panel);border-bottom:1px solid var(--line);flex-wrap:wrap}
  header .logo{font-weight:700;color:var(--acc)}
  input,select,button,textarea{background:var(--panel2);border:1px solid var(--line);color:var(--txt);
    border-radius:6px;padding:6px 8px;font:inherit;font-size:12px}
  button{cursor:pointer} button.acc{background:#0ea5e9;color:#06121f;font-weight:700;border-color:#0ea5e9}
  button:disabled{opacity:.4;cursor:not-allowed}
  a{color:var(--acc)}
  main{display:flex;min-height:calc(100vh - 46px)}
  nav{width:190px;background:var(--panel);border-right:1px solid var(--line);padding:10px;flex-shrink:0}
  nav button{display:block;width:100%;text-align:left;margin-bottom:4px;border:none;background:transparent;color:var(--mut)}
  nav button.on{background:var(--panel2);color:var(--acc);font-weight:700}
  section{flex:1;padding:14px;overflow:auto}
  .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px;margin-bottom:10px}
  .card h3{margin:0 0 8px;font-size:13px;color:var(--acc)}
  table{border-collapse:collapse;width:100%;font-size:12px}
  th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
  th{color:var(--mut);position:sticky;top:0;background:var(--panel)}
  pre{background:#0a0e13;border:1px solid var(--line);border-radius:6px;padding:8px;overflow:auto;white-space:pre-wrap;word-break:break-all;margin:0}
  .mut{color:var(--mut)} .ok{color:var(--ok)} .bad{color:var(--bad)} .warn{color:var(--warn)}
  .pill{display:inline-block;padding:1px 7px;border-radius:999px;border:1px solid var(--line);font-size:11px;margin:1px}
  .pill.m{background:#0ea5e9;color:#06121f;border-color:#0ea5e9;font-weight:700}
  .pill.p{background:#f59e0b;color:#1a1202;border-color:#f59e0b;font-weight:700}
  .hide{display:none}
  .toolbar{display:flex;gap:6px;flex-wrap:wrap;margin:4px 0 8px}
  textarea{width:100%;min-height:120px;font-family:ui-monospace,monospace}
  .kv{display:grid;grid-template-columns:150px 1fr;gap:6px;margin:4px 0}
  .kv label{color:var(--mut);padding-top:6px}
  code.cmd{color:var(--acc)}
  #log{border-top:1px solid var(--line);padding:8px 14px;max-height:150px;overflow:auto;font-size:11px;color:var(--mut)}
  .endpoint{cursor:pointer;padding:4px 6px;border:1px solid var(--line);border-radius:6px;margin:2px 0;display:flex;gap:8px;align-items:center}
  .endpoint:hover{background:var(--panel2)}
  .stat{font-size:11px;color:var(--mut)}
  @media(max-width:800px){main{flex-direction:column}nav{width:100%}}
</style>
</head>
<body>
<header>
  <span class="logo">DETOMSITE MANAGER</span>
  <input id="base" size="34" value=""/>
  <button onclick="setBase()">Set base</button>
  <span id="baseok" class="stat"></span>
  <span style="flex:1"></span>
  <select id="lkind"><option value="admin">admin</option><option value="student">student</option><option value="shopkeeper">shopkeeper</option></select>
  <input id="lemail" placeholder="email"/>
  <input id="lpass" type="password" placeholder="password"/>
  <button class="acc" onclick="login()">Login</button>
  <span id="who" class="stat"></span>
  <button onclick="logout()" id="logoutbtn" class="hide">Logout</button>
</header>
<main>
  <nav>
    <button class="on" data-p="dashboard" onclick="go('dashboard')">Dashboard</button>
    <button data-p="endpoints" onclick="go('endpoints')">All URLs / OpenAPI</button>
    <button data-p="shops" onclick="go('shops')">Shops</button>
    <button data-p="products" onclick="go('products')">Products</button>
    <button data-p="orders" onclick="go('orders')">Orders</button>
    <button data-p="payments" onclick="go('payments')">Payments</button>
    <button data-p="paysettings" onclick="go('paysettings')">Payment Settings</button>
    <button data-p="sms" onclick="go('sms')">SMS / UTR</button>
    <button data-p="users" onclick="go('users')">Users</button>
    <button data-p="tickets" onclick="go('tickets')">Tickets / Feedback</button>
  </nav>
  <section id="view"></section>
</main>
<div id="log"></div>

<script>
let BASE='', TOKEN='', panel='dashboard';
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function log(m){const d=document.createElement('div');d.textContent=`[${new Date().toLocaleTimeString()}] ${m}`;$('#log').prepend(d);}
function call(method,path,body,tok=TOKEN){
  return fetch('/api/proxy',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({base:BASE,method,path,body:body??null,token:tok})}).then(r=>r.json());
}
async function refresh(){ try{
  const s=await (await fetch('/api/state')).json();
  BASE=$('#base').value=s.base||'';
  if(s.token){TOKEN=s.token;$('#who').textContent=(s.user?('as '+s.user):'logged in');$('#logoutbtn').classList.remove('hide');}
}catch(e){}}
async function setBase(){BASE=$('#base').value.trim().replace(/\/$/,'');
  const ok=await call('GET','/openapi.json','',null).then(r=>r.ok!==false);
  $('#baseok').innerHTML='';$('#baseok').textContent=ok?'OK: OpenAPI reachable + '+Object.keys($('#view')?'':'').length:'';
  $('#baseok').textContent=ok?'OpenAPI reachable':'unreachable';
  $('#baseok').className='stat '+(ok?'ok':'bad');
  if(ok) goto('dashboard');
}
async function login(){const r=await (await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({base:BASE,kind:$('#lkind').value,email:$('#lemail').value,password:$('#lpass').value})})).json();
  if(r.error){alert(r.error)}else{TOKEN=r.token;$('#who').textContent='as '+$('#lemail').value;$('#logoutbtn').classList.remove('hide');}}
function logout(){fetch('/api/login',{method:'DELETE'}).then(()=>{TOKEN='';$('#who').textContent='';$('#logoutbtn').classList.add('hide');});}
function go(p){panel=p;document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('on',b.dataset.p===p));render();}
async function render(){
  const v=$('#view');v.innerHTML='<p class="mut">loading…</p>';
  try{
    if(panel==='dashboard')await rDashboard(v);
    else if(panel==='endpoints')await rEndpoints(v);
    else if(panel==='shops')await rShops(v);
    else if(panel==='products')await rProducts(v);
    else if(panel==='orders')await rOrders(v);
    else if(panel==='payments')await rPayments(v);
    else if(panel==='paysettings')await rPaysettings(v);
    else if(panel==='sms')await rSms(v);
    else if(panel==='users')await rUsers(v);
    else if(panel==='tickets')await rTickets(v);
  }catch(e){v.innerHTML='<pre class="bad">'+esc(e.message||e)+'</pre>';}
}
/* ── helpers ─────────────────────────────────────────────── */
function cell(o){return '<pre class="mut" style="max-height:120px">'+esc(JSON.stringify(o,null,1))+'</pre>';}
function table(headers,rows){return '<table><thead><tr>'+headers.map(h=>'<th>'+esc(h)+'</th>').join('')+'</tr></thead><tbody>'+
  rows.map(r=>'<tr>'+r.slice(0,headers.length).map(c=>'<td>'+c+'</td>').join('')+'</tr>').join('')+'</tbody></table>';}
async function rDashboard(v){
  const calls=[['local/status'],['local/summary'],['local/shops'],[ 'local/payment-settings']];
  const outs=await Promise.all(calls.map(c=>call('GET','/'+c[0],null).catch(e=>({__e:String(e)}))));
  const p=(x,m)=>x&&!x.__e?'<div class="card"><h3>'+esc(m)+'</h3>'+cell(x)+'</div>':'';
  v.innerHTML='<div class="card"><h3>Backend</h3>'
    +'<div class="row"><span class="stat mut">Base: </span><code class="cmd">'+esc(BASE)+'</code></div>'
    +p(outs[0],'/local/status')+p(outs[2],'/local/shops ('+((outs[2]||[]).length)+')')+p(outs[1],'/local/summary')+p(outs[3],'Payment settings')+'</div>';
}
/* ── Shops ── */
async function rShops(v){
  const shops=await call('GET','/local/shops');
  const rows=(shops||[]).map(s=>[
    esc(s.id),esc(s.name),esc(s.category),esc(s.phone),esc(s.upi_id||''),esc(s.status),esc(s.approval_status),
    s.present?'<span class="ok">open</span>':'<span class="bad">offline</span>',
    '<button onclick="updateShop(\''+esc(String(s.id))+'\\')">Edit</button>'
  ]);
  v.innerHTML='<div class="card"><h3>Create shop</h3><div class="kv">'
    + 'Name<input id="sp_name" value=""/><span/>
      Category<input id="sp_cat" value=""/><span/>
      Description<input id="sp_desc" value=""/><span/>
      Shopkeeper email<input id="sp_email" value=""/><span/>
      Shopkeeper name<input id="sp_vname" value=""/><span/>
      Phone<input id="sp_phone" value=""/><span/>
      UPI ID<input id="sp_upi" value=""/><span/>'
    +'</div><button class="acc" onclick="createShop()">Create shop</button><span id="spmsg" class="stat"></span></div>'
    +'<div class="card"><h3>All shops ('+(shops||[]).length+')</h3>'+table(['id','name','category','phone','upi','status','approval','present',''],rows)+'</div>';
}
async function createShop(){const b={name:$('#sp_name').value,category:$('#sp_cat').value,description:$('#sp_desc').value,
  shopkeeper_email:$('#sp_email').value,shopkeeper_name:$('#sp_vname').value,phone:$('#sp_phone').value,upi_id:$('#sp_upi').value};
  const r=await call('POST','/local/shops',b);$('#spmsg').textContent=r.error?('ERR '+r.error):('created '+ (r.id||'?'));log('POST /local/shops → '+JSON.stringify(r));go('shops');}
async function updateShop(id){const r=await call('GET','/local/shops/'+id);const s=Array.isArray(r)?r[0]:r;
  const fld=['name','category','description','shopkeeper_email','shopkeeper_name','phone','opening_time','closing_time','upi_id','approval_status','status'];
  const kvs=fld.map(f=>'<label>'+esc(f)+'</label><input id="up_'+esc(f)+'" data-f="'+esc(f)+'" value="'+esc((s||{})[f]??'')+'"/>').join('');
  $('#view').innerHTML='<div class="card"><h3>Edit shop '+esc(String(id))+'</h3><div class="kv">'+kvs+'</div>'
    +'<div class="toolbar"><button class="acc" onclick="saveShop(\''+esc(String(id))+'\')">Save</button>'
    +'<button onclick="go(\'shops\')">Cancel</button><span id="upmsg" class="stat"></span></div></div>'
    +'<div class="card"><h3>Raw</h3>'+cell(s)+'</div>';}
async function saveShop(id){const b={};document.querySelectorAll('[data-f]').forEach(i=>{if(i.value!=='')b[i.dataset.f]=i.value;});
  const r=await call('PATCH','/local/shops/'+id,b);$('#upmsg').textContent=r.error?'ERR '+r.error:'saved ✓';log('PATCH /local/shops/'+id+' → '+JSON.stringify(r));}
/* ── Products ── */
async function rProducts(v){
  const prods=await call('GET','/local/products');
  const rows=(prods||[]).map(p=>[esc(p.id),esc(p.shop_id),esc(p.name),esc(p.category),esc(p.price),esc(p.stock!=null?p.stock:''),esc(p.image||''),'<button onclick="del(\'products/'+esc(String(p.id))+'\')">Delete</button>']);
  v.innerHTML='<div class="card"><h3>Create product</h3><div class="kv">'
    +'shop_id<input id="pd_shop" value=""/><span/>name<input id="pd_name" value=""/><span/>category<input id="pd_cat" value=""/><span/>price<input id="pd_price" value=""/><span/>stock<input id="pd_stock" value=""/>'
    +'</div><button class="acc" onclick="createProduct()">Create</button><span id="pdmsg" class="stat"></span></div>'
    +'<div class="card"><h3>Products ('+(prods||[]).length+')</h3>'+table(['id','shop','name','category','price','stock','image',''],rows)+'</div>';}
async function createProduct(){const b={shop_id:$('#pd_shop').value,name:$('#pd_name').value,category:$('#pd_cat').value,price:Number($('#pd_price').value)||0,stock:$('#pd_stock').value?Number($('#pd_stock').value):undefined};
  const r=await call('POST','/local/products',b);$('#pdmsg').textContent=r.error?'ERR '+r.error:'created '+ (r.id||'?');log('POST /local/products → '+JSON.stringify(r));go('products');}
async function del(path){if(!confirm('DELETE '+path+'?'))return;const r=await call('DELETE','/'+path);log('DELETE '+path+' → '+JSON.stringify(r));render();}
/* ── Orders ── */
async function rOrders(v){
  const orders=await call('GET','/local/orders');
  const rows=(orders||[]).map(o=>[esc(o.id),esc(o.token),esc(o.customer_name||'') ,esc(o.shop_id),esc(o.total),esc(o.status),esc(o.payment_status||''),esc(o.created_at||''),
    '<button onclick="setStatus(\''+esc(String(o.id))+'\\')">Status…</button>']);
  v.innerHTML='<div class="card"><h3>Orders ('+(orders||[]).length+')</h3>'+table(['id','token','customer','shop','total','status','payment','created',''],rows)+'</div>';}
async function setStatus(id){const s=prompt('New status (Pending Payment / Pending Acceptance / Accepted / Preparing / Ready / Confirmed / Delivered / Cancelled):');if(!s)return;
  const r=await call('PATCH','/local/orders/'+id+'/status',{status:s});log('PATCH /local/orders/'+id+'/status '+JSON.stringify(r));render();}
/* ── Payments ── */
async function rPayments(v){
  const pays=await call('GET','/local/payments');
  const rows=(pays||[]).map(p=>[esc(p.id),esc(p.order_id),esc(p.amount),esc(p.status),esc(p.method||''),esc(p.utr_number||''),esc(p.screenshot||''),
    '<button onclick="payStatus(\''+esc(String(p.id))+'\')">Set</button>']);
  v.innerHTML='<div class="card"><h3>Payments ('+(pays||[]).length+')</h3><div class="toolbar">'
    +'<button onclick="confirmUtr()">Simulate bank SMS w/ UTR → confirm</button>'
    +'<button onclick="manualUtr()">Set payment UTR (student)</button></div>'
    +'<p class="stat mut">Simulating the bank SMS posts to /local/sms/incoming; if the UTR matches a pending payment the order auto-confirms (payment Success + order Confirmed).</p></div>'
    +'<div class="card">'+table(['id','order','amount','status','method','utr','screenshot',''],rows)+'</div>';}
async function payStatus(id){const s=prompt('Payment status (Pending/Success/Failed):');if(!s)return;const r=await call('PATCH','/local/payments/'+id+'/status',{status:s});log(JSON.stringify(r));render();}
async function manualUtr(){const oid=prompt('order_id');const u=prompt('student UTR');if(!oid||!u)return;const r=await call('POST','/local/payments/utr',{order_id:oid,utr_number:u});log('POST /local/payments/utr → '+JSON.stringify(r));render();}
async function confirmUtr(){const u=prompt('UTR from the bank SMS (leave empty to extract from text)');const rd=prompt('Simulate bank credit SMS text (UTR will be extracted automatically)')||'';
  const text=u?('Rcvd Rs 500 from PRIYA via UPI. UTR: '+u+' Bal Rs 999.'):rd;
  const r=await call('POST','/local/sms/incoming',{phone:'+91 shop phone',text});log('POST /local/sms/incoming → '+JSON.stringify(r));render();}
/* ── Payment settings ── */
async function rPaysettings(v){
  const s=await call('GET','/local/payment-settings');
  v.innerHTML='<div class="card"><h3>Payment settings</h3><div class="kv"><label>upi_id</label><input id="ps_upi" value="'+esc((s||{}).upi_id||'')+'"/>'
    +'<label>razorpay_enabled</label><input id="ps_rz" value="'+esc((s||{}).razorpay_enabled?'true':'false')+'"/></div>'
    +'<div class="toolbar"><button class="acc" onclick="savePs()">Save</button><span id="psmsg" class="stat"></span></div></div>'
    +'<div class="card"><h3>Raw</h3>'+cell(s)+'</div>';}
async function savePs(){const b={upi_id:$('#ps_upi').value};if($('#ps_rz').value.toLowerCase()==='true')b.razorpay_enabled=true;
  const r=await call('PATCH','/local/payment-settings',b);$('#psmsg').textContent=r.error?'ERR '+r.error:'saved ✓';log('PATCH /local/payment-settings → '+JSON.stringify(r));}
/* ── SMS / UTR ── */
async function rSms(v){
  const logs=await call('GET','/local/sms-logs');
  const rows=(logs||[]).map(l=>[
    '<span class="pill '+(String(l.direction||'out')==='in'?'p':'m')+'">'+esc(l.direction||'out')+'</span>',
    esc(l.sub_order_id),esc(l.phone),esc(l.status),esc((l.message||'').slice(0,120)),esc(l.created_at||'')]);
  v.innerHTML='<div class="card"><h3>SMS flow tester</h3>'
    +'<div class="kv"><label>Bank SMS text</label><textarea id="sms_text" placeholder="paste the shopkeeper\\'s bank credit SMS — the UTR is extracted automatically">Rcvd Rs 120 from PRIYA via UPI. UTR: THQ42010724961 Bal Rs 500.</textarea>'
    +'<label>From phone</label><input id="sms_phone" value="+91 98200 00000"/></div>'
    +'<div class="toolbar"><button class="acc" onclick="sendSms()">Send to /local/sms/incoming</button><span id="smsmsg" class="stat"></span></div>'
    +'<p class="stat mut">A bank-credit SMS that matches a pending student UTR auto-confirms the order. Otherwise reply YES &lt;token&gt; / NO &lt;token&gt; confirms/cancels.</p></div>'
    +'<div class="card"><h3>SMS log ('+(logs||[]).length+')</h3>'+table(['dir','order','phone','status','message','time'],rows)+'</div>';}
async function sendSms(){const r=await call('POST','/local/sms/incoming',{phone:$('#sms_phone').value,text:$('#sms_text').value});
  $('#smsmsg').innerHTML=r.error?'<span class="bad">ERR '+esc(r.error)+'</span>':'<span class="ok">sent ✓</span> <span class="mut">order: '+esc(r.order&&r.order.id?r.order.id:'-')+' matched: '+esc(JSON.stringify(r.matched||{}))+'</span>';log('sms → '+JSON.stringify(r));render();}
/* ── Users ── */
async function rUsers(v){
  const u=await call('GET','/admin/users');
  const rows=(u||[]).map(x=>[esc(x.id),esc(x.name||''),esc(x.email||''),esc(x.role||''),esc(x.phone||''),
    '<button onclick="del(\'admin/users/'+esc(String(x.id))+'\')">Delete</button>']);
  v.innerHTML='<div class="card"><h3>Users ('+(u||[]).length+')</h3>'+table(['id','name','email','role','phone',''],rows)+'</div>';}
/* ── Tickets / feedback ── */
async function rTickets(v){
  const [t,f]=await Promise.all([call('GET','/local/tickets').catch(e=>[]),call('GET','/admin/feedback').catch(e=>[])]);
  v.innerHTML='<div class="card"><h3>Tickets</h3>'+(t||[])?.length?'<p class="mut">/local/tickets requires auth</p>':''+table([
    'id','user','subject','status'],
    (t||[]).map(x=>[esc(x.id),esc(x.user_id||''),esc(x.subject||''),esc(x.status||'')]))
    +'<h3>Feedback (admin)</h3>'+table(['id','user','message','rating'],(f||[]).map(x=>[esc(x.id),esc(x.user_id||''),esc(x.message||x.feedback||''),esc(x.rating??'')]))+'</div>';}
/* ── Endpoints ── */
async function rEndpoints(v){
  const spec=await call('GET','/openapi.json',null,null);
  if(spec.error||!spec.paths){v.innerHTML='<pre class="bad">OpenAPI not available: '+esc(JSON.stringify(spec))+'</pre>';return;}
  const paths=Object.entries(spec.paths||{}).sort();
  const groups={};
  for(const [p,ops] of paths){for(const m of ['get','post','patch','put','delete']){if(ops[m]){
    const g=(p.split('/')[3]||'root').toUpperCase();(groups[g]=groups[g]||[]).push({m,m.toUpperCase(),p,o:ops[m]});}}}
  v.innerHTML=Object.entries(groups).map(([g,list])=>
    '<div class="card"><h3>'+esc(g)+' ('+list.length+')</h3>'+list.map((e,i)=>
      '<div class="endpoint" onclick="callEP('+(JSON.stringify([e.m,e.p]))+')">'
      +'<span class="pill '+(e.m==='get'?'m':'p')+'">'+esc(e.m)+'</span><code>'+esc(e.p)+'</code></div>').join('')+'</div>').join('')
    +'<div class="card hide" id="epbox"><h3>Call endpoint</h3><div class="row"><code id="epmeta"></code></div>'
    +'<textarea id="epbody" placeholder="JSON body / query"></textarea>'
    +'<div class="toolbar"><button class="acc" onclick="sendEP()">Send</button><button onclick="exportEP()">Download JSON</button><span id="epmsg" class="stat"></span></div>'
    +'<pre id="epresp"></pre></div>';window.epSel=null;}
let epSel=null;
function callEP(sel){epSel=sel;const b=document.getElementById('epbox');b.classList.remove('hide');document.getElementById('epbox').scrollIntoView({behavior:'smooth'});
  $('#epmeta').textContent=sel[0].toUpperCase()+' '+BASE+sel[1];
  $('#epbody').value='';$('#epresp').textContent='';$('#epmsg').textContent='';window.epSel=sel;}
async function sendEP(){if(!window.epSel)return;const [m,p]=window.epSel;const raw=$('#epbody').value.trim();
  let body=null,path=p;if(raw){try{body=JSON.parse(raw);}catch(e){path=p+'?'+raw;$('#epresp').textContent='(treated as query string: '+esc(raw)+')';}}
  const r=await call(m,path,body);$('#epresp').textContent=JSON.stringify(r,null,2);log(m+' '+path);}
function exportEP(){const pr=document.getElementById('epresp');if(!pr.textContent)return;const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([pr.textContent],{type:'application/json'}));a.download='response.json';a.click();}
refresh().then(()=>{render();});
</script>
</body>
</html>
"""


# ─────────────────────────  helpers  ─────────────────────────
def load_state() -> dict:
    if os.path.exists(TOKEN_FILE):
        try:
            return json.load(open(TOKEN_FILE))
        except Exception:
            pass
    return {"base": DEFAULT_BASE, "token": "", "user": ""}


def save_state(st: dict) -> None:
    with open(TOKEN_FILE, "w") as f:
        json.dump(st, f)


def api(method: str, path: str, base: str = "", token: str = "", body=None,
        timeout: int = 60):
    base = base or load_state().get("base") or DEFAULT_BASE
    url = path if path.startswith("http") else None
    if url is None:
        # /openapi.json lives at the app ROOT, not under the /api/v1 mount.
        if path.split("?")[0] == "/openapi.json" and "/api" in base:
            root = base.split("/api", 1)[0]
        else:
            root = base.rstrip("/")
        url = root + (path if path.startswith("/") else "/" + path)
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        else:
            data = str(body).encode()
            headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            try:
                return json.loads(raw)
            except Exception:
                return {"ok": True, "raw": raw.decode("utf-8", "replace")}
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        try:
            return {"error": raw and json.loads(raw) or str(e)}
        except Exception:
            return {"error": raw, "status": e.code}
    except Exception as e:
        return {"error": str(e)}


def grab_token(resp: dict) -> str:
    if not isinstance(resp, dict):
        return ""
    for key, val in resp.items():
        if "token" in key.lower() and isinstance(val, str) and val:
            return val
        if key.lower() in ("authorization", "access") and isinstance(val, str):
            return val
    return ""


# ───────────────────────  http server  ───────────────────────
class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload, ctype="application/json"):
        body = json.dumps(payload).encode() if not isinstance(payload, (bytes, str)) else payload.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except Exception:
            return {}

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, MANAGER_HTML, "text/html")
        elif self.path == "/api/state":
            self._send(200, load_state())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        body = self._json()
        if self.path == "/api/base":
            st = load_state(); st["base"] = (body.get("base") or DEFAULT_BASE).rstrip("/")
            save_state(st); self._send(200, {"ok": True, "base": st["base"]})
        elif self.path == "/api/login":
            self.login(body)
        elif self.path == "/api/proxy":
            st = load_state()
            base = body.get("base") or st["base"]
            token = body.get("token") if body.get("token") is not None else st["token"]
            resp = api(body.get("method", "GET"), body.get("path", "/"), base, token,
                       body.get("body"))
            self._send(200, resp)
        else:
            self._send(404, {"error": "not found"})

    def do_DELETE(self):
        if self.path == "/api/login":
            st = load_state(); st["token"] = ""; st["user"] = ""
            save_state(st); self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})

    def login(self, body):
        st = load_state()
        base = body.get("base") or st["base"]
        kind, email, pwd = body.get("kind", "admin"), body.get("email", ""), body.get("password", "")
        endpoints = {
            "admin": ("POST", "/admin/login"),
            "student": ("POST", "/local/auth/login"),
            "shopkeeper": ("POST", "/vendor/login"),
        }
        m, p = endpoints.get(kind, endpoints["admin"])
        resp = api(m, p, base, "", {"email": email, "password": pwd})
        token = grab_token(resp)
        if not token:
            user = resp.get("user") or resp.get("data") or resp
            token = grab_token(user or {})
        if not token:
            self._send(401, {"error": "login failed", "response": resp})
            return
        st["token"] = token
        st["user"] = kind + " " + email
        save_state(st)
        self._send(200, {"ok": True, "token": token, "user": st["user"], "role": kind,
                         "info": resp})


# ─────────────────────────  CLI  ─────────────────────────
def main():
    ap = argparse.ArgumentParser(description="DETOMSITE Manager")
    ap.add_argument("port", nargs="?", type=int, default=8765, help="port (default 8765)")
    ap.add_argument("--base", help="backend base URL")
    ap.add_argument("--login", nargs=3, metavar=("KIND", "EMAIL", "PASSWORD"),
                    help="login: KIND=admin|student|shopkeeper")
    ap.add_argument("--call", nargs="+", help='call e.g. "GET /local/shops" or "PATCH /path" body')
    ap.add_argument("--token", help="set token directly")
    args = ap.parse_args()

    if args.base:
        st = load_state(); st["base"] = args.base.rstrip("/"); save_state(st)
    if args.token:
        st = load_state(); st["token"] = args.token; save_state(st)
    if args.login:
        st = load_state()
        kind, email, pwd = args.login
        endpoints = {
            "admin": ("POST", "/admin/login"),
            "student": ("POST", "/local/auth/login"),
            "shopkeeper": ("POST", "/vendor/login"),
        }
        m, p = endpoints.get(kind, endpoints["admin"])
        resp = api(m, p, st["base"], "", {"email": email, "password": pwd})
        token = grab_token(resp) or grab_token((resp or {}).get("user") or {})
        if not token:
            print(json.dumps({"error": "login failed", "response": resp}, indent=2))
            sys.exit(1)
        st["token"] = token; st["user"] = kind + " " + email
        save_state(st)
        print(json.dumps({"ok": True, "user": st["user"]}, indent=2))
        return
    if args.call:
        st = load_state()
        parts = args.call[0].split(None, 1)
        method = parts[0].upper() if parts else "GET"
        path = parts[1] if len(parts) > 1 else "/"
        body = None
        if len(args.call) > 1:
            try:
                body = json.loads(args.call[1])
            except Exception:
                body = args.call[1]
        print(json.dumps(api(method, path, st["base"], st["token"], body), indent=2))
        return

    class Quiet(Handler):
        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Quiet)
    print(f"DETOMSITE MANAGER → http://127.0.0.1:{args.port}")
    print(f"  backend base : {load_state().get('base')}")
    print("  Ctrl+C to stop")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()