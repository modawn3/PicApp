// 3D 자세 만들기: 관절을 끌어서 자세를 잡고, 지금 보는 방향 그대로 OpenPose 뼈대 그림으로 만든다.
// three.js (MIT) 는 web/vendor 에 들어 있어서 인터넷 없이 돌아간다.
import * as THREE from "./vendor/three.module.min.js";
import { OrbitControls } from "./vendor/OrbitControls.js";

// OpenPose 18점 순서: 0 코, 1 목, 2 오른어깨, 3 오른팔꿈치, 4 오른손목, 5 왼어깨, 6 왼팔꿈치, 7 왼손목,
// 8 오른엉덩이, 9 오른무릎, 10 오른발목, 11 왼엉덩이, 12 왼무릎, 13 왼발목, 14 오른눈, 15 왼눈, 16 오른귀, 17 왼귀
// 사람은 +z 쪽(화면 쪽)을 보고 서 있다. 그래서 사람의 오른쪽이 -x.
const NAMES = ["코", "목", "오른어깨", "오른팔꿈치", "오른손목", "왼어깨", "왼팔꿈치", "왼손목", "오른엉덩이", "오른무릎",
  "오른발목", "왼엉덩이", "왼무릎", "왼발목", "오른눈", "왼눈", "오른귀", "왼귀"];
const COLORS = [[255, 0, 0], [255, 85, 0], [255, 170, 0], [255, 255, 0], [170, 255, 0], [85, 255, 0], [0, 255, 0],
  [0, 255, 85], [0, 255, 170], [0, 255, 255], [0, 170, 255], [0, 85, 255], [0, 0, 255], [85, 0, 255], [170, 0, 255],
  [255, 0, 255], [255, 0, 170], [255, 0, 85]];
// controlnet_aux 의 draw_bodypose 와 같은 선 (앞 17개만 그린다)
const LIMBS = [[1, 2], [1, 5], [2, 3], [3, 4], [5, 6], [6, 7], [1, 8], [8, 9], [9, 10], [1, 11], [11, 12], [12, 13],
  [1, 0], [0, 14], [14, 16], [0, 15], [15, 17]];
const MIRROR = [0, 1, 5, 6, 7, 2, 3, 4, 11, 12, 13, 8, 9, 10, 15, 14, 17, 16];
const HEAD = [0, 14, 15, 16, 17];
const UPPER = [0, 1, 2, 3, 4, 5, 6, 7, 14, 15, 16, 17];
const CENTER = new THREE.Vector3(0, 0.88, 0); // 뼈대 그림의 가운데 (프레임끼리 크기·위치가 같게 고정)
const BODY_H = 1.75;

const V = (x, y, z) => new THREE.Vector3(x, y, z);
const X = V(1, 0, 0), Y = V(0, 1, 0), Z = V(0, 0, 1);
const rad = (d) => d * Math.PI / 180;

// ---------- 기본 자세 (각도로 만든다) ----------
const REST = [V(0, 1.6, 0.08), V(0, 1.45, 0), V(-0.19, 1.43, 0), null, null, V(0.19, 1.43, 0), null, null,
  V(-0.1, 0.95, 0), null, null, V(0.1, 0.95, 0), null, null,
  V(-0.035, 1.64, 0.07), V(0.035, 1.64, 0.07), V(-0.08, 1.61, 0), V(0.08, 1.61, 0)];
const ARM = [0.28, 0.26], LEG = [0.43, 0.42];

