#!/usr/bin/env python3
"""
법원경매 아파트 스크래퍼 v5 — select/button ID 정확 반영
"""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import json, time, re, argparse, os
from datetime import datetime

# ── 관심 지역 ───────────────────────────────────────────
# 수지/광교 지역 (15년 이내 조건 적용)
SUJI_AREAS = [
    "성복동", "풍덕천동", "신봉동", "상현동",
    "광교", "이의동", "원천동",
]
# 분당/판교 지역 (준공연도 조건 미적용)
BUNDANG_AREAS = [
    "분당구", "정자동", "수내동", "미금동", "금정동",
    "서현동", "야탑동", "이매동", "금곡동", "구미동",
    "백현동", "삼평동", "판교동", "운중동",
]
# 서울 강남/송파 지역 (준공연도 조건 미적용)
SEOUL_AREAS = [
    "강남구", "서초구", "송파구",
    "압구정동", "청담동", "삼성동", "대치동", "개포동",
    "도곡동", "역삼동", "논현동", "신사동", "잠원동",
    "반포동", "서초동", "방배동", "양재동",
    "잠실동", "신천동", "문정동", "가락동", "거여동",
    "마천동", "방이동", "오금동", "풍납동", "천호동",
]

# 위례/하남 지역 (준공연도 조건 미적용)
HANAM_AREAS = [
    "위례", "하남시",
    "창우동", "풍산동", "덕풍동", "신장동",
    "미사동", "망월동", "초이동", "학암동",
]

TARGET_AREAS = SUJI_AREAS + BUNDANG_AREAS + SEOUL_AREAS + HANAM_AREAS

MIN_AREA_M2    = 59.0
MIN_BUILD_YEAR = datetime.now().year - 15
SEARCH_URL     = "https://www.courtauction.go.kr/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ151F00.xml"

# 법원 목록 — 수원/성남 + 서울중앙/동부 + 의정부(위례/하남 관할)
COURTS = [
    "수원지방법원",
    "성남지원",
    "서울중앙지방법원",
    "서울동부지방법원",
    "의정부지방법원",
]

def is_no_year_filter(addr):
    """분당/서울/하남/위례 지역 — 준공연도 조건 면제"""
    return any(kw in addr for kw in BUNDANG_AREAS + SEOUL_AREAS + HANAM_AREAS)

# ── 실제 확인된 select/button ID ────────────────────────
ID_COURT = "mf_wfm_mainFrame_sbx_rletCortOfc"
ID_LCL   = "mf_wfm_mainFrame_sbx_rletLclLst"
ID_MCL   = "mf_wfm_mainFrame_sbx_rletMclLst"
ID_SCL   = "mf_wfm_mainFrame_sbx_rletSclLst"
ID_BTN   = "mf_wfm_mainFrame_btn_gdsDtlSrch"

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
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36")
    return webdriver.Chrome(options=opts)

def select_by_text(driver, el_id, text, wait_sec=2):
    """ID로 select 찾아서 텍스트로 선택 후 change 이벤트 발생"""
    el = driver.find_element(By.ID, el_id)
    # value 찾기
    opt = next((o for o in el.find_elements(By.TAG_NAME, "option") if o.text.strip() == text), None)
    if not opt:
        raise ValueError(f"'{text}' 옵션 없음 (id={el_id})")
    driver.execute_script("""
        arguments[0].value = arguments[1];
        arguments[0].dispatchEvent(new Event('change', {bubbles: true}));
    """, el, opt.get_attribute("value"))
    time.sleep(wait_sec)

