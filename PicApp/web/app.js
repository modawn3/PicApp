// 그림 도구 화면. 프리셋(preset.json)의 fields 를 읽어 입력칸을 만든다.
"use strict";

const APP_VERSION = "2026-10-30a"; // server.py 의 APP_VERSION 과 같아야 한다

const $ = (sel, el = document) => el.querySelector(sel);
const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
};
const store = {
  get(k) { try { return JSON.parse(localStorage.getItem("picapp:" + k)); } catch { return null; } },
  set(k, v) { try { localStorage.setItem("picapp:" + k, JSON.stringify(v)); } catch {} },
};

let PRESETS = [];
const S = {};          // 프리셋별 상태: { form, getters, setters, results }
let active = null;
let runningJob = null; // { pid, preset }
let PALETTES = [];
let ASEPRITE = false;  // 빌드한 Aseprite 를 찾았는지 (그림 도구 서버가 알려 줌)
let REMOTE = false;    // 다른 기기에서 접속했는지 (폴더 열기, Aseprite 는 집 컴퓨터에서만)
const paletteRefreshers = [];

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (r.status === 401) location.reload(); // 원격 접속 로그인이 풀렸다
  const data = await r.json().catch(() => ({ error: "응답을 읽을 수 없어요." }));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

// ---------- 그림 읽기 ----------

function fileToImage(file) {
  return new Promise((ok, fail) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => ok(img);
    img.onerror = () => fail(new Error("그림 파일을 열 수 없어요."));
    img.src = url;
  });
}
function urlToImage(url) {
  return new Promise((ok, fail) => {
    const img = new Image();
    img.onload = () => ok(img);
    img.onerror = () => fail(new Error("그림을 불러올 수 없어요."));
    img.src = url;
  });
}
// 투명한 곳이 있으면 흰색으로 채운다 (투명 PNG를 고치면 투명한 곳 전체가 고칠 곳이 되는 문제 방지)
function imageToCanvas(img, flatten) {
  const c = h("canvas");
  c.width = img.naturalWidth; c.height = img.naturalHeight;
  const ctx = c.getContext("2d");
  ctx.drawImage(img, 0, 0);
  let hadAlpha = false;
  const d = ctx.getImageData(0, 0, c.width, c.height).data;
  for (let i = 3; i < d.length; i += 4) if (d[i] < 255) { hadAlpha = true; break; }
  if (flatten) {
    if (hadAlpha) {
      ctx.globalCompositeOperation = "destination-over";
      ctx.fillStyle = "#fff";
      ctx.fillRect(0, 0, c.width, c.height);
      ctx.globalCompositeOperation = "source-over";
    }
  }
  return { canvas: c, hadAlpha };
}
// 검은 바탕에 진한 색 막대만 있으면 OpenPose 뼈대 그림으로 본다
function isSkeleton(canvas) {
  const c = h("canvas"); c.width = c.height = 64;
  const ctx = c.getContext("2d");
  ctx.drawImage(canvas, 0, 0, 64, 64);
  const d = ctx.getImageData(0, 0, 64, 64).data;
  let black = 0, vivid = 0;
  for (let i = 0; i < d.length; i += 4) {
    const mx = Math.max(d[i], d[i + 1], d[i + 2]), mn = Math.min(d[i], d[i + 1], d[i + 2]);
    if (d[i + 3] < 250) continue;  // 뼈대 그림은 투명한 곳이 없다
    if (mx < 25) black++;
    else if (mx - mn > 90 && mx > 120) vivid++;
  }
  const rest = 4096 - black;
  return black > 4096 * 0.75 && vivid > 15 && vivid > rest * 0.5;
}
function pickFile(onFile, multiple) {
  const inp = h("input", { type: "file", accept: "image/*", multiple: !!multiple });
  inp.onchange = () => { if (inp.files.length) multiple ? onFile([...inp.files]) : onFile(inp.files[0]); };
  inp.click();
}
// multiple: onFile 이 파일 목록(이름 순)을 받는다
function dropZone(text, onFile, multiple) {
  const z = h("div", { class: "drop" }, text);
  z.onclick = () => pickFile(onFile, multiple);
  z.ondragover = (e) => { e.preventDefault(); z.classList.add("over"); };
  z.ondragleave = () => z.classList.remove("over");
  z.ondrop = (e) => {
    e.preventDefault(); z.classList.remove("over");
    const files = [...e.dataTransfer.files].filter((f) => f.type.startsWith("image/"));
    if (!files.length) return;
    if (multiple) onFile(files.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true })));
    else onFile(files[0]);
  };
  return z;
}

// ---------- 마스크 칠하기 ----------

