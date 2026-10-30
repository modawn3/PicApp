@echo off
chcp 65001 >nul
rem Aseprite 를 소스에서 빌드한다 (C:\AI-PIC\Aseprite). 처음부터 다시: Aseprite_빌드.bat -Fresh
title Aseprite 빌드
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_aseprite.ps1" %*
echo.
pause
