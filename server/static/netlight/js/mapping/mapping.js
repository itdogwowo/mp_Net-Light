// static/netlight/js/mapping/mapping.js
import { 
  ST, DOM, showMessage, keyXY, jget, jpost, 
  defaultPxldId, autoWH, b64ToU8, FRAME_CACHE 
} from './core.js';  // 添加了 b64ToU8 和 FRAME_CACHE

import { redraw } from './canvas.js';

export async function loadMapping(slaveId, pixelCount = 0) {
  try {
    const name = DOM.pxldNameEl.value;
    const url = `/light/api/mapping/get/?slave_id=${slaveId}&name=${encodeURIComponent(name)}`;
    const res = await jget(url);
    
    if (res.ok && res.data) {
      ST.maps[slaveId] = {};
      
      if (res.data.w && res.data.h) {
        ST.wh[slaveId] = { 
          w: res.data.w | 0, 
          h: res.data.h | 0 
        };
      } else if (pixelCount > 0) {
        ST.wh[slaveId] = autoWH(pixelCount);
      }
      
      ST.layout[slaveId] = { 
        ox: (res.data.ox !== undefined) ? (res.data.ox | 0) : 0,
        oy: (res.data.oy !== undefined) ? (res.data.oy | 0) : 0
      };
      
      if (res.data.map && Array.isArray(res.data.map)) {
        res.data.map.forEach(it => {
          const key = keyXY(it.x, it.y);
          ST.maps[slaveId][key] = {
            pxld_id: it.pxld_id,
            mcu_id: it.mcu_id
          };
        });
        
        console.log(`✅ Slave ${slaveId}: 載入 ${res.data.map.length} 個 mapping 點`);
        return true;
      } else {
        console.log(`ℹ️ Slave ${slaveId}: 無 mapping 數據，將使用默認`);
        return true;
      }
    } else {
      console.error(`❌ Slave ${slaveId}: 載入失敗`, res.err);
      return false;
    }
  } catch (error) {
    console.error(`❌ Slave ${slaveId}: 載入異常`, error);
    return false;
  }
}

export async function loadSlaveRGBW(frame, slaveId) {
  const key = `${slaveId}_${frame}`;
  if (FRAME_CACHE.has(key)) {
    ST.rgbw[slaveId] = FRAME_CACHE.get(key);
    return;
  }

  const name = DOM.pxldNameEl.value;
  const url = `/light/api/pxld/slave_frame_rgbw?name=${encodeURIComponent(name)}&frame=${frame}&slave_id=${slaveId}`;
  const res = await jget(url);
  if (res.ok) {
    const bytes = b64ToU8(res.b64);
    FRAME_CACHE.set(key, bytes);
    ST.rgbw[slaveId] = bytes;
  }
}

export async function loadAllSlavesRGBW(frame) {
  const name = DOM.pxldNameEl.value;
  const url = `/light/api/pxld/all_slaves_rgbw?name=${encodeURIComponent(name)}&frame=${frame}`;
  const res = await jget(url);
  
  if (res.ok && res.data) {
    for (const slaveData of res.data) {
      const sid = slaveData.slave_id;
      ST.allSlavesRGBW[sid] = b64ToU8(slaveData.rgbw_b64);
    }
    return true;
  }
  return false;
}

export async function saveOneSlave(sid) {
  const { w, h } = ST.wh[sid] || { w: 1, h: 1 };
  const layout = ST.layout[sid] || { ox: 0, oy: 0 };
  const m = ST.maps[sid] || {};
  const arr = [];
  
  // 檢查 mcu_id 唯一性（-1 除外）
  const mcuIds = new Set();
  for (const k in m) {
    const mcuId = m[k].mcu_id;
    if (mcuId !== -1) {
      if (mcuIds.has(mcuId)) {
        throw new Error(`mcu_id ${mcuId} 重複！每個 mcu_id（除 -1 外）必須唯一`);
      }
      mcuIds.add(mcuId);
    }
  }
  
  // 轉換 mapping 數據
  for (const k in m) {
    const [x, y] = k.split(",").map(n => parseInt(n, 10));
    arr.push({ 
      x, y, 
      pxld_id: m[k].pxld_id, 
      mcu_id: m[k].mcu_id 
    });
  }
  
  // 如果 mapping 是空的，使用默認值
  if (arr.length === 0) {
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const pxld_id = y * w + x;
        arr.push({ 
          x, y, 
          pxld_id: pxld_id, 
          mcu_id: pxld_id 
        });
      }
    }
  }
  
  return {
    version: 2,
    slave_id: sid,
    ox: layout.ox,
    oy: layout.oy,
    w,
    h,
    map: arr
  };
}

export function updateSaveButtonText() {
  const saveBtn = document.getElementById("saveBtn");
  const sid = ST.activeSlave;
  
  if (sid === -1) {
    saveBtn.textContent = `💾 保存所有 (${ST.slaves.length}個 slave)`;
    saveBtn.style.background = "#1e40af";
  } else {
    saveBtn.textContent = "💾 保存（此 slave）";
    saveBtn.style.background = "#111827";
  }
}

// 自動排列布局函數
export function autoArrangeLayout() {
  console.log("開始自動排列布局...");
  
  let currentX = 0;
  let currentY = 0;
  let maxRowHeight = 0;
  const spacing = 2;
  
  // 按 slave_id 排序
  const sortedSlaves = [...ST.slaves].sort((a, b) => a.slave_id - b.slave_id);
  
  for (const s of sortedSlaves) {
    const sid = s.slave_id;
    const { w, h } = ST.wh[sid] || { w: 1, h: 1 };
    
    // 檢查是否會超出畫布寬度
    if (currentX + w > ST.grid_w) {
      currentX = 0;
      currentY += maxRowHeight + spacing;
      maxRowHeight = 0;
    }
    
    // 設置位置
    ST.layout[sid] = { ox: currentX, oy: currentY };
    
    // 更新當前位置和最大行高
    currentX += w + spacing;
    maxRowHeight = Math.max(maxRowHeight, h);
  }
  
  console.log("自動排列完成");
  return true;
}

// 檢查是否需要自動排列
export function checkAndAutoArrange() {
  const overlappingSlaves = [];
  for (const s of ST.slaves) {
    const sid = s.slave_id;
    const layout = ST.layout[sid] || { ox: 0, oy: 0 };
    if (layout.ox === 0 && layout.oy === 0) {
      overlappingSlaves.push(sid);
    }
  }
  
  if (overlappingSlaves.length > 1) {
    console.log(`發現 ${overlappingSlaves.length} 個 slave 重疊在 (0,0)`);
    
    setTimeout(() => {
      if (confirm(`發現 ${overlappingSlaves.length} 個 slave 重疊在 (0,0)，是否要自動排列布局？`)) {
        autoArrangeLayout();
        redraw();
        showMessage("✅ 已自動排列布局", "success");
      }
    }, 500);
    
    return true;
  }
  return false;
}