class Painter {
  constructor(onChange) {
    this.onChange = onChange;
    this.base = h("canvas");
    this.mask = h("canvas", { class: "mask" });
    this.cursor = h("div", { class: "cursor" });
    this.wrap = h("div", { class: "painter" }, this.base, this.mask, this.cursor);
    this.size = 40; this.erase = false; this.undo = []; this.loaded = false;
    this.note = h("div", { class: "note", hidden: true });

    const sizeIn = h("input", { type: "range", min: 4, max: 200, value: this.size });
    sizeIn.oninput = () => { this.size = +sizeIn.value; };
    this.sizeIn = sizeIn;
    const brush = h("button", { class: "btn on", type: "button" }, "칠하기");
    const eraser = h("button", { class: "btn", type: "button" }, "지우개");
    const setMode = (er) => { this.erase = er; brush.classList.toggle("on", !er); eraser.classList.toggle("on", er); };
    brush.onclick = () => setMode(false);
    eraser.onclick = () => setMode(true);
    this.tools = h("div", { class: "tools" },
      brush, eraser,
      h("button", { class: "btn", type: "button", onclick: () => this.doUndo() }, "되돌리기"),
      h("button", { class: "btn", type: "button", onclick: () => this.clear() }, "모두 지우기"),
      h("label", {}, "붓 크기"), sizeIn);
    this.el = h("div", {}, this.tools, this.wrap, this.note);

    const pos = (e) => {
      const r = this.mask.getBoundingClientRect();
      return [(e.clientX - r.left) * this.mask.width / r.width, (e.clientY - r.top) * this.mask.height / r.height, r];
    };
    let last = null;
    this.mask.addEventListener("pointerdown", (e) => {
      this.mask.setPointerCapture(e.pointerId);
      this.pushUndo();
      last = pos(e);
      this.stroke(last, last);
    });
    this.mask.addEventListener("pointermove", (e) => {
      const p = pos(e);
      const scale = p[2].width / this.mask.width;
      const d = this.size * scale;
      Object.assign(this.cursor.style, { display: "block", width: d + "px", height: d + "px",
        left: (e.clientX - p[2].left - d / 2) + "px", top: (e.clientY - p[2].top - d / 2) + "px" });
      if (last) { this.stroke(last, p); last = p; }
    });
    const end = () => { if (last) { last = null; this.onChange(); } };
    this.mask.addEventListener("pointerup", end);
    this.mask.addEventListener("pointercancel", end);
    this.mask.addEventListener("pointerleave", () => { this.cursor.style.display = "none"; });
  }
  load(img) {
    const { canvas, hadAlpha } = imageToCanvas(img, true);
    for (const c of [this.base, this.mask]) { c.width = canvas.width; c.height = canvas.height; }
    this.base.getContext("2d").drawImage(canvas, 0, 0);
    this.undo = [];
    this.loaded = true;
    this.size = Math.max(8, Math.round(canvas.width * 0.06));
    this.sizeIn.max = Math.max(200, Math.round(canvas.width / 4));
    this.sizeIn.value = this.size;
    this.note.hidden = !hadAlpha;
    this.note.textContent = hadAlpha ? "투명한 배경을 흰색으로 채웠어요. 가능하면 배경 있는 원본을 쓰세요." : "";
  }
  stroke(a, b) {
    const ctx = this.mask.getContext("2d");
    ctx.globalCompositeOperation = this.erase ? "destination-out" : "source-over";
    ctx.strokeStyle = ctx.fillStyle = "#ff2a2a";
    ctx.lineWidth = this.size; ctx.lineCap = ctx.lineJoin = "round";
    ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
  }
  pushUndo() {
    this.undo.push(this.mask.getContext("2d").getImageData(0, 0, this.mask.width, this.mask.height));
    if (this.undo.length > 30) this.undo.shift();
  }
  doUndo() {
    const d = this.undo.pop();
    if (d) { this.mask.getContext("2d").putImageData(d, 0, 0); this.onChange(); }
  }
  clear() { this.pushUndo(); this.mask.getContext("2d").clearRect(0, 0, this.mask.width, this.mask.height); this.onChange(); }
  value() {
    if (!this.loaded) return null;
    return { image: this.base.toDataURL("image/png"), mask: this.mask.toDataURL("image/png") };
  }
}

// ---------- 한글 → 영어 번역 ----------
// 한글이 들어간 칸 아래에 영어 번역을 보여 주고, ComfyUI에는 그 영어를 넣는다. 번역은 고쳐도 된다.

const HANGUL = /[\u1100-\u11ff\u3130-\u318f\uac00-\ud7a3]/;