// f: 앞으로 든 각도, a: 옆으로 벌린 각도, e: 팔꿈치(무릎) 굽힘. side: 오른쪽 -1, 왼쪽 +1
function limb(base, side, f, a, e, lens, knee) {
  const dir = (fwd) => V(0, -1, 0).applyAxisAngle(X, -rad(fwd)).applyAxisAngle(Z, side * rad(a));
  const mid = base.clone().add(dir(f).multiplyScalar(lens[0]));
  const end = mid.clone().add(dir(knee ? f - e : f + e).multiplyScalar(lens[1]));
  return [mid, end];
}
function makePose(p = {}) {
  const j = REST.map((v) => v && v.clone());
  const ra = p.rArm || [0, 8, 5], la = p.lArm || [0, 8, 5], rl = p.rLeg || [0, 3, 0], ll = p.lLeg || [0, 3, 0];
  [j[3], j[4]] = limb(j[2], -1, ...ra, ARM, false);
  [j[6], j[7]] = limb(j[5], 1, ...la, ARM, false);
  [j[9], j[10]] = limb(j[8], -1, ...rl, LEG, true);
  [j[12], j[13]] = limb(j[11], 1, ...ll, LEG, true);
  const neck = j[1].clone();
  for (const i of HEAD) {  // 고개
    j[i].sub(neck).applyAxisAngle(Y, rad(p.headYaw || 0)).applyAxisAngle(X, rad(p.headPitch || 0)).add(neck);
  }
  const pelvis = V(0, 0.95, 0);
  for (const i of UPPER) {  // 허리 굽히기·돌리기
    j[i].sub(pelvis).applyAxisAngle(X, rad(p.bend || 0)).applyAxisAngle(Y, rad(p.twist || 0)).add(pelvis);
  }
  return j;
}
function mirror(j) {
  return MIRROR.map((m) => V(-j[m].x, j[m].y, j[m].z));
}
const walk1 = makePose({ rLeg: [25, 2, 5], lLeg: [-20, 2, 15], rArm: [-20, 6, 15], lArm: [20, 6, 25] });
const walk2 = makePose({ rLeg: [0, 2, 5], lLeg: [15, 2, 55], rArm: [0, 6, 10], lArm: [0, 6, 10] });
const BUILTIN = [
  ["서기", makePose()],
  ["팔 벌리기 (T자)", makePose({ rArm: [0, 90, 0], lArm: [0, 90, 0] })],
  ["걷기 1", walk1], ["걷기 2", walk2], ["걷기 3", mirror(walk1)], ["걷기 4", mirror(walk2)],
  ["달리기", makePose({ bend: 10, rLeg: [45, 2, 75], lLeg: [-30, 2, 45], rArm: [-45, 8, 90], lArm: [50, 8, 90] })],
  ["점프", makePose({ rLeg: [40, 5, 80], lLeg: [30, 5, 70], rArm: [10, 150, 10], lArm: [10, 150, 10] })],
  ["의자에 앉기", makePose({ rLeg: [90, 4, 90], lLeg: [90, 4, 90], rArm: [30, 8, 40], lArm: [30, 8, 40] })],
  ["검 들어 올리기", makePose({ twist: 20, rArm: [150, 20, 40], lArm: [40, 10, 60], rLeg: [-10, 12, 5], lLeg: [15, 12, 15] })],
  ["주문 외우기", makePose({ headPitch: -5, rArm: [80, 15, 30], lArm: [80, 15, 30], rLeg: [0, 6, 0], lLeg: [8, 6, 5] })],
  ["손 흔들기", makePose({ headYaw: 10, lArm: [10, 100, 70], rArm: [0, 8, 5] })],
];

// ---------- 끌어서 움직이기 ----------
const IK = { 4: [2, 3, 4], 7: [5, 6, 7], 10: [8, 9, 10], 13: [11, 12, 13] };
function rotateRule(i, j) {
  const pelvis = j[8].clone().add(j[11]).multiplyScalar(0.5);
  if (i === 3) return [j[2], [3, 4]];
  if (i === 6) return [j[5], [6, 7]];
  if (i === 9) return [j[8], [9, 10]];
  if (i === 12) return [j[11], [12, 13]];
  if (HEAD.includes(i)) return [j[1], HEAD];
  if (i === 2) return [j[1], [2, 3, 4]];
  if (i === 5) return [j[1], [5, 6, 7]];
  if (i === 1) return [pelvis, UPPER];
  if (i === 8) return [pelvis, [8, 9, 10]];
  if (i === 11) return [pelvis, [11, 12, 13]];
  return null;
}
function solveIK(j, [a, b, c], target, viewDir) {
  const S = j[a], E = j[b], W = j[c];
  const l1 = S.distanceTo(E), l2 = E.distanceTo(W);
  const toT = target.clone().sub(S);
  const d = Math.min(Math.max(toT.length(), Math.abs(l1 - l2) + 1e-3), l1 + l2 - 1e-3);
  const u = toT.lengthSq() > 1e-8 ? toT.normalize() : E.clone().sub(S).normalize();
  let v = E.clone().sub(S);
  v.sub(u.clone().multiplyScalar(v.dot(u)));
  if (v.lengthSq() < 1e-8) v = viewDir.clone().cross(u);
  v.normalize();
  const x = (l1 * l1 - l2 * l2 + d * d) / (2 * d);
  const hgt = Math.sqrt(Math.max(0, l1 * l1 - x * x));
  E.copy(S).add(u.clone().multiplyScalar(x)).add(v.multiplyScalar(hgt));
  W.copy(S).add(u.clone().multiplyScalar(d));
}
function dragJoint(j, i, target, viewDir) {
  if (IK[i]) return solveIK(j, IK[i], target, viewDir);
  const rule = rotateRule(i, j);
  if (!rule) return;
  const [pivot, sub] = rule;
  const p = pivot.clone();
  const from = j[i].clone().sub(p), to = target.clone().sub(p);
  if (from.lengthSq() < 1e-8 || to.lengthSq() < 1e-8) return;
  const q = new THREE.Quaternion().setFromUnitVectors(from.normalize(), to.normalize());
  for (const k of sub) j[k].sub(p).applyQuaternion(q).add(p);
}

