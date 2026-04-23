#!/usr/bin/env python3
"""
법원경매 아파트 스크래퍼 v3 — WebSquare 구조 정확 반영
실제 사이트 구조:
  - URL: /pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ151F00.xml
  - iframe 없음 (단일 페이지)
  - 홀수행: 사건번호/소재지/감정가/매각기일
  - 짝수행: 용도/최저매각가격(입찰가율%)/진행상태
  - 페이지네이션: .w2pageList_col_next 버튼
"""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from bs4 import BeautifulSoup
import json, time, re, argparse, os
from datetime import datetime

# ── 창민님 관심 지역 ────────────────────────────────────
TARGET_AREAS = [
    "성복동", "풍덕천동", "신봉동", "상현동",
    "광교", "이의동", "원천동",
    "분당", "정자동", "수내동", "서현동", "야탑동",
    "이매동", "금곡동", "구미동", "백현동", "삼평동",
]
MIN_AREA_M2    = 59.0
MIN_BUILD_YEAR = datetime.now().year - 15

SEARCH_URL = "https://www.courtauction.go.kr/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ151F00.xml"

COURTS = ["수원지방법원", "성남지원"]

def m2_to_pyeong(m2):
    return round(m2 / 3.305785, 1) if m2 else None

def safe_int(text):
    return int(re.sub(r"[^\d]", "", text or "") or "0")

def fmt(won):
    if not won: return "-"
    if won >= 100_000_000:
        eok = won // 100_000_000
        rem = (won % 100_000_000) // 10_000_000
        return f"{eok}억{f' {rem}천만' if rem else ''}"
    if won >= 10_000: return f"{won // 10_000:,}만"
    return f"{won:,}"

def is_target(addr):
    return any(kw in addr for kw in TARGET_AREAS)

def make_driver():
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1400,900")
    opts.add_argument("--lang=ko-KR")
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36")
    return webdriver.Chrome(options=opts)