class Translation {
  constructor(src, key, rows) {
    this.src = src; this.key = key + ":en"; this.done = null; this.pending = null; this.timer = null;
    this.status = h("span", { class: "tr-status" });
    this.en = h("textarea", { rows, spellcheck: "false" });
    this.en.oninput = () => this.save();
    this.el = h("div", { class: "translation", hidden: true },
      h("div", { class: "tr-head" }, h("span", {}, "ComfyUI에 들어갈 영어 (고쳐도 돼요)"), this.status), this.en);
    const saved = store.get(this.key);
    if (saved && saved.src === src.value) { this.done = saved.src; this.en.value = saved.en; }
    this.changed(true);
  }
  save() { store.set(this.key, { src: this.done, en: this.en.value }); }
  changed(now) {
    clearTimeout(this.timer);
    const korean = HANGUL.test(this.src.value);
    this.el.hidden = !korean;
    if (korean && this.done !== this.src.value) {
      this.status.textContent = "…";
      this.timer = setTimeout(() => this.translate().catch(() => {}), now ? 0 : 700);
    }
  }
  async translate() {
    const text = this.src.value;
    if (this.pending && this.pending.text === text) return this.pending.promise;
    const promise = (async () => {
      this.status.classList.remove("error");
      this.status.textContent = "번역하는 중…";
      try {
        const st = await api("/api/translate/status");
        if (st.state === "idle" || st.state === "downloading")
          this.status.textContent = "번역 모델을 처음 받는 중… (약 300MB, 한 번만, 인터넷 필요)";
        else if (st.state === "on_disk" || st.state === "loading")
          this.status.textContent = "번역 모델을 불러오는 중…";
      } catch {}
      try {
        const { english } = await api("/api/translate", { text });
        if (this.src.value === text) {
          this.done = text; this.en.value = english; this.save();
          this.status.textContent = "";
        }
      } catch (e) {
        this.status.textContent = e.message;
        this.status.classList.add("error");
        throw e;
      } finally {
        if (this.pending?.text === text) this.pending = null;
      }
    })();
    this.pending = { text, promise };
    return promise;
  }
  async value() {
    if (!HANGUL.test(this.src.value)) return this.src.value;
    if (this.done !== this.src.value) await this.translate();
    return this.en.value;
  }
}

// ---------- 색 팔레트 ----------

function buildPalette(f, key, st) {
  const NONE = "", CUSTOM = "__custom";
  const s = Object.assign({ name: NONE, colors: [], guide: true, snap: true }, store.get(key) || {});
  const save = () => store.set(key, s);
  const sel = h("select");
  const swatches = h("div", { class: "swatches" });
  const guide = h("input", { type: "checkbox" });
  const snap = h("input", { type: "checkbox" });
  guide.checked = s.guide; snap.checked = s.snap;
  guide.onchange = () => { s.guide = guide.checked; save(); };
  snap.onchange = () => { s.snap = snap.checked; save(); };
  const body = h("div", { class: "pal-body" });

  const fillSelect = () => {
    sel.replaceChildren(h("option", { value: NONE }, "쓰지 않기"),
      ...PALETTES.map((p) => h("option", { value: p.name }, `${p.name} (${p.colors.length}색)`)),
      h("option", { value: CUSTOM }, "직접 고른 색"));
    sel.value = s.name;
  };
  const edited = () => { s.name = CUSTOM; sel.value = CUSTOM; save(); };
  const drawSwatches = () => {
    swatches.replaceChildren(
      ...s.colors.map((c, i) => {
        const inp = h("input", { type: "color", value: c, title: c });
        inp.oninput = () => { s.colors[i] = inp.value; edited(); };
        return h("span", { class: "sw" }, inp,
          h("button", { type: "button", class: "x", title: "빼기", onclick: () => { s.colors.splice(i, 1); edited(); drawSwatches(); } }, "×"));
      }),
      h("button", { type: "button", class: "btn small", onclick: () => { s.colors.push("#888888"); edited(); drawSwatches(); } }, "+ 색"));
    body.hidden = s.name === NONE;
  };
  sel.onchange = () => {
    s.name = sel.value;
    const p = PALETTES.find((x) => x.name === sel.value);
    if (p) s.colors = [...p.colors];
    save(); drawSwatches();
  };
  const extract = h("button", { type: "button", class: "btn small", onclick: () => pickFile(async (file) => {
    try {
      const img = await fileToImage(file);
      const url = imageToCanvas(img, false).canvas.toDataURL("image/png");
      const n = +(prompt("몇 가지 색을 뽑을까요?", "12") || 0);
      if (!n) return;
      const { colors } = await api("/api/palette/extract", { image: url, count: n });
      s.colors = colors; edited(); drawSwatches();
    } catch (e) { alert(e.message); }
  }) }, "그림에서 색 뽑기");
  const saveBtn = h("button", { type: "button", class: "btn small", onclick: async () => {
    const name = prompt("팔레트 이름", PALETTES.some((p) => p.name === s.name) ? s.name : "");
    if (!name) return;
    try {
      PALETTES = await api("/api/palettes", { name, colors: s.colors });
      s.name = name; save();
      paletteRefreshers.forEach((r) => r());
    } catch (e) { alert(e.message); }
  } }, "팔레트로 저장");
  body.append(swatches, h("div", { class: "tools" }, extract, saveBtn));
  if (!f.simple) body.append(  // simple: 도트처럼 팔레트 색만 쓰는 곳
    h("label", { class: "check" }, guide, " 그릴 때 이 색 쪽으로 (색 이름을 프롬프트에 붙임)"),
    h("label", { class: "check" }, snap, " 그린 뒤 이 색만 쓰게 맞추기 (결과에 '팔레트 맞춤' 추가)"));
  paletteRefreshers.push(() => { fillSelect(); drawSwatches(); });
  fillSelect(); drawSwatches();
  st.getters[f.id] = () => (s.name === NONE || !s.colors.length ? null
    : { colors: s.colors, guide: s.guide, snap: s.snap });
  return [sel, body];
}

