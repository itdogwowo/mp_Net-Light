// static/netlight/js/mapping/canvas.js
import { ST, DOM } from './core.js';

// RGBW 到 RGB 的轉換函數
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

// 從 RGBW 數據獲取顏色
export function getColorFromRGBW(rgbwData, pxldId) {
  if (!rgbwData || rgbwData.length === 0) return null;
  
  const offset = pxldId * 4;
  if (offset + 3 >= rgbwData.length) return null;
  
  const r = rgbwData[offset];
  const g = rgbwData[offset + 1];
  const b = rgbwData[offset + 2];
  const w = rgbwData[offset + 3];
  
  const color = rgbwToRgb(r, g, b, w);
  return `rgb(${color.r},${color.g},${color.b})`;
}

// 初始化畫布
export function initCanvas(canvasId = 'main-canvas') {
  const canvas = document.getElementById(canvasId);
  if (!canvas) {
    console.error(`[Canvas] 找不到畫布元素: #${canvasId}`);
    return false;
  }
  
  // 設置 DPR (Device Pixel Ratio)
  const dpr = window.devicePixelRatio || 1;
  
  // 保存到全局狀態
  ST.canvas = canvas;
  ST.ctx = canvas.getContext('2d');
  ST.dpr = dpr;
  
  // 設置 DOM 引用
  DOM.board = canvas;
  DOM.ctx = ST.ctx;
  
  console.log('[Canvas] 畫布初始化成功');
  return true;
}

// 調整畫布大小
export function resizeCanvas() {
  if (!ST.canvas || !ST.ctx) {
    console.warn("[Canvas] 畫布未初始化，無法調整大小");
    return;
  }
  
  let w, h;
  
  if (ST.mode === "board" || ST.isAllSlavesMode) {
    // 總畫板模式或板模式
    w = ST.grid_w * ST.cell;
    h = ST.grid_h * ST.cell;
  } else {
    // 單個 slave 模式
    const wh = ST.wh[ST.activeSlave] || { w: 20, h: 20 };
    w = wh.w * ST.cell;
    h = wh.h * ST.cell;
  }
  
  // 設置畫布尺寸
  const canvas = ST.canvas;
  canvas.style.width = `${w}px`;
  canvas.style.height = `${h}px`;
  canvas.width = w * ST.dpr;
  canvas.height = h * ST.dpr;
  
  // 重置變換
  ST.ctx.setTransform(ST.dpr, 0, 0, ST.dpr, 0, 0);
  ST.ctx.imageSmoothingEnabled = false;
  
  console.log(`[Canvas] 調整大小完成: ${w}x${h} (DPR: ${ST.dpr})`);
}

// 繪製背景
export function drawBackground() {
  if (!ST.ctx) return;
  
  ST.ctx.fillStyle = "#0f1419";
  ST.ctx.fillRect(0, 0, ST.canvas.width / ST.dpr, ST.canvas.height / ST.dpr);
}

// 繪製網格
export function drawGrid(cols, rows) {
  if (!ST.showGrid || !ST.ctx) return;
  
  ST.ctx.strokeStyle = "rgba(255,255,255,0.12)";
  ST.ctx.lineWidth = 0.5;
  
  // 繪製垂直線
  for (let x = 0; x <= cols; x++) {
    ST.ctx.beginPath();
    ST.ctx.moveTo(x * ST.cell + 0.5, 0);
    ST.ctx.lineTo(x * ST.cell + 0.5, rows * ST.cell);
    ST.ctx.stroke();
  }
  
  // 繪製水平線
  for (let y = 0; y <= rows; y++) {
    ST.ctx.beginPath();
    ST.ctx.moveTo(0, y * ST.cell + 0.5);
    ST.ctx.lineTo(cols * ST.cell, y * ST.cell + 0.5);
    ST.ctx.stroke();
  }
}

// 繪製單個 slave 在總畫板上的 LED
export function drawSlaveLEDsOnBoard(sid, ox, oy, w, h) {
  if (!ST.ctx) return;
  
  const rgbwData = ST.allSlavesRGBW[sid];
  if (!rgbwData || rgbwData.length === 0) return;
  
  const m = ST.maps[sid] || {};
  const hasMapping = Object.keys(m).length > 0;
  
  if (hasMapping) {
    // 有 mapping 配置：按照 mapping 繪製
    for (const key in m) {
      const [lx, ly] = key.split(",").map(n => parseInt(n, 10));
      const pxldId = m[key].pxld_id;
      
      if (lx >= 0 && lx < w && ly >= 0 && ly < h) {
        const color = getColorFromRGBW(rgbwData, pxldId);
        if (color) {
          ST.ctx.fillStyle = color;
          ST.ctx.fillRect(
            (ox + lx) * ST.cell, 
            (oy + ly) * ST.cell, 
            ST.cell, 
            ST.cell
          );
        }
      }
    }
  } else {
    // 無 mapping 配置：按照順序繪製
    for (let i = 0; i < w * h && i * 4 < rgbwData.length; i++) {
      const lx = i % w;
      const ly = Math.floor(i / w);
      const color = getColorFromRGBW(rgbwData, i);
      
      if (color) {
        ST.ctx.fillStyle = color;
        ST.ctx.fillRect(
          (ox + lx) * ST.cell, 
          (oy + ly) * ST.cell, 
          ST.cell, 
          ST.cell
        );
      }
    }
  }
}

