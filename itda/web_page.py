"""Traveller-facing page (Tailwind CSS via CDN, Pretendard, Leaflet/OSM).
White + Goryeo celadon (고려청자) palette, minimal dashboard layout — 한글날 edition.
Kept separate from web.py so the server code stays readable."""

PAGE = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>잇다 ItDA</title>
<script src="https://cdn.tailwindcss.com"></script>
<script>tailwind.config={theme:{extend:{colors:{
 cel:{50:'#F2F8F5',100:'#E3F0EA',200:'#C8E1D6',300:'#A6CDBD',400:'#82B6A2',500:'#5F9C86',600:'#4A8270',700:'#3A685A',800:'#2C4F45',900:'#1F3832'},
 ink:'#1C2724',line:'#E4EAE7',paper:'#F6F8F7'},
 fontFamily:{sans:['Pretendard','"Noto Sans KR"','system-ui','sans-serif']}}}}</script>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style type="text/tailwindcss">
body{@apply bg-paper text-ink antialiased font-sans;word-break:keep-all}
.chip{@apply rounded-full border border-line bg-white px-3.5 py-1.5 text-[13px] text-slate-600 transition hover:border-cel-300 hover:text-cel-700}
.chip.on{@apply border-cel-300 bg-cel-50 font-medium text-cel-700}
.segbtn{@apply flex-1 rounded-lg px-4 py-2 text-[13px] font-medium text-slate-500 transition}
.segbtn.on{@apply bg-white text-ink shadow-sm ring-1 ring-line}
.field{@apply w-full rounded-xl border border-line bg-white px-3.5 py-2.5 text-[14px] outline-none transition placeholder:text-slate-400 focus:border-cel-400 focus:ring-4 focus:ring-cel-100}
.lbl2{@apply mb-2 mt-5 block text-[13px] font-medium text-slate-600}
.kcard{@apply rounded-2xl border border-line bg-white p-5}
.pill{@apply inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium}
.fn{@apply ml-0.5 cursor-pointer align-super text-[11px] font-semibold text-cel-600 hover:underline}
.tabbtn{@apply -mb-px border-b-2 border-transparent px-1 pb-3 text-sm font-medium text-slate-400 transition hover:text-slate-600}
.tabbtn.on{@apply border-cel-500 text-ink}
.src-hl{@apply bg-cel-50 ring-2 ring-cel-200}
.nav{@apply flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-[14px] text-slate-500 transition hover:bg-paper hover:text-ink}
.nav.on{@apply bg-cel-50 font-medium text-cel-800}
.ico{@apply flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-cel-50 text-[17px]}
</style>
<style>
#dev h2{font:600 1.05rem/1.4 Pretendard,system-ui,sans-serif;margin:2rem 0 .75rem;color:#1C2724}
#dev .card{margin:.75rem 0;border-radius:1rem;background:#fff;padding:1rem;border:1px solid #E4EAE7}
#dev table{width:100%;border-collapse:collapse;font-size:.85rem} #dev td,#dev th{border-bottom:1px solid #EEF2F0;padding:.55rem .5rem;text-align:left;vertical-align:top} #dev th{color:#64748b;font-weight:500;font-size:.78rem}
#dev .tag{display:inline-block;margin:.25rem .25rem 0 0;border:1px solid #E4EAE7;border-radius:999px;padding:0 .5rem;font-size:.75rem;color:#64748b;background:#F6F8F7}
#dev .sub{color:#64748b} #dev .ok{color:#3A685A} #dev .warn{color:#b45309} #dev .bad{color:#be123c}
#dev .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.75rem} #dev .stat{border-radius:1rem;background:#fff;padding:1rem;border:1px solid #E4EAE7;font-size:.8rem;color:#64748b} #dev .stat b{display:block;font-size:1.5rem;font-weight:600;color:#1C2724}
#dev pre,#livelog{max-height:18rem;overflow:auto;white-space:pre-wrap;border-radius:.75rem;background:#17211E;padding:1rem;font:11.5px/1.6 ui-monospace,Menlo,monospace;color:#D7E5DF}
#dev ul{list-style:disc;padding-left:1.25rem} #dev .lbl{margin-top:.75rem;font-size:.85rem;font-weight:600}
#dev details.card>summary{cursor:pointer}
@keyframes rise{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}} .rise{animation:rise .4s ease both}
.leaflet-container{font-family:Pretendard,system-ui,sans-serif;background:#F2F5F4}
.leaflet-tile-pane{filter:saturate(.3) brightness(1.05) contrast(.95)}  /* calm, near-monochrome basemap */
</style></head>
<body>
<div class="flex min-h-screen">
<aside class="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-line bg-white px-4 py-5 lg:flex">
 <div class="flex items-center gap-2.5 px-2">
  <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-cel-500 text-[17px] font-bold text-white">잇</span>
  <div class="leading-tight"><div class="text-[15px] font-semibold">잇다 <span class="font-normal text-slate-400">ItDA</span></div><div class="text-[11px] tracking-[.25em] text-cel-500">ㅇㅣㅅㄷㅏ</div></div></div>
 <p class="mb-2 mt-8 px-3 text-[11px] font-medium uppercase tracking-wider text-slate-400">메뉴</p>
 <nav class="space-y-1" id="side">
  <button class="nav on" data-v="top"><span>🧭</span>코스 만들기</button>
  <button class="nav" data-v="user"><span>🗺</span>결과</button>
  <button class="nav" data-v="dev"><span>⚖️</span>검증 과정</button></nav>
 <p class="mb-2 mt-8 px-3 text-[11px] font-medium uppercase tracking-wider text-slate-400">NVIDIA 스택</p>
 <ul class="space-y-2 px-3 text-[13px] text-slate-600">
  <li class="flex items-center gap-2"><span class="h-1.5 w-1.5 rounded-full bg-cel-500"></span>Nemotron 3 Super</li>
  <li class="flex items-center gap-2"><span class="h-1.5 w-1.5 rounded-full bg-cel-500"></span>NIM · Nano on L40S</li>
  <li class="flex items-center gap-2"><span class="h-1.5 w-1.5 rounded-full bg-cel-500"></span>NeMoClaw 에이전트</li>
  <li class="flex items-center gap-2"><span class="h-1.5 w-1.5 rounded-full bg-cel-500"></span>OpenShell 샌드박스</li></ul>
 <div class="mt-auto rounded-2xl bg-cel-50 p-4">
  <div class="text-[11px] font-medium text-cel-600">한글날 · 10월 9일</div>
  <div class="mt-1 text-[14px] font-semibold text-cel-900">훈민정음 반포 580돌</div>
  <p class="mt-1 text-xs leading-relaxed text-slate-500">한글로 잇는<br>한국 문화와 역사</p>
  <div class="mt-3 flex items-end gap-3 text-cel-300"><span class="text-2xl leading-none">ㆍ</span><span class="text-2xl leading-none">ㅡ</span><span class="text-2xl leading-none">ㅣ</span><span class="ml-auto text-[10px] text-cel-500">천 · 지 · 인</span></div></div>
</aside>

<div class="min-w-0 flex-1">
<header class="sticky top-0 z-30 border-b border-line bg-white/85 backdrop-blur">
 <div class="mx-auto flex max-w-6xl items-center justify-between px-5 py-3 lg:px-8">
  <div class="flex items-center gap-2 lg:hidden"><span class="flex h-8 w-8 items-center justify-center rounded-lg bg-cel-500 text-sm font-bold text-white">잇</span><span class="font-semibold">잇다</span></div>
  <div class="hidden text-sm text-slate-400 lg:block">잇다 <span class="mx-1.5">/</span><span class="text-ink">한국 문화·역사 여행 에이전트</span></div>
  <div class="flex items-center gap-2 text-xs">
   <span class="pill bg-white text-slate-600 ring-1 ring-line"><span class="h-1.5 w-1.5 rounded-full bg-cel-500"></span>샌드박스 연결됨</span>
   <span class="hidden sm:block"><span class="pill bg-white text-slate-600 ring-1 ring-line">초안까지만 · 예약/결제 안 함</span></span></div></div></header>

<main class="mx-auto max-w-6xl px-5 pb-24 lg:px-8" id="top">
 <div class="rise pt-8">
  <p class="text-[13px] font-medium text-cel-600">한글날 에디션 · 공식 기록 기반 여행 초안</p>
  <h1 class="mt-1.5 text-[26px] font-semibold leading-snug tracking-tight sm:text-3xl">흩어진 기록을, 믿을 수 있는 하루로.</h1>
  <p class="mt-2 max-w-2xl text-[14.5px] leading-relaxed text-slate-500">공식 공지·현장 기록·검색 결과가 서로 다를 때, 무엇이 최신이고 누가 말했는지 따져 원문을 인용해 근거를 남겨요. 함께 가는 분의 상황까지 헤아려 바로 쓸 수 있는 코스로 이어 드려요.</p></div>

 <div class="rise mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
  <div class="kcard !p-4"><div class="flex items-center gap-3"><span class="ico">🔎</span><div><div class="text-[14px] font-semibold">원문 인용</div><div class="text-xs text-slate-400">사실마다 원문 문장 확인</div></div></div></div>
  <div class="kcard !p-4"><div class="flex items-center gap-3"><span class="ico">⚖️</span><div><div class="text-[14px] font-semibold">2/3 정족수</div><div class="text-xs text-slate-400">자료끼리 비교해 확정</div></div></div></div>
  <div class="kcard !p-4"><div class="flex items-center gap-3"><span class="ico">🛡</span><div><div class="text-[14px] font-semibold">허용된 곳만</div><div class="text-xs text-slate-400">정책 밖 접속은 차단</div></div></div></div>
  <div class="kcard !p-4"><div class="flex items-center gap-3"><span class="ico">✋</span><div><div class="text-[14px] font-semibold">초안까지만</div><div class="text-xs text-slate-400">예약·연락·결제 안 함</div></div></div></div></div>

 <div class="mt-4 grid items-start gap-4 lg:grid-cols-[1fr_330px]">
  <div class="rise kcard sm:!p-6" style="animation-delay:.05s">
   <div class="flex items-center justify-between gap-3"><h2 class="shrink-0 whitespace-nowrap text-[15px] font-semibold">새 코스</h2>
    <div class="flex w-full max-w-xs rounded-xl bg-paper p-1 ring-1 ring-line" id="mode"><button class="segbtn on" data-v="challenge">주어진 자료로</button><button class="segbtn" data-v="live">직접 입력</button></div></div>
   <label class="lbl2" id="reqlbl">무엇을 해 드릴까요? <span class="font-normal text-slate-400">(비워 두면 기본 과제)</span></label>
   <textarea id="req" rows="3" class="field resize-none" placeholder="예) 성진정 해설 카드만 만들어 줘 / 비 오는 날 버전으로 짜 줘"></textarea>
   <div id="live" hidden>
    <div class="grid gap-3 sm:grid-cols-[160px_1fr]">
     <div><label class="lbl2">언제 가세요?</label><input type="date" id="date" class="field"></div>
     <div><label class="lbl2">함께 가는 분과 조건</label><input id="comp" class="field" placeholder="아버지 무릎이 안 좋음, 어머니 비건, 7살 아이"></div></div>
    <p class="mt-2 text-xs text-slate-400">입력한 내용은 이번 코스에만 쓰이고, 예약·연락·결제는 하지 않아요.</p></div>
   <div class="grid gap-x-6 sm:grid-cols-2">
    <div><label class="lbl2">누가 가시나요?</label>
     <div class="flex flex-wrap gap-2" id="vis"><button class="chip on" data-v="auto">알아서</button><button class="chip" data-v="foreign">해외 방문객</button><button class="chip" data-v="korean">한국인</button></div></div>
    <div><label class="lbl2">결과 언어</label>
     <div class="flex flex-wrap gap-2" id="lang"><button class="chip on" data-v="">자동</button><button class="chip" data-v="ko">한국어</button><button class="chip" data-v="en">English</button><button class="chip" data-v="ja">日本語</button></div></div></div>
   <label class="lbl2">무엇이 궁금하세요? <span class="font-normal text-slate-400">여러 개</span></label>
   <div class="flex flex-wrap gap-2" id="int"><button class="chip on" data-v="history">역사 이야기</button><button class="chip on" data-v="family">동행 배려</button><button class="chip" data-v="kculture">K-컬처</button></div>
   <div class="mt-6 flex flex-wrap items-center gap-3">
    <button id="go" class="rounded-xl bg-cel-600 px-6 py-3 text-[14px] font-semibold text-white transition hover:bg-cel-700 active:scale-[.99] disabled:cursor-wait disabled:opacity-50">코스 만들기</button>
    <span id="msg" class="text-sm text-rose-600"></span></div>
  </div>

  <div id="prog" class="rise kcard" style="animation-delay:.1s">
   <div class="flex items-center justify-between"><h2 class="text-[15px] font-semibold">진행 상황</h2><span class="text-xs text-slate-400">보통 1–2분</span></div>
   <ol id="steps" class="mt-2 divide-y divide-line"></ol>
   <p id="st" class="mt-3 text-[13px] text-slate-500">코스 만들기를 누르면 여기서 단계별로 보여 드려요.</p>
   <details class="mt-3"><summary class="cursor-pointer text-xs text-slate-400 hover:text-slate-600">실시간 로그 · 프롬프트 보기</summary><pre id="livelog" class="mt-2"></pre></details>
  </div></div>

 <nav id="tabs" class="mt-12 flex gap-6 border-b border-line" hidden><button class="tabbtn on" data-v="user">여행 코스</button><button class="tabbtn" data-v="dev">검증 과정 · 개발자 보기</button></nav>
 <div id="res"></div><div id="dev" hidden></div>
</main>
<footer class="border-t border-line py-8 text-center text-xs text-slate-400">잇다 ItDA · NVIDIA Nemotron · NIM · NeMoClaw · OpenShell · L40S · 지도 © OpenStreetMap</footer>
</div></div>

<script>
const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let visitor='auto',mode='challenge',lang='',lastJob=null;
const pick=(sel,single,cb)=>document.querySelectorAll(sel+' button').forEach(b=>b.onclick=()=>{if(single)document.querySelectorAll(sel+' button').forEach(x=>x.classList.remove('on'));b.classList.toggle('on',single?true:!b.classList.contains('on'));cb&&cb(b)});
pick('#mode',true,b=>{mode=b.dataset.v;$('#live').hidden=mode!=='live';
  $('#reqlbl').innerHTML=mode==='live'?'어디로, 무엇을 하고 싶으세요?':'무엇을 해 드릴까요? <span class="font-normal text-slate-400">(비워 두면 기본 과제)</span>';
  $('#req').placeholder=mode==='live'?'예) 토요일에 부모님 모시고 경복궁이랑 광장시장 반나절':'예) 성진정 해설 카드만 만들어 줘 / 비 오는 날 버전으로 짜 줘'});
pick('#vis',true,b=>visitor=b.dataset.v);pick('#lang',true,b=>lang=b.dataset.v);pick('#int',false);
const showTab=v=>{document.querySelectorAll('#tabs button').forEach(b=>b.classList.toggle('on',b.dataset.v===v));$('#res').hidden=v!=='user';$('#dev').hidden=v!=='dev'};
pick('#tabs',true,b=>showTab(b.dataset.v));
document.querySelectorAll('#side button').forEach(b=>b.onclick=()=>{const v=b.dataset.v;
  if(v!=='top'&&$('#tabs').hidden){$('#msg').textContent='먼저 코스를 만들어 주세요';return}
  document.querySelectorAll('#side button').forEach(x=>x.classList.toggle('on',x===b));
  if(v==='top')return window.scrollTo({top:0,behavior:'smooth'});showTab(v);$('#tabs').scrollIntoView({behavior:'smooth',block:'start'})});

const STEPS=[['①','📥','자료 수집','자료를 모으고 있어요','주어진 자료·입력 정리'],['②','🧭','계획·검색','무엇을 확인할지 계획하고 공식 API로 찾고 있어요','공식 API로 빈 곳 확인'],['③','⚖️','신뢰 검증','자료끼리 비교해서 믿을 만한지 따지고 있어요','원문 인용 · 2/3 정족수'],['④','🗺','코스 구성','상황에 맞는 코스를 짜고 있어요','동행 상황 반영'],['⑤','✅','근거 확인','모든 문장의 근거를 다시 확인하고 있어요','모든 문장 근거 재확인']];
const stat=st=>{const m={done:['완료','bg-cel-500','text-cel-700'],now:['진행 중','bg-amber-400 animate-pulse','text-amber-700'],todo:['대기','bg-slate-300','text-slate-400']}[st];return `<span class="inline-flex shrink-0 items-center gap-1.5 text-xs ${m[2]}"><span class="h-1.5 w-1.5 rounded-full ${m[1]}"></span>${m[0]}</span>`};
function drawSteps(k,done){$('#steps').innerHTML=STEPS.map((s,i)=>{const st=done||i<k-1?'done':i===k-1?'now':'todo';
  return `<li class="flex items-center gap-3 py-2.5"><span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-sm transition ${st==='done'?'bg-cel-500 text-white':st==='now'?'bg-cel-50 ring-1 ring-cel-300':'bg-paper text-slate-400 ring-1 ring-line'}">${st==='done'?'✓':s[1]}</span><div class="min-w-0 flex-1"><div class="text-[13.5px] font-medium ${st==='todo'?'text-slate-400':'text-ink'}">${s[2]}</div><div class="truncate text-xs text-slate-400">${s[4]}</div></div>${stat(st)}</li>`}).join('')}
drawSteps(0,false);

async function startRun(extra){
  const interests=[...document.querySelectorAll('#int .on')].map(b=>b.dataset.v);$('#msg').textContent='';
  if(!interests.length){$('#msg').textContent='궁금한 주제를 하나 이상 골라 주세요';return}
  if(mode==='live'&&!extra.followup&&$('#req').value.trim().length<5){$('#msg').textContent='어디로 무엇을 하고 싶은지 적어 주세요';return}
  $('#go').disabled=true;$('#tabs').hidden=true;$('#res').innerHTML='';$('#dev').innerHTML='';$('#prog').hidden=false;drawSteps(1,false);
  $('#st').textContent=STEPS[0][3];
  const r=await fetch('run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({visitor,interests,mode,lang,request:$('#req').value,date:$('#date').value,companions:$('#comp').value,...extra})});
  const j=await r.json();if(!r.ok){$('#msg').textContent=j.error;$('#st').textContent='';drawSteps(0,false);$('#go').disabled=false;return}
  pollJob(j.job)}
$('#go').onclick=()=>startRun({});
function pollJob(job){
  const poll=async()=>{const s=await (await fetch('status?job='+job)).json();const log=s.lines.join('\n');
    let k=0;STEPS.forEach((x,i)=>{if(log.includes(x[0]))k=i+1});
    drawSteps(Math.max(k,1),s.done&&s.ok);
    $('#st').innerHTML=s.done?(s.ok?`<b class="font-semibold text-cel-700">완료</b> · ${s.elapsed}초`:'<b class="font-semibold text-rose-600">실행 중 문제가 생겼어요.</b> 검증 과정 탭에서 로그를 확인하세요.'):`${(STEPS[Math.max(0,k-1)])[3]} <span class="text-slate-400">· ${s.elapsed}초</span>`;
    const ll=$('#livelog');ll.textContent=log;ll.scrollTop=1e9;
    if(!s.done)return setTimeout(poll,1000);$('#go').disabled=false;
    if(s.ok){lastJob=job;const d=await (await fetch('result?job='+job)).json();renderUser(d);renderDev(d);
      const TR=d.transcript||[];if(TR.length)$('#dev').innerHTML+=`<h2>🧾 프롬프트 기록 (${TR.length}회 호출)</h2>`+TR.map((t,i)=>`<details class="card"><summary><b>${i+1}. ${esc(t.label)}</b> · ${esc(t.model)} · ${esc(t.endpoint)} · ${esc(t.seconds)}s</summary><div class="lbl">system 프롬프트</div><pre>${esc(t.system)}</pre><div class="lbl">user 프롬프트</div><pre>${esc(t.user)}</pre><div class="lbl">모델 응답</div><pre>${esc(t.response)}</pre></details>`).join('');
      $('#dev').innerHTML+=`<h2>실행 로그</h2><pre>${esc(log)}</pre>`;$('#tabs').hidden=false;showTab('user');
      document.querySelectorAll('#side button').forEach(x=>x.classList.toggle('on',x.dataset.v==='user'));
      $('#tabs').scrollIntoView({behavior:'smooth',block:'start'})}
    else{$('#dev').innerHTML=`<pre>${esc(log)}</pre>`;$('#tabs').hidden=false;showTab('dev')}};poll()}
function askFollow(q){if(!q||!q.trim()||!lastJob)return;startRun({followup:q,parent:lastJob});window.scrollTo({top:0,behavior:'smooth'})}

const OK='bg-cel-50 text-cel-700 ring-1 ring-cel-200',WARN='bg-amber-50 text-amber-700 ring-1 ring-amber-200',BAD='bg-rose-50 text-rose-700 ring-1 ring-rose-200',NEU='bg-paper text-slate-600 ring-1 ring-line';
const TYPE={official_notice:'공식 공지',field_survey:'현장 조사',structured_data:'방문단 정보',internal_guideline:'운영 규칙',interpretation_draft:'해설 자료',community_post:'지역 게시판',promotional:'홍보물',personal_blog:'개인 블로그',advertisement:'광고',archive:'과거 기록',web_search:'웹 검색',public_api:'공공 API',external_instruction:'의심되는 외부 지시',other:'기타'};
const TRUST={use:['믿을 수 있음',OK],use_with_caution:['주의해서 사용',WARN],background_only:['참고용',NEU],ignore:['사용 안 함',BAD]};
const MODE={walk:['🚶','도보','#4A8270'],taxi:['🚕','택시','#C2873A'],transit:['🚌','대중교통','#4F74A8']};
const sec=(icon,title,body,sub='')=>`<section class="rise mt-10"><div class="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1"><span class="ico !h-8 !w-8 !text-[15px]">${icon}</span><h3 class="text-[17px] font-semibold">${title}</h3>${sub?`<span class="text-[13px] text-slate-400">${sub}</span>`:''}</div>${body}</section>`;
const pill=(t,cls=NEU)=>`<span class="pill ${cls}">${t}</span>`;

function renderUser(d){
  const R=d.result||{},P=R.plan||{},V=R.resolved||{},S={};(R.sources||[]).forEach(s=>S[s.id]=s);
  if(R.status==='out_of_scope'){
    $('#res').innerHTML=`<div class="rise mx-auto mt-8 max-w-2xl rounded-2xl border border-line bg-white p-8 text-center"><span class="ico mx-auto !h-12 !w-12 !text-2xl">🙏</span><h2 class="mt-4 text-xl font-semibold">${esc(P.title)}</h2><p class="mt-3 leading-relaxed text-slate-600">${esc(R.scope_reason)}</p>
      ${(R.alternatives||[]).length?`<p class="mt-6 text-[13px] font-medium text-slate-500">대신 이렇게 도와드릴 수 있어요</p><div class="mt-3 flex flex-wrap justify-center gap-2">${R.alternatives.map(a=>`<button class="chip" onclick="document.getElementById('req').value=this.textContent;window.scrollTo({top:0,behavior:'smooth'})">${esc(a)}</button>`).join('')}</div>`:''}
      <p class="mt-6 text-xs text-slate-400">검색·검증·코스 생성은 실행하지 않았어요. 자료 없이 지어낸 일정을 드리지 않기 위해서예요.</p></div>`;
    $('#res').hidden=false;$('#dev').hidden=true;return}
  const order=[],num={};const fn=ids=>(ids||[]).filter(i=>S[i]).map(i=>{if(!(i in num)){order.push(i);num[i]=order.length}return `<sup class="fn" data-i="${esc(i)}">[${num[i]}]</sup>`}).join('');
  const conf=(R.consensus||[]).filter(g=>(g.quorum||{}).status==='confirmed').length,used=(R.sources||[]).filter(s=>s.trust!=='ignore').length;
  const VD={supported:['✓ 자료로 확인됨',OK],contradicted:['✕ 자료가 반대 내용을 말함',BAD],no_evidence:['? 자료로 확인되지 않음',NEU],uncertain:['! 자료끼리 엇갈리거나 불확실',WARN]}[P.verdict];
  const lensTxt={foreign:'해외 방문객',korean:'한국인'}[R.lens?.visitor_type]||'';
  let h=`<div class="rise mt-6 rounded-2xl border border-line bg-white p-6">
    <div class="flex flex-wrap gap-2">${pill('초안 · 예약/연락 안 함',OK)}${R.visit_date?pill('📅 '+esc(R.visit_date)):''}${lensTxt?pill(lensTxt):''}${(R.context_signals||[]).map(g=>pill(esc(g.icon)+' '+esc(g.label))).join('')}</div>
    <h2 class="mt-4 text-2xl font-semibold leading-snug tracking-tight">${esc(P.title)}</h2><p class="mt-2 max-w-3xl leading-relaxed text-slate-500">${esc(P.summary)}</p></div>
    <div class="rise mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">${[['📚',used+'<span class="text-base font-normal text-slate-400">/'+(R.sources||[]).length+'</span>','사용한 자료'],['⚖️',conf,'교차 확인된 정보'],['🛡',(V.untrusted_instructions||[]).length,'무시한 의심 지시'],['🔎',(R.tool_calls||[]).length,'직접 찾아본 것']].map(([i,n,t])=>`<div class="kcard !p-4"><div class="flex items-center justify-between"><span class="text-xs text-slate-500">${t}</span><span class="text-sm">${i}</span></div><div class="mt-2 text-2xl font-semibold tracking-tight">${n}</div></div>`).join('')}</div>`;
  if(P.answer)h+=`<div class="rise mt-4 rounded-2xl border border-cel-200 bg-cel-50/60 p-6"><div class="text-xs font-medium text-cel-700">질문에 대한 답</div>${VD?`<div class="mt-3"><span class="pill ${VD[1]} !px-3 !py-1 !text-sm">${VD[0]}</span></div>`:''}<p class="mt-3 text-[17px] leading-relaxed">${esc(P.answer)}</p></div>`;
  if((P.changes||[]).length)h+=`<div class="kcard mt-4"><div class="text-sm font-semibold">이전 초안 대비 바뀐 점</div><ul class="mt-2 list-disc pl-5 text-[14px] text-slate-600">${P.changes.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>`;
  const TL={nearby:'주변 식당·장소',accessibility:'무장애 정보',route:'동선',festival:'행사',kma_weather:'기상청 예보',weather_warning:'기상특보',encyclopedia:'민족문화대백과',place_info:'공식 운영정보'};
  const IN=R.implicit_needs||[];
  if(IN.length){const g={};IN.forEach(n=>{const k=n.signal||'에이전트 추론';(g[k]=g[k]||{icon:n.icon||'💡',items:[],chk:new Set()});g[k].items.push(n);(n.checked_with||[]).forEach(t=>g[k].chk.add(t))});
    h+=sec('🤝','이렇게 배려했어요',`<div class="grid gap-3 md:grid-cols-2 lg:grid-cols-3">${Object.entries(g).map(([k,v])=>`<div class="kcard"><div class="flex items-center gap-2.5"><span class="ico">${esc(v.icon)}</span><b class="font-semibold">${esc(k)}</b></div>
      <ul class="mt-3 space-y-2 text-[13.5px]">${v.items.slice(0,6).map(n=>`<li class="flex gap-2"><span class="pill h-fit shrink-0 ${NEU}">${esc(n.category||'추정')}</span><span>${esc(n.need)}${n.why&&n.why!==k?`<span class="block text-xs text-slate-400">${esc(n.why)}</span>`:''}</span></li>`).join('')}</ul>
      <div class="mt-4 flex flex-wrap gap-1.5 border-t border-line pt-3">${v.chk.size?[...v.chk].map(t=>pill('✓ '+esc(TL[t]||t),OK)).join(''):pill('공식 데이터 미확인 → 현장 확인',WARN)}</div></div>`).join('')}</div>
      ${(P.considerations||[]).length?`<div class="kcard mt-3"><div class="text-sm font-semibold">코스에 이렇게 반영했어요</div><ul class="mt-2 divide-y divide-line text-[13.5px] text-slate-600">${P.considerations.map(c=>`<li class="py-2"><b class="font-medium text-ink">${esc(c.need)}</b> <span class="text-cel-500">→</span> ${esc(c.how_applied)}</li>`).join('')}</ul><p class="mt-2 text-xs text-slate-400">추정이 틀렸다면 아래에서 이어서 말씀해 주세요.</p></div>`:''}`,'말씀하지 않으셨지만 상황에서 추정했어요')}
  const MP=R.map,hasMap=MP&&(MP.points||[]).length>=2;
  if((P.day_card||[]).length||hasMap){
    const card=(P.day_card||[]).length?`<div class="overflow-hidden rounded-2xl border border-line bg-white"><div class="flex items-center justify-between bg-cel-500 px-5 py-3 text-white"><span class="text-[13px] font-medium">오늘의 카드</span><span class="text-xs opacity-80">${esc(R.visit_date||'')}</span></div><div class="p-5"><div class="text-[15px] font-semibold">${esc(P.title)}</div><ul class="mt-3 space-y-2.5 text-[14px] leading-snug text-slate-700">${P.day_card.map(x=>`<li class="flex gap-2.5"><span class="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-cel-400"></span><span>${esc(x)}</span></li>`).join('')}</ul></div></div><p class="mt-2 text-center text-xs text-slate-400">캡처해 두면 현장에서 바로 볼 수 있어요</p>`:'';
    const legs=hasMap?`<ol class="mt-3 divide-y divide-line rounded-2xl border border-line bg-white">${(MP.legs||[]).map(l=>{const m=MODE[l.mode||'walk'];const alt=l.alternatives||{};return `<li class="px-4 py-3"><div class="flex flex-wrap items-center gap-2 text-[13.5px]"><span class="flex h-8 w-8 items-center justify-center rounded-lg text-base" style="background:${m[2]}14">${m[0]}</span><b class="font-medium">${esc(l.from)} → ${esc(l.to)}</b><span class="pill ${NEU}">${m[1]} ${esc(l.minutes)}분</span>${l.fare_won?pill('약 '+Number(l.fare_won).toLocaleString()+'원'):''}${(l.lines||[]).length?pill(esc(l.lines.join(' → '))):''}</div><div class="mt-1 pl-10 text-xs text-slate-400">${esc(l.why||'')}${Object.keys(alt).length?' · 다른 선택: '+Object.entries(alt).map(([k,v])=>`${(MODE[k]||['',k])[1]} ${v.minutes}분${v.fare_won?' '+Number(v.fare_won).toLocaleString()+'원':''}`).join(', '):''}</div></li>`}).join('')}</ol>
      <p class="mt-2 text-xs text-slate-400">총 이동 ${esc(MP.total_minutes||MP.total_walk_minutes)}분 · 경로 TMAP · 지도 © OpenStreetMap</p>`:'';
    h+=sec('🧭','오늘의 카드와 동선',`<div class="grid items-start gap-4 lg:grid-cols-[320px_1fr]"><div>${card}</div><div>${hasMap?`<div id="map" class="h-80 overflow-hidden rounded-2xl border border-line lg:h-96"></div>`:''}${legs}</div></div>`)}
  if((P.itinerary||[]).length)h+=sec('🗺','일정',`<ol class="relative ml-2 space-y-3 border-l border-cel-200 pl-6">${P.itinerary.map(i=>`<li class="relative"><span class="absolute -left-[31px] top-5 h-3 w-3 rounded-full border-2 border-white bg-cel-500 ring-1 ring-cel-200"></span><div class="kcard !p-4"><div class="flex flex-wrap items-center gap-2"><span class="pill ${OK} !font-semibold">${esc(i.time)}</span><b class="text-[15px] font-semibold">${esc(i.place)}</b>${fn(i.evidence)}</div><p class="mt-1.5 text-[14px] text-slate-600">${esc(i.activity)}</p>${i.access_notes?`<p class="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">♿ ${esc(i.access_notes)}</p>`:''}</div></li>`).join('')}</ol>`);
  if((P.phrase_cards||[]).length)h+=sec('🗣','직원에게 이 화면을 보여주세요',`<div class="grid gap-3 md:grid-cols-2">${P.phrase_cards.map(c=>`<div class="rounded-2xl border border-cel-300 bg-white p-6"><div class="text-xs text-slate-400">${esc(c.person)} · ${esc(c.situation)}</div><p class="mt-3 text-[22px] font-semibold leading-snug">${esc(c.show_to_staff)}</p><p class="mt-3 border-t border-line pt-3 text-[13px] text-slate-500">${esc(c.meaning)}</p></div>`).join('')}</div>`);
  if((P.dietary_plan||[]).length)h+=sec('🍽','식사 안내',`<div class="grid gap-3 md:grid-cols-2">${P.dietary_plan.map(x=>`<div class="kcard"><div class="flex flex-wrap items-center gap-2"><b class="font-semibold">${esc(x.person)}</b>${(x.needs||[]).map(n=>pill(esc(n),BAD)).join('')}${fn(x.evidence)}</div><p class="mt-2 text-[14px] text-slate-600">${esc(x.guidance)}</p>${x.ask_on_site?`<p class="mt-2 text-xs text-slate-400">현장에서 물어볼 것: ${esc(x.ask_on_site)}</p>`:''}</div>`).join('')}</div>`);
  if((P.interpretation||[]).length)h+=sec('📜','이야기',`<div class="grid gap-3 md:grid-cols-2">${P.interpretation.map(x=>`<article class="kcard"><h4 class="text-[16px] font-semibold">${esc(x.place)}${fn(x.evidence)}</h4><p class="mt-2 text-[14px] leading-relaxed text-slate-600">${esc(x.text)}</p>${x.caveats?`<p class="mt-3 border-t border-line pt-3 text-xs text-amber-700">※ ${esc(x.caveats)}</p>`:''}</article>`).join('')}</div>`);
  const DX=x=>typeof x==='string'?esc(x):`<b class="font-medium">${esc(x.question||x.q||x.topic||'')}</b> <span class="text-cel-500">→</span> ${esc(x.choice||x.decision||x.answer||'')} ${x.why||x.reason?`<span class="text-slate-400">(${esc(x.why||x.reason)})</span>`:''}${x.risk_if_wrong?`<div class="text-xs text-amber-700">틀리면: ${esc(x.risk_if_wrong)}</div>`:''}`;
  if((P.scenarios||[]).length||(P.decisions||[]).length)h+=sec('🔀','혹시 이런 경우엔',`${(P.scenarios||[]).length?`<div class="grid gap-3 md:grid-cols-2">${P.scenarios.map(x=>`<div class="kcard !p-4 text-[14px]"><div class="text-xs font-medium text-cel-600">만약</div><div class="font-semibold">${esc(x.if)}</div><div class="mt-2 text-slate-600">→ ${esc(x.then)}${fn(x.evidence)}</div></div>`).join('')}</div>`:''}
    ${(P.decisions||[]).length?`<details class="kcard mt-3"><summary class="cursor-pointer text-sm font-semibold">정보가 불완전할 때 이렇게 판단했어요 <span class="font-normal text-slate-400">(${P.decisions.length})</span></summary><ul class="mt-3 space-y-2 text-[13.5px]">${P.decisions.map(x=>`<li>${DX(x)}</li>`).join('')}</ul></details>`:''}`);
  const unc=P.uncertainties||[],apv=P.approvals_needed||[];
  if(unc.length||apv.length)h+=sec('✅','출발 전에',`<div class="grid gap-3 md:grid-cols-2">${unc.length?`<div class="kcard"><div class="text-sm font-semibold">확인이 필요한 것</div><ul class="mt-3 space-y-2 text-[13.5px]">${unc.map(x=>`<li class="flex gap-2.5"><span class="mt-0.5 h-4 w-4 shrink-0 rounded border border-cel-300"></span><span>${esc(x)}</span></li>`).join('')}</ul></div>`:''}${apv.length?`<div class="kcard"><div class="text-sm font-semibold">에이전트가 하지 않은 일 <span class="font-normal text-slate-400">(승인 필요)</span></div><ul class="mt-3 space-y-2 text-[13.5px]">${apv.map(x=>`<li class="flex gap-2.5"><span class="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-slate-300"></span><span>${esc(x)}</span></li>`).join('')}</ul></div>`:''}</div>`);
  const TC=R.tool_calls||[],TN={wiki:'위키백과',weather:'날씨',tavily:'웹 검색',brave:'웹 검색',naver:'네이버',tour:'관광공사',place_info:'관광공사 운영정보',accessibility:'무장애 정보',kma_weather:'기상청 예보',weather_warning:'기상특보',festival:'행사·축제',nearby:'주변 장소',encyclopedia:'민족문화대백과',route:'동선(TMAP)'};
  if(TC.length)h+=sec('🔎','에이전트가 직접 찾아본 것',`<div class="overflow-hidden rounded-2xl border border-line bg-white"><p class="border-b border-line bg-paper px-5 py-3 text-xs text-slate-500">부족한 정보만 허용된 공식 API로 확인했고, 찾은 결과도 그대로 믿지 않고 다른 자료와 비교했어요.</p><ul class="divide-y divide-line text-[13.5px]">${TC.map(c=>{const a=c.args||{};const q=a.query||a.keyword||a.place||a.topic||(Array.isArray(a.places)?a.places.join(' → '):a.places)||'';return `<li class="flex flex-wrap items-center gap-x-3 gap-y-1 px-5 py-3"><b class="w-32 shrink-0 font-medium">${esc(TN[c.tool]||c.tool)}</b><span class="min-w-0 flex-1 truncate text-slate-500">${esc(q)}</span>${c.ok?`<span class="inline-flex items-center gap-1.5 text-xs text-cel-700"><span class="h-1.5 w-1.5 rounded-full bg-cel-500"></span>성공</span>`:`<span class="inline-flex items-center gap-1.5 text-xs text-rose-600"><span class="h-1.5 w-1.5 rounded-full bg-rose-500"></span>실패</span>`}${c.why?`<span class="w-full text-xs text-slate-400 sm:pl-[140px]">${esc(c.why)}</span>`:''}${c.ok?'':`<span class="w-full text-xs text-rose-500 sm:pl-[140px]">${esc((c.error||'').slice(0,90))}</span>`}</li>`}).join('')}</ul></div>`);
  const srcRow=(i,n)=>{const s=S[i],t=TRUST[s.trust]||['',''];return `<li id="src-${esc(i)}" class="flex gap-3 rounded-xl p-3 transition"><span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-cel-50 text-xs font-semibold text-cel-700">${n}</span><div class="min-w-0"><div class="flex flex-wrap items-center gap-1.5"><b class="break-all font-medium">${s.origin==='external'?'🌐 ':''}${esc(s.label||s.path)}</b>${pill(esc(TYPE[s.source_type]||s.source_type||''))}${t[0]?pill(t[0],t[1]):''}${s.content_date||s.doc_date?pill(esc(s.content_date||s.doc_date)):''}</div>
     ${(s.quotes||[]).map(q=>`<p class="mt-1.5 border-l-2 border-cel-300 pl-2.5 text-[13.5px] text-slate-600">“${esc(q)}”</p>`).join('')}${(s.urls||[]).map(u=>`<a class="mt-1 block truncate text-[13.5px] text-cel-700 hover:underline" href="${esc(u.url)}" target="_blank" rel="noopener">${esc(u.title)}</a>`).join('')}${s.trust_reason?`<p class="mt-1 text-xs text-slate-400">${esc(s.trust_reason)}</p>`:''}</div></li>`};
  const rest=(R.sources||[]).filter(s=>!(s.id in num));
  h+=sec('📚','출처',`<div class="kcard !p-3"><ol class="space-y-0.5">${order.length?order.map((i,k)=>srcRow(i,k+1)).join(''):'<li class="p-3 text-sm text-slate-400">인용된 출처가 없습니다.</li>'}</ol>${rest.length?`<details class="mx-3 mt-2 border-t border-line pb-2 pt-3"><summary class="cursor-pointer text-[13px] text-slate-500">참고했지만 쓰지 않은 자료 ${rest.length}개 · 왜 뺐는지</summary><ul class="mt-3 space-y-2">${rest.map(s=>{const t=TRUST[s.trust]||['',''];return `<li class="text-[13.5px]"><b class="font-medium">${esc(s.label||s.path)}</b> ${pill(esc(TYPE[s.source_type]||s.source_type||''))} ${t[0]?pill(t[0],t[1]):''}<div class="text-xs text-slate-400">${esc(s.trust_reason||'')}</div></li>`}).join('')}</ul></details>`:''}</div>`);
  const SUG=(R.request_type&&R.request_type!=='course')?['어떻게 확인할 수 있어요?','관련 자료를 더 찾아 주세요','이 내용으로 반나절 코스 짜 주세요']:['비가 오면 어떻게 바꿔요?','점심은 어디서 먹을까요?','2시간 안으로 줄여 주세요','아이도 같이 가면요?','이동을 더 줄여 주세요'];
  h+=sec('💬','이어서 물어보기',`<div class="kcard"><div class="flex flex-wrap gap-2">${SUG.map(q=>`<button class="chip" onclick="askFollow(this.textContent)">${esc(q)}</button>`).join('')}</div>
    <div class="mt-4 flex gap-2"><input id="fq" class="field" placeholder="예) 아버지가 오래 못 걸으셔서 택시 위주로 바꿔 주세요" onkeydown="if(event.key==='Enter')askFollow(this.value)"><button class="shrink-0 rounded-xl bg-cel-600 px-5 text-[14px] font-semibold text-white transition hover:bg-cel-700" onclick="askFollow(document.getElementById('fq').value)">보내기</button></div>
    <p class="mt-2 text-xs text-slate-400">이전 초안을 바탕으로 같은 검증 과정을 다시 거쳐 답해요 (약 1분).</p></div>`);
  h+=`<p class="mt-10 rounded-2xl bg-cel-50 px-5 py-4 text-center text-xs leading-relaxed text-cel-800">🛡 이 결과는 NVIDIA OpenShell 보안 샌드박스 안에서 Nemotron이 만들었어요. 허용된 공식 API 외에는 아무것도 외부로 보내지 않고, 자료 속 의심스러운 지시는 따르지 않아요.</p>`;
  $('#res').innerHTML=h;$('#res').hidden=false;$('#dev').hidden=true;
  if(hasMap&&window.L){const m=L.map('map',{scrollWheelZoom:false,zoomControl:true});L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap'}).addTo(m);
    const pts=MP.points.map(p=>[p.lat,p.lon]);
    MP.points.forEach((p,i)=>L.marker([p.lat,p.lon],{icon:L.divIcon({className:'',html:`<div style="background:#4A8270;color:#fff;border-radius:50%;width:28px;height:28px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px;border:3px solid #fff;box-shadow:0 1px 4px rgba(28,39,36,.25)">${i+1}</div>`,iconSize:[28,28],iconAnchor:[14,14]})}).addTo(m).bindPopup(`<b>${i+1}. ${esc(p.name)}</b>`));
    (MP.legs||[]).forEach((l,i)=>{const line=(l.path&&l.path.length>1)?l.path:[pts[i],pts[i+1]];const md=MODE[l.mode||'walk'];L.polyline(line,{color:md[2],weight:5,opacity:.85,dashArray:(l.path&&l.path.length>1)?null:'6 8'}).addTo(m).bindTooltip(`${md[0]} ${md[1]} ${l.minutes}분`)});
    // the container may still be resizing (Tailwind applies styles after insert) — re-measure and re-fit a few times
    const fit=()=>{m.invalidateSize();m.fitBounds(L.latLngBounds(pts).pad(0.25))};fit();[150,500,1200].forEach(t=>setTimeout(fit,t))}
  document.querySelectorAll('sup.fn').forEach(e=>e.onclick=()=>{const t=document.getElementById('src-'+e.dataset.i);if(!t)return;document.querySelectorAll('.src-hl').forEach(x=>x.classList.remove('src-hl'));t.classList.add('src-hl');t.scrollIntoView({behavior:'smooth',block:'center'})});
}
function renderDev(d){
  const R=d.result||{},P=R.plan||{},V=R.resolved||{},A=d.audit||[],src={};(R.sources||[]).forEach(s=>src[s.id]=s.path);
  const ev=ids=>(ids||[]).map(i=>`<span class="tag">${esc(src[i]||i)}</span>`).join('');
  const cnt=k=>A.filter(e=>e.kind===k).length;
  let h=`<h2>${esc(P.title)}</h2><p><span class="tag warn">초안 · 예약/발송하지 않음</span> <span class="tag">${esc(R.lens?.visitor_type)} / ${esc((R.lens?.interests||[]).join(', '))}</span> <span class="tag">방문일 ${esc(R.visit_date)}</span></p><p>${esc(P.summary)}</p>`;
  if((P.day_card||[]).length)h+=`<h2>📱 한눈에 보는 일정 카드</h2><div class="card"><ul>${P.day_card.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>`;
  if((P.phrase_cards||[]).length)h+=`<h2>🗣 현장 직원에게 보여주세요</h2>`+P.phrase_cards.map(c=>`<div class="card" style="border-color:#A6CDBD"><div class="sub">${esc(c.person)} · ${esc(c.situation)}</div><div style="font-size:24px;line-height:1.4;margin:6px 0">${esc(c.show_to_staff)}</div><div class="sub">${esc(c.meaning)}</div></div>`).join('');
  if((P.deliverable_text||'').trim())h+=`<h2>요청 결과물</h2><div class="card" style="white-space:pre-wrap">${esc(P.deliverable_text)}</div>`;
  if((P.decisions||[]).length)h+=`<h2>🧭 핵심 결정 (불완전한 정보에서)</h2><div class="card"><table><tr><th>질문</th><th>선택</th><th>이유</th><th>틀리면</th></tr>${P.decisions.map(d=>`<tr><td>${esc(d.question)}</td><td><b>${esc(d.choice)}</b></td><td>${esc(d.why)}</td><td class="warn">${esc(d.risk_if_wrong)}</td></tr>`).join('')}</table></div>`;
  if((P.scenarios||[]).length)h+=`<h2>🔀 상황별 대안 (Plan B)</h2><div class="card"><ul>${P.scenarios.map(x=>`<li><b>만약</b> ${esc(x.if)} → ${esc(x.then)} ${ev(x.evidence)}</li>`).join('')}</ul></div>`;
  h+=`<h2>일정</h2><div class="card"><table><tr><th>시간</th><th>장소</th><th>활동</th><th>접근·주의</th><th>근거</th></tr>`+(P.itinerary||[]).map(i=>`<tr><td>${esc(i.time)}</td><td>${esc(i.place)}</td><td>${esc(i.activity)}</td><td>${esc(i.access_notes)}</td><td>${ev(i.evidence)}</td></tr>`).join('')+`</table></div>`;
  h+=`<h2>음식 제한</h2>`+(P.dietary_plan||[]).map(x=>`<div class="card"><b>${esc(x.person)}</b> ${(x.needs||[]).map(n=>`<span class="tag bad">${esc(n)}</span>`).join('')}<div>${esc(x.guidance)}</div><div class="sub">현장 확인: ${esc(x.ask_on_site)}</div>${ev(x.evidence)}</div>`).join('');
  h+=`<h2>해설</h2>`+(P.interpretation||[]).map(x=>`<div class="card"><b>${esc(x.place)}</b><div>${esc(x.text)}</div><div class="warn">주의: ${esc(x.caveats)}</div>${ev(x.evidence)}</div>`).join('');
  h+=`<h2>왜 이 정보를 골랐나</h2><div class="card"><table><tr><th>주제</th><th>판정</th><th>상태</th><th>결정 기준</th><th>근거</th><th>버린 자료</th></tr>`+(V.facts||[]).map(f=>`<tr><td>${esc(f.topic)}<br><span class="sub">${esc(f.subject)}</span></td><td>${esc(f.decision)}</td><td class="${f.status==='confirmed'?'ok':'warn'}">${esc(f.status)}</td><td><span class="tag">${esc(f.decided_by)}</span><div class="sub">${esc(f.rationale)}</div></td><td>${ev(f.evidence)}</td><td>${(f.overridden||[]).map(o=>`<div><span class="tag">${esc(src[o.doc]||o.doc)}</span> ${esc(o.reason)}</div>`).join('')}</td></tr>`).join('')+`</table></div>`;
  const li=a=>`<ul>${(a||[]).map(x=>`<li>${x}</li>`).join('')||'<li>없음</li>'}</ul>`;
  const CS=(R.consensus||[]).filter(g=>g.candidates.length>1);
  if(CS.length)h+=`<h2>⚖️ 합의 표 (원문 인용 × 근거 점수)</h2><div class="card"><table><tr><th>주제·속성</th><th>후보 (점수 높은 순)</th><th>정족수 판정 (2/3)</th></tr>`+CS.map(g=>`<tr><td>${esc(g.topic)}<br><span class="sub">${esc(g.attribute)}</span></td><td>${g.candidates.map(c=>`<div><b>${esc(c.value)}</b> <span class="tag">${esc(src[c.doc]||c.doc)}</span> 점수 ${esc(c.score)} ${c.quote_verified?'<span class="ok">✓인용</span>':'<span class="bad">✗인용</span>'}</div>`).join('')}</td><td class="${{confirmed:'ok',tentative:'warn',unresolved:'bad'}[(g.quorum||{}).status]||''}"><b>${{confirmed:'확정',tentative:'잠정',unresolved:'미결'}[(g.quorum||{}).status]||''}</b> ${esc((g.quorum||{}).winner)} (${Math.round(((g.quorum||{}).share||0)*100)}%)</td></tr>`).join('')+`</table></div>`;
  const TV={use:'ok',use_with_caution:'warn',background_only:'sub',ignore:'bad'};
  h+=`<h2>🔎 자료 신뢰 판정</h2><div class="card"><table><tr><th>자료</th><th>종류</th><th>판정</th><th>이유</th></tr>`+(R.sources||[]).map(s=>`<tr><td><span class="tag">${esc(s.path)}</span></td><td>${esc(s.source_type)}</td><td class="${TV[s.trust]||''}"><b>${esc(s.trust)}</b></td><td>${esc(s.trust_reason)}</td></tr>`).join('')+`</table></div>`;
  h+=`<h2>확인 필요 · 승인 필요</h2><div class="card"><b class="warn">확인 필요</b>${li((P.uncertainties||[]).map(esc))}<b>승인 필요 (수행하지 않음)</b>${li((P.approvals_needed||[]).map(esc))}</div>`;
  h+=`<h2>🛡 보안 패널</h2><div class="grid"><div class="stat"><b>${cnt('file_read')}</b>허용된 파일 읽기</div><div class="stat"><b class="bad">${cnt('blocked_read')+cnt('blocked_write')}</b>차단된 파일 접근</div><div class="stat"><b class="bad">${(V.untrusted_instructions||[]).length}</b>무시한 외부 지시</div><div class="stat"><b>${(V.excluded_sources||[]).length}</b>제외한 자료</div><div class="stat"><b class="ok">0</b>외부 전송·예약·발송</div></div>`;
  h+=`<div class="card"><b class="bad">따르지 않은 외부 지시</b>${li((V.untrusted_instructions||[]).map(x=>`<span class="tag">${esc(src[x.doc]||x.doc)}</span> ${esc(x.summary)}`))}<b>제외한 자료</b>${li((V.excluded_sources||[]).map(x=>`<span class="tag">${esc(src[x.doc]||x.doc)}</span> ${esc(x.reason)}`))}</div>`;
  $('#dev').innerHTML=h}
</script></body></html>
"""