// ---------- LoRA ----------
// ComfyUI\models\loras 의 파일을 골라 세기와 함께 쓴다. 파일 이름이 부르는 단어로 프롬프트에 붙는다.

let LORAS = null;
const loraRefreshers = [];
async function refreshLoras() {
  LORAS = await api("/api/loras").catch(() => null);
  loraRefreshers.forEach((r) => r());
}

function buildLoras(f, key, st) {
  const slots = (store.get(key) || []).filter((x) => x && typeof x === "object");
  if (!slots.length) slots.push({ name: "", strength: 0.8, word: true });
  const save = () => store.set(key, slots);
  const list = h("div", { class: "loras" });
  const msg = h("div", { class: "hint" });
  const draw = () => {
    const names = LORAS || [];
    msg.textContent = LORAS === null ? "ComfyUI 가 켜지면 LoRA 목록을 읽어요."
      : names.length ? "" : "ComfyUI\\models\\loras 폴더에 LoRA 파일(.safetensors)이 없어요.";
    list.replaceChildren(...slots.map((x, i) => {
      const sel = h("select", {}, h("option", { value: "" }, "쓰지 않기"),
        ...[...new Set([...names, x.name].filter(Boolean))].map((n) =>
          h("option", { value: n }, n.replace(/\.safetensors$/, "") + (names.includes(n) ? "" : " (없음)"))));
      sel.value = x.name || "";
      sel.onchange = () => { x.name = sel.value; save(); };
      const num = h("input", { type: "number", min: 0, max: 1.5, step: 0.05, value: x.strength, title: "세기" });
      num.onchange = () => { x.strength = +num.value; save(); };
      const word = h("input", { type: "checkbox" });
      word.checked = x.word !== false;
      word.onchange = () => { x.word = word.checked; save(); };
      return h("div", { class: "lora-row" }, sel,
        h("label", { class: "muted" }, "세기"), num,
        h("label", { class: "muted", title: "파일 이름을 프롬프트에 붙여요 (학습 노트로 만든 LoRA 는 켜 두세요)" }, word, " 이름 단어"),
        slots.length > 1 ? h("button", { type: "button", class: "btn small", title: "빼기",
          onclick: () => { slots.splice(i, 1); save(); draw(); } }, "×") : null);
    }));
  };
  loraRefreshers.push(draw);
  draw();
  st.getters[f.id] = () => slots.filter((x) => x.name).map((x) => ({ ...x }));
  return [list, msg, h("div", { class: "tools" },
    h("button", { type: "button", class: "btn small", onclick: () => {
      if (slots.length < 4) { slots.push({ name: "", strength: 0.8, word: true }); save(); draw(); } } }, "+ LoRA 더하기"),
    h("button", { type: "button", class: "btn small", onclick: refreshLoras }, "목록 새로 읽기"))];
}

// ---------- 입력칸 ----------

