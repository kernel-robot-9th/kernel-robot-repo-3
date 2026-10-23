'use strict';
// 담고 키오스크 — 실제 로봇 연결판 (2026-10-21). 원본 데모: Codex damgo-kiosk (10-15)
// 주문은 같은 PC 의 kiosk_server.py (/api/*) 로만 보낸다. 서버가 pick_loop.py 를 상품별로 차례대로 돌린다.
const products=[{id:'shrimp',name:'새우깡',price:1500,tag:'바삭한 스낵',note:'짭짤하게, 한 봉지의 즐거움',tint:'#f7eee3'},{id:'choco',name:'초코송이',price:1200,tag:'달콤한 간식',note:'작은 초콜릿으로 달콤한 한입',tint:'#f4f1dc'},{id:'drink',name:'게토레이',price:1800,tag:'시원한 음료',note:'가볍게 채우는 상쾌함',tint:'#edf3e6'},{id:'ramen',name:'컵라면',price:1100,tag:'따뜻한 한 끼',note:'출출할 때 생각나는 한 컵',tint:'#f6ede3'}];
const cart=new Map();const $=id=>document.getElementById(id);let busy=false,poll=null,orderView=null;const MAX_QUANTITY=3;
let enabled=new Set();let robotOk=false;
const won=n=>n.toLocaleString('ko-KR')+'원';   // 10-22 가격
const totalPrice=()=>[...cart].reduce((a,[id,q])=>a+products.find(p=>p.id===id).price*q,0);
const art=id=>`<svg aria-hidden="true"><use href="#${id}"/></svg>`;
const avail=p=>enabled.has(p.id);
const quantity=(p,q)=>`<div class="quantity"><button type="button" data-id="${p.id}" data-op="minus" aria-label="${p.name} 한 개 빼기" ${q===0||busy||!avail(p)?'disabled':''}>−</button><output aria-label="${p.name} 선택 수량">${q}</output><button type="button" data-id="${p.id}" data-op="plus" aria-label="${p.name} 한 개 추가" ${q>=MAX_QUANTITY||busy||!avail(p)?'disabled':''}>+</button></div>`;
function render(){
 const focus=document.activeElement;const focusedId=focus?.dataset?.id;const focusedOp=focus?.dataset?.op;const focusContainer=focus?.closest('.cart-list')?'cart-list':'products';
 $('products').innerHTML=products.map(p=>{const q=cart.get(p.id)||0;const ok=avail(p);return `<article class="product-card ${q?'selected':''} ${ok?'':'unavailable'}" style="--tint:${p.tint}"><button type="button" class="product-choice" data-id="${p.id}" data-op="toggle" aria-pressed="${q>0}" aria-label="${p.name} ${ok?(q?'선택 해제':'선택'):'준비 중'}" ${busy||!ok?'disabled':''}><div class="product-art"><span class="product-label">${ok?p.tag:'준비 중'}</span><span class="selected-check" aria-hidden="true">✓</span>${art(p.id)}</div><h3>${p.name} <span class="price">${won(p.price)}</span></h3><p>${ok?p.note:'로봇이 아직 배우는 중이에요'}</p></button><div class="card-footer"><span>${!ok?'곧 만나요':q?'장바구니에 담았어요':'가볍게 하나 담기'}</span>${quantity(p,q)}</div></article>`}).join('');
 $('cart-list').innerHTML=[...cart].map(([id,q])=>{const p=products.find(x=>x.id===id);return `<li class="cart-row"><span class="cart-thumb" style="--tint:${p.tint}">${art(id)}</span><span class="cart-name">${p.name}<small>${won(p.price*q)}</small></span>${quantity(p,q)}</li>`}).join('');
 const total=[...cart.values()].reduce((a,b)=>a+b,0);$('empty-cart').hidden=total>0;$('clear-cart').hidden=total===0;$('clear-cart').disabled=busy;$('basket-count').textContent=total;$('total-count').textContent=total;$('total-price').textContent=won(totalPrice());
 $('order-button').disabled=!total||busy||!robotOk;$('order-button').firstElementChild.textContent=busy?'로봇이 담는 중':!robotOk?'로봇 연결 확인 중':total?'주문하기':'상품을 선택해 주세요';
 if(focusedId&&focusedOp){const el=$(focusContainer).querySelector(`[data-id="${focusedId}"][data-op="${focusedOp}"]`);if(el&&!el.disabled)el.focus({preventScroll:true});}
}
function change(id,op){if(busy)return;const p=products.find(p=>p.id===id);if(!avail(p))return;const q=cart.get(id)||0;const next=op==='toggle'?(q?0:1):op==='plus'?Math.min(q+1,MAX_QUANTITY):Math.max(q-1,0);if(next)cart.set(id,next);else cart.delete(id);render();$('live-message').textContent=`${p.name} ${next}개 선택`;}
for(const id of ['products','cart-list'])$(id).addEventListener('click',e=>{const b=e.target.closest('button[data-id]');if(b&&!b.disabled)change(b.dataset.id,b.dataset.op)});
$('clear-cart').addEventListener('click',()=>{if(busy)return;cart.clear();render();$('live-message').textContent='장바구니를 비웠습니다';});
async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{cache:'no-store'});const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.error||`서버 오류 ${r.status}`);return j;}
async function refreshInfo(){try{const s=await api('/api/status');enabled=new Set(s.enabled||[]);robotOk=true;$('robot-text').textContent=s.order&&s.order.state==='running'?'로봇이 작업 중':'로봇 연결됨';$('robot-dot').classList.add('on');if(s.order&&s.order.state==='running'&&!busy){busy=true;openDialog(s.order);startPoll();}}catch(e){robotOk=false;$('robot-text').textContent='주문 서버에 연결할 수 없어요';$('robot-dot').classList.remove('on');}render();}
function openDialog(o){$('order-dialog').classList.remove('complete','failed');$('order-number').textContent=`ORDER ${o.id}`;$('dialog-action').textContent='다음 상품부터 취소';$('dialog-action').disabled=false;if(!$('order-dialog').open)$('order-dialog').showModal();paint(o);}
async function startOrder(){if(busy||!cart.size)return;const units=[...cart].flatMap(([id,q])=>Array(q).fill(id));const tp=totalPrice();busy=true;render();spoken='';pendingIntro=`총 ${units.length}개, ${won(tp)}입니다. `;try{const o=await api('/api/order',{units});openDialog(o);startPoll();}catch(e){busy=false;render();alert(`주문을 시작하지 못했어요: ${e.message}`);}}
function startPoll(){if(poll)clearInterval(poll);poll=setInterval(async()=>{try{const s=await api('/api/status');if(s.order)paint(s.order);}catch(e){$('progress-label').textContent='서버 응답 없음 · 로봇을 직접 확인해 주세요';}},700);}
const TITLES=['상품을 집고 있어요','장바구니로 이동해요','장바구니에 담아요'];
let spoken='';
let pendingIntro='';
function announce(o){const n=o.units.length,i=Math.min(o.index,n-1),p=products.find(x=>x.id===o.units[i]);const key=o.id+':'+(o.state==='running'?i:o.state);if(key===spoken)return;spoken=key;
 if(o.state==='running'){const t=(n>1?`${i+1}번째, ${p.name} 집을게요.`:`${p.name} 집을게요.`);say(pendingIntro+t);pendingIntro='';}else if(o.state==='done')say('주문하신 상품을 모두 담았어요.');else say(o.message||'담지 못했어요. 직원을 불러 주세요.');}
