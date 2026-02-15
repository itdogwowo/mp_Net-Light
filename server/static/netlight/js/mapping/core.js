// static/netlight/js/mapping/core.js

// ==================== 工具函數 ====================
export const keyXY = (x, y) => `${x},${y}`;

export function getCookie(name) {
  let val = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        val = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return val;
}

export async function jget(url) {
  const r = await fetch(url);
  return r.json();
}

export async function jpost(url, obj) {
  const csrftoken = getCookie('csrftoken');
  const r = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrftoken,
    },
    body: JSON.stringify(obj)
  });
  return r.json();
}

export function b64ToU8(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export function defaultPxldId(x, y, w, h) {
  return (y * w) + x;
}

export function autoWH(pixelCount) {
  const w = Math.min(20, Math.max(1, pixelCount));
  const h = Math.ceil(pixelCount / w);
  return { w, h };
}

// ==================== 全局狀態 ====================
export const ST = {
  cell: 12,
  grid_w: 140,
  grid_h: 80,
  fps: 30,
  totalFrames: 0,
  frame: 0,
  slaves: [],
  wh: {},
  layout: {},
  maps: {},
  rgbw: {},
  mode: "board",
  activeSlave: -1,
  picked: null,
  playing: false,
  _raf: 0,
  showGrid: true,
  dpr: window.devicePixelRatio || 1,
  allSlavesRGBW: {},
};

export const FRAME_CACHE = new Map();

// ==================== DOM 元素 ====================
export const DOM = {
  board: null,
  ctx: null,
  pxldNameEl: null,
  slaveSelect: null,
  pickedInfoEl: null,
  pxldIdEl: null,
  mcuIdEl: null,
  msgEl: null,
  playBtn: null,
  pauseBtn: null,
  stopBtn: null,
  frameSlider: null,
  frameInfo: null,
};

export function initDOM() {
  DOM.board = document.getElementById("board");
  DOM.ctx = DOM.board.getContext("2d");
  DOM.pxldNameEl = document.getElementById("pxldName");
  DOM.slaveSelect = document.getElementById("slaveSelect");
  DOM.pickedInfoEl = document.getElementById("pickedInfo");
  DOM.pxldIdEl = document.getElementById("pxldId");
  DOM.mcuIdEl = document.getElementById("mcuId");
  DOM.msgEl = document.getElementById("msg");
  DOM.playBtn = document.getElementById("playBtn");
  DOM.pauseBtn = document.getElementById("pauseBtn");
  DOM.stopBtn = document.getElementById("stopBtn");
  DOM.frameSlider = document.getElementById("frameSlider");
  DOM.frameInfo = document.getElementById("frameInfo");
}

export function showMessage(text, type = "info") {
  const colors = {
    success: "#059669",
    error: "#dc2626",
    info: "#6b7280",
    warning: "#d97706"
  };
  
  DOM.msgEl.textContent = text;
  DOM.msgEl.style.color = colors[type] || colors.info;
  
  setTimeout(() => {
    if (DOM.msgEl.textContent === text) {
      DOM.msgEl.textContent = "";
    }
  }, 3000);
}