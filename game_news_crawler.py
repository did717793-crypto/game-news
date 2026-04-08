#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
게임 업계 동향 크롤러 v2.1
- 10개 사이트 크롤링 (매일 00:00 KST 실행, 주말 포함)
- 수집 범위: 실행 전일 00:00 ~ 23:59 KST (고정 24h)
- XLSX 출력 (기존 구조 유지: 신작 소식 / 게임 회사 동향 / HOT TOPIC / 일반)
- HTML 출력 (신규: 신작 소식 / 게임 소식 / 게임 회사 동향 / 일반) → GitHub Pages 배포
- 실행 환경: Python 3.10+
"""

import os
import re
import json
import subprocess
import concurrent.futures
from datetime import datetime, timedelta
from pathlib import Path

import requests
import feedparser
from bs4 import BeautifulSoup
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment
import pytz

# ──────────────────────────────────────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────────────────────────────────────
KST = pytz.timezone("Asia/Seoul")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
# 기사 본문 fetch 전용 헤더 (브라우저 접속처럼 위장)
ARTICLE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}

# 저장 경로
BASE_DIR   = Path(r"C:\Users\Admin\Desktop\일일 체크리스트")
GITHUB_DIR = Path(r"C:\Users\Admin\Documents\game-news")  # git clone 위치

# 루리웹 HOT TOPIC 조회수 기준
RULIWEB_HOT_VIEWS = 5000


# ──────────────────────────────────────────────────────────────────────────────
# 유틸리티
# ──────────────────────────────────────────────────────────────────────────────
def clean(text: str) -> str:
    """surrogate / 제어문자 제거 및 공백 정리"""
    if not isinstance(text, str):
        text = str(text) if text else ""
    text = text.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def get_now() -> datetime:
    return datetime.now(KST)


def get_content_date(now: datetime) -> datetime:
    """수집 대상일 = 실행일 전날 (00:00 KST 기준)"""
    yesterday = now - timedelta(days=1)
    # 자정(00:00)으로 초기화
    return yesterday.replace(hour=0, minute=0, second=0, microsecond=0)


def get_time_window(now: datetime):
    """수집 윈도우: 전일 00:00:00 ~ 23:59:59 KST (항상 24h 고정)"""
    start = get_content_date(now)
    end   = start + timedelta(hours=23, minutes=59, seconds=59)
    return start, end


def get_folder_name(content_date: datetime) -> str:
    """폴더명은 수집 대상일(전일) 기준"""
    return content_date.strftime("%Y.%m.%d")


def parse_pub_dt(pub_dt_str) -> "datetime | None":
    """RSS published 문자열 -> KST datetime 변환"""
    if not pub_dt_str:
        return None
    try:
        import email.utils
        dt = email.utils.parsedate_to_datetime(pub_dt_str)
        return dt.astimezone(KST)
    except Exception:
        return None


def fetch(url: str, timeout: int = 15):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"  [WARN] fetch 실패: {url} — {e}")
        return None


def parse_rss(url: str) -> list:
    try:
        feed = feedparser.parse(url)
        return feed.entries
    except Exception as e:
        print(f"  [WARN] RSS 파싱 실패: {url} — {e}")
        return []


# ──────────────────────────────────────────────────────────────────────────────
# 카테고리 분류 키워드
# ──────────────────────────────────────────────────────────────────────────────
KW_NEW_GAME = [
    "신작", "출시", "런칭", "오픈", "사전예약", "베타", "cbt", "obt",
    "공개", "골드행", "발매", "서비스 시작", "서비스 오픈", "얼리액세스",
    "launch", "release", "announce", "reveal", "pre-registration",
    "early access", "open beta", "closed beta",
]

KW_COMPANY = [
    "인수", "합병", "투자", "펀딩", "실적", "매출", "영업이익", "순이익",
    "구조조정", "서비스 종료", "서비스종료", "파트너십", "계약", "지분",
    "상장", "ipo", "직원 감축", "정리해고",
    "acquisition", "layoff", "merger", "funding", "raises", "acquires",
    "bankruptcy", "shutdown", "restructur", "revenue", "earnings",
]

KW_GAME_NEWS = [
    "업데이트", "패치", "밸런스", "신규 서버", "신규서버", "이벤트",
    "콘텐츠", "시즌", "리뉴얼", "점검", "대규모", "새로운 챕터",
    "신규 캐릭터", "신규 영웅", "신규 맵", "신규 던전",
    "update", "patch", "balance", "season", "content", "event",
    "new character", "new map", "expansion", "dlc", "hotfix",
]


def classify_html(title: str, summary: str) -> str:
    """HTML 출력용 4개 카테고리 분류"""
    text = (title + " " + summary).lower()
    for kw in KW_NEW_GAME:
        if kw in text:
            return "신작 소식"
    for kw in KW_COMPANY:
        if kw in text:
            return "게임 회사 동향"
    for kw in KW_GAME_NEWS:
        if kw in text:
            return "게임 소식"
    return "일반"


def classify_xlsx(title: str, summary: str, is_ruliweb_best: bool, views: int) -> str:
    """XLSX 출력용 원본 4개 카테고리 분류"""
    text = (title + " " + summary).lower()
    for kw in KW_NEW_GAME:
        if kw in text:
            return "신작 소식"
    for kw in KW_COMPANY:
        if kw in text:
            return "게임 회사 동향"
    if is_ruliweb_best or (views and views >= RULIWEB_HOT_VIEWS):
        return "HOT TOPIC"
    return "일반"


# ──────────────────────────────────────────────────────────────────────────────
# 장르 감지 + 제목 접두어 제거
# ──────────────────────────────────────────────────────────────────────────────
_GENRE_KW = [
    ("MMORPG",     ["mmorpg", "mmo", "다중접속", "대규모 다중"]),
    ("수집형 RPG", ["수집형", "가챠", "컬렉션 rpg"]),
    ("방치형",     ["방치형", "방치 rpg", "idle"]),
    ("전략",       ["전략", "slg", "전략 시뮬"]),
    ("슈팅",       ["슈팅", "fps", "tps"]),
    ("배틀로얄",   ["배틀로얄", "battle royale"]),
    ("스포츠",     ["스포츠", "풋볼", "축구"]),
    ("액션 RPG",   ["액션 rpg", "action rpg"]),
    ("RPG",        ["rpg"]),
]

def detect_genre(title: str, body: str) -> str:
    text = (title + " " + (body or "")[:300]).lower()
    for genre, kws in _GENRE_KW:
        if any(kw in text for kw in kws):
            return genre
    return ""

_PREFIX_RE = re.compile(r'^(\[.*?\]|\(.*?\)|【.*?】|《.*?》|〈.*?〉)\s*')

def strip_title_prefix(title: str) -> str:
    """[단독], [게임동향] 등 제목 앞 접두어 반복 제거"""
    result = title
    while True:
        m = _PREFIX_RE.match(result)
        if m:
            result = result[m.end():]
        else:
            break
    return result.strip()


# ──────────────────────────────────────────────────────────────────────────────
# 기사 저장소
# ──────────────────────────────────────────────────────────────────────────────
ARTICLES: list[dict] = []
_seen_urls:   set[str] = set()
_seen_titles: set[str] = set()


def add_article(article: dict):
    url = article.get("url", "").strip()
    title = article.get("title", "").strip()

    if not url or not title:
        return
    if url in _seen_urls:
        return

    title_key = re.sub(r'\s', '', title[:30]).lower()
    if title_key in _seen_titles:
        return

    _seen_urls.add(url)
    _seen_titles.add(title_key)

    article["title"]        = clean(title)
    article["summary"]      = clean(article.get("summary", ""))
    article["site"]         = clean(article.get("site", ""))
    article["collected_at"] = get_now().strftime("%Y-%m-%d %H:%M")
    article.setdefault("views", 0)
    article.setdefault("comments", 0)
    article.setdefault("pub_dt", None)
    article.setdefault("is_domestic", True)
    article.setdefault("is_ruliweb_best", False)

    # pub_dt 파싱 → pub_date (표시용) + _pub_datetime (날짜 필터용)
    _pdt = parse_pub_dt(article.get("pub_dt"))
    article["_pub_datetime"] = _pdt
    article["pub_date"] = _pdt.strftime("%Y-%m-%d %H:%M") if _pdt else ""

    ARTICLES.append(article)


# ──────────────────────────────────────────────────────────────────────────────
# 크롤러 (10개 사이트)
# ──────────────────────────────────────────────────────────────────────────────

# 1. 디스이즈게임 — Google News RSS (Cloudflare 차단으로 직접 접근 불가)
def crawl_thisisgame():
    print("  ▶ 디스이즈게임")
    url = "https://news.google.com/rss/search?q=site:thisisgame.com&hl=ko&gl=KR&ceid=KR:ko"
    for e in parse_rss(url)[:25]:
        add_article({
            "site": "디스이즈게임",
            "title": e.get("title", ""),
            "url": e.get("link", ""),
            "summary": clean(e.get("summary", ""))[:200],
            "pub_dt": e.get("published", None),
            "is_domestic": True,
        })


# 2. 게임메카 — HTML 파싱
def crawl_gamemeca():
    print("  ▶ 게임메카")
    r = fetch("https://www.gamemeca.com/news.php")
    if not r:
        return
    soup = BeautifulSoup(r.text, "lxml")
    for a in soup.select('a[href*="view.php?gid="]')[:25]:
        title = clean(a.get_text())
        if not title or len(title) < 5:
            continue
        href = a.get("href", "")
        if not href.startswith("http"):
            href = "https://www.gamemeca.com/" + href.lstrip("/")
        add_article({"site": "게임메카", "title": title, "url": href, "is_domestic": True})


# 3. 게임조선 — HTML 파싱
def crawl_gamechosun():
    print("  ▶ 게임조선")
    r = fetch("https://gamechosun.co.kr/")
    if not r:
        return
    soup = BeautifulSoup(r.text, "lxml")
    anchors = (
        soup.select('a[href*="view.php?no="]') +
        soup.select('a[href*="/article/"]')
    )
    seen_in_page: set[str] = set()
    for a in anchors[:30]:
        title = clean(a.get_text())
        if not title or len(title) < 5:
            continue
        href = a.get("href", "")
        if not href.startswith("http"):
            href = "https://gamechosun.co.kr" + href
        if href in seen_in_page:
            continue
        seen_in_page.add(href)
        add_article({"site": "게임조선", "title": title, "url": href, "is_domestic": True})


# 4. 인벤 — RSS
def crawl_inven():
    print("  ▶ 인벤")
    for e in parse_rss("https://www.inven.co.kr/webzine/news/rss.php")[:25]:
        add_article({
            "site": "인벤",
            "title": e.get("title", ""),
            "url": e.get("link", ""),
            "summary": clean(e.get("summary", ""))[:200],
            "pub_dt": e.get("published", None),
            "is_domestic": True,
        })


# 5. 게임포커스 — HTML 파싱
def crawl_gamefocus():
    print("  ▶ 게임포커스")
    r = fetch("https://www.gamefocus.co.kr/")
    if not r:
        return
    soup = BeautifulSoup(r.text, "lxml")
    for a in soup.select('a[href*="detail.php?number="]')[:25]:
        title = clean(a.get_text())
        if not title or len(title) < 5:
            continue
        href = a.get("href", "")
        if not href.startswith("http"):
            href = "https://www.gamefocus.co.kr/" + href.lstrip("/")
        add_article({"site": "게임포커스", "title": title, "url": href, "is_domestic": True})


# 6. 루리웹 — 뉴스 + 베스트 HTML 파싱
def crawl_ruliweb():
    print("  ▶ 루리웹 뉴스")
    r = fetch("https://bbs.ruliweb.com/news")
    if r:
        soup = BeautifulSoup(r.text, "lxml")
        for row in soup.select("table.board_list_table tr"):
            a = row.select_one("td.subject a.deco")
            if not a:
                continue
            title = clean(a.get_text())
            url = a.get("href", "")
            if not url.startswith("http"):
                url = "https://bbs.ruliweb.com" + url

            views = 0
            comments = 0
            vt = row.select_one("td.hit")
            if vt:
                try:
                    views = int(re.sub(r'[^\d]', '', vt.get_text()))
                except Exception:
                    pass
            ct = row.select_one("td.replycount")
            if ct:
                try:
                    comments = int(re.sub(r'[^\d]', '', ct.get_text()))
                except Exception:
                    pass

            add_article({
                "site": "루리웹",
                "title": title,
                "url": url,
                "is_domestic": True,
                "is_ruliweb_best": False,
                "views": views,
                "comments": comments,
            })

    print("  ▶ 루리웹 베스트")
    r2 = fetch("https://bbs.ruliweb.com/best/article/all")
    if r2:
        soup = BeautifulSoup(r2.text, "lxml")
        for row in soup.select("table.board_list_table tr"):
            a = row.select_one("td.subject a.deco")
            if not a:
                continue
            title = clean(a.get_text())
            url = a.get("href", "")
            if not url.startswith("http"):
                url = "https://bbs.ruliweb.com" + url

            views = 0
            vt = row.select_one("td.hit")
            if vt:
                try:
                    views = int(re.sub(r'[^\d]', '', vt.get_text()))
                except Exception:
                    pass

            add_article({
                "site": "루리웹",
                "title": title,
                "url": url,
                "is_domestic": True,
                "is_ruliweb_best": True,
                "views": views,
                "comments": 0,
            })


# 7. 네이버뉴스 IT/게임 섹션 — HTML 파싱
def crawl_naver():
    print("  ▶ 네이버뉴스 IT/게임")
    r = fetch("https://news.naver.com/section/105")
    if not r:
        return
    soup = BeautifulSoup(r.text, "lxml")
    for a in soup.select("a.sa_text_title")[:25]:
        title = clean(a.get_text())
        if not title or len(title) < 5:
            continue
        href = a.get("href", "")
        if not href.startswith("http"):
            href = "https://news.naver.com" + href
        add_article({"site": "네이버뉴스", "title": title, "url": href, "is_domestic": True})


# 8. Game Developer — RSS
def crawl_gamedeveloper():
    print("  ▶ Game Developer")
    for e in parse_rss("https://www.gamedeveloper.com/rss.xml")[:25]:
        add_article({
            "site": "Game Developer",
            "title": e.get("title", ""),
            "url": e.get("link", ""),
            "summary": clean(e.get("summary", ""))[:200],
            "pub_dt": e.get("published", None),
            "is_domestic": False,
        })


# 9. VentureBeat — RSS + 게임 키워드 필터
VB_GAME_KW = [
    "game", "gaming", "esport", "nintendo", "sony", "microsoft", "xbox",
    "playstation", "steam", "mobile game", "rpg", "mmorpg", "fps", "unity",
    "unreal", "epic games", "riot", "blizzard", "activision", "ubisoft",
    "ea games", "take-two", "netmarble", "nexon", "krafton", "ncsoft",
]


def crawl_venturebeat():
    print("  ▶ VentureBeat")
    for e in parse_rss("https://venturebeat.com/feed/")[:60]:
        text = (e.get("title", "") + " " + e.get("summary", "")).lower()
        if not any(kw in text for kw in VB_GAME_KW):
            continue
        add_article({
            "site": "VentureBeat",
            "title": e.get("title", ""),
            "url": e.get("link", ""),
            "summary": clean(e.get("summary", ""))[:200],
            "pub_dt": e.get("published", None),
            "is_domestic": False,
        })


# 10. PocketGamer.biz — HTML 파싱 (모바일 B2B)
def crawl_pocketgamer():
    print("  ▶ PocketGamer.biz")
    r = fetch("https://www.pocketgamer.biz/news/")
    if not r:
        return
    soup = BeautifulSoup(r.text, "lxml")
    for a in soup.select("article a")[:30]:
        title = clean(a.get_text())
        if not title or len(title) < 15:
            continue
        href = a.get("href", "")
        if not href.startswith("http"):
            href = "https://www.pocketgamer.biz" + href
        add_article({"site": "PocketGamer.biz", "title": title, "url": href, "is_domestic": False})


def run_all(win_start=None, win_end=None):
    print("\n[1/3] 크롤링 시작")
    crawl_thisisgame()
    crawl_gamemeca()
    crawl_gamechosun()
    crawl_inven()
    crawl_gamefocus()
    crawl_ruliweb()
    crawl_naver()
    crawl_gamedeveloper()
    crawl_venturebeat()
    crawl_pocketgamer()

    # ── 날짜 필터: pub_date 있는 기사는 수집 윈도우 내 것만 유지 ──────────────
    if win_start and win_end:
        ARTICLES[:] = [
            a for a in ARTICLES
            if a.get("_pub_datetime") is None  # 날짜 모름(HTML 스크래핑) → 포함
            or (win_start <= a["_pub_datetime"] <= win_end)
        ]

    # 카테고리 분류
    for art in ARTICLES:
        art["cat_html"] = classify_html(art["title"], art["summary"])
        art["cat_xlsx"] = classify_xlsx(
            art["title"],
            art["summary"],
            art.get("is_ruliweb_best", False),
            art.get("views", 0),
        )

    # ── 해외 기사 제거 (국내 언론사 기사만 대시보드에 표시) ──────────────────
    ARTICLES[:] = [a for a in ARTICLES if a.get("is_domestic", True)]

    # ── 루리웹 BEST 비게임 기사 필터링 ──────────────────────────────────────
    GAME_FILTER_KW = [
        "게임", "모바일", "스팀", "콘솔", "플스", "엑박", "ps5", "ps4", "xbox",
        "닌텐도", "서버", "패치", "업데이트", "출시", "런칭", "사전예약", "오픈",
        "던파", "메이플", "로스트아크", "로아", "리니지", "오버워치", "롤",
        "발로란트", "넥슨", "엔씨", "크래프톤", "카카오게임즈", "넷마블",
        "펄어비스", "스마일게이트", "컴투스", "위메이드", "시프트업",
        "배그", "배틀그라운드", "디아블로", "포트나이트", "마인크래프트",
        "mmo", "rpg", "fps", "moba", "pc방", "e스포츠", "esports",
    ]
    ARTICLES[:] = [
        a for a in ARTICLES
        if not a.get("is_ruliweb_best")
        or any(kw in a.get("title", "").lower() for kw in GAME_FILTER_KW)
    ]

    # ── 사업 PM 관점 콘텐츠 중요도 스코어링 ────────────────────────────────
    # Tier S+ (+12): 신작 발표·사전예약·서비스 오픈 — 경쟁사 게임 라이프사이클 핵심
    PM_TIER_SP = [
        "사전예약", "사전 등록", "사전예약 시작", "사전예약 오픈",
        "cbt", "obt", "얼리 액세스", "얼리엑세스",
        "그랜드 오픈", "신규 서버", "서비스 시작", "정식 출시", "정식출시",
        "정식 서비스", "오픈일 확정", "출시일 확정", "최초 공개", "신작 공개",
        "첫 공개", "월드 프리미어",
    ]
    # Tier S (+10): 업계 구조 변화 — 반드시 알아야 할 비즈니스 이벤트
    PM_TIER_S = [
        "인수", "합병", "매각", "파산", "폐업", "청산",
        "해고", "감원", "구조조정", "희망퇴직", "인력 감축", "정리해고",
        "대규모 해고", "직원 해고", "직원 감축",
        "상장", "ipo", "코스닥 상장", "코스피 상장",
        "서비스 종료", "서버 종료", "서비스종료", "게임 종료",
    ]
    # Tier A (+8): 재무·경영 이벤트
    PM_TIER_A = [
        "투자 유치", "투자", "시리즈 a", "시리즈 b", "시리즈 c",
        "영업이익", "영업손실", "영업 이익", "영업 손실",
        "매출", "적자", "흑자", "손익", "영업실적", "실적 발표",
        "대표이사 교체", "ceo 교체", "신규 대표", "대표 취임", "대표 사임",
    ]
    # Tier B (+6): 게임 업계 흐름·기술 트렌드 (AI는 아래 별도 처리)
    PM_TIER_B = [
        "언리얼", "유니티", "클라우드 게임",
        "게임 시장", "모바일 시장", "글로벌 진출", "해외 진출",
        "규제", "심의", "게임 법", "확률형 아이템",
        "e스포츠", "리그", "대회", "월드챔피언십",
    ]
    # AI는 게임 컨텍스트와 함께 있을 때만 Tier B 인정
    _AI_TERMS   = ["ai", "인공지능", "생성형", "llm", "머신러닝"]
    _AI_GAME_CTX= ["게임", "개발", "스튜디오", "게임사", "콘텐츠", "npc", "캐릭터"]
    # Tier C (+4): 출시·런칭 (일반)
    PM_TIER_C = [
        "출시", "런칭", "오픈", "공개", "발표",
    ]
    # Tier D (+2): 일반 게임 소식
    PM_TIER_D = [
        "업데이트", "패치", "신규 콘텐츠", "이벤트", "시즌",
    ]
    # Tier E (0): 게임 외적 상품 — site_cnt만 반영
    PM_TIER_E = [
        "피규어", "굿즈", "인형", "쿠션", "키링", "포스터", "아크릴",
        "마우스", "키보드", "헤드셋", "모니터", "메모리", "ram", "그래픽카드",
        "노트북", "데스크탑", "주변기기", "pc 부품", "하드웨어",
        "게이밍 체어", "게이밍 의자",
    ]
    # Tier PROMO (+2): 할인/무료 프로모션 — S+ 키워드와 겹쳐도 강제 하향
    PM_TIER_PROMO = [
        "무료 체험", "무료 플레이", "무료 배포", "무료로 즐길", "무료 증정",
        "할인 프로모션", "할인 이벤트", "할인 판매", "특별 할인",
        "무료 증정", "공짜로", "번들 증정",
    ]

    for art in ARTICLES:
        t = art.get("title", "").lower()
        if any(kw in t for kw in PM_TIER_E):
            cs = 0
        elif any(kw in t for kw in PM_TIER_PROMO):
            cs = 2          # 프로모션은 S+ 발동 전에 잡아서 Tier D 수준으로 고정
        elif any(kw in t for kw in PM_TIER_SP):
            cs = 12
        elif any(kw in t for kw in PM_TIER_S):
            cs = 10
        elif any(kw in t for kw in PM_TIER_A):
            cs = 8
        elif (any(kw in t for kw in _AI_TERMS)
              and any(kw in t for kw in _AI_GAME_CTX)):
            cs = 6          # AI + 게임 컨텍스트 → Tier B
        elif any(kw in t for kw in PM_TIER_B):
            cs = 6
        elif any(kw in t for kw in PM_TIER_C):
            cs = 4
        elif any(kw in t for kw in PM_TIER_D):
            cs = 2
        else:
            cs = 1
        art["_content_score"] = cs

    # ── 중복 기사 클러스터링 & 대표 1건 선택 ─────────────────────────────────
    # 3자 이상 고유 키워드 2개 이상 겹치면 동일 기사로 판단
    _STOP = {
        "게임", "이번", "이후", "공개", "발표", "서비스", "업데이트",
        "이상", "국내", "지난", "최근", "현재", "시작", "진행", "관련",
        "뉴스", "기사", "한국", "새로운", "출시", "오픈",
    }

    def _dedup_kw(title: str) -> set:
        raw = set(re.findall(r"[가-힣a-zA-Z0-9]{2,}", title.lower()))
        return {w for w in raw if len(w) >= 3 and w not in _STOP}

    kw_list = [_dedup_kw(a.get("title", "")) for a in ARTICLES]
    visited = [False] * len(ARTICLES)
    clusters = []
    for i in range(len(ARTICLES)):
        if visited[i]:
            continue
        cluster = [i]
        visited[i] = True
        for j in range(i + 1, len(ARTICLES)):
            if visited[j]:
                continue
            if len(kw_list[i] & kw_list[j]) >= 2:   # 고유 키워드 2개 이상 일치
                cluster.append(j)
                visited[j] = True
        clusters.append(cluster)

    kept = []
    for cluster in clusters:
        # 클러스터에서 content_score 가장 높은 기사를 대표로 선택
        # (같으면 수집 사이트 다양성 기준으로 우선)
        best = max(cluster, key=lambda i: (
            ARTICLES[i]["_content_score"],
            len(ARTICLES[i].get("site", "")),
        ))
        rep = ARTICLES[best]
        # 클러스터 사이트 목록 (대표 기사 + 중복들)
        covered = list({ARTICLES[idx].get("site", "") for idx in cluster
                        if ARTICLES[idx].get("site")})
        rep["_site_cnt"]      = len(covered)
        rep["_covered_sites"] = covered
        rep["_score"]         = rep["_site_cnt"] + rep["_content_score"]
        kept.append(rep)

    ARTICLES[:] = kept

    print(f"\n  중복 제거 후: {len(ARTICLES)}건 (원본 클러스터 {len(clusters)}개)")
    by_cat = {}
    for art in ARTICLES:
        c = art["cat_html"]
        by_cat[c] = by_cat.get(c, 0) + 1
    for k, v in by_cat.items():
        print(f"  - {k}: {v}건")


# ──────────────────────────────────────────────────────────────────────────────
# XLSX 출력 (기존 구조 유지)
# ──────────────────────────────────────────────────────────────────────────────
CAT_COLORS_XLSX = {
    "신작 소식":     "FFF2CC",
    "게임 회사 동향": "DDEEFF",
    "HOT TOPIC":    "FFE0E0",
    "일반":          "F8F8F8",
}


def write_ws(ws, articles: list[dict]):
    headers = ["카테고리", "출처", "제목", "요약", "URL", "조회수", "댓글", "수집시각"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1C2340")
        cell.alignment = Alignment(horizontal="center")

    for art in articles:
        cat = art.get("cat_xlsx", "일반")
        ws.append([
            cat,
            art.get("site", ""),
            art.get("title", ""),
            art.get("summary", ""),
            art.get("url", ""),
            art.get("views", 0),
            art.get("comments", 0),
            art.get("collected_at", ""),
        ])
        color = CAT_COLORS_XLSX.get(cat, "F8F8F8")
        for cell in ws[ws.max_row]:
            cell.fill = PatternFill("solid", fgColor=color)

    ws.column_dimensions["A"].width = 14
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 62
    ws.column_dimensions["D"].width = 40
    ws.column_dimensions["E"].width = 52
    ws.column_dimensions["F"].width = 8
    ws.column_dimensions["G"].width = 8
    ws.column_dimensions["H"].width = 16


def save_xlsx(content_date: datetime) -> Path:
    """파일·폴더명 모두 수집 대상일(전일) 기준"""
    folder_name = get_folder_name(content_date)
    folder_path = BASE_DIR / folder_name
    folder_path.mkdir(parents=True, exist_ok=True)

    file_path = folder_path / f"game_news_{content_date.strftime('%Y%m%d')}.xlsx"

    wb = openpyxl.Workbook()

    ws_all = wb.active
    ws_all.title = "전체"
    write_ws(ws_all, ARTICLES)

    for cat_name in ["신작 소식", "게임 회사 동향", "HOT TOPIC"]:
        ws = wb.create_sheet(title=cat_name)
        write_ws(ws, [a for a in ARTICLES if a.get("cat_xlsx") == cat_name])

    wb.save(file_path)
    print(f"  XLSX 저장: {file_path}")
    return file_path


# ──────────────────────────────────────────────────────────────────────────────
# HTML 출력 (lol.ps 스타일, 신규)
# ──────────────────────────────────────────────────────────────────────────────
HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>GAME PULSE — PM 대시보드</title>
  <style>
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
    body{background:#0f0e1a;color:#e8e4ff;font-family:'Apple SD Gothic Neo','Malgun Gothic',-apple-system,BlinkMacSystemFont,sans-serif;font-size:14px;line-height:1.5;min-height:100vh;}
    a{color:inherit;text-decoration:none;}
    ::-webkit-scrollbar{width:5px;height:5px;}
    ::-webkit-scrollbar-track{background:#14122a;}
    ::-webkit-scrollbar-thumb{background:#3d3870;border-radius:3px;}
    ::-webkit-scrollbar-thumb:hover{background:#6c5ce7;}

    /* ── HEADER ── */
    .g-header{background:#1a1830;border-bottom:1px solid #2d2850;padding:0 20px;height:52px;display:flex;align-items:center;gap:14px;position:sticky;top:0;z-index:300;}
    .logo{font-size:15px;font-weight:900;color:#a29bfe;letter-spacing:-.3px;white-space:nowrap;}
    .logo span{color:#fff;}
    .h-nav{display:flex;gap:5px;overflow-x:auto;flex:1;padding:4px 0;}
    .h-nav::-webkit-scrollbar{height:0;}
    .h-date-btn{background:#2d2850;color:#b2bec3;border:1px solid #3d3870;border-radius:5px;padding:3px 10px;font-size:11px;font-weight:700;cursor:pointer;white-space:nowrap;flex-shrink:0;transition:all .15s;}
    .h-date-btn:hover{background:#3d3870;color:#e8e4ff;}
    .h-date-btn.active{background:#6c5ce7;color:#fff;border-color:#6c5ce7;}
    .h-stat{font-size:11px;color:#636e72;white-space:nowrap;}
    .h-stat b{color:#a29bfe;}

    /* ── PM INSIGHTS BAR ── */
    .ins-bar{background:#14122a;border-bottom:1px solid #2d2850;padding:8px 20px;display:flex;gap:0;position:sticky;top:52px;z-index:290;overflow-x:auto;}
    .ins-bar::-webkit-scrollbar{height:0;}
    .ins-item{display:flex;flex-direction:column;align-items:center;padding:2px 20px;border-right:1px solid #2d2850;min-width:90px;}
    .ins-item:last-child{border-right:none;}
    .ins-label{font-size:10px;font-weight:700;color:#636e72;white-space:nowrap;margin-bottom:1px;}
    .ins-val{font-size:22px;font-weight:900;line-height:1.1;}
    .iv-r{color:#e17055;} .iv-c{color:#00b894;} .iv-d{color:#fdcb6e;} .iv-p{color:#a29bfe;}

    /* ── DATE BAR ── */
    .date-bar{background:#1a1830;border-bottom:1px solid #2d2850;padding:8px 20px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
    .date-label{font-size:11px;font-weight:700;color:#6c5ce7;white-space:nowrap;}
    .date-input{background:#2d2850;border:1px solid #3d3870;border-radius:5px;padding:4px 8px;font-size:12px;color:#e8e4ff;outline:none;transition:border-color .15s;}
    .date-input:focus{border-color:#6c5ce7;}
    .date-sep{color:#6c5ce7;font-size:12px;}
    .btn-load{background:#6c5ce7;color:#fff;border:none;border-radius:5px;padding:5px 14px;font-size:12px;font-weight:700;cursor:pointer;transition:background .2s;}
    .btn-load:hover{background:#5a4bd1;}
    .date-quick{display:flex;gap:4px;margin-left:auto;}
    .q-btn{background:#2d2850;color:#b2bec3;border:1px solid #3d3870;border-radius:20px;padding:3px 10px;font-size:11px;font-weight:600;cursor:pointer;transition:all .15s;}
    .q-btn:hover,.q-btn.active{background:#6c5ce7;color:#fff;border-color:#6c5ce7;}
    .date-err{font-size:11px;color:#e17055;font-weight:600;}

    /* ── MAIN TABS ── */
    .main-tabs{background:#1a1830;border-bottom:2px solid #2d2850;padding:0 20px;display:flex;}
    .main-tab{padding:12px 22px;font-size:14px;font-weight:700;color:#636e72;cursor:pointer;border-bottom:3px solid transparent;margin-bottom:-2px;transition:all .15s;white-space:nowrap;}
    .main-tab:hover{color:#a29bfe;}
    .main-tab.active{color:#a29bfe;border-bottom-color:#6c5ce7;}
    .tab-cnt{display:inline-block;background:#2d2850;color:#a29bfe;font-size:10px;font-weight:800;padding:1px 5px;border-radius:8px;margin-left:5px;}
    .main-tab.active .tab-cnt{background:#6c5ce7;color:#fff;}

    /* ── PAGE ── */
    .app-page{display:none;}
    .app-page.active{display:block;}

    /* ── SECTION ── */
    .section{padding:16px 20px;}
    .sec-ttl{font-size:10px;font-weight:800;letter-spacing:1.2px;color:#6c5ce7;text-transform:uppercase;margin-bottom:12px;display:flex;align-items:center;gap:8px;}
    .sec-ttl::after{content:'';flex:1;height:1px;background:linear-gradient(90deg,#2d2850,transparent);}

    /* ── TIMELINE FILTERS ── */
    .tl-filters{display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap;}
    .f-btn{background:#2d2850;color:#b2bec3;border:1px solid #3d3870;border-radius:20px;padding:3px 10px;font-size:11px;font-weight:600;cursor:pointer;transition:all .15s;}
    .f-btn:hover{border-color:#6c5ce7;color:#a29bfe;}
    .f-btn.active{background:#6c5ce7;color:#fff;border-color:#6c5ce7;}

    /* ── GANTT TIMELINE ── */
    .tl-wrap{background:#14122a;border:1px solid #2d2850;border-radius:8px;overflow:hidden;}
    .tl-head-row{display:flex;border-bottom:1px solid #2d2850;background:#1e1c38;}
    .tl-lbl-col{width:186px;min-width:186px;padding:6px 10px;font-size:9px;font-weight:700;color:#636e72;border-right:1px solid #2d2850;flex-shrink:0;}
    .tl-dates-wrap{flex:1;display:flex;overflow:hidden;}
    .tl-day{flex:1;text-align:center;font-size:9px;color:#636e72;padding:3px 0;border-right:1px solid #14122a;}
    .tl-day.wknd{background:rgba(108,92,231,0.06);}
    .tl-day.tod{color:#e17055;font-weight:800;}
    .tl-row{display:flex;border-bottom:1px solid #1a1830;min-height:34px;align-items:center;}
    .tl-row:last-child{border-bottom:none;}
    .tl-row:hover{background:#1c1a34;}
    .tl-event-lbl{width:186px;min-width:186px;padding:5px 10px;border-right:1px solid #2d2850;display:flex;align-items:center;gap:5px;cursor:pointer;overflow:hidden;flex-shrink:0;}
    .tl-event-lbl:hover .tl-gname{color:#a29bfe;}
    .tl-etype{font-size:8px;font-weight:800;padding:2px 4px;border-radius:2px;white-space:nowrap;flex-shrink:0;}
    .tl-gname{font-size:10px;color:#e8e4ff;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
    .tl-bars{flex:1;position:relative;height:34px;}
    .tl-bar{position:absolute;top:7px;height:20px;border-radius:3px;cursor:pointer;display:flex;align-items:center;padding:0 5px;overflow:hidden;transition:opacity .15s;min-width:2px;}
    .tl-bar:hover{opacity:.75;}
    .tl-bar-txt{font-size:8px;font-weight:700;color:rgba(255,255,255,.9);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
    .tl-today{position:absolute;top:0;bottom:0;width:2px;background:rgba(225,112,85,.5);z-index:2;pointer-events:none;}
    .tl-empty{text-align:center;padding:28px;color:#636e72;font-size:13px;}

    /* ── BADGES ── */
    .bdg{display:inline-block;font-size:9px;font-weight:800;padding:2px 5px;border-radius:3px;white-space:nowrap;line-height:1.5;}
    .bp{background:#0984e3;color:#fff;}
    .bc{background:#00b894;color:#fff;}
    .bo{background:#00cec9;color:#fff;}
    .br{background:#e17055;color:#fff;}
    .bs{background:#a29bfe;color:#1a1830;}
    .be{background:#fd79a8;color:#fff;}
    .bg{background:#2d2850;color:#a29bfe;border:1px solid #3d3870;}
    .bst{background:#1e1c38;color:#636e72;}
    .bi{background:#fdcb6e;color:#1a1830;}
    .bh{background:#e17055;color:#fff;}

    /* ── SEARCH ── */
    .search-row{padding:0 20px 10px;display:flex;gap:6px;}
    .search-input{flex:1;max-width:380px;background:#2d2850;border:1px solid #3d3870;border-radius:7px;color:#e8e4ff;padding:7px 12px;font-size:13px;outline:none;transition:border-color .15s;}
    .search-input:focus{border-color:#6c5ce7;}
    .search-input::placeholder{color:#636e72;}

    /* ── ARTICLE LIST ── */
    .art-list{padding:0 20px 40px;}
    .art-item{background:#1a1830;border:1px solid #2d2850;border-radius:7px;margin-bottom:5px;display:flex;align-items:center;gap:8px;padding:9px 12px;cursor:pointer;transition:background .12s,border-color .12s;border-left:3px solid transparent;}
    .art-item:hover{background:#1c1a34;border-color:#3d3870;}
    .ai-p{border-left-color:#0984e3;} .ai-c{border-left-color:#00b894;} .ai-o{border-left-color:#00cec9;}
    .ai-r{border-left-color:#e17055;} .ai-s{border-left-color:#a29bfe;} .ai-e{border-left-color:#fd79a8;}
    .ai-i{border-left-color:#fdcb6e;}
    .art-bdgs{display:flex;gap:3px;flex-shrink:0;align-items:center;flex-wrap:nowrap;}
    .art-1line{flex:1;font-size:13px;font-weight:600;color:#e8e4ff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;}
    .art-item:hover .art-1line{color:#a29bfe;}
    .art-meta{font-size:11px;color:#636e72;white-space:nowrap;flex-shrink:0;}

    /* ── SKELETON ── */
    .sk-item{background:#1a1830;border:1px solid #2d2850;border-radius:7px;margin-bottom:5px;padding:12px;display:flex;gap:8px;align-items:center;}
    .sk{background:linear-gradient(90deg,#2d2850 25%,#3d3870 50%,#2d2850 75%);background-size:200% 100%;animation:shimmer 1.4s infinite;border-radius:3px;}
    @keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}
    .sk-b{width:48px;height:16px;flex-shrink:0;} .sk-t{height:13px;flex:1;} .sk-m{width:70px;height:11px;flex-shrink:0;}

    /* ── MODAL ── */
    .modal-ov{display:none;position:fixed;inset:0;background:rgba(0,0,0,.82);z-index:500;align-items:center;justify-content:center;padding:16px;}
    .modal-ov.open{display:flex;}
    .modal-box{background:#1a1830;border:1px solid #3d3870;border-radius:12px;width:100%;max-width:660px;max-height:82vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 24px 64px rgba(0,0,0,.7);}
    .modal-hd{padding:18px 20px 14px;border-bottom:1px solid #2d2850;display:flex;align-items:flex-start;gap:10px;}
    .modal-ttl{flex:1;font-size:15px;font-weight:700;color:#e8e4ff;line-height:1.4;}
    .modal-x{background:#2d2850;border:none;border-radius:5px;color:#b2bec3;width:30px;height:30px;font-size:18px;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:background .15s;}
    .modal-x:hover{background:#e17055;color:#fff;}
    .modal-meta{padding:8px 20px;border-bottom:1px solid #2d2850;display:flex;gap:6px;flex-wrap:wrap;align-items:center;}
    .modal-dt{font-size:11px;color:#636e72;}
    .modal-body{flex:1;overflow-y:auto;padding:14px 20px;font-size:13px;color:#b2bec3;line-height:1.8;white-space:pre-wrap;word-break:break-word;}
    .modal-no-body{color:#636e72;font-style:italic;text-align:center;padding:36px 0;font-size:13px;}
    .modal-ft{padding:12px 20px;border-top:1px solid #2d2850;display:flex;justify-content:flex-end;}
    .btn-orig{background:#6c5ce7;color:#fff;border:none;border-radius:7px;padding:8px 18px;font-size:13px;font-weight:700;cursor:pointer;text-decoration:none;display:inline-block;transition:background .2s;}
    .btn-orig:hover{background:#5a4bd1;}

    /* ── EMPTY / LOADING ── */
    .empty-st{text-align:center;padding:40px 20px;color:#636e72;}
    .empty-ic{font-size:36px;margin-bottom:10px;}
    .empty-mg{font-size:13px;}
    .ld-ov{display:none;position:fixed;inset:0;background:rgba(15,14,26,.6);z-index:400;align-items:center;justify-content:center;}
    .ld-ov.show{display:flex;}
    .ld-sp{width:36px;height:36px;border:3px solid #2d2850;border-top-color:#6c5ce7;border-radius:50%;animation:spin .7s linear infinite;}
    @keyframes spin{to{transform:rotate(360deg)}}
  </style>
</head>
<body>

<!-- Loading -->
<div class="ld-ov" id="ldOv"><div class="ld-sp"></div></div>

<!-- Modal -->
<div class="modal-ov" id="modalOv">
  <div class="modal-box">
    <div class="modal-hd">
      <div class="modal-ttl" id="mTitle"></div>
      <button class="modal-x" id="mClose">&#215;</button>
    </div>
    <div class="modal-meta" id="mMeta"></div>
    <div class="modal-body" id="mBody"></div>
    <div class="modal-ft">
      <a class="btn-orig" id="mLink" href="#" target="_blank" rel="noopener">기사 원문 보기 &#8599;</a>
    </div>
  </div>
</div>

<!-- Header -->
<div class="g-header">
  <div class="logo">GAME <span>PULSE</span></div>
  <div class="h-nav" id="hNav"></div>
  <div class="h-stat" id="hStat">로딩 중...</div>
</div>

<!-- PM Insights Bar -->
<div class="ins-bar">
  <div class="ins-item"><div class="ins-label">&#128308; 오늘 출시</div><div class="ins-val iv-r" id="ins0">&#8212;</div></div>
  <div class="ins-item"><div class="ins-label">&#128994; 진행 중 CBT</div><div class="ins-val iv-c" id="ins1">&#8212;</div></div>
  <div class="ins-item"><div class="ins-label">&#128202; 이번 주 신작</div><div class="ins-val iv-d" id="ins2">&#8212;</div></div>
  <div class="ins-item"><div class="ins-label">&#128309; 사전예약 중</div><div class="ins-val iv-p" id="ins3">&#8212;</div></div>
</div>

<!-- Date bar -->
<div class="date-bar">
  <div class="date-label">날짜 범위</div>
  <input type="date" class="date-input" id="dFrom">
  <span class="date-sep">~</span>
  <input type="date" class="date-input" id="dTo">
  <button class="btn-load" id="btnLoad">조회</button>
  <div class="date-quick">
    <button class="q-btn active" data-days="0">어제</button>
    <button class="q-btn" data-days="6">7일</button>
    <button class="q-btn" data-days="13">2주</button>
    <button class="q-btn" data-days="29">1개월</button>
  </div>
  <span class="date-err" id="dErr"></span>
</div>

<!-- Main Tabs -->
<div class="main-tabs">
  <div class="main-tab active" data-pg="new">신작 소식 <span class="tab-cnt" id="cntNew">0</span></div>
  <div class="main-tab" data-pg="ind">업계 뉴스 <span class="tab-cnt" id="cntInd">0</span></div>
</div>

<!-- Page: 신작 소식 -->
<div class="app-page active" id="pg-new">
  <div class="section">
    <div class="sec-ttl">신작 타임라인</div>
    <div class="tl-filters">
      <button class="f-btn active" data-et="전체">전체</button>
      <button class="f-btn" data-et="출시">출시</button>
      <button class="f-btn" data-et="OBT">OBT</button>
      <button class="f-btn" data-et="CBT">CBT</button>
      <button class="f-btn" data-et="사전예약">사전예약</button>
      <button class="f-btn" data-et="신규서버">신규서버</button>
    </div>
    <div class="tl-wrap" id="tlWrap"><div class="tl-empty">데이터 로딩 중...</div></div>
  </div>
  <div class="section" style="padding-top:0;padding-bottom:4px"><div class="sec-ttl">신작 뉴스</div></div>
  <div class="search-row"><input type="text" class="search-input" id="schNew" placeholder="게임명, 장르 검색..."></div>
  <div class="art-list" id="lstNew"></div>
</div>

<!-- Page: 업계 뉴스 -->
<div class="app-page" id="pg-ind">
  <div class="section" style="padding-bottom:4px"><div class="sec-ttl">업계 뉴스</div></div>
  <div class="search-row"><input type="text" class="search-input" id="schInd" placeholder="회사명, 키워드 검색..."></div>
  <div class="art-list" id="lstInd"></div>
</div>

<script>
(function(){
  var BASE="data/", DATES=[], DATA=[], tlEt="전체", schN="", schI="";

  /* ── 유틸 ── */
  function esc(s){
    return String(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }
  function pad(n){return n<10?"0"+n:String(n);}
  function fmtD(d){return d.getFullYear()+"-"+pad(d.getMonth()+1)+"-"+pad(d.getDate());}
  function kst(s){return new Date(s+"T00:00:00+09:00");}
  function diffDays(a,b){return Math.round((b-a)/86400000);}

  /* ── 제목 접두어 제거: [단독], [게임동향] 등 ── */
  function cleanT(t){
    return (t||"").replace(/^(\[[\s\S]*?\]|\([\s\S]*?\)|【[\s\S]*?】|《[\s\S]*?》)\s*/g,"").trim();
  }

  /* ── 이벤트 타입 매핑 ── */
  var ET_BDG={"사전예약":"bp","CBT":"bc","OBT":"bo","출시":"br","신규서버":"bs","얼리액세스":"be"};
  var ET_ART={"사전예약":"ai-p","CBT":"ai-c","OBT":"ai-o","출시":"ai-r","신규서버":"ai-s","얼리액세스":"ai-e"};
  var ET_COL={"사전예약":"#0984e3","CBT":"#00b894","OBT":"#00cec9","출시":"#e17055","신규서버":"#a29bfe","얼리액세스":"#fd79a8"};
  var ET_PRI={"출시":1,"OBT":2,"CBT":3,"사전예약":4,"신규서버":5,"얼리액세스":6};
  var NEW_ET=new Set(["사전예약","CBT","OBT","출시","신규서버","얼리액세스"]);

  /* ── 신작/업계 분류 ── */
  function isNew(a){return !!(a.is_new_event||a.category==="신작 소식");}
  function isInd(a){
    if(isNew(a)) return false;
    return a.category==="게임 회사 동향"||a.category==="일반";
  }

  /* ── Skeleton ── */
  function skeleton(id,n){
    var h="";
    for(var i=0;i<n;i++) h+='<div class="sk-item"><div class="sk sk-b"></div><div class="sk sk-t"></div><div class="sk sk-m"></div></div>';
    document.getElementById(id).innerHTML=h;
  }

  /* ── PM Insights ── */
  function calcIns(){
    var today=fmtD(new Date());
    var ws=new Date(); ws.setDate(ws.getDate()-ws.getDay());
    var we=new Date(ws); we.setDate(ws.getDate()+6);
    var wsS=fmtD(ws), weS=fmtD(we);
    var r=0,c=0,d=0,p=0;
    DATA.forEach(function(a){
      var es=a.event_start||"", ee=a.event_end||es;
      if(!es) return;
      if(a.event_type==="출시"&&es<=today&&today<=ee) r++;
      if(a.event_type==="CBT"&&es<=today&&today<=ee) c++;
      if(es>=wsS&&es<=weS&&NEW_ET.has(a.event_type||"")) d++;
      if(a.event_type==="사전예약"&&es<=today&&today<=ee) p++;
    });
    document.getElementById("ins0").textContent=r;
    document.getElementById("ins1").textContent=c;
    document.getElementById("ins2").textContent=d+"건";
    document.getElementById("ins3").textContent=p;
  }

  /* ── 타임라인 (Gantt) ── */
  function renderTL(){
    var wrap=document.getElementById("tlWrap");
    var evts=DATA.filter(function(a){
      if(!a.event_start) return false;
      if(!NEW_ET.has(a.event_type||"")) return false;
      if(tlEt!=="전체"&&a.event_type!==tlEt) return false;
      return true;
    });
    if(!evts.length){
      wrap.innerHTML='<div class="tl-empty">표시할 이벤트 일정이 없습니다</div>';
      return;
    }

    /* 날짜 범위 계산 */
    var today=new Date();
    var allD=[today];
    evts.forEach(function(e){
      if(e.event_start) allD.push(kst(e.event_start));
      if(e.event_end)   allD.push(kst(e.event_end));
    });
    var minD=new Date(Math.min.apply(null,allD));
    var maxD=new Date(Math.max.apply(null,allD));
    minD.setDate(minD.getDate()-2);
    maxD.setDate(maxD.getDate()+3);
    var total=diffDays(minD,maxD)+1;
    if(total>56){
      minD=new Date(today); minD.setDate(today.getDate()-7);
      maxD=new Date(today); maxD.setDate(today.getDate()+42);
      total=50;
    }

    /* 날짜 헤더 */
    var showEvery=total>28?7:total>14?3:1;
    var hdrCells="";
    for(var i=0;i<total;i++){
      var dd=new Date(minD); dd.setDate(minD.getDate()+i);
      var ds=fmtD(dd);
      var isT=(ds===fmtD(today));
      var isW=(dd.getDay()===0||dd.getDay()===6);
      var lbl=(i%showEvery===0)?((dd.getMonth()+1)+"/"+dd.getDate()):"";
      hdrCells+='<div class="tl-day'+(isT?" tod":"")+(isW?" wknd":"")+'">'+esc(lbl)+'</div>';
    }

    /* 이벤트 정렬 */
    evts.sort(function(a,b){
      var ap=ET_PRI[a.event_type]||9, bp=ET_PRI[b.event_type]||9;
      if(ap!==bp) return ap-bp;
      return (a.event_start||"").localeCompare(b.event_start||"");
    });

    /* 오늘 라인 위치 */
    var todayOff=diffDays(minD,today);
    var todayPct=(todayOff>=0&&todayOff<total)?(todayOff/total*100).toFixed(2):-1;

    /* 행 생성 */
    var rows="";
    evts.slice(0,30).forEach(function(art){
      var es=art.event_start, ee=art.event_end||es;
      var esD=kst(es), eeD=kst(ee);
      if(eeD<minD||esD>maxD) return;
      var clS=esD<minD?minD:esD;
      var clE=eeD>maxD?maxD:eeD;
      var off=diffDays(minD,clS);
      var span=diffDays(clS,clE)+1;
      var lp=(off/total*100).toFixed(2);
      var wp=Math.max(span/total*100,0.8).toFixed(2);
      var col=ET_COL[art.event_type]||"#6c5ce7";
      var etCls=ET_BDG[art.event_type]||"";
      var nm=cleanT(art.cleaned_title||art.title||"");
      var idx=DATA.indexOf(art);
      var dateLbl=es.slice(5)+(ee&&ee!==es?"~"+ee.slice(5):"");

      rows+='<div class="tl-row">'+
        '<div class="tl-event-lbl" onclick="openM('+idx+')">'+
          '<span class="tl-etype bdg '+etCls+'">'+esc(art.event_type||"")+'</span>'+
          '<span class="tl-gname">'+esc(nm)+'</span>'+
        '</div>'+
        '<div class="tl-bars">'+
          (todayPct>=0?'<div class="tl-today" style="left:'+todayPct+'%"></div>':'')+
          '<div class="tl-bar" style="left:'+lp+'%;width:'+wp+'%;background:'+col+'" '+
            'onclick="openM('+idx+')" title="'+esc(nm)+': '+esc(dateLbl)+'">'+
            '<span class="tl-bar-txt">'+esc(dateLbl)+'</span>'+
          '</div>'+
        '</div>'+
      '</div>';
    });

    wrap.innerHTML=
      '<div class="tl-head-row">'+
        '<div class="tl-lbl-col">이벤트</div>'+
        '<div class="tl-dates-wrap">'+hdrCells+'</div>'+
      '</div>'+
      rows;
  }

  /* ── 신작 뉴스 리스트 ── */
  function renderNew(){
    var c=document.getElementById("lstNew");
    var q=schN.toLowerCase();
    /* 제외 키워드: 기존 게임 업데이트/이벤트/패치는 신작 탭에서 숨김 */
    var EXCL=["업데이트","패치","밸런스","신규 캐릭터","이벤트 시작","시즌 오픈","점검"];
    var items=DATA.filter(function(a){
      if(!isNew(a)) return false;
      /* 제외 키워드 필터: event_type 이 명확히 있으면 무조건 포함 */
      if(!NEW_ET.has(a.event_type||"")){
        var t=(a.title||"").toLowerCase();
        if(EXCL.some(function(kw){return t.indexOf(kw)!==-1;})) return false;
      }
      if(q){
        var t2=(a.title||"").toLowerCase();
        var g=(a.genre||"").toLowerCase();
        if(t2.indexOf(q)===-1&&g.indexOf(q)===-1) return false;
      }
      return true;
    });
    items.sort(function(a,b){
      var ap=ET_PRI[a.event_type]||9, bp=ET_PRI[b.event_type]||9;
      if(ap!==bp) return ap-bp;
      return (b.score||0)-(a.score||0);
    });
    document.getElementById("cntNew").textContent=items.length;
    if(!items.length){
      c.innerHTML='<div class="empty-st"><div class="empty-ic">&#127918;</div><div class="empty-mg">신작 소식이 없습니다</div></div>';
      return;
    }
    var h="";
    items.forEach(function(art){
      var et=art.event_type||"";
      var ac=ET_ART[et]||"";
      var eb=et?'<span class="bdg '+ET_BDG[et]+'">'+esc(et)+'</span>':"";
      var gb=art.genre?'<span class="bdg bg">'+esc(art.genre)+'</span>':"";
      var ol=cleanT(art.cleaned_title||art.title||"");
      var mt=(art.pub_date||art.collected_at||"").slice(5,10);
      var idx=DATA.indexOf(art);
      h+='<div class="art-item '+ac+'" onclick="openM('+idx+')">'+
        '<div class="art-bdgs">'+eb+gb+'</div>'+
        '<div class="art-1line">'+esc(ol)+'</div>'+
        '<div class="art-meta">'+esc(art.site||"")+(mt?"&nbsp;&middot;&nbsp;"+esc(mt):"")+'</div>'+
      '</div>';
    });
    c.innerHTML=h;
  }

  /* ── 업계 뉴스 리스트 ── */
  function renderInd(){
    var c=document.getElementById("lstInd");
    var q=schI.toLowerCase();
    var items=DATA.filter(function(a){
      if(!isInd(a)) return false;
      if(q&&(a.title||"").toLowerCase().indexOf(q)===-1) return false;
      return true;
    });
    items.sort(function(a,b){return (b.score||0)-(a.score||0);});
    document.getElementById("cntInd").textContent=items.length;
    if(!items.length){
      c.innerHTML='<div class="empty-st"><div class="empty-ic">&#128240;</div><div class="empty-mg">업계 뉴스가 없습니다</div></div>';
      return;
    }
    var h="";
    items.forEach(function(art){
      var catBdg='<span class="bdg bi">'+esc(art.category||"업계")+'</span>';
      var ol=cleanT(art.cleaned_title||art.title||"");
      var mt=(art.pub_date||art.collected_at||"").slice(5,10);
      var idx=DATA.indexOf(art);
      h+='<div class="art-item ai-i" onclick="openM('+idx+')">'+
        '<div class="art-bdgs">'+catBdg+'</div>'+
        '<div class="art-1line">'+esc(ol)+'</div>'+
        '<div class="art-meta">'+esc(art.site||"")+(mt?"&nbsp;&middot;&nbsp;"+esc(mt):"")+'</div>'+
      '</div>';
    });
    c.innerHTML=h;
  }

  /* ── 모달 ── */
  window.openM=function(idx){
    var art=DATA[idx]; if(!art) return;
    document.getElementById("mTitle").textContent=cleanT(art.cleaned_title||art.title||"");
    var et=art.event_type||"";
    var mh=(art.site?'<span class="bdg bst">'+esc(art.site)+'</span>':"")+
      (et?'<span class="bdg '+ET_BDG[et]+'">'+esc(et)+'</span>':"")+
      (art.genre?'<span class="bdg bg">'+esc(art.genre)+'</span>':"")+
      (art.pub_date?'<span class="modal-dt">'+esc(art.pub_date)+'</span>':
        art.collected_at?'<span class="modal-dt">'+esc(art.collected_at)+'</span>':"")+
      (art.event_start?'<span class="modal-dt">&#128197; '+esc(art.event_start+(art.event_end&&art.event_end!==art.event_start?" ~ "+art.event_end:""))+'</span>':"");
    document.getElementById("mMeta").innerHTML=mh;
    var body=(art.body||"").trim();
    if(body.length>20){
      document.getElementById("mBody").textContent=body;
    } else {
      document.getElementById("mBody").innerHTML='<div class="modal-no-body">기사 본문을 불러올 수 없습니다.<br>아래 원문 보기 버튼을 이용해 주세요.</div>';
    }
    document.getElementById("mLink").href=art.url||"#";
    document.getElementById("modalOv").classList.add("open");
    document.body.style.overflow="hidden";
  };

  function closeM(){
    document.getElementById("modalOv").classList.remove("open");
    document.body.style.overflow="";
  }
  document.getElementById("mClose").addEventListener("click",closeM);
  document.getElementById("modalOv").addEventListener("click",function(e){if(e.target===this)closeM();});
  document.addEventListener("keydown",function(e){if(e.key==="Escape")closeM();});

  /* ── 탭 전환 ── */
  document.querySelectorAll(".main-tab").forEach(function(btn){
    btn.addEventListener("click",function(){
      document.querySelectorAll(".main-tab").forEach(function(b){b.classList.remove("active");});
      document.querySelectorAll(".app-page").forEach(function(p){p.classList.remove("active");});
      btn.classList.add("active");
      document.getElementById("pg-"+btn.dataset.pg).classList.add("active");
    });
  });

  /* ── 타임라인 필터 ── */
  document.querySelectorAll(".f-btn[data-et]").forEach(function(btn){
    btn.addEventListener("click",function(){
      document.querySelectorAll(".f-btn[data-et]").forEach(function(b){b.classList.remove("active");});
      btn.classList.add("active");
      tlEt=btn.dataset.et;
      renderTL();
    });
  });

  /* ── 검색 ── */
  document.getElementById("schNew").addEventListener("input",function(){schN=this.value.trim();renderNew();});
  document.getElementById("schInd").addEventListener("input",function(){schI=this.value.trim();renderInd();});

  /* ── 데이터 로드 ── */
  function loadData(dates){
    if(!dates.length){
      ["lstNew","lstInd"].forEach(function(id){
        document.getElementById(id).innerHTML='<div class="empty-st"><div class="empty-ic">&#128235;</div><div class="empty-mg">해당 기간 데이터 없음</div></div>';
      });
      document.getElementById("ins0").textContent=document.getElementById("ins1").textContent=
      document.getElementById("ins2").textContent=document.getElementById("ins3").textContent="0";
      return;
    }
    skeleton("lstNew",6); skeleton("lstInd",4);
    document.getElementById("ldOv").classList.add("show");
    DATA=[]; var pend=dates.length;
    dates.forEach(function(d){
      var x=new XMLHttpRequest();
      x.open("GET",BASE+d+".json?v="+Date.now(),true);
      x.onload=function(){
        if(x.status===200){try{DATA=DATA.concat(JSON.parse(x.responseText));}catch(e){}}
        if(--pend===0) onLoaded();
      };
      x.onerror=function(){if(--pend===0) onLoaded();};
      x.send();
    });
  }

  function onLoaded(){
    document.getElementById("ldOv").classList.remove("show");
    document.getElementById("hStat").innerHTML="수집 <b>"+DATA.length+"</b>건";
    calcIns(); renderTL(); renderNew(); renderInd();
  }

  function loadRange(f,t){
    var fd=kst(f), td=kst(t);
    if(fd>td){document.getElementById("dErr").textContent="시작일이 종료일보다 큽니다";return;}
    document.getElementById("dErr").textContent="";
    loadData(DATES.filter(function(d){var dd=kst(d);return dd>=fd&&dd<=td;}));
  }

  /* ── 날짜 목록 로드 ── */
  function loadDates(){
    var x=new XMLHttpRequest();
    x.open("GET",BASE+"dates.json?v="+Date.now(),true);
    x.onload=function(){
      if(x.status!==200){
        document.getElementById("lstNew").innerHTML='<div class="empty-st"><div class="empty-ic">&#9888;&#65039;</div><div class="empty-mg">데이터 없음 (dates.json 확인 필요)</div></div>';
        return;
      }
      try{DATES=(JSON.parse(x.responseText).dates||[]);}catch(e){DATES=[];}
      var nav=document.getElementById("hNav"); nav.innerHTML="";
      DATES.slice(0,8).forEach(function(d,i){
        var btn=document.createElement("button");
        btn.className="h-date-btn"+(i===0?" active":"");
        btn.textContent=d.slice(5).replace("-","/");
        btn.dataset.d=d;
        btn.addEventListener("click",function(){
          document.querySelectorAll(".h-date-btn").forEach(function(b){b.classList.remove("active");});
          btn.classList.add("active");
          document.getElementById("dFrom").value=d;
          document.getElementById("dTo").value=d;
          loadRange(d,d);
        });
        nav.appendChild(btn);
      });
      if(DATES.length){
        var l=DATES[0];
        document.getElementById("dFrom").value=l;
        document.getElementById("dTo").value=l;
        loadRange(l,l);
      }
    };
    x.onerror=function(){
      document.getElementById("lstNew").innerHTML='<div class="empty-st"><div class="empty-ic">&#9888;&#65039;</div><div class="empty-mg">데이터 로드 실패</div></div>';
    };
    x.send();
  }

  /* ── 날짜 이벤트 ── */
  document.getElementById("btnLoad").addEventListener("click",function(){
    var f=document.getElementById("dFrom").value, t=document.getElementById("dTo").value;
    if(!f||!t){document.getElementById("dErr").textContent="날짜를 선택하세요";return;}
    loadRange(f,t);
  });
  document.querySelectorAll(".q-btn").forEach(function(btn){
    btn.addEventListener("click",function(){
      document.querySelectorAll(".q-btn").forEach(function(b){b.classList.remove("active");});
      btn.classList.add("active");
      var days=parseInt(btn.dataset.days,10), l=DATES[0];
      if(!l) return;
      var t=l, f=days===0?l:fmtD(new Date(kst(l).getTime()-days*86400000));
      document.getElementById("dFrom").value=f;
      document.getElementById("dTo").value=t;
      loadRange(f,t);
    });
  });

  loadDates();
}());
</script>
</body>
</html>
"""



