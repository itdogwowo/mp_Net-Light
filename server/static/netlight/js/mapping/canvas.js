// static/netlight/js/mapping/canvas.js
import { ST, DOM } from './core.js';

export function rgbwToRgb(r, g, b, w) {
  if (r === 0 && g === 0 && b === 0) {
    if (w < 20) return { r: 0, g: 0, b: 0 };
    const brightness = Math.min(255, w * 0.5);
    return { r: brightness, g: brightness, b: brightness };
  }
  
  if (w > 0) {
    const mix = 0.2;
    return {
      r: Math.min(255, r + w * mix),
      g: Math.min(255, g + w * mix),
      b: Math.min(255, b + w * mix)
    };
  }
  
  return { r, g, b };
}

export function getColorFromRGBW(rgbwData, pxldId) {
  const offset = pxldId * 4;
  if (offset + 3 >= rgbwData.length) return null;
  
  const r = rgbwData[offset];
  const g = rgbwData[offset + 1];
  const b = rgbwData[offset + 2];
  const w = rgbwData[offset + 3];
  
  const color = rgbwToRgb(r, g, b, w);
  return `rgb(${color.r},${color.g},${color.b})`;
}

export function resizeCanvas() {
  let w, h;
  if (ST.mode === "board") {
    w = ST.grid_w * ST.cell;
    h = ST.grid_h * ST.cell;
  } else {
    const wh = ST.wh[ST.activeSlave];
    w = wh.w * ST.cell;
    h = wh.h * ST.cell;
  }

  DOM.board.style.width = `${w}px`;
  DOM.board.style.height = `${h}px`;
  DOM.board.width = w * ST.dpr;
  DOM.board.height = h * ST.dpr;
  DOM.ctx.scale(ST.dpr, ST.dpr);
  DOM.ctx.imageSmoothingEnabled = false;
}

export function drawBackground() {
  DOM.ctx.fillStyle = "#0f1419";
  DOM.ctx.fillRect(0, 0, DOM.board.width / ST.dpr, DOM.board.height / ST.dpr);
}

export function drawGrid(cols, rows) {
  if (!ST.showGrid) return;

  DOM.ctx.strokeStyle = "rgba(255,255,255,0.12)";
  DOM.ctx.lineWidth = 0.5;

  for (let x = 0; x <= cols; x++) {
    DOM.ctx.beginPath();
    DOM.ctx.moveTo(x * ST.cell + 0.5, 0);
    DOM.ctx.lineTo(x * ST.cell + 0.5, rows * ST.cell);
    DOM.ctx.stroke();
  }
  for (let y = 0; y <= rows; y++) {
    DOM.ctx.beginPath();
    DOM.ctx.moveTo(0, y * ST.cell + 0.5);
    DOM.ctx.lineTo(cols * ST.cell, y * ST.cell + 0.5);
    DOM.ctx.stroke();
  }
}

export function drawSlaveLEDsOnBoard(sid, ox, oy, w, h) {
  const rgbwData = ST.allSlavesRGBW[sid];
  if (!rgbwData || rgbwData.length === 0) return;
  
  const m = ST.maps[sid] || {};
  const hasMapping = Object.keys(m).length > 0;
  
  if (hasMapping) {
    for (const key in m) {
      const [lx, ly] = key.split(",").map(n => parseInt(n, 10));
      const pxldId = m[key].pxld_id;
      
      if (lx >= 0 && lx < w && ly >= 0 && ly < h) {
        const color = getColorFromRGBW(rgbwData, pxldId);
        if (color) {
          DOM.ctx.fillStyle = color;
          DOM.ctx.fillRect(
            (ox + lx) * ST.cell, 
            (oy + ly) * ST.cell, 
            ST.cell, 
            ST.cell
          );
        }
      }
    }
  } else {
    for (let i = 0; i < w * h && i * 4 < rgbwData.length; i++) {
      const lx = i % w;
      const ly = Math.floor(i / w);
      const color = getColorFromRGBW(rgbwData, i);
      if (color) {
        DOM.ctx.fillStyle = color;
        DOM.ctx.fillRect(
          (ox + lx) * ST.cell, 
          (oy + ly) * ST.cell, 
          ST.cell, 
          ST.cell
        );
      }
    }
  }
}

