// static/netlight/js/mapping/monitor.js - WebSocket Monitor 專用邏輯
import { 
  b64ToU8, 
  formatTimestamp, 
  calcPixelCount, 
  calcAvgBrightness, 
  generateUniqueId,
  LOG_COLORS 
} from './core.js';

/**
 * WebSocket Monitor 管理器
 */
export class WebSocketMonitor {
  constructor() {
    this.ws = null;
    this.connected = false;
    this.mode = 'monitor';
    this.logPaused = false;
    this.lastFrameData = null;
    
    this.stats = {
      received: 0,
      sent: 0,
      errors: 0,
      frameData: 0,
      connectTime: null,
      lastFrameTime: 0,
      frameTimes: [],
      clients: new Set()
    };
    
    this.filters = {};
    this.dom = {};
  }
  
  /**
   * 初始化 DOM 引用
   */
  initDOM(elements) {
    this.dom = elements;
    
    // 初始化過濾器
    this.filters = {
      connection: elements.filterConnection,
      clientMsg: elements.filterClientMsg,
      frameData: elements.filterFrameData,
      frameDataAll: elements.filterFrameDataAll,
      playback: elements.filterPlayback,
      errors: elements.filterErrors,
      autoScroll: elements.autoScroll,
      showDetails: elements.showDetails
    };
  }
  
  /**
   * 連接到 WebSocket
   */
  connect(url) {
    console.log(`[Monitor] 嘗試連接: ${url} (模式: ${this.mode})`);
    
    try {
      this.ws = new WebSocket(url);
      
      this.ws.onopen = () => {
        this.connected = true;
        this.stats.connectTime = Date.now();
        this.updateConnectionStatus(true);
        this.log('WebSocket 連接成功', 'success');
      };
      
      this.ws.onmessage = (event) => {
        this.handleMessage(event);
      };
      
      this.ws.onclose = (event) => {
        this.connected = false;
        this.stats.connectTime = null;
        this.stats.frameTimes = [];
        this.updateConnectionStatus(false);
        this.log(`連接關閉 (code: ${event.code})`, 'warning');
      };
      
      this.ws.onerror = () => {
        this.stats.errors++;
        this.log('WebSocket 錯誤', 'error');
        this.updateStats();
      };
      
    } catch (error) {
      this.stats.errors++;
      this.log(`連接失敗: ${error.message}`, 'error');
    }
  }
  