def _make_articles_data() -> list:
    """ARTICLES 전역 리스트를 JSON 직렬화용 딕셔너리 리스트로 변환"""
    result = []
    for art in ARTICLES:
        result.append({
            "site":            art.get("site", ""),
            "title":           art.get("title", ""),
            "url":             art.get("url", ""),
            "summary":         art.get("summary", ""),
            "body":            art.get("body_text", ""),
            "category":        art.get("cat_html", "일반"),
            "is_domestic":     art.get("is_domestic", True),
            "is_ruliweb_best": art.get("is_ruliweb_best", False),
            "views":           art.get("views", 0),
            "comments":        art.get("comments", 0),
            "collected_at":    art.get("collected_at", ""),
            "pub_date":        art.get("pub_date", ""),
            "score":           art.get("_score", 0),
            "site_cnt":        art.get("_site_cnt", 1),
            "content_score":   art.get("_content_score", 1),
            "covered_sites":   art.get("_covered_sites", []),
            "event_date":      art.get("event_date", ""),
            "event_type":      art.get("event_type", ""),
            "event_start":     art.get("event_start", ""),
            "event_end":       art.get("event_end", ""),
            "genre":           art.get("genre", ""),
            "cleaned_title":   strip_title_prefix(art.get("title", "")),
            "is_new_event":    art.get("cat_html") == "신작 소식",
        })
    return result