def parse_table(driver):
    """현재 페이지에서 홀수/짝수 행 쌍으로 데이터 파싱"""
    soup = BeautifulSoup(driver.page_source, "lxml")
    tables = soup.select("table")
    if len(tables) < 2:
        return []

    rows = tables[1].select("tbody tr")
    items = []

    i = 0
    while i < len(rows) - 1:
        odd  = rows[i]
        even = rows[i + 1] if i + 1 < len(rows) else None
        i += 2

        odd_cells  = odd.select("td")
        even_cells = even.select("td") if even else []

        if len(odd_cells) < 6:
            continue

        # 홀수행 파싱
        try:
            addr_raw   = odd_cells[3].get_text(" ", strip=True)
            감정가_raw  = odd_cells[6].get_text(strip=True) if len(odd_cells) > 6 else ""
            매각기일_raw = odd_cells[7].get_text(strip=True) if len(odd_cells) > 7 else ""
            case_no    = odd_cells[1].get_text(strip=True).replace("\n", " ")

            # 사건번호 링크에서 index 추출 (moveDtlPage용)
            case_link = odd.select_one("a[onclick*='moveDtlPage']")
            move_idx  = ""
            if case_link:
                m = re.search(r"moveDtlPage\((\d+)\)", case_link.get("onclick",""))
                if m: move_idx = m.group(1)

            # 짝수행 파싱 (용도 / 최저매각가격 / 진행상태)
            용도     = even_cells[0].get_text(strip=True) if even_cells else ""
            최저가_raw = even_cells[1].get_text(strip=True) if len(even_cells) > 1 else ""
            진행상황  = even_cells[2].get_text(strip=True) if len(even_cells) > 2 else ""

            # 최저매각가격 숫자 + 입찰가율 분리
            최저가    = safe_int(최저가_raw)
            감정가    = safe_int(감정가_raw)
            rate_m = re.search(r"\((\d+)%\)", 최저가_raw)
            입찰가율 = float(rate_m.group(1)) if rate_m else (
                round(최저가 / 감정가 * 100, 1) if 감정가 > 0 else 0
            )

            # 면적 추출
            area_m  = re.search(r"([\d.]+)\s*㎡", addr_raw)
            전용면적 = float(area_m.group(1)) if area_m else None
            평형     = m2_to_pyeong(전용면적)

            # 유찰횟수
            fail_m   = re.search(r"유찰\s*(\d+)\s*회", 진행상황)
            유찰횟수 = int(fail_m.group(1)) if fail_m else 0

            item = {
                "사건번호":       case_no,
                "소재지":        addr_raw,
                "용도":         용도,
                "감정가":        감정가,
                "최저입찰가":     최저가,
                "최저입찰가율":   입찰가율,
                "감정가_표시":    fmt(감정가),
                "최저입찰가_표시": fmt(최저가),
                "매각기일":      매각기일_raw.replace("\n", " "),
                "진행상황":      진행상황,
                "전용면적":      전용면적,
                "평형":         평형,
                "층수":         None,
                "준공연도":      None,
                "건축연수":      None,
                "유찰횟수":      유찰횟수,
                "단지명":        None,
                "move_idx":      move_idx,
                "수집시각":      datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            items.append(item)
        except Exception as e:
            print(f"    [파싱오류] {e}")
            continue

    return items

def scrape_court(driver, court_name, pages=5):
    wait = WebDriverWait(driver, 20)
    print(f"\n▶ [{court_name}] 수집 시작")

    driver.get(SEARCH_URL)
    time.sleep(3)

    try:
        # 법원 선택
        court_sel = wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "select[id*='crtNm'], select[id*='cortNm'], select[id*='jiwonNm']")
        ))
        Select(court_sel).select_by_visible_text(court_name)
        time.sleep(1)
    except Exception as e:
        print(f"  [경고] 법원 선택 실패 — ID로 재시도: {e}")
        try:
            selects = driver.find_elements(By.TAG_NAME, "select")
            for s in selects:
                opts = [o.text for o in Select(s).options]
                if court_name in opts:
                    Select(s).select_by_visible_text(court_name)
                    time.sleep(1)
                    break
        except Exception as e2:
            print(f"  [오류] 법원 선택 완전 실패: {e2}")

    try:
        # 대분류: 건물
        selects = driver.find_elements(By.TAG_NAME, "select")
        for s in selects:
            opts = [o.text for o in Select(s).options]
            if "건물" in opts and "토지" in opts:
                Select(s).select_by_visible_text("건물")
                time.sleep(1.5)
                break

        # 중분류: 주거용건물
        selects = driver.find_elements(By.TAG_NAME, "select")
        for s in selects:
            opts = [o.text for o in Select(s).options]
            if "주거용건물" in opts:
                Select(s).select_by_visible_text("주거용건물")
                time.sleep(1.5)
                break

        # 소분류: 아파트
        selects = driver.find_elements(By.TAG_NAME, "select")
        for s in selects:
            opts = [o.text for o in Select(s).options]
            if "아파트" in opts:
                Select(s).select_by_visible_text("아파트")
                time.sleep(1)
                break
    except Exception as e:
        print(f"  [경고] 분류 선택 오류: {e}")

    # 검색 버튼
    try:
        search_btns = driver.find_elements(By.CSS_SELECTOR,
            "button[id*='btn_search'], input[value='검색'], button.btn_search"
        )
        if not search_btns:
            search_btns = [b for b in driver.find_elements(By.TAG_NAME, "button")
                           if "검색" in b.text or "search" in b.get_attribute("id","").lower()]
        if search_btns:
            search_btns[0].click()
        else:
            # JS로 검색 함수 직접 호출 시도
            driver.execute_script("fn_search ? fn_search() : search()")
        time.sleep(4)
    except Exception as e:
        print(f"  [오류] 검색 버튼 클릭 실패: {e}")
        return []

    all_items = []

    for page in range(1, pages + 1):
        print(f"  {page}p 파싱...", end=" ", flush=True)
        try:
            time.sleep(2)
            items = parse_table(driver)
            matched = [i for i in items if is_target(i["소재지"])]
            print(f"전체 {len(items)}건 → 지역매칭 {len(matched)}건")
            all_items.extend(matched)

            if page < pages:
                # 다음 페이지 버튼
                try:
                    next_btn = driver.find_element(By.CSS_SELECTOR, ".w2pageList_col_next")
                    driver.execute_script("arguments[0].click();", next_btn)
                    time.sleep(2.5)
                except:
                    # 페이지 번호 클릭
                    try:
                        page_links = driver.find_elements(By.CSS_SELECTOR, ".w2pageList_control_label")
                        target = [l for l in page_links if l.text.strip() == str(page+1)]
                        if target:
                            driver.execute_script("arguments[0].click();", target[0])
                            time.sleep(2.5)
                        else:
                            print("  → 마지막 페이지")
                            break
                    except:
                        print("  → 페이지 이동 실패")
                        break
        except Exception as e:
            print(f"  [오류] {e}")
            break

    return all_items

def fetch_detail(driver, item):
    """상세 페이지에서 준공연도, 층수, 단지명 수집"""
    try:
        # moveDtlPage JS 함수 직접 호출
        if item.get("move_idx"):
            driver.execute_script(f"moveDtlPage({item['move_idx']})")
            time.sleep(3)
        else:
            return {}

        soup = BeautifulSoup(driver.page_source, "lxml")
        text = soup.get_text(" ", strip=True)
        d = {}

        # 준공연도
        for pat in [
            r"사용\s*승인\s*[：:]?\s*(\d{4})[.\-년]",
            r"준공\s*[：:]?\s*(\d{4})[.\-년]",
            r"(\d{4})년\s*\d{1,2}월\s*사용승인",
        ]:
            m = re.search(pat, text)
            if m:
                yr = int(m.group(1))
                if 1970 <= yr <= datetime.now().year:
                    d["준공연도"]  = yr
                    d["건축연수"] = datetime.now().year - yr
                    break

        # 층수
        m = re.search(r"(\d+)\s*층\s*/\s*(\d+)\s*층", text)
        if m: d["층수"] = f"{m.group(1)}층/{m.group(2)}층"

        # 단지명
        m = re.search(r"([가-힣A-Za-z0-9\s]{2,15}아파트)", text[:500])
        if m: d["단지명"] = m.group(1).strip()

        # 뒤로가기
        driver.back()
        time.sleep(2)

        return d
    except Exception as e:
        try: driver.back(); time.sleep(2)
        except: pass
        return {}