// ---------- 몸 비율 (치비) ----------
// 뼈대 그림에만 적용한다. 보통 사람 비율 뼈대로는 머리 큰 치비가 안 나오기 때문.
// head: 목 기준 머리 크기, torso: 목~엉덩이, arm/leg: 팔다리 길이, width: 어깨·엉덩이 폭
const BODY = {
  normal: null,
  semi: { head: 1.25, torso: 0.8, arm: 0.75, leg: 0.7, width: 0.9 },
  chibi: { head: 1.55, torso: 0.6, arm: 0.5, leg: 0.45, width: 0.75 },
};
const CHAINS = [[2, 3, 4, "arm"], [5, 6, 7, "arm"], [8, 9, 10, "leg"], [11, 12, 13, "leg"]];
export function reshape(j, kind) {
  const k = BODY[kind];
  if (!k) return j;
  const P = j[8].clone().add(j[11]).multiplyScalar(0.5);
  const N = j[1], N2 = P.clone().add(N.clone().sub(P).multiplyScalar(k.torso));
  const o = j.map((p) => p.clone());
  o[1] = N2;
  for (const i of HEAD) o[i] = N2.clone().add(j[i].clone().sub(N).multiplyScalar(k.head));
  for (const [a, b, c, part] of CHAINS) {
    const base = a < 8 ? N : P, base2 = a < 8 ? N2 : P;
    o[a] = base2.clone().add(j[a].clone().sub(base).multiplyScalar(k.width));
    o[b] = o[a].clone().add(j[b].clone().sub(j[a]).multiplyScalar(k[part]));
    o[c] = o[b].clone().add(j[c].clone().sub(j[b]).multiplyScalar(k[part]));
  }
  // 바닥(낮은 발목)은 그대로, 코 높이는 보통 몸의 0.95배가 되게 키워서 그림 칸을 채운다
  const ground = (q) => Math.min(q[10].y, q[13].y);
  const g0 = ground(j), g1 = ground(o);
  const s = (j[0].y - g0) * 0.95 / Math.max(o[0].y - g1, 1e-3);
  const pivot = V(P.x, g1, P.z);
  return o.map((p) => p.sub(pivot).multiplyScalar(s).add(V(P.x, g0, P.z)));
}

