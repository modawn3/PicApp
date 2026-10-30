@echo off
chcp 65001 >nul
rem 빌드 폴더를 지우고 Aseprite 를 처음부터 다시 빌드한다 (소스와 도구는 그대로 씀)
title Aseprite 처음부터 빌드
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_aseprite.ps1" -Fresh
echo.
pause