// 繪製總畫板上的所有 slave
export function drawSlaveRectsOnBoard() {
  if (!ST.ctx) return;
  
  // 先繪製所有 slave 的 LED 顏色
  for (const s of ST.slaves) {
    const sid = s.slave_id;
    const layout = ST.layout[sid] || { ox: 0, oy: 0 };
    const wh = ST.wh[sid] || { w: 1, h: 1 };
    
    drawSlaveLEDsOnBoard(sid, layout.ox, layout.oy, wh.w, wh.h);
  }
  
  // 再繪製邊框和標籤
  for (const s of ST.slaves) {
    const sid = s.slave_id;
    const layout = ST.layout[sid] || { ox: 0, oy: 0 };
    const wh = ST.wh[sid] || { w: 1, h: 1 };
    
    // 繪製邊框
    ST.ctx.strokeStyle = "rgba(99,179,237,0.7)";
    ST.ctx.lineWidth = 1;
    ST.ctx.strokeRect(
      layout.ox * ST.cell + 0.5, 
      layout.oy * ST.cell + 0.5, 
      wh.w * ST.cell, 
      wh.h * ST.cell
    );
    
    // 繪製 slave ID 標籤
    ST.ctx.fillStyle = "rgba(255,255,255,0.9)";
    ST.ctx.font = "10px monospace";
    ST.ctx.fillText(`S${sid}`, layout.ox * ST.cell + 3, layout.oy * ST.cell + 12);
  }
}

// 繪製單個 slave 的幀
export function drawSlaveFrame(sid) {
  if (!ST.ctx) return;
  
  const rgbw = ST.rgbw[sid];
  if (!rgbw) return;
  
  const { w, h } = ST.wh[sid] || { w: 1, h: 1 };
  const m = ST.maps[sid] || {};
  const hasMapping = Object.keys(m).length > 0;
  
  if (hasMapping) {
    // 有 mapping 配置
    for (const key in m) {
      const [lx, ly] = key.split(",").map(n => parseInt(n, 10));
      const pxldId = m[key].pxld_id;
      
      if (lx >= 0 && lx < w && ly >= 0 && ly < h) {
        const color = getColorFromRGBW(rgbw, pxldId);
        if (color) {
          ST.ctx.fillStyle = color;
          ST.ctx.fillRect(lx * ST.cell, ly * ST.cell, ST.cell, ST.cell);
        }
      }
    }
  } else {
    // 無 mapping 配置
    for (let i = 0; i < w * h && i * 4 < rgbw.length; i++) {
      const lx = i % w;
      const ly = Math.floor(i / w);
      const color = getColorFromRGBW(rgbw, i);
      
      if (color) {
        ST.ctx.fillStyle = color;
        ST.ctx.fillRect(lx * ST.cell, ly * ST.cell, ST.cell, ST.cell);
      }
    }
  }
}

// 繪製選中的格子
export function drawPicked() {
  if (!ST.picked || !ST.ctx) return;
  
  ST.ctx.strokeStyle = "rgba(245,158,11,0.95)";
  ST.ctx.lineWidth = 2;
  
  let x, y;
  
  if (ST.mode === "board" || ST.isAllSlavesMode) {
    // 總畫板模式
    x = ST.picked.gx * ST.cell;
    y = ST.picked.gy * ST.cell;
  } else {
    // 單個 slave 模式
    x = ST.picked.lx * ST.cell;
    y = ST.picked.ly * ST.cell;
  }
  
  ST.ctx.strokeRect(x + 0.5, y + 0.5, ST.cell, ST.cell);
  
  // 繪製選中資訊
  if (ST.picked.pxld_id !== undefined) {
    ST.ctx.fillStyle = "rgba(0,0,0,0.7)";
    ST.ctx.fillRect(x + 2, y + 2, 80, 30);
    
    ST.ctx.fillStyle = "rgba(255,255,255,0.9)";
    ST.ctx.font = "10px monospace";
    ST.ctx.fillText(`pxld: ${ST.picked.pxld_id}`, x + 5, y + 15);
    ST.ctx.fillText(`mcu: ${ST.picked.mcu_id}`, x + 5, y + 28);
  }
}

