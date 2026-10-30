@echo off
chcp 65001 >nul
rem 모든 줄을 괄호로 묶어 한 번에 읽는다: 업데이트가 이 파일을 바꿔도 지금 창은 안 꼬인다
setlocal EnableDelayedExpansion
(
  cd /d "%~dp0"
  set "PY=%~dp0..\ComfyUI_windows_portable\python_embeded\python.exe"
  if not exist "!PY!" set "PY=C:\AI-PIC\ComfyUI_windows_portable\python_embeded\python.exe"
  if not exist "!PY!" (
    echo ComfyUI 포터블의 파이썬을 찾지 못했어요.
    echo PicApp 폴더를 C:\AI-PIC 안에 두었는지 확인하세요.
    pause
    exit /b 1
  )
  echo 그림 도구를 켜는 중...
  "!PY!" -s "%~dp0server.py"
  pause
  exit /b
)