// ---------- 뼈대 그림 (OpenPose) ----------
export function drawOpenPose(joints, camera, W, H, zoom) {
  const c = document.createElement("canvas");
  c.width = W; c.height = H;
  const ctx = c.getContext("2d");
  ctx.fillStyle = "#000"; ctx.fillRect(0, 0, W, H);
  camera.updateMatrixWorld();
  const r = V(0, 0, 0).setFromMatrixColumn(camera.matrixWorld, 0);
  const u = V(0, 0, 0).setFromMatrixColumn(camera.matrixWorld, 1);
  const k = zoom * 0.88 * H / BODY_H;
  const pts = joints.map((p) => { const d = p.clone().sub(CENTER); return [W / 2 + d.dot(r) * k, H / 2 - d.dot(u) * k]; });
  const stick = 4 * Math.max(W, H) / 768 * 1.5;
  LIMBS.forEach(([a, b], n) => {
    const [x1, y1] = pts[a], [x2, y2] = pts[b];
    const len = Math.hypot(x2 - x1, y2 - y1);
    ctx.beginPath();
    ctx.ellipse((x1 + x2) / 2, (y1 + y2) / 2, len / 2, stick, Math.atan2(y2 - y1, x2 - x1), 0, Math.PI * 2);
    const [R, G, B] = COLORS[n];
    ctx.fillStyle = `rgb(${R * 0.6 | 0},${G * 0.6 | 0},${B * 0.6 | 0})`;
    ctx.fill();
  });
  pts.forEach(([x, y], n) => {
    ctx.beginPath(); ctx.arc(x, y, stick, 0, Math.PI * 2);
    ctx.fillStyle = `rgb(${COLORS[n].join(",")})`; ctx.fill();
  });
  return c;
}

