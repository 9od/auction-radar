#!/usr/bin/env python3
"""Court auction collector: scoped listings, recent results and durable observations."""
import argparse
import json
import re
import sys
import time
from pathlib import Path
from lxml import html
from auction_model import (CONFIG, amount, date_only, empty_archive, in_scope,
                           load_json, merge_archive, normalize, now_kst, state_of, write_json)

BASE = 'https://www.courtauction.go.kr'
SEARCH_URL = BASE + '/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ151F00.xml'
RESULT_URL = BASE + '/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ158M00.xml'
CASE_URL = BASE + '/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ159M00.xml'
IDS = {'court': 'mf_wfm_mainFrame_sbx_rletCortOfc',
       'large': 'mf_wfm_mainFrame_sbx_rletLclLst',
       'medium': 'mf_wfm_mainFrame_sbx_rletMclLst',
       'small': 'mf_wfm_mainFrame_sbx_rletSclLst',
       'search': 'mf_wfm_mainFrame_btn_gdsDtlSrch'}


class CollectionError(RuntimeError):
    pass


class BlockedError(CollectionError):
    pass


def text(node):
    return ' '.join(node.itertext()).strip() if node is not None else ''


def check_blocked(source):
    if re.search(r'web firewall|접근이 차단|IP.*차단|비정상적인 접근', source, re.I):
        raise BlockedError('법원 사이트 접근 차단. 우회·자동 재시도 없이 중단합니다.')


def parse_listing(source, court=''):
    """The current PGJ151F01 grid uses two physical rows per auction lot."""
    check_blocked(source)
    tree = html.fromstring(source)
    tables = tree.xpath('//table[.//td[contains(., "타경")]]')
    if not tables:
        if re.search(r'검색.*(?:없습니다|없음)|총\s*물건수\s*0\s*건', text(tree)):
            return []
        raise CollectionError('물건 표를 찾지 못했습니다. 빈 결과로 덮어쓰지 않습니다.')
    items = []
    for table in tables:
        rows = table.xpath('./tbody/tr') or table.xpath('./tr')
        for index, row in enumerate(rows):
            cells = row.xpath('./td')
            if len(cells) < 8 or '타경' not in text(cells[1]):
                continue
            other = rows[index + 1].xpath('./td') if index + 1 < len(rows) else []
            if len(other) < 3:
                raise CollectionError('물건 행 구조 변경: 가격/진행상황을 확인할 수 없습니다.')
            address = text(cells[3])
            # Prefer 집합건물/building area rather than an earlier land-share area.
            area_match = re.search(r'(?:집합건물|건물)[^\]]*?([\d,]+(?:\.\d+)?)\s*㎡', address)
            if not area_match:
                areas = re.findall(r'([\d,]+(?:\.\d+)?)\s*㎡', address)
                area_match_value = areas[0] if len(areas) == 1 else None
            else:
                area_match_value = area_match.group(1)
            lot = text(cells[2]).strip()
            lot_match = re.fullmatch(r'(?:물건번호\s*)?\[?(\d+)\]?', lot)
            item = {'법원': court, '사건번호': text(cells[1]), '소재지': address,
                    '물건번호': lot_match.group(1) if lot_match else None,
                    '용도': text(other[0]), '감정가': amount(text(cells[6])),
                    '최저입찰가': amount(text(other[1])), '매각기일': text(cells[7]),
                    '진행상황': text(other[2]),
                    '전용면적': float(area_match_value.replace(',', '')) if area_match_value else None,
                    '수집시각': now_kst()}
            failures = re.search(r'유찰\s*(\d+)\s*회', item['진행상황'])
            item['유찰횟수'] = int(failures.group(1)) if failures else 0
            items.append(normalize(item))
    if not items:
        raise CollectionError('사건 표는 있으나 행 파싱 실패. 기존 데이터를 보존합니다.')
    return list({i['id']: i for i in items}.values())


