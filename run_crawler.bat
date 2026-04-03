@echo off
chcp 65001 > nul
cd /d C:\Users\Admin\Documents\game-news

:: 로그 폴더 생성
if not exist logs mkdir logs

:: 날짜 포맷 (YYYYMMDD)
set LOGDATE=%date:~0,4%%date:~5,2%%date:~8,2%

echo [%date% %time%] 크롤러 시작 >> logs\crawler_%LOGDATE%.log
C:\Users\Admin\AppData\Local\Programs\Python\Python314\python.exe game_news_crawler.py >> logs\crawler_%LOGDATE%.log 2>&1
echo [%date% %time%] 크롤러 종료 >> logs\crawler_%LOGDATE%.log

:: 작업 스케줄러 등록 권장: 매일 00:00 KST 실행 (주말 포함)
:: schtasks /create /tn "게임업계동향크롤러" /tr "C:\Users\Admin\Documents\game-news\run_crawler.bat" /sc daily /st 00:00
