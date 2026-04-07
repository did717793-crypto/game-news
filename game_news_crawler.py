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


def run_all():
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
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>게임 업계 동향</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #f0edff;
      color: #1a1a2e;
      font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', -apple-system, BlinkMacSystemFont, sans-serif;
      font-size: 14px;
      line-height: 1.5;
      min-height: 100vh;
    }
    a { color: inherit; text-decoration: none; }

    /* === Header === */
    .g-header {
      background: linear-gradient(135deg, #6c5ce7 0%, #a29bfe 100%);
      padding: 0 28px; height: 58px;
      display: flex; align-items: center; gap: 16px;
      position: sticky; top: 0; z-index: 200;
      box-shadow: 0 2px 12px rgba(108,92,231,0.4);
    }
    .logo { font-size: 17px; font-weight: 800; color: #fff; letter-spacing: -0.3px; white-space: nowrap; }
    .h-stat { font-size: 12px; color: rgba(255,255,255,0.85); margin-left: auto; white-space: nowrap; }
    .h-stat b { color: #fff; }

    /* === Page Navigation === */
    .page-nav { display: flex; gap: 6px; }
    .page-btn {
      background: rgba(255,255,255,0.15); color: rgba(255,255,255,0.85);
      border: 2px solid rgba(255,255,255,0.3); border-radius: 20px;
      padding: 5px 16px; font-size: 13px; font-weight: 700;
      cursor: pointer; transition: all 0.15s; white-space: nowrap;
    }
    .page-btn:hover { background: rgba(255,255,255,0.25); color: #fff; }
    .page-btn.active { background: #fff; color: #6c5ce7; border-color: #fff; }

    /* === App Pages === */
    .app-page { display: none; }
    .app-page.active { display: block; }

    /* === Date Bar === */
    .date-bar {
      background: #fff; border-bottom: 2px solid #e8e4ff;
      padding: 12px 28px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
    }
    .date-label { font-size: 12px; font-weight: 700; color: #6c5ce7; white-space: nowrap; }
    .date-input {
      border: 2px solid #d0c9ff; border-radius: 8px;
      padding: 6px 10px; font-size: 13px; color: #1a1a2e;
      outline: none; cursor: pointer; background: #fff;
    }
    .date-input:focus { border-color: #6c5ce7; }
    .date-sep { color: #6c5ce7; font-weight: 700; }
    .btn-load {
      background: #6c5ce7; color: #fff; border: none; border-radius: 8px;
      padding: 7px 18px; font-size: 13px; font-weight: 700;
      cursor: pointer; transition: background 0.2s;
    }
    .btn-load:hover { background: #5a4bd1; }
    .date-quick { display: flex; gap: 6px; margin-left: auto; }
    .q-btn {
      background: #f0edff; color: #6c5ce7; border: 2px solid #d0c9ff; border-radius: 20px;
      padding: 5px 14px; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.15s;
    }
    .q-btn:hover, .q-btn.active { background: #6c5ce7; color: #fff; border-color: #6c5ce7; }
    .date-hint { font-size: 11px; color: #a29bfe; white-space: nowrap; }
    .date-err { font-size: 12px; color: #e17055; font-weight: 600; }

    /* === Badges === */
    .badge {
      display: inline-block; font-size: 10px; font-weight: 700;
      padding: 2px 7px; border-radius: 20px; white-space: nowrap; line-height: 1.6;
    }
    .bcat-new   { background: #e8f4ff; color: #0984e3; }
    .bcat-game  { background: #e8fff4; color: #00b894; }
    .bcat-co    { background: #f0e8ff; color: #6c5ce7; }
    .bcat-gen   { background: #f5f5f5; color: #636e72; }
    .bsrc-dom   { background: #e3f9ff; color: #0984e3; }
    .bsrc-ovs   { background: #fff0f0; color: #e17055; }
    .bsite      { background: #f5f5f5; color: #636e72; }
    .bhot       { background: #fff0e8; color: #e17055; }
    .bview      { background: #fff8e8; color: #e6a817; }

    /* === Hero Carousel === */
    .hero-sec { padding: 24px 28px 16px; }
    .sec-eyebrow {
      font-size: 11px; font-weight: 800; letter-spacing: 1.5px;
      color: #6c5ce7; text-transform: uppercase; margin-bottom: 16px;
      display: flex; align-items: center; gap: 10px;
    }
    .sec-eyebrow::after {
      content: ''; flex: 1; height: 2px;
      background: linear-gradient(90deg, #6c5ce7 0%, transparent 100%);
    }
    .carousel-outer { position: relative; display: flex; align-items: center; }
    .car-btn {
      background: #6c5ce7; color: #fff; border: none; border-radius: 50%;
      width: 40px; height: 40px; font-size: 24px; flex-shrink: 0;
      cursor: pointer; display: flex; align-items: center; justify-content: center;
      transition: background 0.2s, transform 0.1s;
      box-shadow: 0 2px 8px rgba(108,92,231,0.4); z-index: 10;
    }
    .car-btn:hover { background: #5a4bd1; transform: scale(1.05); }
    .car-btn:active { transform: scale(0.95); }
    .car-btn:disabled { background: #d0c9ff; cursor: default; transform: none; box-shadow: none; }
    .carousel-viewport { overflow: hidden; flex: 1; margin: 0 14px; }
    .carousel-track {
      display: flex; gap: 16px;
      transition: transform 0.4s cubic-bezier(0.25, 0.46, 0.45, 0.94);
    }
    .hero-card {
      flex: 0 0 calc(33.333% - 10.67px);
      min-height: 230px;
      background: #fff; border-radius: 16px; border: 2px solid #e8e4ff;
      padding: 20px 18px; display: flex; flex-direction: column;
      position: relative; overflow: hidden;
      transition: box-shadow 0.2s, transform 0.2s, border-color 0.2s;
    }
    .hero-card::before {
      content: ''; position: absolute; top: 0; left: 0; right: 0; height: 4px;
      background: linear-gradient(90deg, #6c5ce7, #fd79a8);
    }
    .hero-card:hover { box-shadow: 0 8px 24px rgba(108,92,231,0.2); transform: translateY(-3px); border-color: #a29bfe; }
    .hero-rank { font-size: 32px; font-weight: 900; color: #e8e4ff; line-height: 1; margin-bottom: 10px; }
    .rank-gold   { color: #ffd32a; }
    .rank-silver { color: #bdbdbd; }
    .rank-bronze { color: #cd7f32; }
    .hero-title {
      font-size: 13px; font-weight: 700; color: #1a1a2e; line-height: 1.45;
      flex: 1; margin-bottom: 12px;
      display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden;
    }
    .hero-meta { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
    .hero-link {
      margin-top: 12px; display: block; width: 100%;
      background: linear-gradient(135deg, #6c5ce7, #a29bfe);
      color: #fff; border: none; border-radius: 8px;
      padding: 8px 12px; font-size: 11px; font-weight: 700;
      text-align: center; cursor: pointer; text-decoration: none;
      transition: opacity 0.2s;
    }
    .hero-link:hover { opacity: 0.85; }
    .hero-body-wrap { max-height: 0; overflow: hidden; transition: max-height 0.35s ease, padding 0.3s; }
    .hero-card.open .hero-body-wrap { max-height: 200px; padding: 10px 0 4px; }
    .hero-body-text { font-size: 12px; color: #555; line-height: 1.65; white-space: pre-wrap; word-break: break-word; border-top: 1px solid #e8e4ff; padding-top: 10px; }
    .hero-expand-btn {
      display: block; width: 100%; margin-top: 8px;
      background: none; border: 1px solid #d0c9ff; border-radius: 6px;
      color: #9b8fe0; font-size: 11px; font-weight: 600; padding: 5px 0;
      cursor: pointer; text-align: center; transition: all 0.2s;
    }
    .hero-expand-btn:hover { background: #f0edff; border-color: #a29bfe; color: #6c5ce7; }
    .hero-card.open .hero-expand-btn { background: #f0edff; color: #6c5ce7; border-color: #a29bfe; }
    .car-dots { display: flex; justify-content: center; gap: 8px; margin-top: 16px; }
    .car-dot {
      width: 8px; height: 8px; border-radius: 50%;
      background: #d0c9ff; cursor: pointer; transition: all 0.2s;
    }
    .car-dot.active { background: #6c5ce7; width: 24px; border-radius: 4px; }

    /* === Search === */
    .search-bar { padding: 20px 28px 0; max-width: 560px; }
    .search-input {
      width: 100%; background: #fff; border: 2px solid #e8e4ff; border-radius: 10px;
      color: #1a1a2e; padding: 10px 18px; font-size: 13px; outline: none;
      transition: border-color 0.15s; box-shadow: 0 2px 8px rgba(108,92,231,0.08);
    }
    .search-input:focus { border-color: #6c5ce7; }
    .search-input::placeholder { color: #b2bec3; }

    /* === Category Tabs === */
    .tab-bar { padding: 16px 28px 0; display: flex; gap: 8px; flex-wrap: wrap; }
    .tab-btn {
      background: #fff; color: #636e72; border: 2px solid #e8e4ff;
      border-radius: 20px; padding: 6px 18px; font-size: 13px; font-weight: 600;
      cursor: pointer; transition: all 0.15s;
    }
    .tab-all:hover  { border-color: #6c5ce7; color: #6c5ce7; }
    .tab-all.active { background: #6c5ce7; color: #fff; border-color: #6c5ce7; }
    .tab-new:hover  { border-color: #0984e3; color: #0984e3; }
    .tab-new.active { background: #0984e3; color: #fff; border-color: #0984e3; }
    .tab-game:hover  { border-color: #00b894; color: #00b894; }
    .tab-game.active { background: #00b894; color: #fff; border-color: #00b894; }
    .tab-co:hover   { border-color: #6c5ce7; color: #6c5ce7; }
    .tab-co.active  { background: #6c5ce7; color: #fff; border-color: #6c5ce7; }
    .tab-gen:hover  { border-color: #636e72; color: #636e72; }
    .tab-gen.active { background: #636e72; color: #fff; border-color: #636e72; }

    /* === Article List === */
    .article-wrap { padding: 16px 28px 40px; }
    .article-item {
      background: #fff; border-radius: 12px; border: 2px solid #e8e4ff;
      margin-bottom: 8px; overflow: hidden; transition: box-shadow 0.2s;
      border-left: 5px solid #d0c9ff;
    }
    .article-item:hover { box-shadow: 0 4px 16px rgba(108,92,231,0.12); }
    /* 카테고리별 색상 (B+C: 상단 컬러 바 + 배경 틴트) */
    .art-new  { border-left: none; border-top: 4px solid #0984e3; background: #e8f4ff; }
    .art-game { border-left: none; border-top: 4px solid #00b894; background: #e8fff4; }
    .art-co   { border-left: none; border-top: 4px solid #6c5ce7; background: #f0e8ff; }
    .art-gen  { border-left: none; border-top: 4px solid #b2bec3; background: #fff;    }
    .art-new:hover  { box-shadow: 0 4px 16px rgba(9,132,227,0.18); }
    .art-game:hover { box-shadow: 0 4px 16px rgba(0,184,148,0.18); }
    .art-co:hover   { box-shadow: 0 4px 16px rgba(108,92,231,0.18); }
    .art-gen:hover  { box-shadow: 0 4px 16px rgba(108,92,231,0.10); }
    .article-row {
      display: flex; align-items: center; gap: 10px;
      padding: 13px 18px; cursor: pointer; user-select: none;
    }
    .art-badges { display: flex; gap: 4px; flex-shrink: 0; flex-wrap: wrap; max-width: 200px; }
    .art-title {
      flex: 1; font-size: 13px; font-weight: 600; color: #1a1a2e;
      line-height: 1.4; min-width: 0;
    }
    .article-item:hover .art-title { color: #6c5ce7; }
    .art-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
    .btn-url {
      background: linear-gradient(135deg, #6c5ce7, #a29bfe);
      color: #fff; border: none; border-radius: 6px;
      padding: 5px 12px; font-size: 11px; font-weight: 700;
      cursor: pointer; white-space: nowrap; text-decoration: none;
      display: inline-block; transition: opacity 0.2s;
    }
    .btn-url:hover { opacity: 0.85; }
    .art-expand-icon { color: #a29bfe; font-size: 14px; transition: transform 0.3s; flex-shrink: 0; }
    .article-item.open .art-expand-icon { transform: rotate(180deg); }
    .art-body {
      max-height: 0; overflow: hidden;
      transition: max-height 0.4s ease, padding 0.3s;
      background: #f8f5ff; font-size: 13px; color: #444; line-height: 1.7;
      border-top: 0px solid #e8e4ff;
    }
    .article-item.open .art-body {
      max-height: 320px; border-top-width: 1px; padding: 14px 18px;
    }
    .art-site { font-size: 11px; color: #a29bfe; margin-bottom: 6px; }
    .multi-site-badge {
      display: inline-block; background: #fff3cd; color: #856404;
      border: 1px solid #ffc107; border-radius: 4px;
      padding: 1px 7px; font-size: 10px; font-weight: 700;
      vertical-align: middle; margin-left: 4px;
    }
    .art-body-text { white-space: pre-wrap; word-break: break-word; }

    /* === Calendar Page === */
    .cal-header {
      background: #fff; border-bottom: 2px solid #e8e4ff;
      padding: 14px 28px; display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
    }
    .cal-title { font-size: 18px; font-weight: 800; color: #1a1a2e; min-width: 120px; text-align: center; }
    .cal-nav-btn {
      background: #f0edff; color: #6c5ce7; border: 2px solid #d0c9ff;
      border-radius: 8px; padding: 6px 16px; font-size: 13px; font-weight: 700;
      cursor: pointer; transition: all 0.15s;
    }
    .cal-nav-btn:hover { background: #6c5ce7; color: #fff; border-color: #6c5ce7; }
    .cal-legend { display: flex; gap: 14px; margin-left: auto; flex-wrap: wrap; align-items: center; }
    .cal-legend-item { display: flex; align-items: center; gap: 5px; font-size: 11px; color: #636e72; font-weight: 600; }
    .cal-legend-dot { width: 10px; height: 10px; border-radius: 3px; }
    .dot-release { background: #e17055; }
    .dot-presale { background: #0984e3; }
    .dot-cbt     { background: #00b894; }
    .dot-server  { background: #a29bfe; }

    .cal-body { padding: 20px 28px 40px; }
    .cal-grid {
      display: grid; grid-template-columns: repeat(7, 1fr);
      gap: 2px; background: #e8e4ff; border-radius: 12px; overflow: hidden;
    }
    .cal-weekday {
      background: #6c5ce7; color: #fff; text-align: center;
      padding: 10px 4px; font-size: 11px; font-weight: 800; letter-spacing: 0.5px;
    }
    .cal-day {
      background: #fff; min-height: 90px; padding: 8px 6px;
      cursor: default; transition: background 0.15s;
    }
    .cal-day.has-events { cursor: pointer; }
    .cal-day.has-events:hover { background: #f0edff; }
    .cal-day.empty { background: #faf9ff; }
    .cal-day.today { background: #f0edff; }
    .cal-day.today .cal-day-num { color: #6c5ce7; font-weight: 900; background: #6c5ce7; color: #fff; border-radius: 50%; width: 22px; height: 22px; display: flex; align-items: center; justify-content: center; }
    .cal-day-num { font-size: 12px; font-weight: 700; color: #636e72; margin-bottom: 4px; }
    .cal-event {
      font-size: 10px; font-weight: 600; padding: 2px 5px; border-radius: 4px;
      margin-bottom: 2px; line-height: 1.4;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .event-release { background: #fff0ee; color: #e17055; }
    .event-presale { background: #e8f4ff; color: #0984e3; }
    .event-cbt     { background: #e8fff4; color: #00b894; }
    .event-server  { background: #f0e8ff; color: #6c5ce7; }
    .cal-more { font-size: 10px; color: #a29bfe; font-weight: 700; }

    .cal-detail {
      margin-top: 20px; background: #fff; border-radius: 12px; border: 2px solid #e8e4ff;
      overflow: hidden; animation: fadeIn 0.2s ease;
    }
    .cal-detail-header {
      background: linear-gradient(135deg, #6c5ce7, #a29bfe);
      color: #fff; padding: 12px 18px; font-size: 14px; font-weight: 800;
    }
    .cal-detail-item {
      border-bottom: 1px solid #f0edff; padding: 12px 18px;
      display: flex; align-items: flex-start; gap: 10px;
    }
    .cal-detail-item:last-child { border-bottom: none; }
    .cal-evt-tag {
      flex-shrink: 0; font-size: 10px; font-weight: 800; padding: 3px 8px;
      border-radius: 20px; white-space: nowrap;
    }
    .tag-release { background: #fff0ee; color: #e17055; }
    .tag-presale { background: #e8f4ff; color: #0984e3; }
    .tag-cbt     { background: #e8fff4; color: #00b894; }
    .tag-server  { background: #f0e8ff; color: #6c5ce7; }
    .cal-detail-title { font-size: 13px; font-weight: 600; color: #1a1a2e; line-height: 1.4; flex: 1; }
    .cal-detail-link {
      flex-shrink: 0; font-size: 11px; font-weight: 700;
      background: linear-gradient(135deg, #6c5ce7, #a29bfe);
      color: #fff; padding: 4px 10px; border-radius: 6px; text-decoration: none;
      transition: opacity 0.2s;
    }
    .cal-detail-link:hover { opacity: 0.85; }
    .cal-empty-msg { padding: 40px; text-align: center; color: #b2bec3; font-size: 14px; }

    /* === States === */
    .empty-state { padding: 60px 28px; text-align: center; color: #b2bec3; }
    .empty-icon { font-size: 48px; margin-bottom: 12px; }
    .empty-msg { font-size: 15px; }
    .loading { padding: 60px; text-align: center; color: #a29bfe; }
    .loading-spinner {
      width: 40px; height: 40px; border: 4px solid #e8e4ff; border-top-color: #6c5ce7;
      border-radius: 50%; animation: spin 0.8s linear infinite; margin: 0 auto 12px;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
    .article-item { animation: fadeIn 0.25s ease; }

    /* === Footer === */
    .g-footer {
      background: #fff; border-top: 2px solid #e8e4ff;
      padding: 16px 28px; text-align: center; font-size: 11px; color: #b2bec3;
    }

    @media (max-width: 900px) {
      .hero-card { flex: 0 0 calc(50% - 8px); }
      .date-bar, .hero-sec, .search-bar, .tab-bar, .article-wrap, .cal-body { padding-left: 16px; padding-right: 16px; }
      .cal-legend { display: none; }
    }
    @media (max-width: 600px) {
      .hero-card { flex: 0 0 100%; }
      .art-badges { max-width: 120px; }
      .date-quick { display: none; }
    }
  </style>
</head>
<body>

<header class="g-header">
  <div class="logo">&#127918; 게임 업계 동향</div>
  <nav class="page-nav">
    <button class="page-btn active" data-page="news">게임 업계 뉴스</button>
    <button class="page-btn" data-page="calendar">신작 소식</button>
  </nav>
  <div class="h-stat" id="hStats"></div>
</header>

<!-- ========== 게임 업계 뉴스 ========== -->
<div id="newsPage" class="app-page active">

<div class="date-bar">
  <span class="date-label">&#128197; 기간</span>
  <input type="date" id="dateFrom" class="date-input" />
  <span class="date-sep">~</span>
  <input type="date" id="dateTo" class="date-input" />
  <button class="btn-load" id="btnLoad">조회</button>
  <span class="date-hint">※ 최대 1개월</span>
  <span class="date-err" id="dateErr" style="display:none"></span>
  <div class="date-quick">
    <button class="q-btn active" data-days="0">최신</button>
    <button class="q-btn" data-days="7">최근 7일</button>
    <button class="q-btn" data-days="30">최근 30일</button>
  </div>
</div>

<section class="hero-sec">
  <div class="sec-eyebrow">&#128293; 주목 기사 TOP 5</div>
  <div class="carousel-outer">
    <button class="car-btn" id="carPrev">&#8249;</button>
    <div class="carousel-viewport" id="carouselVP">
      <div class="carousel-track" id="carouselTrack"></div>
    </div>
    <button class="car-btn" id="carNext">&#8250;</button>
  </div>
  <div class="car-dots" id="carDots"></div>
</section>

<div class="search-bar">
  <input type="text" id="searchInput" class="search-input" placeholder="&#128269; 기사 제목 검색..." />
</div>
<div class="tab-bar" id="tabBar">
  <button class="tab-btn tab-all active" data-cat="전체">전체</button>
  <button class="tab-btn tab-new" data-cat="신작 소식">신작 소식</button>
  <button class="tab-btn tab-game" data-cat="게임 소식">게임 소식</button>
  <button class="tab-btn tab-co" data-cat="게임 회사 동향">게임 회사 동향</button>
  <button class="tab-btn tab-gen" data-cat="일반">일반</button>
</div>

<div class="article-wrap" id="articleWrap">
  <div class="loading"><div class="loading-spinner"></div><div>데이터 로딩 중...</div></div>
</div>

</div><!-- /newsPage -->

<!-- ========== 신작 소식 ========== -->
<div id="calPage" class="app-page">

<div class="cal-header">
  <button class="cal-nav-btn" id="calPrev">&#8249; 이전달</button>
  <div class="cal-title" id="calTitle"></div>
  <button class="cal-nav-btn" id="calNext">다음달 &#8250;</button>
  <div class="cal-legend">
    <div class="cal-legend-item"><div class="cal-legend-dot dot-release"></div>출시</div>
    <div class="cal-legend-item"><div class="cal-legend-dot dot-presale"></div>사전예약</div>
    <div class="cal-legend-item"><div class="cal-legend-dot dot-cbt"></div>CBT</div>
    <div class="cal-legend-item"><div class="cal-legend-dot dot-server"></div>서버오픈</div>
  </div>
</div>

<div class="cal-body">
  <div id="calGrid" class="cal-grid"></div>
  <div id="calDetail" style="display:none"></div>
</div>

</div><!-- /calPage -->

<footer class="g-footer">엔트런스 게임 업계 동향 &middot; 매일 00:00 KST 자동 수집 &middot; GitHub Pages 제공</footer>

<script>
(function () {
  var DATA = [];
  var DATES = [];
  var curCat = "\uc804\uccb4";
  var searchQ = "";
  var carIdx = 0;
  var HERO = [];
  var CAR_VISIBLE = 3;
  var calYear = new Date().getFullYear();
  var calMonth = new Date().getMonth();

  function fmtDate(d) {
    var y = d.getFullYear(), m = String(d.getMonth()+1).padStart(2,"0"), dd = String(d.getDate()).padStart(2,"0");
    return y+"-"+m+"-"+dd;
  }
  function parseKST(s) { return new Date(s+"T00:00:00+09:00"); }
  function daysBetween(a,b) { return Math.round(Math.abs(b-a)/86400000); }
  function esc(s) {
    if (!s) return "";
    return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }
  function stripHtml(html) {
    if (!html) return "";
    var tmp = document.createElement("div");
    tmp.innerHTML = html;
    return (tmp.textContent || tmp.innerText || "").trim();
  }
  function fmtBody(txt) {
    if (!txt) return txt;
    // 마침표 뒤 공백을 줄바꿈으로 변환 → 가독성 향상
    return txt.replace(/[.]\s+/g, ".\\n").replace(/[?]\s+/g, "?\\n").replace(/[!]\s+/g, "!\\n");
  }

  var CAT_CLS = {"\uc2e0\uc791 \uc18c\uc2dd":"bcat-new","\uac8c\uc784 \uc18c\uc2dd":"bcat-game","\uac8c\uc784 \ud68c\uc0ac \ub3d9\ud5a5":"bcat-co","\uc77c\ubc18":"bcat-gen"};
  function catBadge(c) { return '<span class="badge '+(CAT_CLS[c]||"bcat-gen")+'">'+esc(c)+'</span>'; }
  function srcBadge(dom) { return '<span class="badge '+(dom?"bsrc-dom":"bsrc-ovs")+'">'+(dom?"\uad6d\ub0b4":"\ud574\uc678")+'</span>'; }
  function siteBadge(s) { return '<span class="badge bsite">'+esc(s)+'</span>'; }
  function viewBadge(v) { return v?'<span class="badge bview">&#128065; '+v.toLocaleString()+'</span>':""; }
  function hotBadge(h) { return h?'<span class="badge bhot">&#128293;HOT</span>':""; }
  function multiSiteBadge(cnt,sites){
    if(!cnt||cnt<=1) return "";
    var tip=sites&&sites.length?sites.join(", "):"";
    return '<span class="multi-site-badge" title="'+esc(tip)+'">&#128240; '+cnt+'\uac1c \uc0ac\uc774\ud2b8</span>';
  }

  function getEventType(title) {
    var t = (title||"").toLowerCase();
    if (t.indexOf("\uc0ac\uc804\uc608\uc57d")!==-1) return "presale";
    if (t.indexOf("cbt")!==-1||t.indexOf("\ud074\ub85c\uc988\ubca0\ud0c0")!==-1||t.indexOf("\ube44\uacf5\uac1c\ud14c\uc2a4\ud2b8")!==-1) return "cbt";
    if (t.indexOf("\uc11c\ubc84\uc624\ud508")!==-1||t.indexOf("\uc11c\ubc84 \uc624\ud508")!==-1||t.indexOf("\uc2e0\uaddc \uc11c\ubc84")!==-1||t.indexOf("\uc2e0\uc11c\ubc84")!==-1) return "server";
    return "release";
  }
  var EVT_LABELS = {release:"\ucd9c\uc2dc", presale:"\uc0ac\uc804\uc608\uc57d", cbt:"CBT", server:"\uc11c\ubc84\uc624\ud508"};
  var EVT_CLS   = {release:"event-release", presale:"event-presale", cbt:"event-cbt", server:"event-server"};
  var TAG_CLS   = {release:"tag-release",   presale:"tag-presale",   cbt:"tag-cbt",   server:"tag-server"};

  /* ── Data Loading ── */
  function loadDates() {
    fetch("data/dates.json?v="+Date.now())
      .then(function(r){return r.json();})
      .then(function(j){
        DATES = j.dates||[];
        if (!DATES.length) { showEmpty("\uc218\uc9d1\ub41c \ub370\uc774\ud130\uac00 \uc5c6\uc2b5\ub2c8\ub2e4."); return; }
        var latest=DATES[0], oldest=DATES[DATES.length-1];
        ["dateFrom","dateTo"].forEach(function(id){
          var el=document.getElementById(id); el.min=oldest; el.max=latest;
        });
        document.getElementById("dateFrom").value=latest;
        document.getElementById("dateTo").value=latest;
        var ld=parseKST(latest); calYear=ld.getFullYear(); calMonth=ld.getMonth();
        loadRange(latest,latest);
      })
      .catch(function(){showEmpty("dates.json \ub85c\ub4dc \uc2e4\ud328 \u2014 \ud06c\ub864\ub7ec\ub97c \uba3c\uc800 \uc2e4\ud589\ud574 \uc8fc\uc138\uc694.");});
  }

  function loadRange(fromStr,toStr) {
    document.getElementById("articleWrap").innerHTML='<div class="loading"><div class="loading-spinner"></div><div>\ub85c\ub529 \uc911...</div></div>';
    document.getElementById("hStats").textContent="";
    DATA=[];
    var from=parseKST(fromStr), to=parseKST(toStr);
    if (from>to){var t=from;from=to;to=t;}
    var targets=DATES.filter(function(d){var dt=parseKST(d);return dt>=from&&dt<=to;});
    if (!targets.length){showEmpty("\uc120\ud0dd\ud55c \uae30\uac04\uc5d0 \uc218\uc9d1\ub41c \ub370\uc774\ud130\uac00 \uc5c6\uc2b5\ub2c8\ub2e4.");return;}
    var done=0;
    targets.forEach(function(d){
      (function(tag){
        fetch("data/"+tag+".json?v="+Date.now())
          .then(function(r){return r.json();})
          .then(function(arr){arr.forEach(function(a){a._fileDate=tag;}); DATA=DATA.concat(arr);})
          .catch(function(){})
          .finally(function(){if(++done===targets.length)onReady();});
      })(d);
    });
  }

  function onReady() {
    var CAT_ORDER={"\uc2e0\uc791 \uc18c\uc2dd":1,"\uac8c\uc784 \ud68c\uc0ac \ub3d9\ud5a5":2,"\uac8c\uc784 \uc18c\uc2dd":3,"\uc77c\ubc18":4};
    DATA.sort(function(a,b){
      var sd=(b.score||0)-(a.score||0);
      if(sd!==0) return sd;
      return (CAT_ORDER[a.category]||5)-(CAT_ORDER[b.category]||5);
    });
    HERO=DATA.slice(0,5);
    renderCarousel();
    renderList();
    document.getElementById("hStats").innerHTML="\uc218\uc9d1 <b>"+DATA.length+"</b>\uac74";
    renderCalendar();
  }

  /* ── Carousel (3 visible) ── */
  function renderCarousel() {
    var track=document.getElementById("carouselTrack"), dots=document.getElementById("carDots");
    track.innerHTML=""; dots.innerHTML="";
    if (!HERO.length) return;
    HERO.forEach(function(art,i){
      var rc=i===0?"rank-gold":i===1?"rank-silver":i===2?"rank-bronze":"";
      var bodyText=fmtBody((art.body||"").trim()||stripHtml(art.summary||"").trim());
      var hasBody=bodyText.length>0;
      var card=document.createElement("div"); card.className="hero-card";
      card.innerHTML=
        '<div class="hero-rank '+rc+'">'+(i+1)+'</div>'+
        '<div class="hero-title">'+esc(art.title)+'</div>'+
        '<div class="hero-meta">'+catBadge(art.category)+" "+srcBadge(art.is_domestic)+" "+siteBadge(art.site)+" "+viewBadge(art.views)+" "+hotBadge(art.is_ruliweb_best)+" "+multiSiteBadge(art.site_cnt,art.covered_sites)+'</div>'+
        (hasBody?'<button class="hero-expand-btn">&#9660; \ubcf8\ubb38 \uc694\uc57d \ubcf4\uae30</button>'+
          '<div class="hero-body-wrap"><div class="hero-body-text">'+esc(bodyText)+'</div></div>':'')+
        '<a class="hero-link" href="'+esc(art.url)+'" target="_blank" rel="noopener">\uae30\uc0ac \uc6d0\ubb38\ubcf4\uae30 &#8594;</a>';
      var btn=card.querySelector(".hero-expand-btn");
      if(btn){
        btn.addEventListener("click",function(e){
          e.stopPropagation();
          card.classList.toggle("open");
          btn.textContent=card.classList.contains("open")
            ?"\u25b2 \uc811\uae30"
            :"\u25bc \ubcf8\ubb38 \uc694\uc57d \ubcf4\uae30";
        });
      }
      track.appendChild(card);
    });
    var maxIdx=Math.max(0,HERO.length-CAR_VISIBLE);
    for (var i=0;i<=maxIdx;i++){
      var dot=document.createElement("div");
      dot.className="car-dot"+(i===0?" active":"");
      dot.addEventListener("click",(function(idx){return function(){gotoSlide(idx);};})(i));
      dots.appendChild(dot);
    }
    carIdx=0; updateCarPos();
  }

  function gotoSlide(idx){
    var maxIdx=Math.max(0,HERO.length-CAR_VISIBLE);
    carIdx=Math.max(0,Math.min(idx,maxIdx));
    updateCarPos();
  }
  function updateCarPos(){
    var track=document.getElementById("carouselTrack");
    if (!track.children.length) return;
    var cardW=track.children[0].offsetWidth+16;
    track.style.transform="translateX(-"+(carIdx*cardW)+"px)";
    document.querySelectorAll(".car-dot").forEach(function(d,i){d.className="car-dot"+(i===carIdx?" active":"");});
    var maxIdx=Math.max(0,HERO.length-CAR_VISIBLE);
    document.getElementById("carPrev").disabled=(carIdx===0);
    document.getElementById("carNext").disabled=(carIdx>=maxIdx);
  }
  document.getElementById("carPrev").addEventListener("click",function(){gotoSlide(carIdx-1);});
  document.getElementById("carNext").addEventListener("click",function(){gotoSlide(carIdx+1);});
  (function(){
    var vp=document.getElementById("carouselVP"),sx=0;
    vp.addEventListener("touchstart",function(e){sx=e.touches[0].clientX;},{passive:true});
    vp.addEventListener("touchend",function(e){var dx=e.changedTouches[0].clientX-sx;if(dx>50)gotoSlide(carIdx-1);else if(dx<-50)gotoSlide(carIdx+1);});
  }());

  /* ── Article List ── */
  function getFiltered(){
    return DATA.filter(function(a){
      return (curCat==="\uc804\uccb4"||a.category===curCat)&&(!searchQ||a.title.toLowerCase().indexOf(searchQ)!==-1);
    });
  }
  function renderList(){
    var wrap=document.getElementById("articleWrap"), items=getFiltered();
    if (!items.length){showEmpty("\uc870\uac74\uc5d0 \ub9de\ub294 \uae30\uc0ac\uac00 \uc5c6\uc2b5\ub2c8\ub2e4.");return;}
    wrap.innerHTML="";
    items.forEach(function(art){
      var bodyText=fmtBody((art.body||"").trim()||stripHtml(art.summary||"").trim());
      if (!bodyText) bodyText="(\uae30\uc0ac \ubcf8\ubb38 \uc694\uc57d \uc5c6\uc74c)";
      var catColorCls=art.category==="\uc2e0\uc791 \uc18c\uc2dd"?"art-new":art.category==="\uac8c\uc784 \uc18c\uc2dd"?"art-game":art.category==="\uac8c\uc784 \ud68c\uc0ac \ub3d9\ud5a5"?"art-co":"art-gen";
      var item=document.createElement("div"); item.className="article-item "+catColorCls;
      item.innerHTML=
        '<div class="article-row">'+
          '<div class="art-badges">'+catBadge(art.category)+" "+srcBadge(art.is_domestic)+" "+siteBadge(art.site)+" "+hotBadge(art.is_ruliweb_best)+" "+multiSiteBadge(art.site_cnt,art.covered_sites)+'</div>'+
          '<div class="art-title">'+esc(art.title)+'</div>'+
          '<div class="art-actions">'+
            viewBadge(art.views)+
            ' <a class="btn-url" href="'+esc(art.url)+'" target="_blank" rel="noopener" onclick="event.stopPropagation()">\uae30\uc0ac \uc6d0\ubb38\ubcf4\uae30</a>'+
            ' <span class="art-expand-icon">&#9660;</span>'+
          '</div>'+
        '</div>'+
        '<div class="art-body">'+
          '<div class="art-site">'+esc(art.site)+(art.collected_at?' &middot; '+esc(art.collected_at):'')+'</div>'+
          '<div class="art-body-text">'+esc(bodyText)+'</div>'+
        '</div>';
      item.querySelector(".article-row").addEventListener("click",function(e){
        if(e.target.classList.contains("btn-url")||e.target.closest(".btn-url"))return;
        item.classList.toggle("open");
      });
      wrap.appendChild(item);
    });
  }
  function showEmpty(msg){
    document.getElementById("articleWrap").innerHTML='<div class="empty-state"><div class="empty-icon">&#128235;</div><div class="empty-msg">'+msg+'</div></div>';
  }

  /* ── Calendar ── */
  function renderCalendar(){
    var grid=document.getElementById("calGrid"), titleEl=document.getElementById("calTitle");
    var detail=document.getElementById("calDetail");
    detail.style.display="none"; grid.innerHTML="";
    var MONTHS=["1\uc6d4","2\uc6d4","3\uc6d4","4\uc6d4","5\uc6d4","6\uc6d4","7\uc6d4","8\uc6d4","9\uc6d4","10\uc6d4","11\uc6d4","12\uc6d4"];
    titleEl.textContent=calYear+"\ub144 "+MONTHS[calMonth];

    var WDAYS=["\uc77c","\uc6d4","\ud654","\uc218","\ubaa9","\uae08","\ud1a0"];
    WDAYS.forEach(function(d){var el=document.createElement("div");el.className="cal-weekday";el.textContent=d;grid.appendChild(el);});

    // Build date → articles map
    // event_date(기사 내 이벤트 발생일) 우선, 없으면 신작 기사는 _fileDate 사용
    var newsMap={};
    DATA.forEach(function(art){
      var dateStr="";
      if (art.event_date) {
        dateStr=art.event_date;       // 이벤트 날짜가 있으면 그 날에 표시
      } else if (art.category==="\uc2e0\uc791 \uc18c\uc2dd") {
        dateStr=art._fileDate||"";   // 신작 소식은 수집일에 폴백
      }
      if (!dateStr) return;
      if (!newsMap[dateStr]) newsMap[dateStr]=[];
      newsMap[dateStr].push(art);
    });

    var today=new Date(), todayStr=fmtDate(today);
    var firstDay=new Date(calYear,calMonth,1).getDay();
    var daysInMonth=new Date(calYear,calMonth+1,0).getDate();

    for (var i=0;i<firstDay;i++){var e=document.createElement("div");e.className="cal-day empty";grid.appendChild(e);}

    for (var d=1;d<=daysInMonth;d++){
      var cell=document.createElement("div");
      var ds=calYear+"-"+String(calMonth+1).padStart(2,"0")+"-"+String(d).padStart(2,"0");
      var isToday=(ds===todayStr);
      cell.className="cal-day"+(isToday?" today":"");
      var numEl=document.createElement("div"); numEl.className="cal-day-num"; numEl.textContent=d;
      cell.appendChild(numEl);
      var arts=newsMap[ds]||[];
      if (arts.length>0) {
        cell.classList.add("has-events");
        var shown=0;
        arts.forEach(function(art){
          if(shown>=3)return;
          var etype=getEventType(art.title);
          var ev=document.createElement("div");
          ev.className="cal-event "+EVT_CLS[etype];
          ev.textContent="["+EVT_LABELS[etype]+"] "+art.title;
          ev.title=art.title;
          cell.appendChild(ev); shown++;
        });
        if(arts.length>3){var more=document.createElement("div");more.className="cal-more";more.textContent="+"+(arts.length-3)+"\uac74 \ub354";cell.appendChild(more);}
        (function(dsCopy,artsCopy){cell.addEventListener("click",function(){showCalDetail(dsCopy,artsCopy);});})(ds,arts);
      }
      grid.appendChild(cell);
    }
  }

  function showCalDetail(dateStr,arts){
    var detail=document.getElementById("calDetail");
    var MONTHS=["1\uc6d4","2\uc6d4","3\uc6d4","4\uc6d4","5\uc6d4","6\uc6d4","7\uc6d4","8\uc6d4","9\uc6d4","10\uc6d4","11\uc6d4","12\uc6d4"];
    var dt=parseKST(dateStr);
    var label=dt.getFullYear()+"\ub144 "+MONTHS[dt.getMonth()]+" "+dt.getDate()+"\uc77c \uc2e0\uc791 \uc18c\uc2dd";
    var html='<div class="cal-detail"><div class="cal-detail-header">&#128197; '+esc(label)+' ('+arts.length+'\uac74)</div>';
    arts.forEach(function(art){
      var etype=getEventType(art.title);
      html+='<div class="cal-detail-item">'+
        '<span class="cal-evt-tag '+TAG_CLS[etype]+'">'+EVT_LABELS[etype]+'</span>'+
        '<div class="cal-detail-title">'+esc(art.title)+'</div>'+
        '<a class="cal-detail-link" href="'+esc(art.url)+'" target="_blank" rel="noopener">\uc6d0\ubb38\ubcf4\uae30</a>'+
        '</div>';
    });
    html+='</div>';
    detail.innerHTML=html;
    detail.style.display="block";
    detail.scrollIntoView({behavior:"smooth",block:"nearest"});
  }

  document.getElementById("calPrev").addEventListener("click",function(){calMonth--;if(calMonth<0){calMonth=11;calYear--;}renderCalendar();});
  document.getElementById("calNext").addEventListener("click",function(){calMonth++;if(calMonth>11){calMonth=0;calYear++;}renderCalendar();});

  /* ── Page Navigation ── */
  document.querySelectorAll(".page-btn").forEach(function(btn){
    btn.addEventListener("click",function(){
      document.querySelectorAll(".page-btn").forEach(function(b){b.classList.remove("active");});
      btn.classList.add("active");
      var page=btn.dataset.page;
      document.getElementById("newsPage").classList.toggle("active",page==="news");
      document.getElementById("calPage").classList.toggle("active",page==="calendar");
      if(page==="calendar") renderCalendar();
    });
  });

  /* ── Tab / Search / Date ── */
  document.getElementById("tabBar").addEventListener("click",function(e){
    var btn=e.target.closest(".tab-btn"); if(!btn)return;
    document.querySelectorAll(".tab-btn").forEach(function(b){b.classList.remove("active");});
    btn.classList.add("active"); curCat=btn.dataset.cat; renderList();
  });
  document.getElementById("searchInput").addEventListener("input",function(e){
    searchQ=e.target.value.toLowerCase().trim(); renderList();
  });
  document.getElementById("btnLoad").addEventListener("click",function(){
    var from=document.getElementById("dateFrom").value, to=document.getElementById("dateTo").value;
    var errEl=document.getElementById("dateErr");
    if(!from||!to){errEl.textContent="\ub0a0\uc9dc\ub97c \uc120\ud0dd\ud574 \uc8fc\uc138\uc694.";errEl.style.display="";return;}
    if(daysBetween(parseKST(from),parseKST(to))>30){errEl.textContent="\ucd5c\ub300 30\uc77c\uae4c\uc9c0 \uc870\ud68c \uac00\ub2a5\ud569\ub2c8\ub2e4.";errEl.style.display="";return;}
    errEl.style.display="none";
    document.querySelectorAll(".q-btn").forEach(function(b){b.classList.remove("active");});
    loadRange(from,to);
  });
  document.querySelectorAll(".q-btn").forEach(function(btn){
    btn.addEventListener("click",function(){
      document.querySelectorAll(".q-btn").forEach(function(b){b.classList.remove("active");});
      btn.classList.add("active");
      document.getElementById("dateErr").style.display="none";
      if(!DATES.length)return;
      var days=parseInt(btn.dataset.days,10), latest=DATES[0], toStr=latest;
      var fromStr=days===0?latest:fmtDate(new Date(parseKST(latest).getTime()-days*86400000));
      document.getElementById("dateFrom").value=fromStr;
      document.getElementById("dateTo").value=toStr;
      loadRange(fromStr,toStr);
    });
  });

  loadDates();
}());
</script>
</body>
</html>"""



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
            "score":           art.get("_score", 0),
            "site_cnt":        art.get("_site_cnt", 1),
            "content_score":   art.get("_content_score", 1),
            "covered_sites":   art.get("_covered_sites", []),
            "event_date":      art.get("event_date", ""),
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


def fetch_article_body(url: str, timeout: int = 10) -> str:
    """기사 원문 URL에서 본문 텍스트 추출 (최대 1200자)"""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
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
                    return text[:1200]
        # 폴백: 충분히 긴 <p> 태그 모음
        paras = [clean(p.get_text()) for p in soup.select("p")
                 if len(p.get_text().strip()) > 40]
        if paras:
            return " ".join(paras[:6])[:1200]
        return ""
    except Exception:
        return ""


def enrich_articles_body():
    """수집된 기사 본문 fetch + 이벤트 날짜 추출 (병렬 8 workers)"""
    targets = [a for a in ARTICLES if not a.get("body_text")]
    print(f"  본문 보강 중 ({len(targets)}건, 병렬 8)...")

    def _fetch(art):
        body = fetch_article_body(art["url"])
        if body:
            art["body_text"] = body

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(_fetch, targets))

    # ── 이벤트 날짜 추출 (신작 관련 + 높은 content_score 기사 우선) ──────────
    ref_year = datetime.now(KST).year
    for art in ARTICLES:
        if art.get("event_date"):        # 이미 있으면 스킵
            continue
        if art.get("_content_score", 0) >= 4:   # S+·S·A·B·C 등급만
            ev = extract_event_date(
                art.get("title", ""),
                art.get("body_text", ""),
                ref_year,
            )
            if ev:
                art["event_date"] = ev

    filled = sum(1 for a in ARTICLES if a.get("body_text"))
    ev_cnt = sum(1 for a in ARTICLES if a.get("event_date"))
    print(f"  본문 보강 완료: {filled}/{len(ARTICLES)}건 / 이벤트 날짜: {ev_cnt}건")


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
    run_all()

    if not ARTICLES:
        print("[ERROR] 수집된 기사 없음. 종료.")
        return

    # 1-1. 본문 보강 (병렬 fetch)
    print("\n[1-1] 기사 본문 보강")
    enrich_articles_body()

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
