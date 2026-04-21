#!/usr/bin/env python3
"""
법원경매 아파트 스크래퍼 — 창민님 맞춤 버전
대상: https://www.courtauction.go.kr
출력: auction_data.json

사용법:
  pip install requests beautifulsoup4 lxml
  python scraper.py
  python scraper.py --pages 5
  python scraper.py --max-price 800000000
  python scraper.py --no-detail   (빠른 수집, 면적/연도 필터 생략)
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import argparse
import re
from datetime import datetime

# ── 기본 설정 ──────────────────────────────────────────
BASE_URL = "https://www.courtauction.go.kr"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    "Referer": BASE_URL,
    "Accept-Language": "ko-KR,ko;q=0.9",
}
REQUEST_DELAY = 2.5  # 초 (서버 부하 방지)

# ── 창민님 관심 지역 키워드 ────────────────────────────
TARGET_AREAS = [
    # 수지구
    "성복동", "풍덕천동", "신봉동", "상현동",
    # 광교 (수원시 영통구)
    "광교", "이의동", "원천동",
    # 분당구
    "분당", "정자동", "수내동", "서현동", "야탑동",
    "이매동", "금곡동", "구미동", "백현동", "삼평동",
]

# ── 필터 기준 ──────────────────────────────────────────
MIN_AREA_M2  = 59.0   # 전용 59㎡ ≒ 공급 30평
MAX_BUILD_YEAR_AGO = 15  # 준공 15년 이내
MIN_BUILD_YEAR = datetime.now().year - MAX_BUILD_YEAR_AGO  # 2011년 이후

# ── 관할 법원 코드 ─────────────────────────────────────
# 수지/광교 → 수원지방법원 / 분당 → 성남지원
COURT_MAP = {
    "B000010": "수원지방법원",
    "B000011": "성남지원",
}

# ── 유틸 ───────────────────────────────────────────────
def safe_int(text):
    return int(re.sub(r"[^\d]", "", text or "") or "0")

def fmt(won):
    if not won:
        return "-"
    if won >= 100_000_000:
        eok = won // 100_000_000
        rem = (won % 100_000_000) // 10_000_000
        return f"{eok}억{f' {rem}천만' if rem else ''}"
    if won >= 10_000:
        return f"{won // 10_000:,}만"
    return f"{won:,}"

def m2_to_pyeong(m2):
    return round(m2 / 3.305785, 1) if m2 else None

def is_target(addr):
    return any(kw in addr for kw in TARGET_AREAS)

# ── 목록 수집 ──────────────────────────────────────────
def fetch_list(court_code, page):
    try:
        resp = requests.get(
            f"{BASE_URL}/pgj/pgj1000/PGJ1G11.pgj",
            params={"jiwonNm": court_code, "srnPage": page,
                    "termDiv": "1", "gubun": "1", "subbul": "1"},
            headers=HEADERS, timeout=15
        )
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"    [오류] {e}")
        return None

def parse_list(html):
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    items = []
    for row in soup.select("table.Ltbl_dt tbody tr"):
        cols = row.select("td")
        if len(cols) < 7:
            continue
        try:
            link = row.select_one("a[href*='PGJ1G12']")
            href = link["href"] if link else ""
            감정가 = safe_int(cols[3].get_text())
            최저가 = safe_int(cols[4].get_text())
            items.append({
                "사건번호":     cols[0].get_text(strip=True),
                "소재지":      cols[1].get_text(strip=True),
                "물건종류":     cols[2].get_text(strip=True),
                "감정가":      감정가,
                "최저입찰가":   최저가,
                "최저입찰가율": round(최저가 / 감정가 * 100, 1) if 감정가 else 0,
                "감정가_표시":  fmt(감정가),
                "최저입찰가_표시": fmt(최저가),
                "매각기일":    cols[5].get_text(strip=True),
                "진행상황":    cols[6].get_text(strip=True),
                "상세링크":    BASE_URL + href if href else "",
                "수집시각":    datetime.now().strftime("%Y-%m-%d %H:%M"),
                # 상세 수집 후 채워질 필드
                "전용면적":    None,
                "평형":       None,
                "층수":       None,
                "준공연도":    None,
                "건축연수":    None,
                "유찰횟수":    0,
                "단지명":     None,
            })
        except Exception as e:
            print(f"    [경고] 파싱 오류: {e}")
    return items

# ── 상세 수집 ──────────────────────────────────────────
def fetch_detail(url):
    if not url:
        return {}
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        text = BeautifulSoup(resp.text, "lxml").get_text(" ", strip=True)
        d = {}

        # 전용면적
        m = re.search(r"전용면적\s*[：:＊]?\s*([\d.]+)\s*㎡", text)
        if not m:
            m = re.search(r"전용\s*([\d.]+)\s*㎡", text)
        if m:
            d["전용면적"] = float(m.group(1))
            d["평형"]    = m2_to_pyeong(d["전용면적"])

        # 층수 (예: 12층/25층)
        m = re.search(r"(\d+)\s*층\s*/\s*(\d+)\s*층", text)
        if m:
            d["층수"] = f"{m.group(1)}층/{m.group(2)}층"
        else:
            m = re.search(r"소재\s*층\s*[：:]?\s*(\d+)", text)
            if m:
                d["층수"] = f"{m.group(1)}층"

        # 준공연도 (사용승인일 우선)
        for pat in [
            r"사용\s*승인\s*[：:]?\s*(\d{4})[.\-년]",
            r"준공\s*[：:]?\s*(\d{4})[.\-년]",
            r"건축\s*연도\s*[：:]?\s*(\d{4})",
            r"(\d{4})년\s*\d{1,2}월\s*사용승인",
        ]:
            m = re.search(pat, text)
            if m:
                yr = int(m.group(1))
                if 1970 <= yr <= datetime.now().year:
                    d["준공연도"] = yr
                    d["건축연수"] = datetime.now().year - yr
                    break

        # 유찰횟수
        m = re.search(r"유찰\s*(\d+)\s*회", text)
        if m:
            d["유찰횟수"] = int(m.group(1))

        # 단지명 (아파트명 추출)
        m = re.search(r"([가-힣A-Za-z0-9\s]{2,15}아파트)", text[:600])
        if m:
            d["단지명"] = m.group(1).strip()

        return d
    except Exception as e:
        print(f"    [경고] 상세 실패: {e}")
        return {}

# ── 최종 필터 ──────────────────────────────────────────
def final_filter(items, max_price, min_price, max_rate):
    result, skip = [], {"면적": 0, "연도": 0, "가격": 0}
    for item in items:
        # 면적 (상세 수집된 경우)
        if item["전용면적"] is not None and item["전용면적"] < MIN_AREA_M2:
            skip["면적"] += 1
            continue
        # 준공연도 (상세 수집된 경우)
        if item["준공연도"] is not None and item["준공연도"] < MIN_BUILD_YEAR:
            skip["연도"] += 1
            continue
        # 가격
        if max_price and item["최저입찰가"] > max_price:
            skip["가격"] += 1
            continue
        if min_price and item["최저입찰가"] < min_price:
            skip["가격"] += 1
            continue
        if max_rate and item["최저입찰가율"] > max_rate:
            skip["가격"] += 1
            continue
        result.append(item)
    return result, skip

# ── 메인 ───────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="경매레이더 — 수지/광교/분당 전용")
    parser.add_argument("--pages",     type=int,   default=5)
    parser.add_argument("--max-price", type=int,   default=None, help="최대 최저입찰가(원)")
    parser.add_argument("--min-price", type=int,   default=None, help="최소 최저입찰가(원)")
    parser.add_argument("--max-rate",  type=float, default=None, help="최대 입찰가율(%)")
    parser.add_argument("--no-detail", action="store_true",      help="상세 수집 생략 (빠름)")
    parser.add_argument("--output",    default="auction_data.json")
    args = parser.parse_args()

    do_detail = not args.no_detail

    print(f"\n{'━'*56}")
    print(f"  경매레이더 — 수지/광교/분당 아파트 스크래퍼")
    print(f"{'━'*56}")
    print(f"  관심 지역  : {', '.join(TARGET_AREAS[:4])} 외 {len(TARGET_AREAS)-4}곳")
    print(f"  면적 조건  : 전용 {MIN_AREA_M2}㎡({m2_to_pyeong(MIN_AREA_M2)}평) 이상")
    print(f"  준공 조건  : {MIN_BUILD_YEAR}년 이후 ({MAX_BUILD_YEAR_AGO}년 이내)")
    print(f"  상세 수집  : {'ON — 면적/연도 필터 적용' if do_detail else 'OFF — 지역 필터만'}")
    print(f"{'━'*56}\n")

    all_matched = []

    for code, label in COURT_MAP.items():
        print(f"▶ {label} 수집 중")
        for page in range(1, args.pages + 1):
            print(f"  {page}p 조회...", end=" ", flush=True)
            html = fetch_list(code, page)
            items = parse_list(html)

            if not items:
                print("없음, 종료")
                break

            # 지역 1차 필터 (빠르게)
            matched = [i for i in items if is_target(i["소재지"])]
            print(f"전체 {len(items)}건 → 지역매칭 {len(matched)}건")

            # 상세 수집
            if do_detail and matched:
                for n, item in enumerate(matched, 1):
                    print(f"    [{n}/{len(matched)}] {item['소재지'][:28]}")
                    item.update({k: v for k, v in fetch_detail(item["상세링크"]).items() if v is not None})
                    time.sleep(REQUEST_DELAY)

            all_matched.extend(matched)
            time.sleep(REQUEST_DELAY)
        print()

    # 최종 필터
    filtered, skip = final_filter(all_matched, args.max_price, args.min_price, args.max_rate)
    filtered.sort(key=lambda x: x["최저입찰가율"])

    # 요약
    print(f"{'─'*56}")
    print(f"  지역 매칭 합계  : {len(all_matched)}건")
    print(f"  면적 미달 제외  : {skip['면적']}건 (전용 {MIN_AREA_M2}㎡ 미만)")
    print(f"  준공연도 제외   : {skip['연도']}건 ({MIN_BUILD_YEAR}년 이전)")
    print(f"  가격 조건 제외  : {skip['가격']}건")
    print(f"  ✅ 최종 결과    : {len(filtered)}건")
    print(f"{'─'*56}\n")

    # 저장
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
            "items":  filtered,
        }, f, ensure_ascii=False, indent=2)

    print(f"💾 저장 완료: {args.output}\n")

    # TOP 결과 출력
    if filtered:
        print("─── 관심 물건 TOP 10 (입찰가율 낮은 순) ───")
        for item in filtered[:10]:
            area  = f"{item['전용면적']}㎡({item['평형']}평)" if item.get("전용면적") else "면적미상"
            year  = f"{item['준공연도']}년({item['건축연수']}년차)" if item.get("준공연도") else "연도미상"
            floor = item.get("층수", "-")
            fail  = f" | 유찰 {item['유찰횟수']}회" if item.get("유찰횟수") else ""
            name  = f" [{item['단지명']}]" if item.get("단지명") else ""
            print(f"\n  {item['사건번호']}{name}")
            print(f"  📍 {item['소재지']}")
            print(f"  🏠 {area} | {floor} | {year}")
            print(f"  💰 감정가 {item['감정가_표시']} → 최저 {item['최저입찰가_표시']} ({item['최저입찰가율']}%){fail}")
            print(f"  📅 {item['매각기일']} | {item['진행상황']}")
    else:
        print("⚠️  조건에 맞는 물건이 없습니다.")
        if do_detail:
            print("   → --no-detail 로 먼저 지역 매칭만 확인해보세요.")

if __name__ == "__main__":
    main()
