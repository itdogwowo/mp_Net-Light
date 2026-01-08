// static/netlight/js/mapping/mapping.js
import { ST, DOM, FRAME_CACHE, showMessage, loadSlaveMapping, saveSlaveMapping, fetchAPI, b64ToU8 } from './core.js';
import { initCanvas, redraw } from './canvas.js';
import { initUI, handleCanvasClick } from './ui.js';
import { WebSocketPlayer } from './websocket.js';

// 初始化 WebSocket 播放器
export const player = new WebSocketPlayer();

// 載入所有模組
export async function loadModules() {
  console.log("[Mapping] 開始載入模組");
  
  try {
    // 1. 初始化畫布（必須在 DOM 完全載入後）
    if (!document.getElementById('main-canvas')) {
      console.warn("[Mapping] 畫布元素尚未存在，等待 DOM 載入");
      // 等待 DOM 載入
      await new Promise(resolve => {
        if (document.readyState === 'loading') {
          document.addEventListener('DOMContentLoaded', resolve);
        } else {
          resolve();
        }
      });
    }
    
    // 初始化畫布
    if (!initCanvas('main-canvas')) {
      console.error("[Mapping] 畫布初始化失敗");
      return;
    }
    
    // 2. 初始化 UI
    initUI();
    
    // 3. 載入配置和數據
    await loadInitialData();
    
    console.log("[Mapping] 所有模組載入完成");
    return true;
  } catch (error) {
    console.error("[Mapping] 載入模組錯誤:", error);
    showMessage(`❌ 載入模組錯誤: ${error.message}`, "error");
    return false;
  }
}

// 載入初始數據
async function loadInitialData() {
  console.log("[Mapping] 開始載入初始數據");
  
  try {
    // 1. 獲取 PXLD 信息
    const pxldInfo = await fetchAPI('/light/api/pxld/info/?name=show.pxld');
    if (pxldInfo.ok) {
      ST.totalFrames = pxldInfo.info.total_frames || 0;
      ST.fps = pxldInfo.info.fps || 30;
      console.log(`[Mapping] PXLD 信息: ${ST.totalFrames} 幀, ${ST.fps} FPS`);
    }
    
    // 2. 獲取 slave 列表
    const slavesData = await fetchAPI('/light/api/pxld/slaves/?name=show.pxld');
    if (slavesData.ok) {
      ST.slaves = slavesData.slaves || [];
      console.log(`[Mapping] 載入 ${ST.slaves.length} 個 slave`);
      
      // 初始化 slave 數據結構
      ST.rgbw = {};
      ST.allSlavesRGBW = {};
      ST.wh = {};
      ST.maps = {};
      ST.layout = {};
      
      // 為每個 slave 載入配置
      for (const slave of ST.slaves) {
        const slaveId = slave.slave_id;
        
        // 載入 mapping 配置
        const mappingData = await fetchAPI(`/light/api/mapping/get/?slave_id=${slaveId}`);
        if (mappingData.ok && mappingData.data) {
          const data = mappingData.data;
          ST.wh[slaveId] = { w: data.w || 1, h: data.h || 1 };
          ST.layout[slaveId] = { ox: data.ox || 0, oy: data.oy || 0 };
          
          // 建立 mapping 查詢表
          const map = {};
          if (data.map && Array.isArray(data.map)) {
            data.map.forEach(item => {
              const key = `${item.x},${item.y}`;
              map[key] = {
                pxld_id: item.pxld_id || 0,
                mcu_id: item.mcu_id || 0
              };
            });
          }
          ST.maps[slaveId] = map;
          
          console.log(`[Mapping] Slave ${slaveId} 配置載入: ${data.w}x${data.h}`);
        } else {
          // 使用默認配置
          ST.wh[slaveId] = { w: 20, h: 20 };
          ST.layout[slaveId] = { ox: 0, oy: 0 };
          ST.maps[slaveId] = {};
          console.log(`[Mapping] Slave ${slaveId} 使用默認配置`);
        }
      }
    }
    
    // 3. 載入布局配置
    const layoutData = await fetchAPI('/light/api/layout/get/');
    if (layoutData.ok && layoutData.data && layoutData.data.layout) {
      layoutData.data.layout.forEach(item => {
        if (ST.layout[item.slave_id]) {
          ST.layout[item.slave_id].ox = item.ox || 0;
          ST.layout[item.slave_id].oy = item.oy || 0;
        }
      });
      console.log("[Mapping] 布局配置載入完成");
    }
    
    // 4. 計算總畫板尺寸
    calculateBoardDimensions();
    
    // 5. 初始化選中的 slave
    if (ST.slaves.length > 0) {
      ST.activeSlave = ST.slaves[0].slave_id;
      console.log(`[Mapping] 初始選中 slave: ${ST.activeSlave}`);
    }
    
    // 6. 初始化幀緩存
    FRAME_CACHE.clear();
    
    console.log("[Mapping] 初始數據載入完成");
  } catch (error) {
    console.error("[Mapping] 載入初始數據錯誤:", error);
    throw error;
  }
}

