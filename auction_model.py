"""Filtering and append-only auction observations; no network or browser dependency."""
import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / 'auction_config.json').read_text(encoding='utf-8'))
KST = ZoneInfo('Asia/Seoul')
CASE_RE = re.compile(r'\d{4}\s*타경\s*\d+?(?=\d{4}\s*타경|[^\d]|$)')


def now_kst():
    return datetime.now(KST).isoformat(timespec='seconds')


def date_only(value):
    m = re.search(r'(20\d{2})[.\-/]?(\d{2})[.\-/]?(\d{2})', str(value or ''))
    if not m:
        return None
    try:
        return datetime(*map(int, m.groups())).date().isoformat()
    except ValueError:
        return None


def amount(value):
    """Never concatenate a percentage or a second amount into a price."""
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None
    text = re.sub(r'\([^)]*\)', '', str(value or '')).strip()
    if not re.fullmatch(r'[\d,]+\s*원?', text):
        return None
    n = int(re.sub(r'\D', '', text))
    return n if n > 0 else None


def region_of(address):
    text = str(address or '')
    # 위례 spans 송파구, 성남 수정구 and 하남 학암동.
    if '위례' in text or ('하남시' in text and '학암동' in text):
        return '위례'
    if re.match(r'^서울(?:특별시|시)?\s', text):
        return '서울'
    for city in ('수원', '안양', '과천', '하남'):
        if re.search(rf'(?:^|\s){city}시\s', text):
            return city
    if '용인시' in text and '수지구' in text:
        return '용인 수지'
    if '성남시' in text:
        return '성남 전체'
    return None


def normalize(item):
    item = deepcopy(item)
    raw_case = str(item.get('사건번호', ''))
    item.setdefault('사건번호_원문', raw_case)
    cases = [re.sub(r'\s', '', m.group()) for m in CASE_RE.finditer(raw_case)]
    if cases:
        item['사건번호'] = cases[0]
        item['관련사건'] = sorted(set(item.get('관련사건', []) + cases[1:]))
    if not item.get('법원'):
        item['법원'] = raw_case.split(cases[0][:4])[0].strip() if cases else ''
    item['법원'] = {'수원지방법원 성남지원': '성남지원', '수원지방법원 안양지원': '안양지원'}.get(item['법원'], item['법원'])
    item['주소'] = re.sub(r'\s+', ' ', str(item.get('소재지', '')).split('[')[0]).strip()
    item['지역'] = region_of(item['주소'])
    item['매각일'] = date_only(item.get('매각일') or item.get('매각기일'))
    item['전용면적'] = float(item['전용면적']) if item.get('전용면적') else None
    for key in ('감정가', '최저입찰가', '낙찰가'):
        item[key] = amount(item.get(key))
    item['최저입찰가율'] = round(item['최저입찰가'] / item['감정가'] * 100, 2) if item['감정가'] and item['최저입찰가'] else None
    item['낙찰가율'] = round(item['낙찰가'] / item['감정가'] * 100, 2) if item['감정가'] and item['낙찰가'] else None
    item['전용평'] = round(item['전용면적'] / 3.305785, 1) if item['전용면적'] else None
    # Court + primary case + lot. Legacy records without lot use normalized address.
    identity = str(item.get('물건번호') or item['주소'])
    key = '|'.join((item['법원'], item.get('사건번호', ''), identity))
    item['id'] = hashlib.sha256(key.encode()).hexdigest()[:24]
    return item


def in_scope(item, config=CONFIG, check_price=True):
    a = item.get('전용면적')
    return bool(region_of(item.get('주소') or item.get('소재지'))
                and item.get('용도') == '아파트'
                and a is not None and config['min_area_m2'] <= a <= config['max_area_m2']
                and (not check_price or (item.get('최저입찰가') is not None
                     and 0 < item['최저입찰가'] <= config['max_price'])))


def state_of(item, today=None):
    status = str(item.get('진행상황') or '')
    if any(word in status for word in ('불허가', '미납', '재매각')):
        return '확인필요'
    if re.search(r'매각|낙찰|대금납부|배당|종결', status) and not re.search(r'매각기일|매각예정', status):
        return '완료'
    if any(word in status for word in ('취하', '취소', '기각', '각하')):
        return '종료'
    if any(word in status for word in ('변경', '연기', '정지')):
        return '확인필요'
    day = today or datetime.now(KST).date().isoformat()
    return '확인필요' if not item.get('매각일') or item['매각일'] < day else '진행'


def empty_archive():
    return {'schema_version': 2, '설명': '관심 경매 물건과 회차별 관측을 누적 보관합니다. 목록에서 사라졌다는 이유만으로 낙찰 처리하지 않습니다.', 'items': []}


OBSERVATION_KEYS = ('매각일', '진행상황', '감정가', '최저입찰가', '낙찰가', '낙찰가율', '결과출처')


def merge_archive(archive, incoming, observed_at=None):
    """Preserve all old records and distinct round/result observations, idempotently."""
    result = deepcopy(archive)
    records = {i['id']: deepcopy(i) for i in result.get('items', [])}
    stamp = observed_at or now_kst()
    for raw in incoming:
        item = normalize(raw)
        old = records.get(item['id'])
        if not old:
            # Migrate legacy identity only when address + court + case match uniquely.
            matches = [r for r in records.values() if r['법원'] == item['법원'] and r['사건번호'] == item['사건번호'] and r['주소'] == item['주소']]
            if len(matches) == 1:
                old = matches[0]
                del records[old['id']]
        if not old and not in_scope(item):
            continue
        first = old.get('최초수집', stamp) if old else stamp
        history = deepcopy(old.get('이력', [])) if old else []
        # Missing result fields in a listing do not erase confirmed prices for the same round.
        if old and old.get('매각일') == item.get('매각일'):
            for field in ('낙찰가', '낙찰가율', '결과출처'):
                if not item.get(field) and old.get(field):
                    item[field] = old[field]
        event = {k: item.get(k) for k in OBSERVATION_KEYS}
        if not any(all(h.get(k) == event[k] for k in OBSERVATION_KEYS) for h in history):
            history.append(dict(event, 확인시각=stamp))
        # Replaying old rounds enriches history without replacing the newer listing.
        is_older = old and old.get('매각일') and item.get('매각일') and item['매각일'] < old['매각일']
        latest = dict(item, **old) if is_older else dict(old or {}, **item)
        latest['id'] = item['id']
        records[item['id']] = dict(latest, 최초수집=first, 최종확인=stamp, 이력=history)
    result['items'] = sorted(records.values(), key=lambda i: (i['법원'], i['사건번호'], i['id']))
    result['갱신일시'] = stamp
    result['총건수'] = len(result['items'])
    return result


def load_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return deepcopy(default)
    # Corrupt history must stop the run, never silently start an empty archive.
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)
