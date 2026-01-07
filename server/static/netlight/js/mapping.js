// static/netlight/js/mapping.js
// Mapping + 播放（PXLD v3）
// - 預設選項：總畫板 (-1)
// - board 模式：顯示多 slave layout（blit）
// - slave 模式：真正重繪該 slave 的 w*h 画布
// - pxld_id 預設排列：column-major (0,0)(0,1)... => pxld_id = x*h + y
// - 顯示：RGB 用 (r,g,b)，若 r=g=b=0 且 w>0 => 灰階 (w,w,w) [1]
// - 格線：永遠疊加，避免全白/全色時以為壞了

const board = document.getElementById("board");
const ctx = board.getContext("2d");

const pxldNameEl = document.getElementById("pxldName");
const slaveSelect = document.getElementById("slaveSelect");
const pickedInfoEl = document.getElementById("pickedInfo");
const pxldIdEl = document.getElementById("pxldId");
const mcuIdEl = document.getElementById("mcuId");
const msgEl = document.getElementById("msg");

const playBtn = document.getElementById("playBtn");
const pauseBtn = document.getElementById("pauseBtn");
const stopBtn = document.getElementById("stopBtn");
const frameSlider = document.getElementById("frameSlider");
const frameInfo = document.getElementById("frameInfo");

// --- util ---
function keyXY(x, y) { return `${x},${y}`; }

async function jget(url) {
  const r = await fetch(url);
  return r.json();
}

async function jpost(url, obj) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(obj),
  });
  return r.json();
}