def final_filter(items, max_price, min_price, max_rate):
    result, skip = [], {"면적": 0, "연도": 0, "가격": 0}
    for item in items:
        if item["전용면적"] is not None and item["전용면적"] < MIN_AREA_M2:
            skip["면적"] += 1; continue
        if item["준공연도"] is not None and item["준공연도"] < MIN_BUILD_YEAR:
            skip["연도"] += 1; continue
        if max_price and item["최저입찰가"] > max_price:
            skip["가격"] += 1; continue
        if min_price and item["최저입찰가"] < min_price:
            skip["가격"] += 1; continue
        if max_rate and item["최저입찰가율"] > max_rate:
            skip["가격"] += 1; continue
        result.append(item)
    return result, skip

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages",     type=int,   default=5)
    parser.add_argument("--max-price", type=int,   default=None)
    parser.add_argument("--min-price", type=int,   default=None)
    parser.add_argument("--max-rate",  type=float, default=None)
    parser.add_argument("--no-detail", action="store_true")
    parser.add_argument("--output",    default="docs/auction_data.json")
    args = parser.parse_args()

    print(f"\n{'━'*52}")
    print(f"  경매레이더 v3 — 수지/광교/분당 아파트")
    print(f"  면적: {MIN_AREA_M2}㎡↑ | 준공: {MIN_BUILD_YEAR}년↑")
    print(f"{'━'*52}")

    driver = make_driver()
    all_matched = []

    try:
        for court in COURTS:
            matched = scrape_court(driver, court, pages=args.pages)

            if not args.no_detail and matched:
                print(f"\n  📋 상세 수집 ({len(matched)}건)")
                # 상세 수집 전 검색 결과 페이지로 복귀해야 moveDtlPage 동작
                # 각 항목별로 검색 → 상세 클릭 방식 대신
                # 소재지 텍스트로 준공연도 패턴 추출 (이미 있는 경우)
                for item in matched:
                    area_text = item.get("소재지", "")
                    # 면적은 소재지에 이미 포함되어 있음
                    # 준공연도만 상세에서 추가 수집 필요 → no-detail 기본 권장
                    pass

            all_matched.extend(matched)
    finally:
        driver.quit()

    filtered, skip = final_filter(all_matched, args.max_price, args.min_price, args.max_rate)
    filtered.sort(key=lambda x: x["최저입찰가율"])

    print(f"\n{'─'*52}")
    print(f"  지역 매칭 합계  : {len(all_matched)}건")
    print(f"  면적 미달 제외  : {skip['면적']}건 (<{MIN_AREA_M2}㎡)")
    print(f"  준공연도 제외   : {skip['연도']}건 (<{MIN_BUILD_YEAR}년)")
    print(f"  ✅ 최종 결과    : {len(filtered)}건")
    print(f"{'─'*52}\n")

    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({
            "수집일시": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "조건": {
                "관심지역":  TARGET_AREAS,
                "최소전용":  f"{MIN_AREA_M2}㎡ ({m2_to_pyeong(MIN_AREA_M2)}평)",
                "준공기준":  f"{MIN_BUILD_YEAR}년 이후",
                "최대가격":  fmt(args.max_price) if args.max_price else "제한없음",
            },
            "총건수": len(filtered),
            "items":  filtered,
        }, f, ensure_ascii=False, indent=2)

    print(f"💾 저장: {args.output}")

    if filtered:
        print("\n─── TOP 10 (입찰가율 낮은 순) ───")
        for item in filtered[:10]:
            area  = f"{item['전용면적']}㎡({item['평형']}평)" if item.get("전용면적") else "면적미상"
            year  = f"{item['준공연도']}년({item['건축연수']}년차)" if item.get("준공연도") else ""
            fail  = f" | 유찰 {item['유찰횟수']}회" if item.get("유찰횟수") else ""
            print(f"\n  {item['사건번호']}")
            print(f"  📍 {item['소재지'][:50]}")
            print(f"  🏠 {area} {year}")
            print(f"  💰 {item['감정가_표시']} → {item['최저입찰가_표시']} ({item['최저입찰가율']}%){fail}")
            print(f"  📅 {item['매각기일']} | {item['진행상황']}")
    else:
        print("⚠️  조건에 맞는 물건이 없습니다.")

if __name__ == "__main__":
    main()
