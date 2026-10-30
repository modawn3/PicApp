@echo off
chcp 65001 >nul
rem 그림 도구를 끄지 않고 화면의 '업데이트' 버튼을 써도 돼요. 이 파일은 그림 도구가 안 켜질 때 쓰세요.
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
  "!PY!" -s "%~dp0updater.py"
  pause
  exit /b
)
