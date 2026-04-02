# 게임 업계 동향 크롤러 v2.0 — 설치 및 설정 가이드

## 1. 파일 구성

```
C:\Users\Admin\Documents\game-news\
├── game_news_crawler.py   ← 메인 크롤러
├── requirements.txt
├── run_crawler.bat        ← 작업 스케줄러 실행 파일
├── logs\                  ← 실행 로그 (자동 생성)
├── index.html             ← GitHub Pages 최신 결과 (자동 생성)
└── game_news_YYYYMMDD.html ← 날짜별 결과 (자동 생성)
```

XLSX 결과물은 별도 경로에 저장됩니다:
```
C:\Users\Admin\Desktop\일일 체크리스트\YYYY.MM.DD\game_news_YYYYMMDD.xlsx
```

---

## 2. 사전 준비

### Python 패키지 설치
```
cd C:\Users\Admin\Documents\game-news
pip install -r requirements.txt
```

### 테스트 실행
```
python game_news_crawler.py
```
정상 실행 시 터미널에 수집 현황이 출력되고, `index.html`이 생성됩니다.

---

## 3. GitHub 저장소 설정 (최초 1회)

### 3-1. GitHub 저장소 생성
1. https://github.com 접속 → **New repository**
2. Repository name: `game-news`
3. **Public** 선택 (Pages 무료 이용 조건)
4. **Create repository** 클릭

### 3-2. 로컬 연결
```
cd C:\Users\Admin\Documents\game-news
git init
git remote add origin https://github.com/[내계정명]/game-news.git
git branch -M main
git add .
git commit -m "Initial commit"
git push -u origin main
```

### 3-3. GitHub Pages 활성화
1. 저장소 → **Settings** → **Pages**
2. Source: **Deploy from a branch**
3. Branch: `main` / `/ (root)`
4. **Save** 클릭
5. 약 1~2분 후 `https://[계정명].github.io/game-news/` 접근 가능

### 3-4. 인증 토큰 설정 (push 자동화)
1. GitHub → Settings → **Developer settings** → **Personal access tokens** → Tokens (classic)
2. **Generate new token** → `repo` 권한 체크
3. 생성된 토큰을 Windows 자격 증명 관리자에 저장:
   ```
   git config --global credential.helper manager
   ```
   첫 push 시 브라우저 인증 또는 토큰 입력 창이 뜹니다.

---

## 4. Windows 작업 스케줄러 등록

> **수집 주기**: 매일 00:00 KST 실행 → 전일(00:00~23:59) 뉴스 취합
> 예) 4/3 00:00 실행 → 4/2 뉴스 수집 → `game_news_20260402.html` 생성

1. **작업 스케줄러** 실행 (시작 메뉴 검색)
2. **작업 만들기** 클릭
3. **일반** 탭:
   - 이름: `게임 업계 동향 크롤러`
   - 체크: `사용자가 로그온하지 않아도 실행`
4. **트리거** 탭 → **새로 만들기**:
   - 시작: `매일` / 시간: `00:00`
   - ※ 주말 포함 매일 실행 (요일 필터 없음)
5. **동작** 탭 → **새로 만들기**:
   - 프로그램/스크립트: `C:\Users\Admin\Documents\game-news\run_crawler.bat`
6. **확인** → 관리자 비밀번호 입력

또는 명령 프롬프트(관리자 권한)에서 한 줄 등록:
```
schtasks /create /tn "게임업계동향크롤러" /tr "C:\Users\Admin\Documents\game-news\run_crawler.bat" /sc daily /st 00:00 /ru SYSTEM
```

---

## 5. 결과물 접근 URL

| 항목 | URL |
|------|-----|
| 최신 페이지 | `https://[계정명].github.io/game-news/` |
| 날짜별 페이지 | `https://[계정명].github.io/game-news/game_news_20260401.html` |
| XLSX 파일 | `C:\Users\Admin\Desktop\일일 체크리스트\...` (로컬) |

---

## 6. HTML 페이지 기능

| 기능 | 설명 |
|------|------|
| TOP 5 카드 | 조회수·중요도 기준 상위 5개 기사 (루리웹 베스트 우선) |
| 신작 소식 | CBT·사전예약·출시 등 신규 게임 관련 |
| 게임 소식 | 업데이트·패치·이벤트 등 서비스 중 게임 관련 |
| 게임 회사 동향 | 인수·합병·투자·실적·구조조정 관련 |
| 일반 | 위 3개 미해당 기사 |
| 기사 제목 클릭 | 원문 URL로 이동 |
| 검색 | 제목 실시간 키워드 검색 |
| 국내/해외 배지 | 파란=국내, 붉은=해외 |
| HOT 배지 | 루리웹 베스트 게시판 기사 |

---

## 7. 알려진 제한사항

| 사이트 | 이슈 | 대응 |
|--------|------|------|
| 디스이즈게임 | Cloudflare 직접 차단 | 구글뉴스 RSS 경유 |
| VentureBeat | 게임 전용 RSS 403 | 전체 RSS + 게임 키워드 필터 |
| 대부분 HTML 사이트 | 발행 시각 파싱 불가 | pub_dt = None, 최신순 상위만 수집 |
| 게임포커스·게임조선 | CSS 셀렉터 변경 가능성 | 첫 실행 후 실패 시 셀렉터 수정 필요 |

---

## 8. 셀렉터 수정 방법

사이트 구조 변경으로 기사가 수집되지 않을 경우:

1. Chrome에서 해당 사이트 접속
2. **F12** → **Elements** 탭
3. 기사 제목 링크 요소 확인
4. `game_news_crawler.py`에서 해당 함수의 `soup.select(...)` 부분 수정