// 繪製 HUD 資訊
export function drawHUD() {
  if (!ST.ctx) return;
  
  ST.ctx.fillStyle = "rgba(0,0,0,0.65)";
  ST.ctx.fillRect(4, 4, 340, 46);
  
  ST.ctx.fillStyle = "rgba(255,255,255,0.95)";
  ST.ctx.font = "10px monospace";
  
  const mode = ST.isAllSlavesMode ? "board (all slaves)" : ST.mode;
  const sid = ST.activeSlave;
  
  const gridStr = (ST.isAllSlavesMode || ST.mode === "board") 
    ? `${ST.grid_w}x${ST.grid_h}` 
    : `${ST.wh[sid]?.w || 1}x${ST.wh[sid]?.h || 1}`;
  
  // 第一行：模式、slave、幀、FPS
  ST.ctx.fillText(
    `mode=${mode} slave=${sid} frame=${ST.frame}/${Math.max(0, ST.totalFrames - 1)}`, 
    8, 18
  );
  
  // 第二行：網格尺寸、單元格尺寸
  ST.ctx.fillText(
    `grid=${gridStr} cell=${ST.cell}px slaves=${ST.slaves?.length || 0}`, 
    8, 34
  );
}

// 繪製總畫板模式下的額外資訊
export function drawBoardInfo() {
  if ((!ST.isAllSlavesMode && ST.mode !== "board") || !ST.ctx) return;
  
  const canvasWidth = ST.canvas.width / ST.dpr;
  
  // 繪製統計資訊
  ST.ctx.fillStyle = "rgba(0,0,0,0.65)";
  ST.ctx.fillRect(canvasWidth - 144, 4, 140, 34);
  
  ST.ctx.fillStyle = "rgba(255,255,255,0.95)";
  ST.ctx.font = "10px monospace";
  ST.ctx.textAlign = "right";
  
  // 顯示活動 slave 數
  const activeSlaves = Object.keys(ST.allSlavesRGBW).length;
  ST.ctx.fillText(
    `active slaves: ${activeSlaves}`,
    canvasWidth - 8,
    18
  );
  
  // 顯示總像素數
  let totalPixels = 0;
  for (const sid in ST.allSlavesRGBW) {
    const data = ST.allSlavesRGBW[sid];
    if (data) {
      totalPixels += Math.floor(data.length / 4);
    }
  }
  
  ST.ctx.fillText(
    `total pixels: ${totalPixels}`,
    canvasWidth - 8,
    34
  );
  
  ST.ctx.textAlign = "left";
}

// 主重繪函數
export function redraw() {
  if (!ST.canvas || !ST.ctx) {
    console.warn("[Canvas] 畫布未初始化");
    return;
  }
  
  console.log("[Canvas] 開始重繪");
  
  try {
    // 調整畫布大小
    resizeCanvas();
    
    // 清空畫布
    ST.ctx.clearRect(0, 0, ST.canvas.width / ST.dpr, ST.canvas.height / ST.dpr);
    
    // 繪製背景
    drawBackground();
    
    // 判斷繪製模式
    if (ST.isAllSlavesMode || ST.mode === "board") {
      // 總畫板模式
      console.log("[Canvas] 繪製總畫板模式");
      drawSlaveRectsOnBoard();
      drawGrid(ST.grid_w, ST.grid_h);
      drawBoardInfo();
    } else {
      // 單個 slave 模式
      console.log("[Canvas] 繪製單個 slave 模式");
      const { w, h } = ST.wh[ST.activeSlave] || { w: 1, h: 1 };
      drawSlaveFrame(ST.activeSlave);
      drawGrid(w, h);
    }
    
    // 繪製選中的格子和 HUD
    drawPicked();
    drawHUD();
    
    console.log("[Canvas] 重繪完成");
  } catch (error) {
    console.error("[Canvas] 重繪錯誤:", error);
  }
}

// 輔助函數：繪製格子邊框
export function drawCellBorder(x, y, color = "rgba(255,255,255,0.3)") {
  if (!ST.ctx) return;
  
  ST.ctx.strokeStyle = color;
  ST.ctx.lineWidth = 1;
  ST.ctx.strokeRect(x * ST.cell + 0.5, y * ST.cell + 0.5, ST.cell, ST.cell);
}

// 輔助函數：繪製格子填充
export function drawCellFill(x, y, color = "rgba(255,255,255,0.1)") {
  if (!ST.ctx) return;
  
  ST.ctx.fillStyle = color;
  ST.ctx.fillRect(x * ST.cell, y * ST.cell, ST.cell, ST.cell);
}

// 檢查畫布是否已初始化
export function isCanvasInitialized() {
  return !!(ST.canvas && ST.ctx);
}