function b64ToU8(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

// 你要的順序：(0,0)(0,1)... => column-major
// pxld_id = x*h + y
function defaultPxldId(x, y, w, h) {
  return (x * h) + y;
}

// 初始 w/h：A 模式，由 pixel_count 自動推導（你可再改）
function autoWH(pixelCount) {
  const w = Math.min(20, Math.max(1, pixelCount));
  const h = Math.ceil(pixelCount / w);
  return { w, h };
}

// 點擊座標換算：避免 canvas CSS scale 造成點擊偏移
function eventToGrid(ev) {
  const rect = board.getBoundingClientRect();
  const rx = (ev.clientX - rect.left) / rect.width;
  const ry = (ev.clientY - rect.top) / rect.height;
  const px = rx * board.width;
  const py = ry * board.height;
  return { gx: Math.floor(px / st.cell), gy: Math.floor(py / st.cell) };
}

const st = {
  cell: 16,

  // board 模式總畫板大小（格子）
  grid_w: 140,
  grid_h: 80,

  fps: 30,
  totalFrames: 0,
  frame: 0,

  slaves: [],        // from pxld/slaves
  wh: {},            // slave_id -> {w,h}
  layout: {},        // slave_id -> {ox,oy}
  maps: {},          // slave_id -> {"x,y":{pxld_id,mcu_id}}
  rgbw: {},          // slave_id -> Uint8Array

  mode: "board",     // 'board' or 'slave'
  activeSlave: -1,   // -1 => board
  picked: null,      // {sid,lx,ly,gx,gy}
  playing: false,
  _raf: 0,

  // debug / 防“全白误判”
  showGrid: true,
  showCellBorder: true,     // 每格边框
  showStats: true,
};

// ---------- canvas size ----------
function resizeCanvas() {
  if (st.mode === "board") {
    board.width = st.grid_w * st.cell;
    board.height = st.grid_h * st.cell;
  } else {
    const { w, h } = st.wh[st.activeSlave];
    board.width = w * st.cell;
    board.height = h * st.cell;
  }
}

// ---------- drawing ----------
function drawBackground() {
  ctx.fillStyle = "#0f1419";
  ctx.fillRect(0, 0, board.width, board.height);
}

function drawGrid(cols, rows) {
  if (!st.showGrid) return;

  ctx.strokeStyle = "rgba(255,255,255,0.10)";
  ctx.lineWidth = 1;

  for (let x = 0; x <= cols; x++) {
    ctx.beginPath();
    ctx.moveTo(x * st.cell + 0.5, 0);
    ctx.lineTo(x * st.cell + 0.5, board.height);
    ctx.stroke();
  }
  for (let y = 0; y <= rows; y++) {
    ctx.beginPath();
    ctx.moveTo(0, y * st.cell + 0.5);
    ctx.lineTo(board.width, y * st.cell + 0.5);
    ctx.stroke();
  }
}

function drawSlaveRectsOnBoard() {
  for (const s of st.slaves) {
    const sid = s.slave_id;
    const { w, h } = st.wh[sid];
    const { ox, oy } = st.layout[sid] || { ox: 0, oy: 0 };

    const x = ox * st.cell, y = oy * st.cell;
    const pw = w * st.cell, ph = h * st.cell;

    ctx.fillStyle = "rgba(99,179,237,0.12)";
    ctx.fillRect(x, y, pw, ph);

    ctx.strokeStyle = "rgba(99,179,237,0.95)";
    ctx.lineWidth = 2;
    ctx.strokeRect(x + 0.5, y + 0.5, pw, ph);

    ctx.fillStyle = "rgba(255,255,255,0.9)";
    ctx.font = "12px monospace";
    ctx.fillText(`S${sid} ${w}x${h}`, x + 4, y + 14);

    // mapping marker
    const m = st.maps[sid] || {};
    for (const k in m) {
      const [lx, ly] = k.split(",").map(n => parseInt(n, 10));
      ctx.fillStyle = "rgba(16,185,129,0.9)";
      ctx.fillRect(
        (ox + lx) * st.cell + st.cell * 0.25,
        (oy + ly) * st.cell + st.cell * 0.25,
        st.cell * 0.5,
        st.cell * 0.5
      );
    }
  }
}

// RGBW -> display RGB
function rgbwToRgb(r, g, b, w) {
  // 單色 LED：v3 用 [0,0,0,W] [1]
  if (r === 0 && g === 0 && b === 0 && w > 0) {
    return { r: w, g: w, b: w };
  }
  // RGB LED：顯示 RGB；W 可先忽略（避免“全白”誤判）
  return { r, g, b };
}

function drawSlaveFrame(sid) {
  const rgbw = st.rgbw[sid];
  if (!rgbw) return;

  const { w, h } = st.wh[sid];

  // 逐 LED 畫格子：pxld_id 對應 bytes_offset = pxld_id*4 [2]
  // 你要 column-major：
  // pxld_id = x*h + y  => x = floor(pxld_id/h), y = pxld_id % h
  for (let off = 0; off + 3 < rgbw.length; off += 4) {
    const pxldId = (off >> 2);

    const x = Math.floor(pxldId / h);
    const y = pxldId % h;
    if (x >= w) break;

    const r = rgbw[off], g = rgbw[off + 1], b = rgbw[off + 2], ww = rgbw[off + 3];
    const c = rgbwToRgb(r, g, b, ww);

    ctx.fillStyle = `rgb(${c.r},${c.g},${c.b})`;
    ctx.fillRect(x * st.cell, y * st.cell, st.cell, st.cell);
  }

  // 叠加 mapping marker
  const m = st.maps[sid] || {};
  for (const k in m) {
    const [lx, ly] = k.split(",").map(n => parseInt(n, 10));
    ctx.fillStyle = "rgba(16,185,129,0.9)";
    ctx.fillRect(lx * st.cell + st.cell * 0.25, ly * st.cell + st.cell * 0.25, st.cell * 0.5, st.cell * 0.5);
  }
}

function drawPicked() {
  if (!st.picked) return;
  ctx.strokeStyle = "rgba(245,158,11,0.95)";
  ctx.lineWidth = 3;
  ctx.strokeRect(st.picked.gx * st.cell + 0.5, st.picked.gy * st.cell + 0.5, st.cell, st.cell);
}

function drawHUD() {
  // 顯示基本狀態，避免“全白像壞了”
  ctx.fillStyle = "rgba(0,0,0,0.55)";
  ctx.fillRect(6, 6, 360, 54);
  ctx.fillStyle = "rgba(255,255,255,0.92)";
  ctx.font = "12px monospace";

  const mode = st.mode;
  const sid = st.activeSlave;
  ctx.fillText(`mode=${mode} slave=${sid} frame=${st.frame}/${Math.max(0, st.totalFrames - 1)} fps=${st.fps}`, 12, 24);
  ctx.fillText(`grid=${(mode === "board") ? `${st.grid_w}x${st.grid_h}` : `${st.wh[sid].w}x${st.wh[sid].h}`} cell=${st.cell}px`, 12, 42);
}

function redraw() {
  resizeCanvas();
  ctx.clearRect(0, 0, board.width, board.height);
  drawBackground();

  if (st.mode === "board") {
    drawSlaveRectsOnBoard();
    drawGrid(st.grid_w, st.grid_h);
  } else {
    const { w, h } = st.wh[st.activeSlave];
    drawSlaveFrame(st.activeSlave);
    drawGrid(w, h);
  }

  drawPicked();
  drawHUD();
}

// ---------- hit test ----------
function hitBoard(gx, gy) {
  for (const s of st.slaves) {
    const sid = s.slave_id;
    const { w, h } = st.wh[sid];
    const { ox, oy } = st.layout[sid] || { ox: 0, oy: 0 };
    if (gx >= ox && gy >= oy && gx < ox + w && gy < oy + h) {
      return { sid, lx: gx - ox, ly: gy - oy };
    }
  }
  return null;
}

// ---------- click ----------
board.addEventListener("click", async (ev) => {
  const { gx, gy } = eventToGrid(ev);

  if (st.mode === "board") {
    const hit = hitBoard(gx, gy);
    if (!hit) {
      st.picked = null;
      pickedInfoEl.textContent = `未命中任何 slave：(${gx},${gy})`;
      redraw();
      return;
    }
    st.picked = { gx, gy, ...hit };
  } else {
    const sid = st.activeSlave;
    const { w, h } = st.wh[sid];
    if (gx < 0 || gy < 0 || gx >= w || gy >= h) return;
    st.picked = { sid, lx: gx, ly: gy, gx, gy };
  }

  const { sid, lx, ly } = st.picked;
  const mapKey = keyXY(lx, ly);
  const cur = (st.maps[sid] || {})[mapKey];
  const { w, h } = st.wh[sid];

  // 顯示資訊
  pickedInfoEl.textContent =
    `mode=${st.mode} slave=${sid} local=(${lx},${ly})` +
    (st.mode === "board" ? ` global=(${gx},${gy})` : "") +
    (cur ? ` pxld=${cur.pxld_id} mcu=${cur.mcu_id}` : "");

  if (cur) {
    pxldIdEl.value = cur.pxld_id;
    mcuIdEl.value = cur.mcu_id;
  } else {
    // 未設定 mapping：按你規則自動填 pxld_id
    const def = defaultPxldId(lx, ly, w, h);
    pxldIdEl.value = def;
    // mcu_id：預設跟 pxld_id 一樣（你可刪掉改為 0）
    mcuIdEl.value = def;
  }

  redraw();
});

// ---------- apply/save ----------
document.getElementById("applyBtn").addEventListener("click", () => {
  if (!st.picked) return;
  const { sid, lx, ly } = st.picked;

  st.maps[sid] = st.maps[sid] || {};
  st.maps[sid][keyXY(lx, ly)] = {
    pxld_id: parseInt(pxldIdEl.value, 10) || 0,
    mcu_id: parseInt(mcuIdEl.value, 10) || 0,
  };
  msgEl.textContent = `已套用：S${sid} (${lx},${ly})`;
  redraw();
});

document.getElementById("saveBtn").addEventListener("click", async () => {
  const sid = st.activeSlave;
  if (sid === -1) {
    msgEl.textContent = "請先選擇某個 slave 再保存（總畫板不保存 mapping）";
    return;
  }

  const { w, h } = st.wh[sid];
  const arr = [];
  const m = st.maps[sid] || {};
  for (const k in m) {
    const [x, y] = k.split(",").map(n => parseInt(n, 10));
    arr.push({ x, y, pxld_id: m[k].pxld_id, mcu_id: m[k].mcu_id });
  }

  const body = { version: 1, slave_id: sid, w, h, map: arr };
  const res = await jpost("/light/api/mapping/set/", body);
  msgEl.textContent = res.ok ? `保存成功：mapping_slave_${sid}.json` : `保存失敗：${res.err || "unknown"}`;
});

// ---------- load mapping + frame rgbw ----------
async function loadMapping(slaveId) {
  const res = await jget(`/light/api/mapping/get/?slave_id=${slaveId}`);
  st.maps[slaveId] = {};
  if (res.ok && res.data && res.data.map) {
    for (const it of res.data.map) {
      st.maps[slaveId][keyXY(it.x, it.y)] = { pxld_id: it.pxld_id, mcu_id: it.mcu_id };
    }
    // B 階段：mapping 檔有 w/h 就覆蓋
    if (res.data.w && res.data.h) {
      st.wh[slaveId] = { w: res.data.w | 0, h: res.data.h | 0 };
    }
  }
}

async function loadSlaveRGBW(frame, slaveId) {
  const name = pxldNameEl.value;
  const url = `/light/api/pxld/slave_frame_rgbw?name=${encodeURIComponent(name)}&frame=${frame}&slave_id=${slaveId}`;
  const res = await jget(url);
  if (res.ok) st.rgbw[slaveId] = b64ToU8(res.b64);
}

// ---------- slave select ----------
slaveSelect.addEventListener("change", async () => {
  const sid = parseInt(slaveSelect.value, 10);

  st.activeSlave = sid;
  st.mode = (sid === -1) ? "board" : "slave";
  st.picked = null;
  pickedInfoEl.textContent = "-";

  // 先清屏，立即反馈
  resizeCanvas();
  drawBackground();
  redraw();

  if (sid !== -1) {
    await loadMapping(sid);
    await loadSlaveRGBW(st.frame, sid);
  }
  redraw();
});

// ---------- playback ----------
function stopPlayback() {
  st.playing = false;
  if (st._raf) cancelAnimationFrame(st._raf);
  st._raf = 0;
}

async function tick(now, lastRef) {
  if (!st.playing) return;

  const dt = now - lastRef.last;
  const frameTime = 1000 / st.fps;

  if (dt >= frameTime) {
    st.frame = (st.frame + 1) % st.totalFrames;
    frameSlider.value = String(st.frame);
    frameInfo.textContent = `frame: ${st.frame} / ${Math.max(0, st.totalFrames - 1)}`;

    if (st.mode === "slave" && st.activeSlave !== -1) {
      await loadSlaveRGBW(st.frame, st.activeSlave);
    }
    redraw();
    lastRef.last = now - (dt % frameTime);
  }

  st._raf = requestAnimationFrame(t => tick(t, lastRef));
}

function play() {
  if (st.playing || st.totalFrames <= 0) return;
  st.playing = true;
  const lastRef = { last: performance.now() };
  st._raf = requestAnimationFrame(t => tick(t, lastRef));
}

playBtn && playBtn.addEventListener("click", play);
pauseBtn && pauseBtn.addEventListener("click", () => { st.playing = false; });
stopBtn && stopBtn.addEventListener("click", () => {
  stopPlayback();
  st.frame = 0;
  frameSlider.value = "0";
  frameInfo.textContent = `frame: 0 / ${Math.max(0, st.totalFrames - 1)}`;
  redraw();
});

frameSlider && frameSlider.addEventListener("input", async () => {
  const v = parseInt(frameSlider.value, 10) || 0;
  st.frame = v;
  frameInfo.textContent = `frame: ${st.frame} / ${Math.max(0, st.totalFrames - 1)}`;
  if (st.mode === "slave" && st.activeSlave !== -1) {
    await loadSlaveRGBW(st.frame, st.activeSlave);
  }
  redraw();
});

// ---------- bootstrap ----------
async function bootstrap() {
  msgEl.textContent = "載入 PXLD...";

  const name = pxldNameEl.value;

  const info = await jget(`/light/api/pxld/info/?name=${encodeURIComponent(name)}`);
  if (!info.ok) { msgEl.textContent = `PXLD info 失敗：${info.err}`; return; }

  st.fps = info.info.fps;
  st.totalFrames = info.info.total_frames;

  frameSlider.max = String(Math.max(0, st.totalFrames - 1));
  frameSlider.value = "0";
  frameInfo.textContent = `frame: 0 / ${Math.max(0, st.totalFrames - 1)}`;

  const sres = await jget(`/light/api/pxld/slaves/?name=${encodeURIComponent(name)}`);
  if (!sres.ok) { msgEl.textContent = `PXLD slaves 失敗：${sres.err}`; return; }

  st.slaves = sres.slaves;

  // A：先自動 w/h
  for (const s of st.slaves) st.wh[s.slave_id] = autoWH(s.pixel_count);

  // layout：讀不到就自動排
  const lres = await jget("/light/api/config/layout/get/");
  st.layout = {};
  if (lres.ok && lres.data && lres.data.layout) {
    for (const it of lres.data.layout) st.layout[it.slave_id] = { ox: it.ox | 0, oy: it.oy | 0 };
  }

  let curx = 0, cury = 0, rowh = 0;
  for (const s of st.slaves) {
    const sid = s.slave_id;
    if (!st.layout[sid]) {
      const { w, h } = st.wh[sid];
      st.layout[sid] = { ox: curx, oy: cury };
      curx += w + 2;
      rowh = Math.max(rowh, h);
      if (curx > st.grid_w - 45) {
        curx = 0;
        cury += rowh + 2;
        rowh = 0;
      }
    }
  }

  // slaveSelect：插入「總畫板」
  slaveSelect.innerHTML = "";
  const o0 = document.createElement("option");
  o0.value = "-1";
  o0.textContent = "總畫板";
  slaveSelect.appendChild(o0);

  for (const s of st.slaves) {
    const opt = document.createElement("option");
    opt.value = String(s.slave_id);
    opt.textContent = `Slave ${s.slave_id} (${s.pixel_count} LED)`;
    slaveSelect.appendChild(opt);
  }

  st.activeSlave = -1;
  st.mode = "board";
  slaveSelect.value = "-1";

  msgEl.textContent = "完成（要播放請先選某個 slave）";
  redraw();
}

bootstrap().catch(console.error);