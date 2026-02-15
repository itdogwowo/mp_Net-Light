// static/netlight/js/mapping.js - 修正版本
console.log('🚀 開始加載模塊化版本');

// 創建一個簡單的消息顯示函數，用於模塊加載錯誤時
function showError(message) {
    const msgEl = document.getElementById('msg');
    if (msgEl) {
        msgEl.textContent = message;
        msgEl.style.color = '#dc2626';
    }
    console.error(message);
}

function showInfo(message) {
    const msgEl = document.getElementById('msg');
    if (msgEl) {
        msgEl.textContent = message;
        msgEl.style.color = '#6b7280';
    }
    console.log(message);
}

async function loadModules() {
  try {
    // 顯示初始消息
    showInfo('⏳ 正在加載模塊...');
    
    // 1. 加載 core.js
    const core = await import('./mapping/core.js');
    console.log('✅ core.js 加載成功');
    
    // 2. 初始化 DOM
    core.initDOM();
    // 注意：現在 core 模塊已經加載，使用 core.showMessage
    core.showMessage('⏳ 正在加載其他模塊...', 'info');
    
    // 3. 加載 canvas.js
    const canvas = await import('./mapping/canvas.js');
    console.log('✅ canvas.js 加載成功');
    
    // 4. 加載 mapping.js (業務邏輯)
    const mapping = await import('./mapping/mapping.js');
    console.log('✅ mapping.js (業務邏輯) 加載成功');
    
    // 5. 加載 websocket.js
    const websocket = await import('./mapping/websocket.js');
    console.log('✅ websocket.js 加載成功');
    
    // 6. 加載 ui.js
    const ui = await import('./mapping/ui.js');
    console.log('✅ ui.js 加載成功');
    
    // 所有模塊加載成功，開始初始化
    core.showMessage('✅ 模塊加載完成，正在初始化...', 'success');
    
    // 初始化 WebSocket 播放器和 UI
    const wsPlayer = new websocket.WebSocketPlayer();
    const uiHandler = new ui.UIHandler(wsPlayer);
    
    // 啟動主要初始化流程
    await bootstrap(core, canvas, mapping, websocket, ui, wsPlayer);
    
  } catch (error) {
    console.error('❌ 模塊加載失敗:', error);
    
    // 使用我們自己定義的 showError 函數
    showError(`❌ 模塊加載失敗: ${error.message}`);
    
    // 回退到單文件版本
    loadFallbackVersion();
  }
}

function loadFallbackVersion() {
  console.log('🔄 嘗試加載備用版本...');
  
  const script = document.createElement('script');
  script.src = '/static/netlight/js/mapping-single.js';
  script.onload = () => {
    console.log('✅ 備用版本加載成功');
    showInfo('✅ 使用備用版本啟動...');
  };
  script.onerror = () => {
    console.error('❌ 備用版本也加載失敗');
    showError('❌ 所有版本加載失敗，請刷新頁面');
  };
  document.head.appendChild(script);
}

