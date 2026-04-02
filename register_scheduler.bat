@echo off
echo ========================================
echo  Game News Crawler - Task Scheduler
echo ========================================
echo.

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Run as Administrator required.
    pause
    exit /b 1
)

schtasks /delete /tn "GameNewsCrawler" /f >nul 2>&1

schtasks /create /tn "GameNewsCrawler" /tr "C:\Users\Admin\Documents\game-news\run_crawler.bat" /sc daily /st 00:00 /ru "%USERNAME%" /rl HIGHEST /f

if %errorLevel% equ 0 (
    echo.
    echo [SUCCESS] Task Scheduler registered!
    echo  - Task: GameNewsCrawler
    echo  - Time: Daily 00:00
    echo  - Script: C:\Users\Admin\Documents\game-news\run_crawler.bat
    echo  - Log: C:\Users\Admin\Documents\game-news\logs\
) else (
    echo.
    echo [ERROR] Registration failed. Code: %errorLevel%
)

pause
