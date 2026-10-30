# 개발용 (프로그램 사용에는 필요 없음)

- `ui2api.py`: ComfyUI 화면용 워크플로(.json) → API 형식. `python ui2api.py object_info.json 입력.json 출력.json`
- `object_info.json`: 2026-10-17 ComfyUI 최신판 + Inpaint-CropAndStitch, Inspyrenet-Rembg, controlnet_aux 의 노드 정보 스냅숏
- `make_presets.py`: 프리셋세트_v1 → PicApp/presets 를 만든 스크립트 (기록용)

PicApp 의 7개 workflow_api.json 은 이 방법으로 바꾼 뒤, 실제 ComfyUI 서버의 /prompt 검사를 모두 통과했다.

## 새 버전 내보내기 (자동 업데이트)

PicApp 의 업데이트 버튼은 GitHub 저장소(server.py DEFAULT_SETTINGS 의 `update_repo`)의 `main` 최신 커밋을 받는다.
저장소 구조: 루트에 `PicApp/`, `dev/` (= 이 app 폴더 그대로, `.gitignore` 참고).
PicApp 을 고친 뒤 저장소에 커밋·푸시해야 승진 PC 에 뜬다. **커밋 메시지 첫 줄이 '바뀐 것' 목록에 그대로 보이니 쉬운 한국어로** 쓴다.
settings.json 은 저장소에 넣지 않는다 (기본값은 server.py DEFAULT_SETTINGS). 새 사용자 파일 폴더가 생기면 updater.py 의 SKIP_DIRS/KEEP_DIRS 에도 넣는다.