async function bootstrap(core, canvas, mapping, websocket, ui, wsPlayer) {
  try {
    const { ST, DOM, showMessage, jget, autoWH } = core;
    const { loadMapping, loadAllSlavesRGBW, checkAndAutoArrange, updateSaveButtonText, autoArrangeLayout } = mapping;
    const { redraw } = canvas;
    
    showMessage("⏳ 載入 PXLD...", "info");
    
    const name = DOM.pxldNameEl.value;
    
    // 載入 PXLD 信息
    const info = await jget(`/light/api/pxld/info/?name=${encodeURIComponent(name)}`);
    if (!info.ok) { 
      showMessage(`❌ 失敗：${info.err}`, 'error');
      return; 
    }
    
    ST.fps = info.info.fps;
    ST.totalFrames = info.info.total_frames;
    
    DOM.frameSlider.max = String(Math.max(0, ST.totalFrames - 1));
    DOM.frameSlider.value = "0";
    DOM.frameInfo.textContent = `frame: 0`;
    
    // 載入 slave 列表
    const sres = await jget(`/light/api/pxld/slaves/?name=${encodeURIComponent(name)}`);
    if (!sres.ok) { 
      showMessage(`❌ 失敗：${sres.err}`, 'error');
      return; 
    }
    
    ST.slaves = sres.slaves;
    
    // 載入所有 slave 的 mapping
    const mappingPromises = [];
    for (const s of ST.slaves) {
      const slaveId = s.slave_id;
      const pixelCount = s.pixel_count;
      
      ST.wh[slaveId] = autoWH(pixelCount);
      ST.layout[slaveId] = { ox: 0, oy: 0 };
      
      mappingPromises.push(loadMapping(slaveId, pixelCount));
    }
    
    await Promise.all(mappingPromises);
    await loadAllSlavesRGBW(0);
    
    // 檢查是否需要自動排列
    checkAndAutoArrange();
    
    // 更新 UI
    updateSlaveSelect(ST, DOM);
    updateSaveButtonText();
    ST.activeSlave = -1;
    ST.mode = "board";
    DOM.slaveSelect.value = "-1";
    
    // 添加自動排列按鈕
    createAutoArrangeButton(autoArrangeLayout, redraw);
    
    // 預先連接 WebSocket
    showMessage("正在建立 WebSocket 連接...", "info");
    wsPlayer.connect('playback');
    
    setTimeout(async () => {
      if (wsPlayer.connected) {
        const initialized = await wsPlayer.initPlayback(name, -1);
        if (initialized) {
          showMessage(`✅ WebSocket 播放器就緒！可進行 ${ST.fps}fps 流暢播放`, 'success');
        }
      } else {
        showMessage(`⚠️ WebSocket 連接失敗，將使用較慢的 HTTP 模式`, 'warning');
      }
    }, 2000);
    
    showMessage(`✅ 完成！載入 ${ST.slaves.length} 個 slave`, 'success');
    redraw();
    
  } catch (error) {
    console.error('初始化錯誤:', error);
    showMessage(`❌ 初始化失敗: ${error.message}`, 'error');
  }
}

function updateSlaveSelect(ST, DOM) {
  DOM.slaveSelect.innerHTML = "";
  const o0 = document.createElement("option");
  o0.value = "-1";
  o0.textContent = "總畫板";
  DOM.slaveSelect.appendChild(o0);
  
  for (const s of ST.slaves) {
    const opt = document.createElement("option");
    opt.value = String(s.slave_id);
    const { w, h } = ST.wh[s.slave_id];
    const layout = ST.layout[s.slave_id] || { ox: 0, oy: 0 };
    opt.textContent = `Slave ${s.slave_id} (${s.pixel_count} LED, ${w}x${h} @ ${layout.ox},${layout.oy})`;
    DOM.slaveSelect.appendChild(opt);
  }
}

function createAutoArrangeButton(autoArrangeLayout, redraw) {
  const controlPanel = document.querySelector('[style*="flex: 0 0 360px"]');
  if (!controlPanel) return;
  
  const autoArrangeBtn = document.createElement('button');
  autoArrangeBtn.id = 'autoArrangeBtn';
  autoArrangeBtn.className = 'btn';
  autoArrangeBtn.textContent = '🔄 自動排列佈局';
  autoArrangeBtn.style.marginTop = '8px';
  autoArrangeBtn.style.background = '#d97706';
  autoArrangeBtn.style.width = '100%';
  
  autoArrangeBtn.addEventListener('click', () => {
    if (confirm("確定要自動排列所有 slave 的佈局嗎？這將重新計算所有 slave 的位置。")) {
      // 需要從模塊獲取 showMessage，這裡我們直接使用全局的 DOM
      const msgEl = document.getElementById('msg');
      if (msgEl) {
        msgEl.textContent = '⏳ 正在自動排列佈局...';
        msgEl.style.color = '#6b7280';
      }
      
      autoArrangeLayout();
      redraw();
      
      setTimeout(() => {
        if (msgEl) {
          msgEl.textContent = '✅ 已自動排列佈局';
          msgEl.style.color = '#059669';
        }
      }, 500);
    }
  });
  
  const saveBtn = document.getElementById('saveBtn');
  if (saveBtn) {
    saveBtn.parentNode.insertBefore(autoArrangeBtn, saveBtn);
  } else {
    controlPanel.appendChild(autoArrangeBtn);
  }
}

// 開始加載模塊
document.addEventListener('DOMContentLoaded', () => {
  console.log('📄 DOM 已加載，開始加載模塊');
  loadModules();
});