function paint(o){orderView=o;announce(o);const n=o.units.length,i=Math.min(o.index,n-1),p=products.find(x=>x.id===o.units[i])||products[0];$('active-product').setAttribute('href',`#${p.id}`);
 const phase=o.phase??0;[...$('steps').children].forEach((x,k)=>{x.className=o.state==='done'||k<phase?'done':k===phase?'active':''});
 const doneUnits=o.done_units||0;$('progress-bar').style.width=`${o.state==='done'?100:((doneUnits+phase/3)/n*100)}%`;
 if(o.state==='running'){$('dialog-title').textContent=o.title||TITLES[phase];$('dialog-description').textContent=`${p.name} · ${i+1}번째 상품 / 총 ${n}개`;$('progress-label').textContent=o.message||`${doneUnits} / ${n}개 담기 완료`;$('dialog-action').textContent=o.cancel?'이번 상품까지만 담고 멈춰요':'다음 상품부터 취소';$('dialog-action').disabled=!!o.cancel;}
 else finish(o);}
function finish(o){if(poll){clearInterval(poll);poll=null;}const n=o.units.length;$('dialog-action').disabled=false;
 if(o.state==='done'){$('order-dialog').classList.add('complete');$('dialog-title').textContent='장바구니가 준비됐어요!';$('dialog-description').textContent=`${n}개 상품을 로봇이 담았어요.`;$('progress-label').textContent=o.message||'담기 완료';$('dialog-action').textContent='다음 주문 시작하기';}
 else{$('order-dialog').classList.add('failed');$('dialog-title').textContent=o.state==='cancelled'?'주문을 멈췄어요':'담지 못했어요';$('dialog-description').textContent=`${o.done_units||0} / ${n}개 담기 완료`;$('progress-label').textContent=o.message||'직원을 불러 주세요';$('dialog-action').textContent='확인';}}
