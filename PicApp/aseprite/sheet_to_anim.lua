-- 그림 도구가 부르는 스크립트: 스프라이트 시트 PNG 한 장을 프레임이 나뉜 .aseprite 로 만든다.
-- aseprite -b --script-param sheet=... --script-param out=... (cw ch count cols ms) --script sheet_to_anim.lua
local p = app.params
local sheet = Image{ fromFile = p.sheet }
local cw, ch = tonumber(p.cw), tonumber(p.ch)
local count, cols = tonumber(p.count), tonumber(p.cols)
local ms = tonumber(p.ms) or 120

local spr = Sprite(cw, ch, ColorMode.RGB)
local layer = spr.layers[1]
layer.name = "그림"
for i = 0, count - 1 do
  local frame = spr.frames[1]
  if i > 0 then frame = spr:newEmptyFrame(i + 1) end
  local img = Image(cw, ch, ColorMode.RGB)
  img:drawImage(sheet, Point(-(i % cols) * cw, -(i // cols) * ch))
  spr:newCel(layer, frame, img, Point(0, 0))
  frame.duration = ms / 1000
end
spr:saveAs(p.out)