// 計算總畫板尺寸
function calculateBoardDimensions() {
  let maxX = 0;
  let maxY = 0;
  
  for (const slave of ST.slaves) {
    const sid = slave.slave_id;
    const layout = ST.layout[sid] || { ox: 0, oy: 0 };
    const wh = ST.wh[sid] || { w: 1, h: 1 };
    
    maxX = Math.max(maxX, layout.ox + wh.w);
    maxY = Math.max(maxY, layout.oy + wh.h);
  }
  
  // 添加邊距
  ST.grid_w = Math.max(50, maxX + 5);
  ST.grid_h = Math.max(30, maxY + 5);
  
  console.log(`[Mapping] 總畫板尺寸: ${ST.grid_w}x${ST.grid_h}`);
}

// 啟動函數
export async function bootstrap() {
  console.log("[Mapping] 啟動系統");
  
  try {
    // 1. 載入模組
    const modulesLoaded = await loadModules();
    if (!modulesLoaded) {
      showMessage("❌ 模組載入失敗", "error");
      return;
    }
    
    // 2. 初始重繪（確保畫布已初始化）
    if (ST.canvas && ST.ctx) {
      redraw();
    } else {
      console.error("[Mapping] 畫布未初始化，無法重繪");
      showMessage("❌ 畫布初始化失敗", "error");
      return;
    }
    
    // 3. 綁定事件監聽器
    bindEventListeners();
    
    // 4. 設置默認狀態
    ST.mode = "board";
    ST.isAllSlavesMode = true;
    ST.cell = 20;
    ST.showGrid = true;
    
    // 5. 連接 WebSocket
    player.connect('playback');
    
    console.log("[Mapping] 系統啟動完成");
    showMessage("✅ 系統啟動完成", "success");
  } catch (error) {
    console.error("[Mapping] 啟動錯誤:", error);
    showMessage(`❌ 啟動錯誤: ${error.message}`, "error");
  }
}

// 綁定事件監聽器
function bindEventListeners() {
  console.log("[Mapping] 綁定事件監聽器");
  
  // 畫布點擊事件
  if (ST.canvas) {
    ST.canvas.addEventListener('click', handleCanvasClick);
  }
  
  // 窗口大小變化事件
  window.addEventListener('resize', () => {
    setTimeout(redraw, 100);
  });
  
  // 鍵盤事件
  document.addEventListener('keydown', handleKeyDown);
}

// 處理鍵盤事件
function handleKeyDown(event) {
  switch (event.key) {
    case ' ':
      // 空格鍵切換播放/暫停
      if (player.playing) {
        player.pause();
      } else {
        player.play();
      }
      break;
      
    case 'ArrowLeft':
      // 左箭頭：上一幀
      if (player.currentFrame > 0) {
        player.seek(player.currentFrame - 1);
      }
      break;
      
    case 'ArrowRight':
      // 右箭頭：下一幀
      if (player.currentFrame < player.totalFrames - 1) {
        player.seek(player.currentFrame + 1);
      }
      break;
      
    case 'g':
      // G 鍵切換網格顯示
      ST.showGrid = !ST.showGrid;
      redraw();
      break;
      
    case '+':
    case '=':
      // 增加單元格大小
      if (ST.cell < 50) {
        ST.cell += 2;
        redraw();
      }
      break;
      
    case '-':
      // 減少單元格大小
      if (ST.cell > 8) {
        ST.cell -= 2;
        redraw();
      }
      break;
  }
}

// 切換模式
export function toggleMode() {
  if (ST.mode === "board") {
    ST.mode = "single";
    ST.isAllSlavesMode = false;
  } else {
    ST.mode = "board";
    ST.isAllSlavesMode = true;
  }
  
  redraw();
  console.log(`[Mapping] 切換模式: ${ST.mode}`);
}

// 切換 slave
export function switchSlave(slaveId) {
  if (ST.wh[slaveId]) {
    ST.activeSlave = slaveId;
    redraw();
    console.log(`[Mapping] 切換到 slave: ${slaveId}`);
  }
}

// 初始化播放器
export async function initPlayback(filename = 'show.pxld', slaveId = -1) {
  try {
    const success = await player.initPlayback(filename, slaveId);
    if (success) {
      showMessage("✅ 播放器初始化成功", "success");
      return true;
    }
  } catch (error) {
    console.error("[Mapping] 初始化播放器錯誤:", error);
    showMessage(`❌ 初始化播放器錯誤: ${error.message}`, "error");
  }
  return false;
}

// 導出其他函數
export { player };