def parse_result_table(source, court=''):
    """Read explicitly labelled result columns; never use minimum price as sale price."""
    check_blocked(source)
    tree = html.fromstring(source)
    items = []
    recognized = False
    for table in tree.xpath('//table'):
        headers = [re.sub(r'\s', '', text(n)) for n in table.xpath('.//thead//th')]
        if not headers:
            headers = [re.sub(r'\s', '', text(n)) for n in table.xpath('.//tr[1]/th')]
        if not any('사건번호' in h for h in headers) or not any('결과' in h or '진행상황' in h for h in headers):
            continue
        recognized = True
        for row in table.xpath('.//tbody/tr'):
            cells = row.xpath('./td')
            if len(cells) != len(headers):
                continue
            values = dict(zip(headers, [text(c) for c in cells]))
            def val(*labels):
                return next((v for k, v in values.items() if any(label in k for label in labels)), '')
            case = val('사건번호')
            if '타경' not in case:
                continue
            addr = val('소재지', '주소')
            areas = re.findall(r'([\d.]+)\s*㎡', val('면적') or addr)
            item = {'법원': court, '사건번호': case, '소재지': addr,
                    '물건번호': val('물건번호') or None, '용도': val('용도'),
                    '전용면적': float(areas[-1]) if areas else None,
                    '감정가': amount(val('감정')), '최저입찰가': amount(val('최저')),
                    '낙찰가': amount(val('매각가격', '매각금액', '낙찰가', '낙찰금액')),
                    '진행상황': val('결과', '진행상황'), '매각기일': val('매각기일', '입찰일'),
                    '결과출처': RESULT_URL, '수집시각': now_kst()}
            items.append(normalize(item))
    if not recognized or (not items and '타경' in text(tree)):
        raise CollectionError('매각결과 표 구조 확인 필요. 과거 보관 물건은 사건별 기일내역으로 조회합니다.')
    return items


def parse_case_results(payload, tracked):
    data = payload.get('data') or {}
    if data.get('ipcheck') is False:
        raise BlockedError('법원 사이트가 조회를 차단했습니다.')
    if not data.get('dma_csBasInf'):
        raise CollectionError('사건 조회 결과 없음')
    schedule = data.get('dlt_rletCsGdsDtsDxdyInf')
    if not isinstance(schedule, list):
        raise CollectionError('기일내역 응답 구조 확인 필요')
    lots = {str(r.get('dspslGdsSeq')) for r in schedule if r.get('dspslGdsSeq') is not None}
    updates = []
    for item in tracked:
        lot = str(item.get('물건번호') or '')
        if not lot and len(lots) == 1:
            lot = next(iter(lots))
        if not lot:
            continue  # Ambiguous multiple lots: do not attach another apartment's result.
        for row in schedule:
            if str(row.get('dspslGdsSeq')) != lot:
                continue
            day = date_only(row.get('dspslDxdyYmd'))
            status = str(row.get('rsltNm') or row.get('rsltCd') or '').strip()
            if not day or not re.search(r'[가-힣]', status):
                continue  # Unknown numeric codes are not guessed.
            # Explicit sale-price fields only. Some responses include price in result text.
            sale_price = next((amount(row[k]) for k in ('dspslPrc', 'sucbidAmt', '매각가격', '낙찰가') if amount(row.get(k))), None)
            price_match = re.search(r'(?:매각|낙찰)\s*\(\s*([\d,]+)\s*원?\s*\)', status)
            if not sale_price and price_match:
                sale_price = amount(price_match.group(1))
            updates.append(dict(item, 물건번호=lot, 매각일=day, 매각기일=day,
                                진행상황=status, 낙찰가=sale_price, 낙찰가율=None,
                                감정가=amount(row.get('aeeEvlAmt')) or item.get('감정가'),
                                최저입찰가=amount(row.get('lwsDspslPrc')) or item.get('최저입찰가'),
                                결과출처=CASE_URL))
    return sorted(updates, key=lambda x: x['매각일'])


def make_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    opts = Options()
    # The WebSquare page can postpone even DOMContentLoaded while loading
    # non-essential resources. Return immediately after navigation starts and
    # let load_page wait for the one control the collector actually needs.
    opts.page_load_strategy = 'none'
    for option in ('--headless=new', '--no-sandbox', '--disable-dev-shm-usage', '--window-size=1400,900'):
        opts.add_argument(option)
    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(60)
    driver.set_script_timeout(35)
    return driver