  /**
   * 斷開連接
   */
  disconnect() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
      this.connected = false;
      this.log('手動斷開連接', 'info');
    }
  }
  
  /**
   * 處理 WebSocket 訊息
   */
  handleMessage(event) {
    this.stats.received++;
    
    try {
      const data = JSON.parse(event.data);
      const msgType = data.type;
      
      // 更新統計
      if (msgType === 'frame_data' || msgType === 'frame_data_all') {
        this.stats.frameData++;
        this.updateFPS();
      }
      
      // 記錄客戶端
      if (data.device_id) {
        this.stats.clients.add(data.device_id);
      }
      
      // 更新當前幀信息
      if (msgType === 'frame_data_all') {
        this.displayCurrentFrame(data);
      }
      
      // 記錄日誌
      const typeMap = {
        'connection': 'connection',
        'disconnection': 'connection',
        'client_message': 'client_message',
        'frame_data': 'frame_data',
        'frame_data_all': 'frame_data_all',
        'playback_started': 'playback',
        'playback_paused': 'playback',
        'playback_stopped': 'playback',
        'playback_ready': 'playback',
        'error': 'error',
        'playback_error': 'error',
      };
      
      const logType = typeMap[msgType] || 'received';
      this.log(`⬇️ ${msgType}`, logType, data);
      
    } catch (error) {
      this.log(`⬇️ 接收 (非 JSON): ${event.data.substring(0, 100)}...`, 'received');
    }
    
    this.updateStats();
  }
  
  /**
   * 發送訊息
   */
  send(data) {
    if (!this.connected) {
      this.log('請先連接 WebSocket', 'error');
      return false;
    }
    
    if (this.mode === 'monitor') {
      this.log('監察模式不能發送控制訊息', 'warning');
      return false;
    }
    
    try {
      this.ws.send(JSON.stringify(data));
      this.stats.sent++;
      this.log(`⬆️ 發送: ${data.type}`, 'sent', data);
      this.updateStats();
      return true;
    } catch (error) {
      this.stats.errors++;
      this.log(`發送失敗: ${error.message}`, 'error');
      return false;
    }
  }
  
  /**
   * 記錄日誌(帶過濾)
   */
  log(message, type = 'info', data = null) {
    if (this.logPaused) return;
    
    // 檢查過濾器
    if (data && data.type) {
      const filterMap = {
        'connection': this.filters.connection,
        'disconnection': this.filters.connection,
        'client_message': this.filters.clientMsg,
        'frame_data': this.filters.frameData,
        'frame_data_all': this.filters.frameDataAll,
        'playback_started': this.filters.playback,
        'playback_paused': this.filters.playback,
        'playback_stopped': this.filters.playback,
        'playback_ready': this.filters.playback,
        'error': this.filters.errors,
        'playback_error': this.filters.errors,
      };
      
      const filter = filterMap[data.type];
      if (filter && !filter.checked) return;
    }
    
    const timestamp = formatTimestamp();
    const color = LOG_COLORS[type] || LOG_COLORS.info;
    
    const logEntry = document.createElement('div');
    logEntry.style.cssText = `
      margin-bottom: 6px;
      border-left: 3px solid ${color};
      padding-left: 8px;
      padding-top: 2px;
      padding-bottom: 2px;
      cursor: pointer;
    `;
    
    let content = `<span style="color: #6b7280;">[${timestamp}]</span> `;
    content += `<span style="color: ${color}; font-weight: 600;">${message}</span>`;
    
    // 添加詳細信息
    if (data) {
      content += this.formatDataDetails(data, logEntry);
    }
    
    logEntry.innerHTML = content;
    this.dom.messageLog.appendChild(logEntry);
    
    // 自動滾動
    if (this.filters.autoScroll.checked && !this.logPaused) {
      this.dom.messageLog.scrollTop = this.dom.messageLog.scrollHeight;
    }
    
    // 限制日誌數量
    while (this.dom.messageLog.children.length > 1000) {
      this.dom.messageLog.removeChild(this.dom.messageLog.firstChild);
    }
  }
  
  /**
   * 格式化數據詳情
   */
  formatDataDetails(data, logEntry) {
    let html = '';
    
    if (data.type === 'frame_data') {
      const pixelCount = calcPixelCount(data.rgbw_b64);
      html += `<div style="color: #6b7280; font-size: 0.85em; margin-left: 20px;">`;
      html += `幀: ${data.frame}, Slave: ${data.slave_id}, LEDs: ${pixelCount}, 來源: ${data.device_id || 'unknown'}`;
      html += `</div>`;
      
    } else if (data.type === 'frame_data_all') {
      let totalPixels = 0;
      let totalDataSize = 0;
      
      for (const slave of data.slaves) {
        totalPixels += calcPixelCount(slave.rgbw_b64);
        totalDataSize += slave.rgbw_b64.length;
      }
      
      html += `<div style="color: #6b7280; font-size: 0.85em; margin-left: 20px;">`;
      html += `幀: ${data.frame}, Slaves: ${data.slaves.length} 個, 總 LEDs: ${totalPixels}, 來源: ${data.device_id || 'unknown'}`;
      html += `</div>`;
      
      // 可展開的詳細信息
      if (this.filters.showDetails.checked) {
        const detailId = generateUniqueId();
        html += `<div id="${detailId}" style="display: none; margin-left: 20px; margin-top: 4px; padding: 8px; background: rgba(0,0,0,0.2); border-radius: 4px; font-size: 0.9em;">`;
        
        for (const slave of data.slaves) {
          const pixelCount = calcPixelCount(slave.rgbw_b64);
          const rgbwBytes = b64ToU8(slave.rgbw_b64);
          const avgBrightness = calcAvgBrightness(rgbwBytes);
          
          html += `<div style="margin: 2px 0;">Slave ${slave.slave_id}: ${pixelCount} LEDs, 平均亮度: ${avgBrightness}</div>`;
        }
        
        html += `</div>`;
        
        // 點擊展開/收起
        logEntry.addEventListener('click', () => {
          const detailEl = document.getElementById(detailId);
          if (detailEl) {
            detailEl.style.display = detailEl.style.display === 'none' ? 'block' : 'none';
          }
        });
      }
      
    } else if (data.type === 'client_message') {
      html += `<div style="color: #3b82f6; font-size: 0.85em; margin-left: 20px;">`;
      html += `客戶端 ${data.device_id} 發送: ${data.data.type}`;
      html += `</div>`;
      
    } else if (data.type === 'playback_ready') {
      html += `<div style="color: #6b7280; font-size: 0.85em; margin-left: 20px;">`;
      html += `FPS: ${data.fps}, 總幀數: ${data.total_frames}, Slaves: ${data.total_slaves}`;
      html += `</div>`;
    }
    
    return html;
  }
  
  /**
   * 顯示當前幀信息
   */
  displayCurrentFrame(data) {
    this.lastFrameData = data;
    
    let html = '<div style="display: grid; gap: 8px;">';
    html += `<div><strong>幀號:</strong> ${data.frame}</div>`;
    html += `<div><strong>時間:</strong> ${new Date(data.timestamp).toLocaleTimeString()}</div>`;
    html += `<div><strong>來源:</strong> ${data.device_id || 'unknown'}</div>`;
    
    if (data.slaves) {
      html += `<div><strong>Slaves:</strong> ${data.slaves.length} 個</div>`;
      html += '<div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid #e5e7eb;">';
      html += '<div style="font-weight: 600; margin-bottom: 4px;">點擊 Slave 查看詳情:</div>';
      
      for (const slave of data.slaves) {
        const pixelCount = calcPixelCount(slave.rgbw_b64);
        html += `
          <button class="slave-detail-btn" data-slave-id="${slave.slave_id}" 
                  style="display: block; width: 100%; padding: 6px; margin: 2px 0; 
                         background: #e5e7eb; border: 1px solid #d1d5db; border-radius: 4px; 
                         cursor: pointer; text-align: left; font-family: monospace; font-size: 11px;">
            Slave ${slave.slave_id}: ${pixelCount} LEDs
          </button>
        `;
      }
      html += '</div>';
    }
    
    html += '</div>';
    this.dom.currentFrameInfo.innerHTML = html;
    
    // 綁定點擊事件
    this.dom.currentFrameInfo.querySelectorAll('.slave-detail-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const slaveId = parseInt(btn.dataset.slaveId);
        this.viewSlaveDetail(slaveId);
      });
    });
  }
  
  /**
   * 查看 Slave 詳細數據
   */
  viewSlaveDetail(slaveId) {
    if (!this.lastFrameData || !this.lastFrameData.slaves) return;
    
    const slave = this.lastFrameData.slaves.find(s => s.slave_id === slaveId);
    if (!slave) return;
    
    const rgbwBytes = b64ToU8(slave.rgbw_b64);
    const pixelCount = rgbwBytes.length / 4;
    
    let html = `<div style="padding: 8px;">`;
    html += `<h4 style="margin: 0 0 12px 0; color: #667eea;">Slave ${slaveId} 詳細數據</h4>`;
    html += `<div style="margin-bottom: 12px;">`;
    html += `<div><strong>總像素數:</strong> ${pixelCount}</div>`;
    html += `<div><strong>數據大小:</strong> ${rgbwBytes.length} bytes</div>`;
    html += `</div>`;
    
    html += `<div style="margin-bottom: 8px; font-weight: 600;">前 50 個像素的 RGBW 值:</div>`;
    html += `<div style="max-height: 500px; overflow-y: auto; background: #f9fafb; padding: 8px; border-radius: 4px;">`;
    
    const displayCount = Math.min(50, pixelCount);
    for (let i = 0; i < displayCount; i++) {
      const offset = i * 4;
      const r = rgbwBytes[offset];
      const g = rgbwBytes[offset + 1];
      const b = rgbwBytes[offset + 2];
      const w = rgbwBytes[offset + 3];
      
      const rgbColor = `rgb(${r},${g},${b})`;
      
      html += `
        <div style="display: flex; align-items: center; gap: 8px; margin: 2px 0; padding: 4px; 
                    background: ${i % 2 === 0 ? '#fff' : '#f3f4f6'}; border-radius: 2px;">
          <div style="width: 30px; text-align: right; color: #6b7280;">${i}:</div>
          <div style="width: 20px; height: 20px; background: ${rgbColor}; border: 1px solid #d1d5db; border-radius: 2px;"></div>
          <div style="flex: 1;">
            R:<span style="color: #ef4444;">${String(r).padStart(3, ' ')}</span>
            G:<span style="color: #10b981;">${String(g).padStart(3, ' ')}</span>
            B:<span style="color: #3b82f6;">${String(b).padStart(3, ' ')}</span>
            W:<span style="color: #f59e0b;">${String(w).padStart(3, ' ')}</span>
          </div>
        </div>
      `;
    }
    
    if (pixelCount > 50) {
      html += `<div style="color: #6b7280; text-align: center; margin-top: 8px;">... 還有 ${pixelCount - 50} 個像素</div>`;
    }
    
    html += `</div></div>`;
    this.dom.slaveDetails.innerHTML = html;
  }
  
  /**
   * 更新連接狀態顯示
   */
  updateConnectionStatus(connected) {
    if (connected) {
      this.dom.statusEl.textContent = `✅ 已連接 (${this.mode})`;
      this.dom.statusEl.style.color = '#059669';
    } else {
      this.dom.statusEl.textContent = '❌ 未連接';
      this.dom.statusEl.style.color = '#dc2626';
    }
  }
  
  /**
   * 更新統計信息
   */
  updateStats() {
    this.dom.statReceived.textContent = this.stats.received;
    this.dom.statSent.textContent = this.stats.sent;
    this.dom.statFrameData.textContent = this.stats.frameData;
    this.dom.statErrors.textContent = this.stats.errors;
    
    if (this.stats.connectTime) {
      const uptime = Math.floor((Date.now() - this.stats.connectTime) / 1000);
      this.dom.statUptime.textContent = `${uptime}s`;
    } else {
      this.dom.statUptime.textContent = '0s';
    }
    
    // 更新 FPS
    if (this.stats.frameTimes.length > 0) {
      const avgFrameTime = this.stats.frameTimes.reduce((a, b) => a + b) / this.stats.frameTimes.length;
      const fps = 1000 / avgFrameTime;
      this.dom.statFps.textContent = fps.toFixed(1);
      this.dom.statFps.style.color = fps >= 35 ? '#10b981' : fps >= 20 ? '#f59e0b' : '#ef4444';
    }
  }
  
  /**
   * 更新 FPS 統計
   */
  updateFPS() {
    const now = performance.now();
    if (this.stats.lastFrameTime > 0) {
      const frameTime = now - this.stats.lastFrameTime;
      this.stats.frameTimes.push(frameTime);
      if (this.stats.frameTimes.length > 60) {
        this.stats.frameTimes.shift();
      }
    }
    this.stats.lastFrameTime = now;
  }
  
  /**
   * 清除日誌
   */
  clearLog() {
    this.dom.messageLog.innerHTML = '<div style="color: #9ca3af;">日誌已清除</div>';
    this.dom.currentFrameInfo.innerHTML = '<div style="color: #6b7280;">等待幀數據...</div>';
    this.dom.slaveDetails.innerHTML = '<div style="color: #6b7280;">選擇一個 slave 查看詳情...</div>';
    
    this.stats.received = 0;
    this.stats.sent = 0;
    this.stats.frameData = 0;
    this.stats.errors = 0;
    this.stats.frameTimes = [];
    this.stats.clients.clear();
    this.lastFrameData = null;
    
    this.updateStats();
  }
  
  /**
   * 切換日誌暫停狀態
   */
  toggleLogPause() {
    this.logPaused = !this.logPaused;
    this.dom.pauseLogBtn.textContent = this.logPaused ? '▶️ 恢復' : '⏸️ 暫停';
    this.dom.pauseLogBtn.style.background = this.logPaused ? '#10b981' : '#f59e0b';
    this.log(this.logPaused ? '日誌已暫停' : '日誌已恢復', 'info');
  }
  
  /**
   * 切換模式
   */
  setMode(mode) {
    this.mode = mode;
    this.log(`模式切換為: ${mode}`, 'info');
  }
}