def build_html() -> str:
    """index.html 동적 셸 반환 (데이터는 data/*.json 에서 동적 로드)"""
    return HTML_TEMPLATE


def save_html() -> Path:
    """index.html 을 GITHUB_DIR 에 저장 (날짜별 파일 없음)"""
    GITHUB_DIR.mkdir(parents=True, exist_ok=True)
    index = GITHUB_DIR / "index.html"
    index.write_text(HTML_TEMPLATE, encoding="utf-8")
    print(f"  HTML 저장: {index}")
    return index


def save_json(content_date: datetime) -> Path:
    """수집 기사를 data/YYYY-MM-DD.json 으로 저장"""
    data_dir = GITHUB_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    date_str  = content_date.strftime("%Y-%m-%d")
    file_path = data_dir / f"{date_str}.json"
    articles  = _make_articles_data()

    file_path.write_text(
        json.dumps(articles, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"  JSON 저장: {file_path} ({len(articles)}건)")
    return file_path


def update_dates_json(max_days: int = 30):
    """data/dates.json — 저장된 날짜 목록을 최신 순으로 유지 (최대 max_days 일)"""
    data_dir   = GITHUB_DIR / "data"
    dates_file = data_dir / "dates.json"
    data_dir.mkdir(parents=True, exist_ok=True)

    # 기존 JSON 파일 목록 스캔
    existing = sorted(
        [p.stem for p in data_dir.glob("????-??-??.json")],
        reverse=True
    )
    # 최대 max_days 개만 유지
    dates = existing[:max_days]

    # 임시 파일에 먼저 쓴 뒤 교체 → 중단 시 손상 방지
    tmp = dates_file.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"dates": dates}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    tmp.replace(dates_file)
    print(f"  dates.json 업데이트: {len(dates)}개 날짜")