def parse_table(driver):
    """홀수/짝수 행 쌍으로 파싱"""
    soup   = BeautifulSoup(driver.page_source, "lxml")
    tables = soup.select("table")
    if len(tables) < 2:
        return []

    rows  = tables[1].select("tbody tr")
    items = []
    i = 0
    while i < len(rows):
        odd  = rows[i]
        even = rows[i+1] if i+1 < len(rows) else None
        i += 2

        odd_cells  = odd.select("td")
        even_cells = even.select("td") if even else []
        if len(odd_cells) < 6:
            continue

        try:
            addr_raw    = odd_cells[3].get_text(" ", strip=True)
            감정가_raw   = odd_cells[6].get_text(strip=True) if len(odd_cells) > 6 else ""
            매각기일_raw  = odd_cells[7].get_text(strip=True) if len(odd_cells) > 7 else ""
            case_no     = odd_cells[1].get_text(strip=True).replace("\n", " ")

            용도        = even_cells[0].get_text(strip=True) if even_cells else ""
            최저가_raw  = even_cells[1].get_text(strip=True) if len(even_cells) > 1 else ""
            진행상황    = even_cells[2].get_text(strip=True) if len(even_cells) > 2 else ""

            # 최저입찰가: (49%) 괄호 제거 후 숫자만 추출
            price_text  = re.sub(r"\([^)]*\)", "", 최저가_raw).strip()
            최저가       = safe_int(price_text)
            감정가       = safe_int(감정가_raw)

            # 입찰가율: 괄호 안 % 우선
            rate_m      = re.search(r"\((\d+)%\)", 최저가_raw)
            입찰가율    = float(rate_m.group(1)) if rate_m else (
                round(최저가 / 감정가 * 100, 1) if 감정가 > 0 else 0
            )

            # 면적
            area_m      = re.search(r"([\d.]+)\s*㎡", addr_raw)
            전용면적    = float(area_m.group(1)) if area_m else None
            평형         = m2_to_pyeong(전용면적)

            # 유찰횟수
            fail_m      = re.search(r"유찰\s*(\d+)\s*회", 진행상황)
            유찰횟수    = int(fail_m.group(1)) if fail_m else 0

            items.append({
                "사건번호":       case_no,
                "소재지":        addr_raw,
                "용도":          용도,
                "감정가":        감정가,
                "최저입찰가":     최저가,
                "최저입찰가율":   입찰가율,
                "감정가_표시":    fmt(감정가),
                "최저입찰가_표시": fmt(최저가),
                "매각기일":      매각기일_raw.replace("\n", " "),
                "진행상황":      진행상황,
                "전용면적":      전용면적,
                "평형":          평형,
                "층수":          None,
                "준공연도":      None,
                "건축연수":      None,
                "유찰횟수":      유찰횟수,
                "수집시각":      datetime.now().strftime("%Y-%m-%d %H:%M"),
            })
        except Exception as e:
            continue

    return items

def get_current_page(driver):
    try:
        active = driver.find_element(By.CSS_SELECTOR, ".w2pageList_label_selected")
        return int(active.text.strip())
    except:
        return 1

def get_current_page(driver):
    try:
        active = driver.find_element(By.CSS_SELECTOR, ".w2pageList_label_selected")
        return int(active.text.strip())
    except:
        return 1

def get_total_pages(driver):
    try:
        labels = driver.find_elements(By.CSS_SELECTOR, ".w2pageList_control_label")
        nums = [int(l.text.strip()) for l in labels if l.text.strip().isdigit()]
        return max(nums) if nums else 1
    except:
        return 1

def get_total_count(driver):
    try:
        tables = driver.find_elements(By.CSS_SELECTOR, "table")
        if tables:
            text = tables[0].text
            m = re.search(r"총\s*물건수\s*(\d+)건", text)
            if m:
                return int(m.group(1))
    except:
        pass
    return 0

