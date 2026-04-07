@echo off
cd /d C:\Users\Admin\Documents\game-news

if not exist logs mkdir logs

set YEAR=%date:~0,4%
set MON=%date:~5,2%
set DAY=%date:~8,2%
set LOGDATE=%YEAR%%MON%%DAY%
set PYTHONIOENCODING=utf-8

echo [%date% %time%] START >> logs\crawler_%LOGDATE%.log
C:\Users\Admin\AppData\Local\Programs\Python\Python314\python.exe game_news_crawler.py >> logs\crawler_%LOGDATE%.log 2>&1
echo [%date% %time%] END >> logs\crawler_%LOGDATE%.log