// ---------- 화면 ----------
// ui: { h, api, store, addResult(url, label), sendTo(presetId, fieldId, url) -> Promise, frameCount(presetId, fieldId) }
export function mount(root, ui) {
  const { h } = ui;
  let joints = (ui.store.get("pose3d:joints") || []).length === 18
    ? ui.store.get("pose3d:joints").map((a) => V(...a)) : makePose();
  const undo = [];
  const saveState = () => ui.store.set("pose3d:joints", joints.map((p) => p.toArray()));
  const pushUndo = () => { undo.push(joints.map((p) => p.clone())); if (undo.length > 50) undo.shift(); };

  // 3D 장면
  const view = h("div", { class: "pose-view" });
  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  view.append(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x202024);
  const camera = new THREE.PerspectiveCamera(35, 1, 0.05, 50);
  scene.add(new THREE.GridHelper(4, 16, 0x666666, 0x3a3a3a));
  scene.add(new THREE.AmbientLight(0xffffff, 1.2));
  const sun = new THREE.DirectionalLight(0xffffff, 1.5); sun.position.set(2, 4, 3); scene.add(sun);
  const balls = joints.map((_, i) => {
    const m = new THREE.Mesh(new THREE.SphereGeometry(i >= 14 ? 0.022 : 0.035, 20, 14),
      new THREE.MeshStandardMaterial({ color: new THREE.Color(...COLORS[i].map((c) => c / 255)) }));
    m.userData.i = i; scene.add(m); return m;
  });
  const bones = LIMBS.map((_, n) => {
    const m = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, 1, 10),
      new THREE.MeshStandardMaterial({ color: new THREE.Color(...COLORS[n].map((c) => c * 0.6 / 255)) }));
    scene.add(m); return m;
  });
  // 얼굴 방향을 알 수 있게 코 앞에 작은 표시
  const facing = new THREE.Mesh(new THREE.ConeGeometry(0.02, 0.06, 10), new THREE.MeshStandardMaterial({ color: 0xffffff }));
  scene.add(facing);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.copy(CENTER);
  controls.enablePan = false;
  controls.minDistance = 1.5; controls.maxDistance = 8;
  const camSaved = ui.store.get("pose3d:camera");
  camera.position.copy(camSaved ? V(...camSaved) : V(0, 0.95, 4.2));
  controls.update();

  const label = h("div", { class: "pose-label" }, "관절(공)을 끌어서 움직여요. 빈 곳을 끌면 보는 방향이 돌아가요.");
  view.append(label);

  const update = () => {
    joints.forEach((p, i) => balls[i].position.copy(p));
    LIMBS.forEach(([a, b], n) => {
      const A = joints[a], B = joints[b], m = bones[n];
      const d = B.clone().sub(A);
      m.position.copy(A).add(B).multiplyScalar(0.5);
      m.scale.set(1, Math.max(d.length(), 1e-4), 1);
      m.quaternion.setFromUnitVectors(Y, d.normalize());
    });
    const eyes = joints[14].clone().add(joints[15]).multiplyScalar(0.5);
    const look = joints[0].clone().sub(joints[1].clone().add(eyes).multiplyScalar(0.5));
    look.y = 0;
    facing.position.copy(joints[0]).add(look.clone().setLength(0.05));
    if (look.lengthSq() > 1e-8) facing.quaternion.setFromUnitVectors(Y, look.normalize());
    drawPreview();
  };
  const resize = () => {
    const w = view.clientWidth || 460, hh = Math.round(w * 1.15);
    renderer.setSize(w, hh, false);
    renderer.domElement.style.width = "100%"; renderer.domElement.style.height = "auto";
    camera.aspect = w / hh; camera.updateProjectionMatrix();
  };
  new ResizeObserver(resize).observe(view);

  // 끌기
  const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
  let drag = null, hover = null;
  const pick = (e) => {
    const r = renderer.domElement.getBoundingClientRect();
    mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(mouse, camera);
    return ray.intersectObjects(balls)[0]?.object.userData.i;
  };
  const setHover = (i) => {
    if (hover === i) return;
    if (hover != null) balls[hover].scale.setScalar(1);
    hover = i;
    if (i != null) balls[i].scale.setScalar(1.6);
    label.textContent = i != null ? NAMES[i] : "관절(공)을 끌어서 움직여요. 빈 곳을 끌면 보는 방향이 돌아가요.";
    renderer.domElement.style.cursor = i != null ? "grab" : "";
  };
  renderer.domElement.addEventListener("pointerdown", (e) => {
    const i = pick(e);
    if (i == null) return;
    controls.enabled = false;  // OrbitControls 보다 먼저 듣는다 (capture)
    renderer.domElement.setPointerCapture(e.pointerId);
    pushUndo();
    const normal = camera.getWorldDirection(V(0, 0, 0));
    drag = { i, plane: new THREE.Plane().setFromNormalAndCoplanarPoint(normal, joints[i]), normal };
    setHover(i);
  }, { capture: true });
  renderer.domElement.addEventListener("pointermove", (e) => {
    if (!drag) { setHover(pick(e)); return; }
    pick(e);
    const hit = ray.ray.intersectPlane(drag.plane, V(0, 0, 0));
    if (hit) { dragJoint(joints, drag.i, hit, drag.normal); update(); }
  });
  const end = () => {
    if (drag) { drag = null; controls.enabled = true; saveState(); }
  };
  renderer.domElement.addEventListener("pointerup", end);
  renderer.domElement.addEventListener("pointercancel", end);
  controls.addEventListener("end", () => ui.store.set("pose3d:camera", camera.position.toArray()));
  controls.addEventListener("change", drawPreview);

  // 조작 칸
  const setPose = (j) => { pushUndo(); joints = j.map((p) => p.clone()); saveState(); update(); };
  const builtin = h("select", {}, h("option", { value: "" }, "기본 자세 고르기…"),
    BUILTIN.map(([n], i) => h("option", { value: i }, n)));
  builtin.onchange = () => { if (builtin.value !== "") setPose(BUILTIN[+builtin.value][1]); builtin.value = ""; };
  const savedSel = h("select");
  let SAVED = [];
  const fillSaved = () => savedSel.replaceChildren(h("option", { value: "" }, `저장한 자세 (${SAVED.length})…`),
    ...SAVED.map((p, i) => h("option", { value: i }, p.name)));
  savedSel.onchange = () => { if (savedSel.value !== "") setPose(SAVED[+savedSel.value].joints.map((a) => V(...a))); savedSel.value = ""; };
  ui.api("/api/poses").then((x) => { SAVED = x; fillSaved(); }).catch(() => fillSaved());
  fillSaved();
  const btn = (text, onclick, title) => h("button", { type: "button", class: "btn small", onclick, title }, text);
  const camTo = (deg, elev = 0) => {
    const dist = camera.position.distanceTo(controls.target);
    camera.position.set(Math.sin(rad(deg)) * dist * Math.cos(rad(elev)), CENTER.y + Math.sin(rad(elev)) * dist,
      Math.cos(rad(deg)) * dist * Math.cos(rad(elev)));
    controls.update(); ui.store.set("pose3d:camera", camera.position.toArray());
  };

  const ratio = h("select", {},
    h("option", { value: "512x768" }, "세로 512x768"), h("option", { value: "512x512" }, "정사각 512x512"),
    h("option", { value: "512x704" }, "3:4 512x704"));
  ratio.value = ui.store.get("pose3d:ratio") || "512x768";
  ratio.onchange = () => { ui.store.set("pose3d:ratio", ratio.value); drawPreview(); };
  const zoom = h("input", { type: "range", min: 0.5, max: 1.5, step: 0.05, value: ui.store.get("pose3d:zoom") || 1 });
  zoom.oninput = () => { ui.store.set("pose3d:zoom", +zoom.value); drawPreview(); };
  const body = h("select", {},
    h("option", { value: "normal" }, "보통"), h("option", { value: "semi" }, "조금 귀엽게 (머리 크게)"),
    h("option", { value: "chibi" }, "치비 (2~3등신)"));
  body.value = ui.store.get("pose3d:body") || "normal";
  body.onchange = () => { ui.store.set("pose3d:body", body.value); drawPreview(); };
  const preview = h("canvas", { class: "pose-preview" });
  function drawPreview() {
    const [W, H] = ratio.value.split("x").map(Number);
    const c = drawOpenPose(reshape(joints, body.value), camera, W, H, +zoom.value);
    preview.width = W; preview.height = H;
    preview.getContext("2d").drawImage(c, 0, 0);
  }
  const image = () => {
    const [W, H] = ratio.value.split("x").map(Number);
    return drawOpenPose(reshape(joints, body.value), camera, W, H, +zoom.value).toDataURL("image/png");
  };
  const note = h("div", { class: "hint" });
  const frames = () => {
    const n = ui.frameCount("10_sprite", "poses");
    note.textContent = n ? `애니메이션 프레임: ${n}장 모였어요.` : "";
  };

  root.append(
    view,
    h("div", { class: "tools" }, builtin, savedSel),
    h("div", { class: "tools" },
      btn("되돌리기", () => { const u = undo.pop(); if (u) { joints = u; saveState(); update(); } }),
      btn("좌우 뒤집기", () => setPose(mirror(joints)), "왼쪽과 오른쪽 자세를 바꿔요 (걷기 반대 발 만들 때)"),
      btn("자세 저장", async () => {
        const name = prompt("자세 이름");
        if (!name) return;
        try { SAVED = await ui.api("/api/poses", { name, joints: joints.map((p) => p.toArray()) }); fillSaved(); }
        catch (e) { alert(e.message); }
      })),
    h("div", { class: "field" }, h("label", { class: "title" }, "보는 방향"),
      h("div", { class: "tools" }, btn("정면", () => camTo(0)), btn("비스듬히", () => camTo(35, 8)),
        btn("오른쪽 옆", () => camTo(-90)), btn("왼쪽 옆", () => camTo(90)), btn("뒤", () => camTo(180)),
        btn("위에서", () => camTo(20, 35))),
      h("div", { class: "hint" }, "뼈대 그림은 지금 보는 방향 그대로 만들어져요. 애니메이션 프레임은 보는 방향을 바꾸지 말고 자세만 바꿔요.")),
    h("div", { class: "pose-out" },
      h("div", {}, preview),
      h("div", { class: "pose-out-ctl" },
        h("label", { class: "title" }, "뼈대 그림 비율"), ratio,
        h("label", { class: "title" }, "크기"), zoom,
        h("label", { class: "title" }, "몸 비율"), body,
        h("div", { class: "hint" }, "그릴 탭의 비율과 맞추세요. 크기는 모든 프레임에 똑같이 써요. 몸 비율은 이 뼈대 그림에만 적용돼요 (치비 캐릭터는 '치비'로)."))),
    h("div", { class: "actions" },
      h("button", { type: "button", class: "btn primary", onclick: async () => {
        await ui.sendTo("03_pose", "pose", image());
      } }, "자세 참고 캐릭터로 보내기"),
      h("button", { type: "button", class: "btn", onclick: async () => {
        await ui.sendTo("10_sprite", "poses", image(), true); frames();
      } }, "애니메이션 프레임으로 더하기"),
      h("button", { type: "button", class: "btn", onclick: () => ui.addResult(image(), "뼈대 그림") }, "결과로 남기기")),
    note);
  resize(); update(); frames();
  renderer.setAnimationLoop(() => { if (root.offsetParent !== null) renderer.render(scene, camera); });
  return { refresh: frames };
}
