/* Shared, dependency-free presentation rules (also exercised by Node tests). */
(function(root) {
  'use strict';
  const positive = n => Number.isFinite(Number(n)) && Number(n) > 0 ? Number(n) : null;
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function day(value) {
    const m = String(value || '').match(/(20\d{2})[.\-/]?(\d{2})[.\-/]?(\d{2})/);
    return m ? `${m[1]}-${m[2]}-${m[3]}` : '';
  }
  function today() { return new Intl.DateTimeFormat('sv-SE', {timeZone:'Asia/Seoul'}).format(new Date()); }
  function region(address) {
    const a = address || '';
    if (a.includes('위례') || (a.includes('하남시') && a.includes('학암동'))) return '위례';
    if (/^서울(?:특별시|시)?\s/.test(a)) return '서울';
    for (const c of ['수원','안양','과천','하남']) if (new RegExp(`(?:^|\\s)${c}시\\s`).test(a)) return c;
    if (a.includes('용인시') && a.includes('수지구')) return '용인 수지';
    if (a.includes('성남시') && a.includes('분당구')) return '성남 분당·판교';
    return '';
  }
  function normalized(raw) {
    const i = {...raw};
    const original = String(i.사건번호 || '');
    const m = original.match(/\d{4}\s*타경\s*\d+?(?=\d{4}\s*타경|[^\d]|$)/);
    i.사건번호_원문 = i.사건번호_원문 || original;
    i.사건번호 = m ? m[0].replace(/\s/g,'') : original;
    i.법원 = i.법원 || (m ? original.slice(0,m.index).trim() : '법원 미확인');
    i.주소 = i.주소 || String(i.소재지 || '').split('[')[0].replace(/\s+/g,' ').trim();
    i.지역 = i.지역 || region(i.주소);
    i.매각일 = day(i.매각일 || i.매각기일);
    i.전용면적 = positive(i.전용면적);
    for (const field of ['감정가','최저입찰가','낙찰가']) i[field] = positive(i[field]);
    i.최저입찰가율 = i.감정가 && i.최저입찰가 ? i.최저입찰가 / i.감정가 * 100 : null;
    i.낙찰가율 = i.감정가 && i.낙찰가 ? i.낙찰가 / i.감정가 * 100 : null;
    i.id = i.id || [i.법원,i.사건번호,i.물건번호 || i.주소].join('|');
    return i;
  }
  function scope(i) {
    return !!(region(i.주소) && i.용도 === '아파트' && i.전용면적 >= 84 && i.전용면적 <= 135 && i.최저입찰가 > 0 && i.최저입찰가 <= 1500000000);
  }
  function state(i, date=today()) {
    const s = i.진행상황 || '';
    if (/불허가|미납|재매각/.test(s)) return 'pending';
    if (/매각|낙찰|대금납부|배당|종결/.test(s) && !/매각기일|매각예정/.test(s)) return 'done';
    if (/취하|취소|기각|각하/.test(s)) return 'done';
    if (/변경|연기|정지/.test(s) || !i.매각일 || i.매각일 < date || i.재확인필요) return 'pending';
    return 'active';
  }
  function views(listing, archive, date=today()) {
    const history = (archive.items || []).map(normalized);
    const merged = new Map(history.map(i => [i.id, {...i, 재확인필요:true}]));
    for (const raw of listing.items || []) {
      const item = normalized(raw);
      const saved = history.find(h => h.id === item.id || (h.법원 === item.법원 && h.사건번호 === item.사건번호 && h.주소 === item.주소));
      if (saved) {
        // Archive can contain confirmed results newer than the last listing snapshot.
        merged.set(saved.id, {...item,...saved, 재확인필요: item.재확인필요 || false});
      } else merged.set(item.id, item);
    }
    const done = new Map(), active = [], pending = [];
    for (const i of merged.values()) {
      // The archive preserves records even after they stop matching the current budget.
      for (const h of i.이력 || []) {
        const event = normalized({...i,...h, 이력:i.이력, 재확인필요:false});
        if (scope(event) && state(event,date) === 'done') {
          const key = i.id + ':' + event.매각일;
          const previous = done.get(key);
          if (!previous || event.낙찰가 || !previous.낙찰가) done.set(key, {...event, viewId:key});
        }
      }
      if (!scope(i)) continue;
      const s = state(i,date);
      if (s === 'done') done.set(i.id+':'+i.매각일, {...i, viewId:i.id+':'+i.매각일});
      else (s === 'active' ? active : pending).push(i);
    }
    return {active, pending, done:[...done.values()]};
  }
  function name(i) {
    const a = i.주소 || '';
    const matches = [...a.matchAll(/\(([^)]+)\)/g)];
    if (matches.length) return matches[matches.length-1][1].split(',').pop().trim();
    const m = a.match(/\s([^\s]+(?:아파트|마을|자이|푸르지오|래미안|힐스테이트|베르디움)[^\s]*)/);
    return m ? m[1] : a.split(' ').slice(2).join(' ') || '주소 확인 필요';
  }
  function won(n) {
    if (!positive(n)) return '미확인';
    const eok = Math.floor(n / 1e8), man = Math.round(n % 1e8 / 1e4);
    return eok ? `${eok}억${man ? ' '+man.toLocaleString('ko-KR')+'만' : ''}` : `${man.toLocaleString('ko-KR')}만`;
  }
  function rate(n) { return Number.isFinite(n) ? `${n.toFixed(1)}%` : '미확인'; }
  function projectUrl(value) {
    if (!value) return '';
    try { const u = new URL(value); return u.protocol === 'https:' && u.hostname === 'chatgpt.com' && /^\/g\/g-p-[a-zA-Z0-9-]+(?:\/project)?\/?$/.test(u.pathname) ? u.origin+u.pathname : ''; } catch { return ''; }
  }
  function prompt(i) {
    return `${i.법원} ${i.사건번호}${i.물건번호 ? ' (물건번호 '+i.물건번호+')' : ''}\n${i.주소}\n\n이 아파트 경매 물건을 실거주 집 구하기 관점에서 검색해서 철저히 분석해줘.\n수집 정보: 전용 ${i.전용면적}㎡, 감정가 ${won(i.감정가)}, 현재 최저입찰가 ${won(i.최저입찰가)}, 매각일 ${i.매각일 || '미확인'}, 진행상황 ${i.진행상황 || '미확인'}.${i.낙찰가 ? '\n확인된 낙찰가 '+won(i.낙찰가)+' (감정가 대비 '+rate(i.낙찰가율)+').' : ''}\n\n최신 진행상황, 동일 평형·층의 실거래/호가, 권리관계와 인수할 임차보증금, 명도, 대출·부대비용, 교통·학교·주거환경을 확인해줘. 적정 입찰가와 필요한 자기자금을 근거와 함께 제시하고, 확인된 사실과 추가 확인이 필요한 내용을 구분해줘. 수집 정보가 오래됐을 수 있으니 법원 원문을 먼저 확인해줘.`;
  }
  const api = {positive, escape, day, today, region, normalized, scope, state, views, name, won, rate, projectUrl, prompt};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.Auction = api;
})(typeof window !== 'undefined' ? window : globalThis);