_ETYPE_MAP = [
    ("사전예약",   ["사전예약", "사전 예약", "사전등록", "사전 등록"]),
    ("CBT",        ["cbt", "클로즈드 베타", "클베", "비공개 테스트", "비공개베타"]),
    ("OBT",        ["obt", "오픈 베타", "공개 베타"]),
    ("신규서버",   ["신규 서버", "신서버", "새 서버"]),
    ("종료",       ["서비스 종료", "서버 종료", "게임 종료", "서비스종료"]),
    ("얼리액세스", ["얼리 액세스", "얼리엑세스", "early access"]),
    ("출시",       ["정식 출시", "정식출시", "그랜드 오픈", "런칭", "서비스 시작", "정식 서비스"]),
]

def detect_event_type(text: str) -> str:
    t = text.lower()
    for etype, kws in _ETYPE_MAP:
        if any(kw in t for kw in kws):
            return etype
    return "출시"


def extract_event_range(title: str, body: str, ref_year: int):
    """(event_start, event_end) YYYY-MM-DD 반환. 없으면 ('', '')"""
    text = (title or "") + " " + (body or "")[:600]

    def mk(y, mo, d):
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y}-{mo:02d}-{d:02d}"
        return None

    # 명시적 범위: MM월 DD일 ~ MM월 DD일
    m = re.search(
        r"(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*[~\-]\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일",
        text
    )
    if m:
        s = mk(ref_year, int(m.group(1)), int(m.group(2)))
        e = mk(ref_year, int(m.group(3)), int(m.group(4)))
        if s and e and s <= e:
            return s, e

    # 단일 날짜 수집
    dates = []
    for m2 in re.finditer(r"(20\d\d)\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", text):
        d = mk(int(m2.group(1)), int(m2.group(2)), int(m2.group(3)))
        if d:
            dates.append(d)
    for m2 in re.finditer(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", text):
        d = mk(ref_year, int(m2.group(1)), int(m2.group(2)))
        if d:
            dates.append(d)
    dates = sorted(set(dates))
    if dates:
        return dates[0], dates[0]
    return "", ""


def extract_event_date(title: str, body: str, ref_year: int) -> str:
    """기사 제목/본문에서 이벤트 발생 날짜 추출 (YYYY-MM-DD 반환, 없으면 "")
    우선순위: 연월일 > 월일 > M/D 슬래시 패턴
    """
    text = (title or "") + " " + (body or "")[:400]
    # 2026년 4월 2일 패턴
    m = re.search(r"(20\d\d)\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y}-{mo:02d}-{d:02d}"
    # 4월 2일 패턴 (연도 없음 → ref_year)
    m = re.search(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", text)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{ref_year}-{mo:02d}-{d:02d}"
    # 4/2 슬래시 패턴
    m = re.search(r"\b(\d{1,2})/(\d{1,2})\b", text)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{ref_year}-{mo:02d}-{d:02d}"
    return ""


def extract_date_from_soup(soup) -> "datetime | None":
    """기사 페이지 HTML에서 발행일 추출 (meta → time → 텍스트 순)"""
    # 1. meta 태그 (가장 신뢰도 높음)
    for attrs in [
        {"property": "article:published_time"},
        {"name": "pubdate"},
        {"name": "article:published"},
        {"property": "og:updated_time"},
        {"name": "Date"},
    ]:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            try:
                s = tag["content"].strip()
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                return dt.astimezone(KST)
            except Exception:
                pass
    # 2. <time datetime="...">
    tag = soup.find("time", attrs={"datetime": True})
    if tag:
        try:
            s = tag["datetime"].strip()
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.astimezone(KST)
        except Exception:
            pass
    # 3. 페이지 상단 텍스트에서 날짜 패턴 (YYYY-MM-DD / YYYY.MM.DD)
    text = soup.get_text()[:4000]
    m = re.search(r"(20\d{2})[.\-](0?[1-9]|1[0-2])[.\-](0?[1-9]|[12]\d|3[01])", text)
    if m:
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return datetime(y, mo, d, 12, 0, tzinfo=KST)
        except Exception:
            pass
    return None


def fetch_article_body(url: str, timeout: int = 10):
    """기사 원문 URL에서 (본문 텍스트, 발행일) 반환"""
    try:
        session = requests.Session()
        session.headers.update(ARTICLE_HEADERS)
        r = session.get(url, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        # 발행일 먼저 추출 (태그 제거 전)
        pub_dt = extract_date_from_soup(soup)

        for tag in soup(["script", "style", "nav", "header", "footer", "aside",
                          "figure", "figcaption", ".copyright", ".ad", ".banner"]):
            tag.decompose()
        # 한국 게임 언론사 전용 셀렉터 (우선순위 순)
        SITE_SELECTORS = [
            # 게임조선
            ".article_body", ".articleView", ".view_content",
            # 디스이즈게임
            ".news-content", ".view_article", ".article-text",
            # 게임메카
            ".view_text", ".article-body-content",
            # 인벤
            ".news_content", ".view-content",
            # 게임포커스
            ".article_view", ".news_view", ".news-view",
            # 루리웹
            ".view_content", ".board_main_content",
            # 네이버 뉴스
            ".newsct_article", "#articleBodyContents", ".article-body",
            # 공통
            "article", ".article-body", ".article_body", "#articleBody",
            ".post-content", ".entry-content", ".content-body",
            "[itemprop='articleBody']", ".story-body",
        ]
        for sel in SITE_SELECTORS:
            el = soup.select_one(sel)
            if el:
                text = clean(el.get_text(separator=" "))
                if len(text) > 80:
                    return text[:1200], pub_dt
        # 폴백: 충분히 긴 <p> 태그 모음
        paras = [clean(p.get_text()) for p in soup.select("p")
                 if len(p.get_text().strip()) > 40]
        if paras:
            return " ".join(paras[:6])[:1200], pub_dt
        return "", pub_dt
    except Exception:
        return "", None


def enrich_articles_body(win_start=None, win_end=None):
    """수집된 기사 본문 fetch + 발행일 추출 + 날짜 재필터 (병렬 8 workers)"""
    targets = [a for a in ARTICLES if not a.get("body_text")]
    print(f"  본문 보강 중 ({len(targets)}건, 병렬 8)...")

    def _fetch(art):
        body, pub_dt = fetch_article_body(art["url"])
        if body:
            art["body_text"] = body
        # pub_date 없는 기사(HTML 스크래핑)에 날짜 채우기
        if not art.get("pub_date") and pub_dt:
            art["_pub_datetime"] = pub_dt
            art["pub_date"] = pub_dt.strftime("%Y-%m-%d %H:%M")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(_fetch, targets))

    # 날짜 재필터: 본문 fetch 후 날짜 확인된 기사 중 범위 벗어난 것 제거
    if win_start and win_end:
        before = len(ARTICLES)
        ARTICLES[:] = [
            a for a in ARTICLES
            if a.get("_pub_datetime") is None
            or (win_start <= a["_pub_datetime"] <= win_end)
        ]
        removed = before - len(ARTICLES)
        if removed:
            print(f"  날짜 재필터: {removed}건 제거 (범위 외)")

    # ── 이벤트 날짜 + 타입 + 기간 추출 ────────────────────────────────────────
    ref_year = datetime.now(KST).year
    for art in ARTICLES:
        if art.get("_content_score", 0) < 4:
            continue
        t = art.get("title", "")
        b = art.get("body_text", "")
        # 이벤트 타입 (신작 소식 카테고리 기사만)
        if art.get("cat_html") in ("신작 소식", "게임 소식"):
            art["event_type"] = detect_event_type(t + " " + b)
        # 이벤트 날짜(단일) — 기존 로직
        if not art.get("event_date"):
            ev = extract_event_date(t, b, ref_year)
            if ev:
                art["event_date"] = ev
        # 이벤트 기간 (start/end)
        if not art.get("event_start"):
            es, ee = extract_event_range(t, b, ref_year)
            if es:
                art["event_start"] = es
                art["event_end"]   = ee
            elif art.get("event_date"):
                art["event_start"] = art["event_date"]
                art["event_end"]   = art["event_date"]

    filled = sum(1 for a in ARTICLES if a.get("body_text"))
    ev_cnt = sum(1 for a in ARTICLES if a.get("event_date"))
    print(f"  본문 보강 완료: {filled}/{len(ARTICLES)}건 / 이벤트 날짜: {ev_cnt}건")
    # 장르 감지 (본문 보강 후 실행)
    for art in ARTICLES:
        if not art.get("genre"):
            art["genre"] = detect_genre(
                art.get("title", ""),
                art.get("body_text", "") or art.get("summary", "")
            )


def push_github(content_date: datetime):
    try:
        os.chdir(GITHUB_DIR)
        msg = f"Update: {content_date.strftime('%Y-%m-%d')} 뉴스 수집"
        subprocess.run(["git", "add", "."],               check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", msg],      check=True, capture_output=True)
        subprocess.run(["git", "push", "origin", "main"], check=True, capture_output=True)
        print("  GitHub Pages 배포 완료 ✓")
    except subprocess.CalledProcessError as e:
        print(f"  [WARN] GitHub 푸시 실패: {e.stderr.decode(errors='ignore') if e.stderr else e}")
    except Exception as e:
        print(f"  [WARN] GitHub 배포 오류: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────────────────────────────────────
def main():
    now          = get_now()
    content_date = get_content_date(now)   # 수집 대상일 (전일)
    win_start, win_end = get_time_window(now)

    print(f"=== 게임 업계 동향 크롤러 v3.0 | 실행: {now.strftime('%Y-%m-%d %H:%M')} KST ===")
    print(f"    수집 대상: {win_start.strftime('%Y-%m-%d %H:%M')} ~ {win_end.strftime('%Y-%m-%d %H:%M')} KST")

    # 1. 크롤링 + 분류 (주말 포함 매일 실행)
    run_all(win_start, win_end)

    if not ARTICLES:
        print("[ERROR] 수집된 기사 없음. 종료.")
        return

    # 1-1. 본문 보강 (병렬 fetch)
    print("\n[1-1] 기사 본문 보강")
    enrich_articles_body(win_start, win_end)

    # 2. XLSX 저장 (전일 날짜 기준)
    print("\n[2/4] XLSX 저장")
    save_xlsx(content_date)

    # 3. JSON 저장 + index.html 갱신
    print("\n[3/4] JSON + HTML 저장")
    save_json(content_date)
    update_dates_json()
    save_html()

    # 4. GitHub 배포
    print("\n[4/4] GitHub Pages 배포")
    push_github(content_date)

    print(f"\n=== 완료: {len(ARTICLES)}건 처리 ===")


if __name__ == "__main__":
    main()