function buildField(preset, f, st) {
  const key = `${preset.id}:${f.id}`;
  const saved = store.get(key);
  const title = h("label", { class: "title" }, f.label);
  const hint = f.hint ? h("div", { class: "hint" }, f.hint) : null;
  const box = h("div", { class: "field" }, title);

  if (f.type === "textarea" || f.type === "text") {
    const inp = f.type === "textarea"
      ? h("textarea", { rows: f.rows || 3 })
      : h("input", { type: "text" });
    inp.value = saved ?? f.default ?? "";
    const tr = f.translate === false ? null : new Translation(inp, key, f.rows || 3);
    inp.oninput = () => { store.set(key, inp.value); tr?.changed(); };
    st.getters[f.id] = tr ? () => tr.value() : () => inp.value;
    st.resetters.push(() => { inp.value = f.default ?? ""; store.set(key, null); tr?.changed(); });
    if (f.presets) box.append(h("div", { class: "chips" }, f.presets.map((p) =>
      h("button", { type: "button", class: "btn small", onclick: () => { inp.value = p.value; inp.oninput(); } }, p.label))));
    box.append(inp);
    if (tr) box.append(tr.el);
  } else if (f.type === "number") {
    const range = h("input", { type: "range", min: f.min, max: f.max, step: f.step });
    const num = h("input", { type: "number", min: f.min, max: f.max, step: f.step });
    const set = (v) => { range.value = num.value = v; store.set(key, +v); };
    set(saved ?? f.default);
    range.oninput = () => set(range.value);
    num.onchange = () => set(num.value);
    st.getters[f.id] = () => +num.value;
    st.resetters.push(() => set(f.default));
    box.append(h("div", { class: "row" }, range, num));
  } else if (f.type === "choice") {
    const sel = h("select", {}, f.options.map((o) => h("option", { value: o.value }, o.label)));
    sel.value = saved ?? f.default ?? f.options[0].value;
    sel.onchange = () => store.set(key, sel.value);
    st.getters[f.id] = () => sel.value;
    st.resetters.push(() => { sel.value = f.default ?? f.options[0].value; store.set(key, null); });
    if (f.auto_alpha_from) st.autoAlpha[f.auto_alpha_from] = (hasAlpha) => {
      const o = f.options.find((x) => !!x.alpha === hasAlpha);
      if (o) { sel.value = o.value; store.set(key, sel.value); }
    };
    if (f.auto_from) st.autoRatio[f.auto_from] = (ratio) => {
      let best = f.options[0];
      for (const o of f.options) if (Math.abs(o.ratio - ratio) < Math.abs(best.ratio - ratio)) best = o;
      sel.value = best.value; store.set(key, sel.value);
    };
    box.append(sel);
  } else if (f.type === "seed") {
    const num = h("input", { type: "number", min: 0, step: 1 });
    const rnd = h("input", { type: "checkbox" });
    const s = saved || { seed: 0, random: true };
    num.value = s.seed; rnd.checked = s.random;
    const save = () => store.set(key, { seed: +num.value || 0, random: rnd.checked });
    num.onchange = () => { rnd.checked = false; save(); };
    rnd.onchange = save;
    st.getters[f.id] = () => (rnd.checked ? -1 : +num.value || 0);
    st.seedSetters.push((v) => { num.value = v; save(); });
    box.append(h("div", { class: "row" }, num, h("label", {}, rnd, " 매번 새로")));
  } else if (f.type === "toggle") {
    const cb = h("input", { type: "checkbox" });
    cb.checked = saved ?? f.default ?? true;
    cb.onchange = () => store.set(key, cb.checked);
    st.getters[f.id] = () => cb.checked;
    st.resetters.push(() => { cb.checked = f.default ?? true; store.set(key, null); });
    if (f.skeleton_for) st.skeletonSet[f.skeleton_for] = (on) => { cb.checked = on; store.set(key, on); };
    title.replaceChildren(cb, " ", f.label);
    title.classList.add("check-title");
    if (f.group_label) box.prepend(h("label", { class: "title" }, f.group_label));
    box.classList.add("toggle");
  } else if (f.type === "loras") {
    box.append(...buildLoras(f, key, st));
  } else if (f.type === "palette") {
    box.append(...buildPalette(f, key, st));
  } else if (f.type === "image") {
    let value = null;
    const empty = "여기에 그림을 끌어다 놓거나 눌러서 고르기";
    const zone = dropZone(empty, (file) => fileToImage(file).then(load).catch(alert));
    const clear = h("button", { type: "button", class: "btn small", hidden: true, onclick: () => {
      value = null; zone.replaceChildren(empty); clear.hidden = true; } }, "빼기");  // 안 써도 되는 칸만
    const load = (img) => {
      const conv = imageToCanvas(img, !!f.flatten);
      value = conv.canvas.toDataURL("image/png");
      st.skeletonSet[f.id]?.(isSkeleton(conv.canvas));
      st.autoAlpha[f.id]?.(conv.hadAlpha);
      zone.replaceChildren(h("img", { src: value }), "다른 그림으로 바꾸려면 누르기");
      clear.hidden = f.required !== false;
      st.autoRatio[f.id]?.(img.naturalWidth / img.naturalHeight);
    };
    st.getters[f.id] = () => value;
    st.loaders[f.id] = load;
    box.append(zone, clear);
  } else if (f.type === "images") {
    // 여러 장 (애니메이션 프레임). 순서를 바꾸거나 뺄 수 있다.
    const list = [];
    const strip = h("div", { class: "frames" });
    const count = h("div", { class: "hint" });
    const draw = () => {
      strip.replaceChildren(...list.map((url, i) => h("div", { class: "frame" },
        h("img", { src: url, alt: `프레임 ${i + 1}` }),
        h("span", { class: "num" }, String(i + 1)),
        h("div", { class: "frame-btns" },
          h("button", { type: "button", class: "btn small", title: "앞으로", disabled: i === 0,
            onclick: () => { [list[i - 1], list[i]] = [list[i], list[i - 1]]; draw(); } }, "◀"),
          h("button", { type: "button", class: "btn small", title: "빼기",
            onclick: () => { list.splice(i, 1); draw(); } }, "×"),
          h("button", { type: "button", class: "btn small", title: "뒤로", disabled: i === list.length - 1,
            onclick: () => { [list[i + 1], list[i]] = [list[i], list[i + 1]]; draw(); } }, "▶")))));
      count.textContent = list.length ? `${list.length}장` : "";
      clear.hidden = !list.length;
    };
    const add = (img) => {
      const canvas = imageToCanvas(img, false).canvas;
      if (!list.length) {
        st.autoRatio[f.id]?.(img.naturalWidth / img.naturalHeight);
        st.skeletonSet[f.id]?.(isSkeleton(canvas));
      }
      list.push(canvas.toDataURL("image/png"));
      draw();
    };
    const zone = dropZone("그림 여러 장을 끌어다 놓거나 눌러서 고르기 (파일 이름 순서로 들어가요)", async (files) => {
      for (const file of files) await fileToImage(file).then(add).catch(alert);
    }, true);
    const clear = h("button", { type: "button", class: "btn small", hidden: true,
      onclick: () => { list.length = 0; draw(); } }, "모두 빼기");
    st.getters[f.id] = () => [...list];
    st.counts[f.id] = () => list.length;
    st.loaders[f.id] = add;
    box.append(zone, strip, h("div", { class: "row" }, count, clear));
  } else if (f.type === "mask_image") {
    const painter = new Painter(() => {});
    painter.el.hidden = true;
    const zone = dropZone("고칠 그림을 끌어다 놓거나 눌러서 고르기 (배경 있는 원본)", (file) => fileToImage(file).then(load).catch(alert));
    const change = h("button", { class: "btn", type: "button", hidden: true,
      onclick: () => pickFile((file) => fileToImage(file).then(load).catch(alert)) }, "다른 그림 올리기");
    const load = (img) => { painter.load(img); painter.el.hidden = false; zone.hidden = true; change.hidden = false; };
    st.getters[f.id] = () => painter.value();
    st.loaders[f.id] = load;
    box.append(zone, painter.el, change);
  }
  if (hint) box.append(hint);
  return box;
}