async function onAction(){const o=orderView;if(o&&o.state==='running'){try{await api('/api/cancel',{});}catch(e){}return;}busy=false;const ok=o&&o.state==='done';orderView=null;if(ok)cart.clear();$('order-dialog').close();render();}
$('order-button').addEventListener('click',startOrder);$('dialog-action').addEventListener('click',onAction);$('order-dialog').addEventListener('cancel',e=>{e.preventDefault();});
render();refreshInfo();setInterval(()=>{if(!busy)refreshInfo();},5000);

// ---- 음성 주문 (2026-10-21): 크롬 내장 음성 인식(ko-KR)으로 받아쓰기 -> 상품·수량 뽑기 -> 장바구니 -> 확인 뒤 주문 ----
// 말소리는 크롬이 구글 음성 인식 서버로 보낸다(인터넷 필요). 로봇은 확인("주문해" 또는 버튼) 전에는 움직이지 않는다.
const SYN={shrimp:['새우깡','새우 깡','새우','쉬림프'],choco:['초코송이','초코 송이','초코','쪼꼬송이','초콜릿'],drink:['게토레이','게토','이온음료','음료수'],ramen:['컵라면','컵 라면','라면']};
const NUM=[['다섯',5],['넷',4],['네',4],['셋',3],['세',3],['둘',2],['두',2],['하나',1],['한',1]];
function parseOrder(text){
 const s=text.replace(/\s+/g,'');const hits=[];
 for(const [id,words] of Object.entries(SYN)){let best=-1,len=0;for(const w of words){const k=s.indexOf(w.replace(/\s+/g,''));if(k>=0&&(best<0||k<best)){best=k;len=w.replace(/\s+/g,'').length;}}if(best>=0)hits.push({id,at:best,len});}
 hits.sort((a,b)=>a.at-b.at);
 return hits.map((h,i)=>{const seg=s.slice(h.at+h.len,i+1<hits.length?hits[i+1].at:s.length).slice(0,8);let q=1;const m=seg.match(/^\D{0,2}?(\d+)/);if(m)q=parseInt(m[1],10);else for(const [w,n] of NUM){if(seg.startsWith(w)||seg.slice(0,3).includes(w+'개')||seg.slice(0,4).includes(w+'봉')){q=n;break;}}return {id:h.id,q:Math.max(1,q)};});
}
const YES=/^(응|네|예|어|그래|좋아|주문|담아|해줘|ㅇㅇ|맞아|오케이)/, NO=/(아니|취소|다시|싫어|그만)/;
let rec=null,voiceMode='order';
function say(text,then){try{speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(text);u.lang='ko-KR';u.rate=1.05;let done=false;const fin=()=>{if(!done){done=true;if(then)setTimeout(then,300);}};u.onend=fin;u.onerror=fin;speechSynthesis.speak(u);setTimeout(fin,1500+text.length*150);}catch(e){if(then)then();}}
function vtext(t,cls){const el=$('voice-text');el.textContent=t;el.className='voice-text'+(cls?' '+cls:'');}
function setListening(on){$('voice-button').classList.toggle('listening',on);$('voice-label').textContent=on?(voiceMode==='confirm'?'"주문해" 또는 "아니"라고 말해 주세요':'듣고 있어요… 말씀해 주세요'):'말로 주문하기';}
function listen(mode){
 const SR=window.SpeechRecognition||window.webkitSpeechRecognition;if(!SR){vtext('이 브라우저는 음성 인식을 지원하지 않아요 (크롬에서 열어 주세요)','warn');return;}
 if(busy)return;voiceMode=mode;const r=new SR();rec=r;r.lang='ko-KR';r.interimResults=true;r.maxAlternatives=1;let finalText='',lastText='';
 r.onresult=e=>{if(rec!==r)return;let t='';for(const r of e.results)t+=r[0].transcript;lastText=t;vtext(`"${t}"`,'heard');if(e.results[e.results.length-1].isFinal)finalText=t;};
 r.onerror=e=>{if(rec!==r)return;setListening(false);if(e.error==='aborted'){vtext('듣기가 끊겼어요. 버튼을 다시 눌러 주세요','warn');return;}vtext(e.error==='network'?'음성 인식 서버에 연결하지 못했어요 (인터넷 확인)':e.error==='not-allowed'?'마이크 사용을 허용해 주세요 (주소창 왼쪽 자물쇠 → 마이크)':e.error==='no-speech'?'아무 말도 안 들렸어요. 다시 눌러 주세요':`음성 인식 오류: ${e.error}`,'warn');};
 // 10-21 진단: 단계마다 화면에 표시 (조용히 끝나면 어디서 막혔는지 몰랐음)
 let heardSound=false;
 r.onstart=()=>{if(rec===r)vtext('마이크 켜짐 · 말씀해 주세요');};
 r.onaudiostart=()=>{if(rec===r)vtext('마이크 소리 받는 중…');};
 r.onsoundstart=()=>{heardSound=true;if(rec===r)vtext('소리가 들려요…');};
 r.onspeechstart=()=>{if(rec===r)vtext('말소리 인식 중…');};
 r.onend=()=>{if(rec!==r)return;rec=null;setListening(false);const t=(finalText||lastText).trim();if(t)handleSpeech(t);else if($('voice-text').className.indexOf('warn')<0)vtext(heardSound?'소리는 들렸는데 말을 알아듣지 못했어요. 또박또박 다시 말해 주세요':'마이크로 소리가 안 들어왔어요 (마이크 켜짐·입력 장치 확인)','warn');};
 try{r.start();setListening(true);}catch(e){vtext('음성 인식을 시작하지 못했어요','warn');}
}
function cartSummary(){return [...cart].map(([id,q])=>`${products.find(p=>p.id===id).name} ${q}개`).join(', ');}
function handleSpeech(t){
 if(voiceMode==='confirm'){
  if(NO.test(t)){cart.clear();render();vtext(`"${t}" → 주문을 취소했어요. 다시 말씀해 주세요`,'warn');say('취소했어요. 다시 말씀해 주세요.');voiceMode='order';return;}
  if(YES.test(t.replace(/\s+/g,''))||/주문/.test(t)){vtext(`"${t}" → 주문할게요`,'heard');say('주문할게요. 로봇이 담아 드릴게요.');startOrder();voiceMode='order';return;}
  vtext(`"${t}" → 잘 못 알아들었어요. "주문해" 또는 "아니"라고 말하거나 버튼을 눌러 주세요`,'warn');say('주문해 또는 아니라고 말씀해 주세요.',()=>{if(!busy&&voiceMode==='confirm')listen('confirm');});return;}
 const items=parseOrder(t);
 if(!items.length){vtext(`"${t}" → 상품 이름을 못 찾았어요. 새우깡이나 초코송이를 말씀해 주세요`,'warn');say('상품 이름을 못 알아들었어요. 다시 말씀해 주세요.');return;}
 const soon=items.filter(x=>!enabled.has(x.id)).map(x=>products.find(p=>p.id===x.id).name);
 const ok=items.filter(x=>enabled.has(x.id));
 cart.clear();for(const x of ok)cart.set(x.id,Math.min(x.q,MAX_QUANTITY));render();
 const over=ok.some(x=>x.q>MAX_QUANTITY)?` (한 상품은 최대 ${MAX_QUANTITY}개)`:'';
 const soonMsg=soon.length?`${soon.join(', ')}는 아직 준비 중이에요. `:'';
 if(!cart.size){vtext(`"${t}" → ${soonMsg}담을 수 있는 상품이 없어요`,'warn');say(soonMsg+'담을 수 있는 상품이 없어요.');return;}
 const sum=cartSummary();
 // 10-21 사용자 요청: 되묻지 말고 바로 주문
 vtext(`"${t}" → ${soonMsg}${sum}${over} 담을게요`,'heard');if(soonMsg)say(soonMsg);startOrder();
}
$('voice-button').addEventListener('click',()=>{if(rec){const r=rec;try{r.stop();}catch(e){}return;}  // 듣는 중에 누르면 멈추고 들은 데까지 처리
 if(busy)return;speechSynthesis.cancel();voiceMode='order';
 // 10-21 사용자 요청: 버튼을 누르면 먼저 묻고, 질문이 끝나면 듣기 시작
 vtext('무엇을 주문하시겠습니까?','heard');$('voice-label').textContent='질문하는 중…';$('voice-button').disabled=true;
 say('무엇을 주문하시겠습니까?',()=>{$('voice-button').disabled=false;if(!busy)listen('order');});});