def scrape_court(driver, court_name, pages=10):
    wait = WebDriverWait(driver, 20)
    print(f"\n▶ [{court_name}] 수집 시작")

    driver.get(SEARCH_URL)
    time.sleep(3)

    try:
        # 법원 선택
        select_by_text(driver, ID_COURT, court_name, wait_sec=1)
        print(f"  법원 선택 완료: {court_name}")

        # 대분류: 건물
        select_by_text(driver, ID_LCL, "건물", wait_sec=1.5)

        # 중분류: 주거용건물
        select_by_text(driver, ID_MCL, "주거용건물", wait_sec=1.5)

        # 소분류: 아파트
        select_by_text(driver, ID_SCL, "아파트", wait_sec=1)
        print("  분류 선택 완료: 건물 > 주거용건물 > 아파트")

    except Exception as e:
        print(f"  [오류] 폼 설정 실패: {e}")
        return []

    # 검색 버튼 클릭
    try:
        btn = driver.find_element(By.ID, ID_BTN)
        driver.execute_script("arguments[0].click();", btn)
        print("  검색 실행...")
        time.sleep(4)
    except Exception as e:
        print(f"  [오류] 검색 버튼 실패: {e}")
        return []

    all_items  = []
    seen_cases = set()

    # 실제 총 페이지 수 파악
    total_count = get_total_count(driver)
    total_pages = min(get_total_pages(driver), pages)
    print(f"  총 {total_count}건 / {total_pages}페이지 수집 예정")

    for page in range(1, total_pages + 1):
        print(f"  {page}p 파싱...", end=" ", flush=True)
        time.sleep(2)

        items   = parse_table(driver)
        matched = [i for i in items
                   if is_target(i["소재지"]) and i["사건번호"] not in seen_cases]
        for item in matched:
            seen_cases.add(item["사건번호"])

        print(f"전체 {len(items)}건 → 지역매칭 {len(matched)}건")
        all_items.extend(matched)

        if page >= total_pages:
            break

        # 다음 페이지 이동 — .w2pageList_control_label 중 숫자 텍스트로 클릭
        moved = False
        try:
            next_num = str(page + 1)
            labels = driver.find_elements(By.CSS_SELECTOR, ".w2pageList_control_label")
            for label in labels:
                if label.text.strip() == next_num:
                    driver.execute_script("arguments[0].click();", label)
                    time.sleep(3)
                    # 실제 이동 확인
                    cur = get_current_page(driver)
                    if cur == page + 1:
                        moved = True
                    break
        except Exception as e:
            print(f"  [경고] 페이지이동 오류: {e}")

        if not moved:
            # next 버튼 시도
            try:
                next_btn = driver.find_element(By.CSS_SELECTOR, ".w2pageList_col_next")
                driver.execute_script("arguments[0].click();", next_btn)
                time.sleep(3)
                cur = get_current_page(driver)
                if cur == page + 1:
                    moved = True
            except:
                pass

        if not moved:
            print(f"  → 마지막 페이지 (총 {page}p)")
            break

    return all_items

def final_filter(items, max_price, min_price, max_rate):
    result, skip = [], {"면적": 0, "연도": 0, "가격": 0}
    for item in items:
        # 면적 조건 (공통)
        if item["전용면적"] is not None and item["전용면적"] < MIN_AREA_M2:
            skip["면적"] += 1; continue
        # 준공연도 조건 — 분당/서울은 면제
        if not is_no_year_filter(item["소재지"]):
            if item["준공연도"] is not None and item["준공연도"] < MIN_BUILD_YEAR:
                skip["연도"] += 1; continue
        # 가격 조건 (공통)
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
    parser.add_argument("--output",    default="docs/auction_data.json")
    args = parser.parse_args()

    print(f"\n{'━'*52}")
    print(f"  경매레이더 v5 — 수지/광교/분당 아파트")
    print(f"  면적: {MIN_AREA_M2}㎡↑ | 준공: {MIN_BUILD_YEAR}년↑")
    print(f"{'━'*52}")

    driver      = make_driver()
    all_matched = []

    try:
        for court in COURTS:
            matched = scrape_court(driver, court, pages=args.pages)
            all_matched.extend(matched)
    finally:
        driver.quit()

    # 전체 중복 제거
    seen, dedup = set(), []
    for item in all_matched:
        if item["사건번호"] not in seen:
            seen.add(item["사건번호"])
            dedup.append(item)

    filtered, skip = final_filter(dedup, args.max_price, args.min_price, args.max_rate)
    filtered.sort(key=lambda x: x["최저입찰가율"])

    print(f"\n{'─'*52}")
    print(f"  지역 매칭 합계  : {len(dedup)}건")
    print(f"  면적 미달 제외  : {skip['면적']}건")
    print(f"  준공연도 제외   : {skip['연도']}건")
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
        print("\n─── TOP 10 ───")
        for item in filtered[:10]:
            area = f"{item['전용면적']}㎡({item['평형']}평)" if item.get("전용면적") else "면적미상"
            fail = f" | 유찰 {item['유찰횟수']}회" if item.get("유찰횟수") else ""
            print(f"\n  {item['사건번호']}")
            print(f"  📍 {item['소재지'][:50]}")
            print(f"  🏠 {area}")
            print(f"  💰 {item['감정가_표시']} → {item['최저입찰가_표시']} ({item['최저입찰가율']}%){fail}")
            print(f"  📅 {item['매각기일']} | {item['진행상황']}")
    else:
        print("⚠️  조건에 맞는 물건이 없습니다.")

if __name__ == "__main__":
    main()