// 3D 자세 만들기 같은 도구 탭 (ComfyUI 워크플로 없음). 화면은 처음 열 때 불러온다.
function buildTool(preset, st) {
  st.runBtn = h("button"); st.stopBtn = h("button");
  const holder = h("div", {}, h("p", { class: "muted" }, "불러오는 중…"));
  st.form = h("div", { hidden: true }, h("h2", {}, preset.name), h("p", { class: "desc" }, preset.description || ""), holder);
  st.open = async () => {
    if (st.tool) return st.tool.refresh?.();
    st.tool = {};
    try {
      const mod = await import("/web/" + preset.tool + ".js");
      holder.replaceChildren();
      st.tool = mod.mount(holder, {
        h, api, store,
        addResult: (url, label) => {
          st.results.unshift({ when: new Date(), images: [{ label, url, filename: "pose.png", send: true }] });
          st.results = st.results.slice(0, 12);
          renderResults();
        },
        sendTo: async (pid, fid, url, stay) => {
          const img = await urlToImage(url);
          if (!S[pid]?.loaders[fid]) throw new Error("보낼 탭이 없어요.");
          if (!stay) showTab(pid);
          S[pid].loaders[fid](img);
        },
        frameCount: (pid, fid) => S[pid]?.counts[fid]?.() ?? 0,
      });
    } catch (e) {
      st.tool = null;
      holder.replaceChildren(h("p", { class: "note" }, "3D 화면을 열지 못했어요: " + e.message));
    }
  };
  return st.form;
}

function buildForm(preset) {
  const st = S[preset.id] = { getters: {}, loaders: {}, autoRatio: {}, autoAlpha: {}, skeletonSet: {}, counts: {},
    seedSetters: [], resetters: [], results: [] };
  if (preset.tool) return buildTool(preset, st);
  const basic = [], adv = [];
  for (const f of preset.fields) (f.advanced ? adv : basic).push(buildField(preset, f, st));
  const runBtn = h("button", { class: "btn primary", type: "button", onclick: () => run(preset) }, preset.run_label || "그리기");
  const stopBtn = h("button", { class: "btn", type: "button", disabled: true,
    onclick: () => api("/api/interrupt", { id: runningJob?.id }) }, "중지");
  st.runBtn = runBtn; st.stopBtn = stopBtn;
  st.form = h("div", { hidden: true },
    h("h2", {}, preset.name),
    h("p", { class: "desc" }, preset.description || ""),
    basic,
    adv.length ? h("details", { class: "adv" }, h("summary", {}, "고급 설정"), adv,
      h("button", { class: "btn", type: "button", onclick: () => st.resetters.forEach((r) => r()) }, "글자·숫자를 처음 값으로")) : null,
    h("div", { class: "actions" }, runBtn, stopBtn));
  return st.form;
}

// ---------- 실행과 결과 ----------

function setStatus(text, error) {
  const el = $("#run-status");
  el.textContent = text;
  el.classList.toggle("error", !!error);
  el.classList.toggle("muted", !error && !runningJob);
}

function setRunning(on) {
  for (const st of Object.values(S)) { st.runBtn.disabled = on; st.stopBtn.disabled = !on; }
}