export function drawSlaveRectsOnBoard() {
  for (const s of ST.slaves) {
    const sid = s.slave_id;
    const layout = ST.layout[sid] || { ox: 0, oy: 0 };
    const wh = ST.wh[sid] || { w: 1, h: 1 };
    
    drawSlaveLEDsOnBoard(sid, layout.ox, layout.oy, wh.w, wh.h);
    
    DOM.ctx.strokeStyle = "rgba(99,179,237,0.7)";
    DOM.ctx.lineWidth = 1;
    DOM.ctx.strokeRect(
      layout.ox * ST.cell + 0.5, 
      layout.oy * ST.cell + 0.5, 
      wh.w * ST.cell, 
      wh.h * ST.cell
    );
    
    DOM.ctx.fillStyle = "rgba(255,255,255,0.9)";
    DOM.ctx.font = "10px monospace";
    DOM.ctx.fillText(`S${sid}`, layout.ox * ST.cell + 3, layout.oy * ST.cell + 12);
  }
}

export function drawSlaveFrame(sid) {
  const rgbw = ST.rgbw[sid];
  if (!rgbw) return;

  const { w, h } = ST.wh[sid] || { w: 1, h: 1 };
  const m = ST.maps[sid] || {};
  const hasMapping = Object.keys(m).length > 0;
  
  if (hasMapping) {
    for (const key in m) {
      const [lx, ly] = key.split(",").map(n => parseInt(n, 10));
      const pxldId = m[key].pxld_id;
      
      if (lx >= 0 && lx < w && ly >= 0 && ly < h) {
        const color = getColorFromRGBW(rgbw, pxldId);
        if (color) {
          DOM.ctx.fillStyle = color;
          DOM.ctx.fillRect(lx * ST.cell, ly * ST.cell, ST.cell, ST.cell);
        }
      }
    }
  } else {
    for (let i = 0; i < w * h && i * 4 < rgbw.length; i++) {
      const lx = i % w;
      const ly = Math.floor(i / w);
      const color = getColorFromRGBW(rgbw, i);
      if (color) {
        DOM.ctx.fillStyle = color;
        DOM.ctx.fillRect(lx * ST.cell, ly * ST.cell, ST.cell, ST.cell);
      }
    }
  }
}

export function drawPicked() {
  if (!ST.picked) return;
  DOM.ctx.strokeStyle = "rgba(245,158,11,0.95)";
  DOM.ctx.lineWidth = 2;
  DOM.ctx.strokeRect(
    ST.picked.gx * ST.cell + 0.5, 
    ST.picked.gy * ST.cell + 0.5, 
    ST.cell, 
    ST.cell
  );
}

export function drawHUD() {
  DOM.ctx.fillStyle = "rgba(0,0,0,0.65)";
  DOM.ctx.fillRect(4, 4, 340, 46);
  DOM.ctx.fillStyle = "rgba(255,255,255,0.95)";
  DOM.ctx.font = "10px monospace";

  const mode = ST.mode;
  const sid = ST.activeSlave;
  const gridStr = (mode === "board") 
    ? `${ST.grid_w}x${ST.grid_h}` 
    : `${ST.wh[sid].w}x${ST.wh[sid].h}`;

  DOM.ctx.fillText(
    `mode=${mode} slave=${sid} frame=${ST.frame}/${Math.max(0, ST.totalFrames - 1)} fps=${ST.fps}`, 
    8, 18
  );
  DOM.ctx.fillText(`grid=${gridStr} cell=${ST.cell}px`, 8, 34);
}

export function redraw() {
  resizeCanvas();
  DOM.ctx.clearRect(0, 0, DOM.board.width / ST.dpr, DOM.board.height / ST.dpr);
  drawBackground();

  if (ST.mode === "board") {
    drawSlaveRectsOnBoard();
    drawGrid(ST.grid_w, ST.grid_h);
  } else {
    const { w, h } = ST.wh[ST.activeSlave];
    drawSlaveFrame(ST.activeSlave);
    drawGrid(w, h);
  }

  drawPicked();
  drawHUD();
}