def load_page(driver, url, ready_id=None, attempts=2):
    """Load a court page with one bounded retry for transient renderer stalls."""
    from selenium.common.exceptions import TimeoutException, WebDriverException
    from selenium.webdriver.support.ui import WebDriverWait

    last_error = None
    for attempt in range(attempts):
        try:
            driver.get(url)
        except (TimeoutException, WebDriverException) as exc:
            last_error = exc
            try:
                driver.execute_script('window.stop()')
            except Exception:
                pass
        try:
            check_blocked(driver.page_source)
            if ready_id:
                WebDriverWait(driver, 25).until(
                    lambda d: d.find_elements('id', ready_id)
                )
            return
        except BlockedError:
            raise
        except Exception as exc:
            last_error = exc
        if attempt + 1 < attempts:
            time.sleep(8)
    raise CollectionError(f'법원 페이지 로딩 실패 ({attempts}회 시도): {last_error}')


def restart_driver(driver):
    """A renderer timeout poisons the Chrome session; replace it for next court."""
    if driver is not None:
        try:
            driver.quit()
        except Exception:
            pass
    return make_driver()


def select_text(driver, el_id, value):
    element = driver.find_element('id', el_id)
    options = element.find_elements('tag name', 'option')
    opt = next((o for o in options if o.text.strip() == value or o.text.strip().endswith(' ' + value)), None)
    if opt is None:
        raise CollectionError(f'{value}: 법원/분류 선택항목 없음')
    selected_value = opt.get_attribute('value')
    driver.execute_script('''
        arguments[0].value = arguments[1];
        arguments[0].dispatchEvent(new Event('change', {bubbles: true}));
    ''', element, selected_value)
    time.sleep(1)
    return selected_value


def current_page(driver):
    elements = driver.find_elements('css selector', '.w2pageList_label_selected')
    return int(elements[0].text) if elements and elements[0].text.isdigit() else 1


def advance_page(driver, wanted):
    for selector in ('.w2pageList_control_label', '.w2pageList_col_next'):
        for node in driver.find_elements('css selector', selector):
            if selector.endswith('control_label') and node.text.strip() != str(wanted):
                continue
            driver.execute_script('arguments[0].click()', node)
            time.sleep(CONFIG['request_interval_seconds'])
            if current_page(driver) == wanted:
                return True
    return False


def read_all_pages(driver, parse, court, page_limit=8):
    items, fingerprints = [], set()
    page = 1
    while True:
        source = driver.page_source
        rows = parse(source, court)
        if not rows:
            return items
        fingerprint = tuple(i['id'] for i in rows)
        if fingerprint in fingerprints:
            raise CollectionError(f'{court}: 페이지 반복 감지, 전체 수집 미완료')
        fingerprints.add(fingerprint)
        items.extend(rows)
        count = re.search(r'총\s*물건수\s*[:：]?\s*([\d,]+)\s*건', text(html.fromstring(source)))
        total = int(count.group(1).replace(',', '')) if count else None
        labels = driver.find_elements('css selector', '.w2pageList_control_label')
        visible_pages = [int(n.text) for n in labels if n.text.isdigit()]
        if total is not None and len(items) >= total:
            break
        if page_limit and page >= page_limit:
            break  # Requested bounded collection is a successful run.
        if not advance_page(driver, page + 1):
            if (total is not None and len(items) < total) or (visible_pages and max(visible_pages) > page):
                raise CollectionError(f'{court}: 다음 페이지 이동 실패')
            if total is None:
                raise CollectionError(f'{court}: 총 물건수를 확인하지 못해 수집 완결성 확인 불가')
            break
        page += 1
    return items


def scrape_court(driver, court, page_limit=8):
    load_page(driver, SEARCH_URL, IDS['court'])
    time.sleep(CONFIG['request_interval_seconds'])
    check_blocked(driver.page_source)
    code = select_text(driver, IDS['court'], court)
    for key, value in [('large', '건물'), ('medium', '주거용건물'), ('small', '아파트')]:
        select_text(driver, IDS[key], value)
    driver.find_element('id', IDS['search']).click()
    time.sleep(CONFIG['request_interval_seconds'])
    items = read_all_pages(driver, parse_listing, court, page_limit)
    for item in items:
        item['법원코드'] = code
    return items, code