async function run(preset) {
  const st = S[preset.id];
  const ver = await api("/api/status").then((x) => x.version).catch(() => APP_VERSION);
  if (ver !== APP_VERSION) {
    setStatus("프로그램 파일이 바뀌었어요. 검은 창(그림 도구)을 닫고 그림도구_실행.bat 을 다시 켜 주세요.", true);
    return;
  }
  const values = {};
  setRunning(true);
  runningJob = { pid: preset.id };
  setStatus("보내는 중…");
  try {
    for (const [id, get] of Object.entries(st.getters)) values[id] = await get();
    const { prompt_id, seed } = await api("/api/run", { preset: preset.id, values });
    if (seed != null) st.seedSetters.forEach((s) => s(seed));
    runningJob.id = prompt_id;
    await poll(preset, prompt_id);
  } catch (e) {
    setStatus(e.message, true);
  } finally {
    runningJob = null;
    setRunning(false);
  }
}

async function poll(preset, id) {
  for (;;) {
    await new Promise((r) => setTimeout(r, 1000));
    const s = await api("/api/job/" + id);
    if (s.status === "queued") setStatus(`차례를 기다리는 중 (앞에 ${s.ahead}개)…`);
    else if (s.status === "running")
      setStatus(`${preset.name}: 그리는 중${s.frames > 1 ? ` (프레임 ${s.frame}/${s.frames})` : ""}… ${s.elapsed}초`);
    else if (s.status === "error") { setStatus(s.message, true); return; }
    else if (s.status === "done") {
      const st = S[preset.id];
      st.results.unshift({ when: new Date(), seed: s.seed, elapsed: s.elapsed, images: s.images });
      st.results = st.results.slice(0, 5);
      if (active === preset.id) renderResults();
      setStatus(`다 됐어요 (${s.elapsed}초). 결과는 ComfyUI의 output 폴더에도 저장돼요.`);
      return;
    } else { setStatus("작업을 찾을 수 없어요.", true); return; }
  }
}

function sendTargets() {
  const out = [];
  for (const p of PRESETS) for (const f of p.fields)
    if (f.type === "image" || f.type === "mask_image" || f.type === "images") out.push({ p, f });
  return out;
}

function openSendMenu(btn, url) {
  document.querySelectorAll(".menu").forEach((m) => m.remove());
  const r = btn.getBoundingClientRect();
  const menu = h("div", { class: "menu" }, sendTargets().map(({ p, f }) =>
    h("button", { type: "button", onclick: async () => {
      menu.remove();
      const img = await urlToImage(url);
      showTab(p.id);
      S[p.id].loaders[f.id](img);
    } }, `${p.name} · ${f.label}${f.type === "images" ? " (끝에 더하기)" : ""}`)));
  menu.style.left = (r.left + window.scrollX) + "px";
  menu.style.top = (r.bottom + window.scrollY + 4) + "px";
  document.body.append(menu);
  setTimeout(() => document.addEventListener("click", () => menu.remove(), { once: true }), 0);
}

async function asepriteOpen(im) {
  try {
    setStatus("Aseprite 를 여는 중…");
    const r = await api("/api/aseprite/open", { url: im.url, sheet: im.sheet });
    im.url = r.url;
    im.aseOpened = true;
    renderResults();
    setStatus(im.sheet
      ? "Aseprite 에 프레임으로 나눠 열었어요. 고친 뒤 Ctrl+S 로 저장하고 '고친 것 가져오기' 를 누르세요."
      : "Aseprite 로 열었어요. 고친 뒤 Ctrl+S 로 저장하고 '고친 것 가져오기' 를 누르세요.");
  } catch (e) { setStatus(e.message, true); }
}

async function asepriteImport(im) {
  try {
    setStatus("Aseprite 에서 저장한 것을 가져오는 중…");
    const r = await api("/api/aseprite/import", { url: im.url, sheet: im.sheet });
    im.url = r.url;
    renderResults();
    setStatus("가져왔어요. 이제 '다른 기능으로 보내기' 도 고친 그림으로 보내요.");
  } catch (e) { setStatus(e.message, true); }
}

function renderResults() {
  const box = $("#results");
  box.replaceChildren();
  const st = S[active];
  if (!st.results.length && !runningJob) setStatus("아직 만든 그림이 없어요.");
  for (const res of st.results) for (const im of res.images) {
    const send = h("button", { class: "btn", type: "button" }, "다른 기능으로 보내기");
    send.onclick = (e) => { e.stopPropagation(); openSendMenu(send, im.url); };
    box.append(h("div", { class: "card" },
      h("div", { class: "img", onclick: () => view(im.url) }, h("img", { src: im.url, loading: "lazy", alt: im.label })),
      h("div", { class: "meta" },
        h("b", {}, im.label),
        h("span", { class: "muted" }, res.when.toLocaleTimeString() + (res.seed != null ? ` · 시드 ${res.seed}` : "")),
        h("div", { class: "btns" },
          h("a", { class: "btn", href: im.url, download: im.filename }, "저장"),
          im.send ? send : null,
          ASEPRITE && !im.filename?.endsWith(".gif")
            ? h("button", { class: "btn", type: "button", onclick: () => asepriteOpen(im) }, "Aseprite로 열기") : null,
          im.aseOpened
            ? h("button", { class: "btn", type: "button", onclick: () => asepriteImport(im) }, "고친 것 가져오기") : null))));
  }
}

