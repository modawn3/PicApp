@echo off
chcp 65001 >nul
rem Claude 데스크톱 앱에 그림 도구를 연결하기 (처음 한 번만). 업데이트한 뒤에 다시 할 필요 없어요.
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
  "!PY!" -s "%~dp0claude_mcp.py" --setup
  pause
  exit /b
)
