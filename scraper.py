#!/usr/bin/env python3
"""
법원경매 아파트 스크래퍼 — Selenium 버전
대상: https://www.courtauction.go.kr
"""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import json, time, re, argparse
from datetime import datetime

# ── 창민님 관심 지역 ────────────────────────────────────
TARGET_AREAS = [
    "성복동", "풍덕천동", "신봉동", "상현동",
    "광교", "이의동", "원천동",
    "분당", "정자동", "수내동", "서현동", "야탑동",
    "이매동", "금곡동", "구미동", "백현동", "삼평동",
]

MIN_AREA_M2      = 59.0
MIN_BUILD_YEAR   = datetime.now().year - 15   # 15년 이내

# 관할 법원 (수원 / 성남)
COURTS = [
    {"label": "수원지방법원", "value": "수원지방법원"},
    {"label": "성남지원",    "value": "수원지방법원 성남지원"},
]

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
    opts.add_argument("--window-size=1280,900")
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36")
    return webdriver.Chrome(options=opts)

def scrape_court(driver, court_value, pages=5):
    wait = WebDriverWait(driver, 15)
    items = []

    print(f"\n▶ [{court_value}] 수집 시작")

    # 메인 접속
    driver.get("https://www.courtauction.go.kr/pgj/index.on")
    time.sleep(2)

    # iframe 진입
    try:
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.NAME, "indexFrame")))
    except:
        try:
            frames = driver.find_elements(By.TAG_NAME, "iframe")
            if frames:
                driver.switch_to.frame(frames[0])
        except:
            print("  [오류] iframe 진입 실패")
            return []

    # 물건검색 메뉴 클릭
    try:
        menu = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//a[contains(text(),'물건검색') or contains(@href,'PGJ153') or contains(@onclick,'153')]")
        ))
        menu.click()
        time.sleep(2)
    except Exception as e:
        print(f"  [오류] 물건검색 메뉴 클릭 실패: {e}")
        # 직접 URL 시도
        try:
            driver.get("https://www.courtauction.go.kr/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ153F00.xml")
            time.sleep(2)
            driver.switch_to.default_content()
            wait.until(EC.frame_to_be_available_and_switch_to_it((By.NAME, "indexFrame")))
        except:
            pass

    # 법원 선택
    try:
        court_sel = Select(wait.until(EC.presence_of_element_located((By.ID, "idJiwonNm"))))
        court_sel.select_by_visible_text(court_value)
        time.sleep(0.5)
    except Exception as e:
        print(f"  [경고] 법원 선택 실패: {e}")

    # 물건종류: 아파트
    try:
        apt_sel = Select(driver.find_element(By.ID, "idSubBul"))
        apt_sel.select_by_visible_text("아파트")
        time.sleep(0.5)
    except:
        try:
            # 체크박스 방식일 수 있음
            apt_cb = driver.find_element(By.XPATH, "//input[@type='checkbox' and following-sibling::*[contains(text(),'아파트')]]")
            if not apt_cb.is_selected():
                apt_cb.click()
        except:
            pass

    # 검색 버튼
    try:
        search_btn = driver.find_element(By.XPATH,
            "//input[@type='button' and (@value='검색' or @value='조회')] | //button[contains(text(),'검색') or contains(text(),'조회')]"
        )
        search_btn.click()
        time.sleep(3)
    except Exception as e:
        print(f"  [오류] 검색 버튼 실패: {e}")
        return []

    # 페이지 순회
    for page in range(1, pages + 1):
        print(f"  {page}p 파싱...", end=" ", flush=True)
        try:
            soup = BeautifulSoup(driver.page_source, "lxml")
            rows = soup.select("table tbody tr")

            page_items = []
            for row in rows:
                cols = row.select("td")
                if len(cols) < 6:
                    continue
                text_all = row.get_text(" ")
                if "아파트" not in text_all:
                    continue
                try:
                    addr = cols[1].get_text(strip=True) if len(cols) > 1 else ""
                    감정가  = safe_int(cols[3].get_text() if len(cols) > 3 else "")
                    최저가  = safe_int(cols[4].get_text() if len(cols) > 4 else "")
                    link_tag = row.select_one("a[href]")
                    href = link_tag["href"] if link_tag else ""

                    item = {
                        "사건번호":      cols[0].get_text(strip=True),
                        "소재지":       addr,
                        "감정가":       감정가,
                        "최저입찰가":    최저가,
                        "최저입찰가율":  round(최저가 / 감정가 * 100, 1) if 감정가 else 0,
                        "감정가_표시":   fmt(감정가),
                        "최저입찰가_표시": fmt(최저가),
                        "매각기일":     cols[5].get_text(strip=True) if len(cols) > 5 else "",
                        "진행상황":     cols[6].get_text(strip=True) if len(cols) > 6 else "",
                        "상세링크":     "https://www.courtauction.go.kr" + href if href.startswith("/") else href,
                        "수집시각":     datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "전용면적":     None,
                        "평형":        None,
                        "층수":        None,
                        "준공연도":     None,
                        "건축연수":     None,
                        "유찰횟수":     0,
                        "단지명":      None,
                    }
                    page_items.append(item)
                except:
                    continue

            matched = [i for i in page_items if is_target(i["소재지"])]
            print(f"전체 {len(page_items)}건 → 지역매칭 {len(matched)}건")
            items.extend(matched)

            # 다음 페이지
            if page < pages:
                try:
                    next_btn = driver.find_element(By.XPATH,
                        f"//a[contains(@onclick,'{page+1}') and contains(@onclick,'page')] | //a[text()='{page+1}']"
                    )
                    next_btn.click()
                    time.sleep(2)
                except:
                    print("  → 다음 페이지 없음")
                    break

        except Exception as e:
            print(f"  [오류] 페이지 파싱: {e}")
            break

    driver.switch_to.default_content()
    return items