function view(url) {
  const v = $("#viewer");
  $("img", v).src = url;
  v.hidden = false;
}

function showTab(pid) {
  active = pid;
  store.set("tab", pid);
  for (const p of PRESETS) S[p.id].form.hidden = p.id !== pid;
  document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("active", b.dataset.id === pid));
  renderResults();
  S[pid].open?.();
}

async function checkComfy() {
  const el = $("#comfy-status");
  try {
    const s = await api("/api/status");
    if (s.version !== APP_VERSION) {
      el.textContent = "새 버전을 받았어요. 검은 창을 닫고 그림도구_실행.bat 을 다시 켜 주세요";
      el.className = "pill bad";
      return;
    }
    const ase = !!s.aseprite && !s.remote;
    if (ase !== ASEPRITE) { ASEPRITE = ase; if (active) renderResults(); }
    if (!!s.remote !== REMOTE) { REMOTE = !!s.remote; $("#open-folder").hidden = REMOTE; }
    if (s.update && !UPDATE_CHECKED) { UPDATE_CHECKED = true; checkUpdate(); }
    el.textContent = s.comfy ? "ComfyUI 연결됨" : "ComfyUI 꺼짐 (켜는 중이면 잠시 기다리세요)";
    if (s.comfy && LORAS === null) refreshLoras();
    el.className = "pill " + (s.comfy ? "ok" : "bad");
  } catch {
    el.textContent = "프로그램 창이 꺼졌어요";
    el.className = "pill bad";
  }
}

// ---------- 업데이트 (updater.py) ----------

let UPDATE_CHECKED = false;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function checkUpdate() {
  const btn = $("#update-btn");
  const s = await api("/api/update/check").catch(() => null);
  if (!s || !s.configured) { btn.hidden = true; return; }
  btn.hidden = false;
  btn.classList.toggle("new", !!s.available);
  btn.textContent = s.available ? "새 버전 받기" : "업데이트 확인";
  btn.title = s.error || (s.available ? "바뀐 것:\n" + s.changes.join("\n") : "지금이 최신이에요");
}

async function doUpdate() {
  if (runningJob) { setStatus("그림을 다 만든 뒤에 업데이트하세요.", true); return; }
  setStatus("새 버전이 있는지 확인하는 중…");
  const s = await api("/api/update/check").catch((e) => ({ error: e.message }));
  if (s.error) { setStatus("업데이트를 확인하지 못했어요: " + s.error, true); return; }
  if (!s.available) { setStatus("지금이 최신이에요."); checkUpdate(); return; }
  if (!confirm("새 버전을 받을까요?\n\n바뀐 것:\n- " + s.changes.join("\n- ") +
      "\n\n내 설정, 팔레트, 자세, 번역사전, 결과 그림은 그대로 둬요.")) { setStatus(""); return; }
  setStatus("새 버전을 받는 중…");
  try {
    const r = await api("/api/update/apply", {});
    if (!r.restart) { setStatus(r.message); checkUpdate(); return; }
    setStatus("업데이트했어요. 그림 도구를 다시 켜는 중…");
    await sleep(2500);
    for (let i = 0; i < 60; i++) {
      try { await api("/api/status"); location.reload(); return; } catch { await sleep(1000); }
    }
    setStatus("다시 켜지지 않았어요. 검은 창을 닫고 그림도구_실행.bat 을 다시 켜 주세요.", true);
  } catch (e) { setStatus("업데이트하지 못했어요: " + e.message, true); }
}

async function init() {
  PALETTES = await api("/api/palettes").catch(() => []);
  PRESETS = (await api("/api/presets")).sort((a, b) => (a.order ?? 99) - (b.order ?? 99));
  const nav = $("#tabs"), form = $("#form-area");
  let group = null;
  for (const p of PRESETS) {
    if (p.group !== group) { group = p.group; nav.append(h("h2", {}, group || "기타")); }
    nav.append(h("button", { type: "button", "data-id": p.id, onclick: () => showTab(p.id) }, p.name));
    form.append(buildForm(p));
  }
  const saved = store.get("tab");
  showTab(PRESETS.some((p) => p.id === saved) ? saved : PRESETS[0].id);
  $("#viewer").onclick = () => { $("#viewer").hidden = true; };
  $("#update-btn").onclick = doUpdate;
  setInterval(checkUpdate, 6 * 3600 * 1000);
  $("#open-folder").onclick = () => api("/api/open-folder", {}).catch((e) => setStatus("폴더를 열지 못했어요: " + e.message, true));
  checkComfy();
  setInterval(checkComfy, 5000);
  refreshLoras();
}

init().catch((e) => setStatus("프리셋을 읽지 못했어요: " + e.message, true));
