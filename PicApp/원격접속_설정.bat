@echo off
chcp 65001 >nul
rem 다른 기기(Tailscale)에서 그림 도구에 들어오게 켜고 끄기, 비밀번호 정하기
setlocal EnableDelayedExpansion
(
  cd /d "%~dp0"
  set "PY=%~dp0..\ComfyUI_windows_portable\python_embeded\python.exe"
  if not exist "!PY!" set "PY=C:\AI-PIC\ComfyUI_windows_portable\python_embeded\python.exe"
  if not exist "!PY!" (
    echo ComfyUI 포터블의 파이썬을 찾지 못했어요.
    pause
    exit /b 1
  )
  "!PY!" -s "%~dp0remote.py" --setup
  pause
  exit /b
)