def scrape_recent_results(driver, court, page_limit=8):
    load_page(driver, RESULT_URL)
    time.sleep(CONFIG['request_interval_seconds'])
    check_blocked(driver.page_source)
    # Discover controls from their actual option labels instead of inventing page IDs.
    selected = False
    for node in driver.find_elements('tag name', 'select'):
        options = node.find_elements('tag name', 'option')
        if any(o.text.strip() == court or o.text.strip().endswith(' ' + court) for o in options):
            select_text(driver, node.get_attribute('id'), court)
            selected = True
            break
    if not selected:
        raise CollectionError('매각결과 법원 선택 컨트롤 확인 필요')
    buttons = driver.find_elements('xpath', '//*[self::button or self::a or self::input][normalize-space(.)="검색" or @value="검색"]')
    buttons = [b for b in buttons if b.is_displayed()]
    if len(buttons) != 1:
        raise CollectionError('매각결과 검색 버튼 확인 필요')
    buttons[0].click()
    time.sleep(CONFIG['request_interval_seconds'])
    return read_all_pages(driver, parse_result_table, court, page_limit)


def fetch_case(driver, court_code, case_no):
    time.sleep(CONFIG['request_interval_seconds'])
    result = driver.execute_async_script('''
        const [body, done] = arguments;
        fetch('/pgj/pgj15A/selectAuctnCsSrchRslt.on', {
          method:'POST', headers:{'Content-Type':'application/json'},
          credentials:'same-origin', body:JSON.stringify(body), signal:AbortSignal.timeout(30000)
        }).then(async r => done({status:r.status, text:await r.text()}))
          .catch(e => done({error:String(e)}));
    ''', {'dma_srchCsDtlInf': {'cortOfcCd': court_code, 'csNo': case_no}})
    if result.get('error'):
        raise CollectionError(result['error'])
    check_blocked(result.get('text', ''))
    if result.get('status') != 200:
        raise CollectionError('사건 조회 HTTP 오류')
    return json.loads(result['text'])


def current_listing_snapshot(incoming, previous_items):
    """Keep last-known rows without duplicating legacy rows that lacked a lot number."""
    current = {i['id']: i for i in incoming if in_scope(i)}
    natural_keys = {(i['법원'], i['사건번호'], i['주소']) for i in current.values()}
    for raw in previous_items:
        old = normalize(raw)
        natural_key = (old['법원'], old['사건번호'], old['주소'])
        if not old.get('물건번호') and natural_key in natural_keys:
            continue
        if in_scope(old) and old['id'] not in current:
            current[old['id']] = dict(old, 재확인필요=True)
    return current


