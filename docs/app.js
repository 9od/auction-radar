'use strict';
const A = window.Auction, $ = id => document.getElementById(id), esc = A.escape;
let listing = {}, archive = {}, groups = {active:[],done:[],pending:[]}, tab = 'active', shown = [], current = null;
const STORAGE = 'auction_personal_v2';
let personal = {memos:{},excluded:[],projectUrl:''};
function readStored(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) || fallback; } catch { return fallback; } }
const stored = readStored(STORAGE, null);
if (stored && stored.memos && Array.isArray(stored.excluded)) personal = stored;
const legacyMemos = readStored('auction_memos_v1', {}), legacyExcluded = readStored('auction_excluded_v1', []);
let toastTimer;
function toast(message) { $('toast').textContent=message; $('toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('toast').hidden=true,5500); }
function persist() { try { localStorage.setItem(STORAGE,JSON.stringify(personal)); return true; } catch { toast('브라우저에 저장하지 못했습니다. 백업 파일을 받아 주세요.'); return false; } }
function migratePersonal(items) {
  let changed=false;
  for (const i of items) {
    const oldKey = i.사건번호_원문;
    if (!oldKey) continue;
    if (legacyMemos[oldKey] && !personal.memos[i.id]) { personal.memos[i.id]=legacyMemos[oldKey]; changed=true; }
    if (!personal.migratedLegacy && legacyExcluded.includes(oldKey) && !personal.excluded.includes(i.id)) { personal.excluded.push(i.id); changed=true; }
  }
  if (!personal.migratedLegacy) { personal.migratedLegacy=true; changed=true; }
  if (changed) persist();
}
async function fetchJson(file) {
  const url = new URL(file,document.baseURI); url.searchParams.set('t',Date.now());
  const r = await fetch(url,{cache:'no-store'});
  if (!r.ok) throw new Error(`${file} 응답 오류 (${r.status})`);
  const json = await r.json();
  if (!json || !Array.isArray(json.items)) throw new Error(`${file} 데이터 형식 오류`);
  return json;
}
async function load() {
  $('refresh').disabled=true;
  const responses=await Promise.allSettled([fetchJson('auction_data.json'),fetchJson('auction_archive.json')]);
  const warnings=[];
  if (responses[0].status==='fulfilled') listing=responses[0].value; else warnings.push('진행 목록을 불러오지 못했습니다.');
  if (responses[1].status==='fulfilled') archive=responses[1].value; else warnings.push('누적 기록을 불러오지 못했습니다.');
  groups=A.views(listing,archive);
  migratePersonal([...groups.active,...groups.done,...groups.pending]);
  const report=listing.수집상태;
  if (!report || !report.전체성공) warnings.push('확대 지역 수집이 모두 확인되지 않았습니다. 마지막 저장 자료를 표시합니다.');
  if (listing.수집일시 && A.day(listing.수집일시)<A.today()) warnings.push('수집일이 지난 자료입니다. 현재 기일과 상태를 다시 확인하세요.');
  $('notice').textContent=warnings.join(' '); $('notice').hidden=!warnings.length;
  $('updated').textContent=`마지막 자료 ${listing.수집일시 || '미확인'}`;
  for (const key of ['active','done','pending']) $('count-'+key).textContent=groups[key].length;
  $('stat-active').textContent=groups.active.length;
  $('stat-done').textContent=groups.done.length;
  const rates=groups.done.map(i=>i.낙찰가율).filter(Number.isFinite);
  $('stat-rate').textContent=rates.length ? A.rate(rates.reduce((a,b)=>a+b,0)/rates.length) : '미확인';
  const details=(report?.상세 || []);
  $('collection-details').innerHTML=details.length ? details.map(r=>`<div class="report-row">${esc(r.법원 || '전체')} · ${esc(r.종류)} · ${r.성공 ? `확인 (${r.조회건수 ?? r.확인건수 ?? 0}건)` : '미완료 — '+esc(r.오류 || '확인 필요')}</div>`).join('') : '<p>확대 범위의 첫 수집 실행을 기다리고 있습니다.</p>';
  render(); $('refresh').disabled=false;
}
function render() {
  const query=$('search').value.trim().toLowerCase(), area=$('region').value, district=$('district').value, budget=Number($('budget').value);
  $('district-label').hidden=area!=='서울';
  shown=groups[tab].filter(i=>{
    if (!$('show-excluded').checked && personal.excluded.includes(i.id)) return false;
    if (area && i.지역!==area) return false;
    if (area==='서울' && district && !i.주소.includes(district)) return false;
    if (i.최저입찰가>budget) return false;
    return !query || `${i.주소} ${i.법원} ${i.사건번호} ${(i.관련사건 || []).join(' ')}`.toLowerCase().includes(query);
  });
  const sort=$('sort').value;
  shown.sort((a,b)=>sort==='price' ? a.최저입찰가-b.최저입찰가 : sort==='rate' ? (tab==='done' ? (a.낙찰가율 ?? Infinity)-(b.낙찰가율 ?? Infinity) : (a.최저입찰가율 ?? Infinity)-(b.최저입찰가율 ?? Infinity)) : sort==='area' ? b.전용면적-a.전용면적 : (tab==='active' ? 1 : -1)*(a.매각일 || '').localeCompare(b.매각일 || ''));
  $('result-count').textContent=`${shown.length}건${area ? ' · '+area : ''}${tab==='done' ? ' · 낙찰가율은 실제 낙찰가 기준' : ''}`;
  $('empty').hidden=shown.length>0;
  $('rows').innerHTML=shown.map((i,index)=>{
    const done=tab==='done', rate=done ? i.낙찰가율 : i.최저입찰가율;
    return `<tr class="${personal.excluded.includes(i.id)?'excluded':''}">
      <td><button class="apt-name" data-detail="${index}">${esc(A.name(i))}</button><p class="address">${esc(i.주소)}</p><p class="area-line">전용 ${esc(i.전용면적)}㎡ <span class="muted">· ${esc(i.지역)}</span></p><p class="case-line">${esc(i.법원)} · ${esc(i.사건번호)}${i.물건번호 ? ' · 물건 '+esc(i.물건번호) : ''}${personal.memos[i.id] ? ' · 메모 있음' : ''}</p></td>
      <td><span class="price">${esc(A.won(i.최저입찰가))}</span><span class="secondary">감정 ${esc(A.won(i.감정가))}</span></td>
      <td><span class="rate ${done?'sale':''}">${esc(A.rate(rate))}</span><span class="secondary">${done?'낙찰가율':'최저입찰가율'}</span></td>
      <td><span class="date">${esc(i.매각일 || '기일 미확인')}</span><br><span class="status ${done?'good':tab==='pending'?'warn':''}">${esc(i.진행상황 || '확인 필요')}</span>${tab==='pending'?'<span class="secondary">최신 결과 재확인 필요</span>':''}</td>
      <td>${done?`<strong>${i.낙찰가?'낙찰 '+esc(A.won(i.낙찰가)):'낙찰가 미확인 / 해당 없음'}</strong>`:''}<div class="row-actions"><button data-detail="${index}">상세</button><button data-analysis="${index}" class="primary">ChatGPT 분석 ↗</button></div></td>
    </tr>`;
  }).join('');
}
function showDetail(index, analysis=false) {
  current=shown[index]; if(!current) return;
  const i=current;
  $('detail-region').textContent=i.지역;
  $('detail-title').textContent=A.name(i);
  $('detail-address').textContent=i.주소;
  const fields=[['법원',i.법원],['사건번호',i.사건번호],['물건번호',i.물건번호 || '미확인'],['전용면적',i.전용면적+'㎡'],['감정가',A.won(i.감정가)],['최저입찰가',A.won(i.최저입찰가)],['매각일',i.매각일 || '미확인'],['진행상황',i.진행상황 || '미확인'],['낙찰가 / 낙찰가율',`${A.won(i.낙찰가)} / ${A.rate(i.낙찰가율)}`]];
  $('detail-fields').innerHTML=fields.map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('');
  $('map-link').href='https://map.kakao.com/link/search/'+encodeURIComponent(i.주소);
  $('analysis-prompt').value=A.prompt(i);
  $('memo').value=personal.memos[i.id]?.text || '';
  $('memo-price').value=personal.memos[i.id]?.price || '';
  $('exclude').textContent=personal.excluded.includes(i.id)?'제외 해제':'목록에서 제외';
  $('history').innerHTML=(i.이력 || []).slice().sort((a,b)=>(b.매각일 || '').localeCompare(a.매각일 || '')).map(h=>`<div class="history-row"><strong>${esc(h.매각일 || '기일 미확인')} · ${esc(h.진행상황 || '미확인')}</strong><br>최저 ${esc(A.won(h.최저입찰가))}${h.낙찰가?' · 낙찰 '+esc(A.won(h.낙찰가))+' ('+esc(A.rate(h.낙찰가율))+')':''}<span class="secondary">확인 ${esc(h.확인시각 || '')}</span></div>`).join('') || '<p>추가 회차 기록이 없습니다.</p>';
  $('detail-dialog').showModal();
  if(analysis) $('analysis-prompt').focus();
}
async function copyPrompt() {
  try { await navigator.clipboard.writeText($('analysis-prompt').value); toast('질문을 복사했습니다. 프로젝트에 붙여넣어 주세요.'); return true; }
  catch { $('analysis-prompt').focus(); $('analysis-prompt').select(); toast('자동 복사를 사용할 수 없습니다. 선택된 질문을 Ctrl+C로 복사해 주세요.'); return false; }
}
function download(data,filename) {
  const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
  const link=document.createElement('a');link.href=url;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function settings() { $('project-url').value=personal.projectUrl || ''; $('settings-dialog').showModal(); }
$('rows').addEventListener('click',e=>{const button=e.target.closest('[data-detail],[data-analysis]');if(button) showDetail(Number(button.dataset.detail ?? button.dataset.analysis),button.hasAttribute('data-analysis'));});
const tabs=[...document.querySelectorAll('[data-tab]')];
function selectTab(button) {
  tab=button.dataset.tab;
  for(const b of tabs){b.setAttribute('aria-selected',String(b===button));b.tabIndex=b===button?0:-1;}
  $('results').setAttribute('aria-labelledby',button.id);render();
}
tabs.forEach((b,index)=>{b.addEventListener('click',()=>selectTab(b));b.addEventListener('keydown',e=>{let next;if(e.key==='ArrowRight')next=(index+1)%tabs.length;if(e.key==='ArrowLeft')next=(index+tabs.length-1)%tabs.length;if(e.key==='Home')next=0;if(e.key==='End')next=tabs.length-1;if(next!==undefined){e.preventDefault();selectTab(tabs[next]);tabs[next].focus();}});});
for(const id of ['search','region','district','budget','sort','show-excluded']) $(id).addEventListener('input',render);
$('reset').addEventListener('click',()=>{$('search').value='';$('region').value='';$('district').value='';$('budget').value='1500000000';$('sort').value='date';$('show-excluded').checked=false;render();});
$('refresh').addEventListener('click',load);
$('settings-open').addEventListener('click',settings);
$('copy-prompt').addEventListener('click',copyPrompt);
$('open-project').addEventListener('click',()=>{
  const url=A.projectUrl(personal.projectUrl);
  if(!url){settings();toast('집구하기 프로젝트 주소를 먼저 저장해 주세요.');return;}
  // Open synchronously during the user gesture. No unsupported auto-send/project API.
  copyPrompt();window.open(url,'_blank','noopener,noreferrer');
});
$('save-settings').addEventListener('click',()=>{
  const value=$('project-url').value.trim(), valid=A.projectUrl(value);
  if(value && !valid){toast('ChatGPT 프로젝트 주소를 확인해 주세요. https://chatgpt.com/g/g-p-…/project 형식입니다.');return;}
  personal.projectUrl=valid;if(persist()){$('settings-dialog').close();toast('프로젝트 주소를 저장했습니다.');}
});
$('save-memo').addEventListener('click',()=>{
  if(!current)return;
  if(!$('memo-price').checkValidity()){$('memo-price').reportValidity();return;}
  personal.memos[current.id]={text:$('memo').value,price:$('memo-price').value,savedAt:new Date().toISOString()};
  if(persist()){toast('메모를 저장했습니다.');render();}
});
$('exclude').addEventListener('click',()=>{if(!current)return;const id=current.id;personal.excluded=personal.excluded.includes(id)?personal.excluded.filter(k=>k!==id):[...personal.excluded,id];if(persist()){$('detail-dialog').close();render();}});
$('export').addEventListener('click',()=>{if(!Array.isArray(archive.items)){toast('누적 기록을 먼저 불러와 주세요.');return;}download(archive,'auction-archive-'+A.today()+'.json');});
$('export-personal').addEventListener('click',()=>download({schema_version:2,...personal},'auction-personal-'+A.today()+'.json'));
$('import-personal').addEventListener('change',async e=>{
  try {
    const file=e.target.files[0];if(!file)return;if(file.size>5000000)throw new Error('파일 크기 초과');
    const data=JSON.parse(await file.text());
    if(data.schema_version!==2 || !data.memos || typeof data.memos!=='object' || Array.isArray(data.memos) || !Array.isArray(data.excluded) || !data.excluded.every(x=>typeof x==='string'))throw new Error('백업 형식 오류');
    const memos={};for(const [k,v] of Object.entries(data.memos)){if(['__proto__','constructor','prototype'].includes(k) || !v || typeof v.text!=='string')throw new Error('메모 형식 오류');memos[k]={text:v.text,price:String(v.price || ''),savedAt:String(v.savedAt || '')};}
    personal={memos:{...personal.memos,...memos},excluded:[...new Set([...personal.excluded,...data.excluded])],projectUrl:A.projectUrl(data.projectUrl)||personal.projectUrl,migratedLegacy:true};
    if(persist()){render();toast('백업을 복원했습니다.');}
  } catch {toast('백업 파일을 읽지 못했습니다. 경매레이더 개인 백업 JSON인지 확인해 주세요.');}
  e.target.value='';
});
for(const button of document.querySelectorAll('[data-close]'))button.addEventListener('click',()=>$(button.dataset.close).close());
for(const dialog of document.querySelectorAll('dialog'))dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}});
const districts=['강남구','강동구','강북구','강서구','관악구','광진구','구로구','금천구','노원구','도봉구','동대문구','동작구','마포구','서대문구','서초구','성동구','성북구','송파구','양천구','영등포구','용산구','은평구','종로구','중구','중랑구'];
for(const district of districts){const option=document.createElement('option');option.value=option.textContent=district;$('district').append(option);}
load();