def fetch_detail(driver, url):
    if not url:
        return {}
    try:
        driver.get(url)
        time.sleep(2)
        # iframe 있으면 진입
        try:
            frames = driver.find_elements(By.TAG_NAME, "iframe")
            if frames:
                driver.switch_to.frame(frames[0])
        except:
            pass

        text = BeautifulSoup(driver.page_source, "lxml").get_text(" ", strip=True)
        d = {}

        m = re.search(r"전용면적\s*[：:＊]?\s*([\d.]+)\s*㎡", text)
        if not m:
            m = re.search(r"전용\s*([\d.]+)\s*㎡", text)
        if m:
            d["전용면적"] = float(m.group(1))
            d["평형"]    = m2_to_pyeong(d["전용면적"])

        m = re.search(r"(\d+)\s*층\s*/\s*(\d+)\s*층", text)
        if m:
            d["층수"] = f"{m.group(1)}층/{m.group(2)}층"

        for pat in [
            r"사용\s*승인\s*[：:]?\s*(\d{4})[.\-년]",
            r"준공\s*[：:]?\s*(\d{4})[.\-년]",
            r"(\d{4})년\s*\d{1,2}월\s*사용승인",
        ]:
            m = re.search(pat, text)
            if m:
                yr = int(m.group(1))
                if 1970 <= yr <= datetime.now().year:
                    d["준공연도"] = yr
                    d["건축연수"] = datetime.now().year - yr
                    break

        m = re.search(r"유찰\s*(\d+)\s*회", text)
        if m:
            d["유찰횟수"] = int(m.group(1))

        m = re.search(r"([가-힣A-Za-z0-9\s]{2,15}아파트)", text[:600])
        if m:
            d["단지명"] = m.group(1).strip()

        driver.switch_to.default_content()
        return d
    except:
        driver.switch_to.default_content()
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
    print(f"  경매레이더 — 수지/광교/분당 아파트")
    print(f"  면적: {MIN_AREA_M2}㎡ 이상 | 준공: {MIN_BUILD_YEAR}년 이후")
    print(f"{'━'*52}")

    driver = make_driver()
    all_matched = []

    try:
        for court in COURTS:
            matched = scrape_court(driver, court["value"], pages=args.pages)

            if not args.no_detail and matched:
                print(f"  상세 수집 중... ({len(matched)}건)")
                for n, item in enumerate(matched, 1):
                    print(f"    [{n}/{len(matched)}] {item['소재지'][:25]}")
                    detail = fetch_detail(driver, item["상세링크"])
                    item.update({k: v for k, v in detail.items() if v is not None})
                    time.sleep(2)

            all_matched.extend(matched)
    finally:
        driver.quit()

    filtered, skip = final_filter(all_matched, args.max_price, args.min_price, args.max_rate)
    filtered.sort(key=lambda x: x["최저입찰가율"])

    print(f"\n{'─'*52}")
    print(f"  지역 매칭 합계  : {len(all_matched)}건")
    print(f"  면적 미달 제외  : {skip['면적']}건")
    print(f"  준공연도 제외   : {skip['연도']}건")
    print(f"  ✅ 최종 결과    : {len(filtered)}건")
    print(f"{'─'*52}\n")

    import os
    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({
            "수집일시": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "조건": {
                "관심지역": TARGET_AREAS,
                "최소전용": f"{MIN_AREA_M2}㎡ ({m2_to_pyeong(MIN_AREA_M2)}평)",
                "준공기준": f"{MIN_BUILD_YEAR}년 이후",
                "최대가격": fmt(args.max_price) if args.max_price else "제한없음",
            },
            "총건수": len(filtered),
            "items": filtered,
        }, f, ensure_ascii=False, indent=2)

    print(f"💾 저장: {args.output}")

    if filtered:
        print("\n─── TOP 10 ───")
        for item in filtered[:10]:
            area  = f"{item['전용면적']}㎡({item['평형']}평)" if item.get("전용면적") else "면적미상"
            year  = f"{item['준공연도']}년({item['건축연수']}년차)" if item.get("준공연도") else "연도미상"
            print(f"\n  {item['사건번호']}")
            print(f"  📍 {item['소재지']}")
            print(f"  🏠 {area} | {item.get('층수','-')} | {year}")
            print(f"  💰 {item['감정가_표시']} → {item['최저입찰가_표시']} ({item['최저입찰가율']}%)")
            print(f"  📅 {item['매각기일']} | {item['진행상황']}")

if __name__ == "__main__":
    main()