def run(args):
    archive_path = Path(args.archive)
    archive = load_json(archive_path, empty_archive())
    previous = load_json(args.output, {'items': []})
    archive = merge_archive(archive, previous.get('items', []), previous.get('수집일시') or now_kst())
    if args.import_results:
        imported = load_json(args.import_results)
        rows = imported.get('items', []) if isinstance(imported, dict) else imported
        for row in rows:
            if not row.get('결과출처') or not row.get('법원') or not row.get('사건번호'):
                raise ValueError('결과 가져오기에는 법원·사건번호·결과출처가 필요합니다.')
        archive = merge_archive(archive, rows)
        write_json(archive_path, archive)
        return 0
    reports, incoming, court_codes = [], [], {}
    driver = None
    blocked = False
    listings_merged = False
    try:
        driver = make_driver()
        for court in CONFIG['courts']:
            try:
                rows, code = scrape_court(driver, court, args.pages)
                incoming.extend(rows)
                court_codes[court] = code
                reports.append({'법원': court, '종류': '진행', '성공': True, '조회건수': len(rows)})
            except BlockedError:
                blocked = True
                raise
            except Exception as exc:
                reports.append({'법원': court, '종류': '진행', '성공': False, '오류': str(exc)[:240]})
                driver = restart_driver(driver)
        archive = merge_archive(archive, incoming)
        listings_merged = True
        for court in CONFIG['courts']:
            try:
                rows = scrape_recent_results(driver, court, args.pages)
                archive = merge_archive(archive, rows)
                reports.append({'법원': court, '종류': '최근결과', '성공': True, '조회건수': len(rows)})
            except BlockedError:
                blocked = True
                raise
            except Exception as exc:
                reports.append({'법원': court, '종류': '최근결과', '성공': False, '오류': str(exc)[:240]})
                driver = restart_driver(driver)
        load_page(driver, CASE_URL)
        time.sleep(CONFIG['request_interval_seconds'])
        check_blocked(driver.page_source)
        groups = {}
        for item in archive['items']:
            if (state_of(item) != '진행' or any(h.get('매각일') and h['매각일'] < now_kst()[:10] and h.get('진행상황') not in ('매각', '낙찰') for h in item.get('이력', []))):
                groups.setdefault((item['법원'], item['사건번호']), []).append(item)
        for (court, case_no), tracked in groups.items():
            try:
                code = court_codes.get(court) or tracked[0].get('법원코드')
                if not code:
                    raise CollectionError('법원코드 미확인')
                updates = parse_case_results(fetch_case(driver, code, case_no), tracked)
                if not updates:
                    raise CollectionError('물건별 결과를 확정할 수 없습니다. 원문 확인 필요')
                archive = merge_archive(archive, updates)
                reports.append({'법원': court, '사건번호': case_no, '종류': '기일내역', '성공': True, '확인건수': len(updates)})
            except BlockedError:
                blocked = True
                raise
            except Exception as exc:
                reports.append({'법원': court, '사건번호': case_no, '종류': '기일내역', '성공': False, '오류': str(exc)[:240]})
    except Exception as exc:
        reports.append({'종류': '실행', '성공': False, '오류': str(exc)[:240], '접근차단': blocked})
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
    # Partial failures must not remove last-known records or mark missing lots as sold.
    if not listings_merged:
        archive = merge_archive(archive, incoming)
    write_json(archive_path, archive)
    success_courts = {r['법원'] for r in reports if r.get('종류') == '진행' and r.get('성공')}
    new_by_id = current_listing_snapshot(incoming, previous.get('items', []))
    for item in new_by_id.values():
        item['목록상태'] = state_of(item)
    stamp = now_kst()
    listing_success = len(success_courts) == len(CONFIG['courts'])
    result_reports = [r for r in reports if r.get('종류') in ('최근결과', '기일내역')]
    results_success = bool(result_reports) and all(r['성공'] for r in result_reports)
    status = {'실행시각': stamp, '법원별페이지상한': args.pages,
              '목록정렬': '법원 검색 기본 순서 (등록일 최신순 미확인)',
              '목록수집성공': listing_success, '완료결과수집성공': results_success,
              '전체성공': listing_success and results_success, '상세': reports}
    write_json(args.output, {'schema_version': 2, '수집일시': stamp if success_courts else previous.get('수집일시'),
                            '조건': CONFIG, '수집상태': status, '총건수': len(new_by_id),
                            'items': list(new_by_id.values())})
    write_json(Path(args.output).parent / 'collection_status.json', status)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    # Result history is secondary and may be unavailable outside its public
    # result window. Fail the workflow only when the primary current listing
    # collection is incomplete; the UI still warns when result checks fail.
    return 0 if listing_success else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pages', type=int, default=8, help='법원별 앞 N페이지 수집 (기본 8). 0: 전체 페이지')
    parser.add_argument('--output', default='docs/auction_data.json')
    parser.add_argument('--archive', default='docs/auction_archive.json')
    parser.add_argument('--import-results', help='출처를 확인한 과거 결과 JSON 병합 (네트워크 요청 없음)')
    args = parser.parse_args()
    if args.pages < 0:
        parser.error('--pages는 0 이상이어야 합니다')
    sys.exit(run(args))


if __name__ == '__main__':
    main()
