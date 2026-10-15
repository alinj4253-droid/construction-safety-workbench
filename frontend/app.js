'use strict';
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const TITLES={p1:['工作台','总览 / 今日待办'],p2:['AI 安全助手','小安 · 规范检索与文书生成'],p6:['隐患办理','双 Agent 协作 · 人工签发'],p3:['隐患台账','双轨闭环管理'],p4:['AI 监控','领导驾驶舱 · 态势统计'],p5:['知识库','查依据 · 管资料']};
let CUR_USER=null,token=localStorage.getItem('safety_token')||'',toastTimer;
async function api(path,method='GET',body){
  const headers={Authorization:'Bearer '+token};if(body && !(body instanceof FormData))headers['Content-Type']='application/json';
  const r=await fetch(path,{method,headers,body:body?(body instanceof FormData?body:JSON.stringify(body)):undefined});
  const data=await r.json();if(!r.ok){if(r.status===401)toLogin();throw Error(data.message||'请求失败');}return data.data;
}
function toast(s){$('toast').textContent=s;$('toast').classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.remove('show'),3500);}
function openModal(t,b,f=''){$('mTitle').textContent=t;$('mBody').innerHTML=b;$('mFoot').innerHTML=f;$('mask').classList.add('on');}
function closeModal(){$('mask').classList.remove('on');}
function go(id,el){if(!CUR_USER)return toLogin();document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.id===id));document.querySelectorAll('[data-page]').forEach(n=>n.classList.toggle('active',n.dataset.page===id));$('tb-title').textContent=TITLES[id][0];$('tb-crumb').textContent=TITLES[id][1];if(window['load_'+id])window['load_'+id]().catch(toast);}
function applyUser(){for(const prefix of ['sb','tb']){$(prefix+'Avatar').textContent=CUR_USER.display_name[0];$(prefix+'Name').textContent=CUR_USER.display_name;$(prefix+'Role').textContent=CUR_USER.role;}$('sbId').textContent='工号 '+CUR_USER.employee_no;$('p1Name').textContent=CUR_USER.display_name;}
async function doLogin(){try{const d=await api('/api/auth/login','POST',{username:$('lgUser').value,password:document.querySelector('#loginGate input[type=password]').value});token=d.token;localStorage.setItem('safety_token',token);CUR_USER=d.user;applyUser();$('loginGate').classList.remove('on');go('p1');toast('欢迎回来，'+CUR_USER.display_name);}catch(e){toast(e.message);}}
async function toLogin(msg){if(token){try{await api('/api/auth/logout','POST');}catch{}}token='';CUR_USER=null;localStorage.removeItem('safety_token');$('umenu').classList.remove('on');$('loginGate').classList.add('on');if(msg)toast(msg);}
function toggleUmenu(e){e.stopPropagation();$('umenu').classList.toggle('on');}
function toggleNtf(e){e.stopPropagation();$('ntfPanel').classList.toggle('on');}
function ntfGo(e,pg){e.stopPropagation();$('ntfPanel').classList.remove('on');go(pg);}
function showProfile(){openModal('个人信息设置',`<div class="frm"><p>姓名：${esc(CUR_USER.display_name)}</p><p>岗位：${esc(CUR_USER.role)}</p><p>工号：${esc(CUR_USER.employee_no)}</p><p>项目：${esc(CUR_USER.project)}</p><p class="frm-tip">演示账号由本地管理员维护，用于操作留痕和会话归属。</p></div>`,'<button class="btn" onclick="closeModal()">关闭</button>');}
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal();});
window.addEventListener('unhandledrejection',e=>{toast(e.reason?.message||'操作未完成，请重试');e.preventDefault();});
(async()=>{const users=await api('/api/auth/users');$('lgUser').innerHTML=users.map(u=>`<option value="${esc(u.username)}">${esc(u.display_name)} · ${esc(u.role)}（工号 ${esc(u.employee_no)}）</option>`).join('');document.querySelector('.lg-tip').textContent='本地演示账号 · 初始密码 123456 · 操作与对话按身份留痕';if(token){try{CUR_USER=await api('/api/auth/me');applyUser();$('loginGate').classList.remove('on');go('p1');}catch{token='';localStorage.removeItem('safety_token');}}})();
