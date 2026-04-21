# 경매레이더 🏢

수지/광교/분당 아파트 경매 자동 수집 + 웹 뷰어

매일 오전 7시 GitHub Actions가 자동으로 법원경매 데이터를 수집하고,
GitHub Pages로 어디서든 접속 가능한 대시보드를 제공합니다.

---

## 세팅 방법 (최초 1회)

### 1단계. 레포 생성

GitHub에서 새 레포를 만드세요.
- 레포 이름: `auction-radar` (또는 원하는 이름)
- **Private** 권장 (개인 용도)
- README 없이 빈 레포로 생성

### 2단계. 파일 업로드

이 폴더의 파일들을 GitHub에 올리세요.

```
auction-radar/
├── .github/
│   └── workflows/
│       └── scrape.yml     ← Actions 자동 실행 설정
├── docs/
│   └── index.html         ← 웹 뷰어
├── scraper.py             ← 스크래퍼
└── requirements.txt       ← 패키지 목록
```

터미널에서:
```bash
git init
git remote add origin https://github.com/[내계정]/auction-radar.git
git add .
git commit -m "초기 세팅"
git push -u origin main
```

### 3단계. GitHub Pages 활성화

레포 → Settings → Pages
- Source: `Deploy from a branch`
- Branch: `main` / `docs` 폴더 선택
- Save

잠시 후 `https://[내계정].github.io/auction-radar/` 주소가 생성됩니다.

### 4단계. 첫 번째 수집 실행

레포 → Actions → `경매 데이터 자동 수집` → `Run workflow`

2~5분 후 데이터가 수집되고 페이지에서 바로 확인 가능합니다.

---

## 이후 동작

- **매일 오전 7시** 자동 실행 (변경하려면 `scrape.yml`의 cron 수정)
- 수동 실행: Actions → Run workflow
- 새 데이터 반영: 페이지에서 `⟳ 새로고침` 클릭

---

## 필터 조건 변경

`scraper.py` 상단의 설정값을 수정하세요:

```python
TARGET_AREAS = ["성복동", "풍덕천동", ...]  # 관심 지역
MIN_AREA_M2  = 59.0    # 전용면적 최소 (㎡)
MAX_BUILD_YEAR_AGO = 15  # 준공 연수
```

수정 후 git push하면 다음 Actions 실행부터 적용됩니다.

---

## 스케줄 변경

`.github/workflows/scrape.yml`에서 cron 수정:

```yaml
- cron: '0 22 * * *'   # UTC 22:00 = KST 07:00 매일
- cron: '0 22 * * 1'   # 월요일만
- cron: '0 22 * * 1,4' # 월/목
```

---

## 주의사항

- 개인 비영리 목적으로만 사용
- 요청 간격 2.5초로 서버 부하 최소화
- 투자 결정 전 반드시 법원경매 원본 사이트 확인
