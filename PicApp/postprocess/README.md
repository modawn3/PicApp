# 후처리 (ComfyUI 밖에서 하는 일)

도트 변환(축소·팔레트 줄이기), 스프라이트 시트 묶기처럼 ComfyUI 노드로 하기 어려운 일을 여기에 파이썬 파일로 둔다.

파일 하나 = 후처리 하나. `postprocess/이름.py` 안에 아래 함수가 있으면 된다.

```python
def run(images, params):
    # images: [(PIL.Image, 원래파일이름), ...]  params: preset.json 에 적은 값
    return [(바뀐그림, 원래파일이름), ...]
```

프리셋에서 쓰는 법 (`preset.json`):

```json
"postprocess": [
  {"step": "이름", "from_node": "12", "label": "결과 칸에 보일 이름", "params": {"palette": 16}}
]
```

`from_node` 의 결과 그림을 받아 처리하고, 결과는 `PicApp/results/` 에 저장되어 화면에 함께 나온다.

- `from_node` 는 목록도 된다: `["8", "12", "10"]`
- `"params_from": "palette"` 를 쓰면 그 칸의 값이 params 로 들어오고, `"enabled_key": "snap"` 값이 꺼져 있으면 건너뛴다.
- 들어 있는 것: `palette.py` (모든 색을 팔레트 색으로 맞춤, 투명도 유지), `pixel.py` (도트 변환, `to_pixel`/`pick_colors` 를 다른 후처리에서 써도 됨), `sprite.py` (프레임들 → 시트 + GIF)
- `"fields": ["size", ...]` 를 쓰면 그 칸들의 값이 params 로 들어온다.
- `run` 이 `(그림, 이름, 꼬리표)` 를 돌려주면 결과 이름에 꼬리표가 붙는다 (한 장에서 여러 장 낼 때).
- 네 번째 값으로 `{"ext": "gif", "frames": [그림...], "duration": ms}` 를 주면 움직이는 GIF 로 저장한다 (GIF 는 다른 기능으로 보낼 수 없음).
- 애니메이션처럼 `repeat_over` 프리셋이면 `images` 에 모든 프레임이 순서대로 들어온다.
