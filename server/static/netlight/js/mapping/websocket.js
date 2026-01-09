// static/netlight/js/mapping/websocket.js - 修正 JSON 解析問題
import { ST, DOM, showMessage, b64ToU8, FRAME_CACHE } from './core.js';
import { redraw } from './canvas.js';

export class WebSocketPlayer {
  constructor() {
    this.ws = null;
    this.connected = false;
    this.playing = false;
    this.currentFrame = 0;
    this.totalFrames = 0;
    this.fps = 30;
    this.decoderReady = false;
    this.allSlaveIds = [];
    
    // 🔥 控制狀態(防止殘留幀)
    this.shouldAcceptFrames = true;
    this.lastControlTimestamp = 0;
    
    this.performance = {
      frameTimes: [],
      lastFrameTime: 0,
      avgFps: 0,
      latency: 0
    };
  }

  connect(deviceId = 'playback') {
    if (this.ws && this.connected) {
      this.disconnect();
    }
    
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    let wsUrl;
    
    if (deviceId === 'playback') {
      wsUrl = `${protocol}//${window.location.host}/ws/light/playback/`;
    } else {
      wsUrl = `${protocol}//${window.location.host}/ws/light/device/${deviceId}/`;
    }
    
    this.ws = new WebSocket(wsUrl);
    
    this.ws.onopen = () => {
      console.log("WebSocket connected");
      this.connected = true;
      showMessage("✅ WebSocket 連接成功", "success");
    };
    
    // 🔥 修正:只在這裡解析一次 JSON
    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);  // 只解析一次
        this.handleMessage(msg);  // 傳入已解析的對象
      } catch (error) {
        console.error("[WS] ❌ JSON 解析失敗:", error, event.data);
      }
    };
    
    this.ws.onclose = () => {
      console.log("WebSocket disconnected");
      this.connected = false;
      this.playing = false;
      this.decoderReady = false;
      this.shouldAcceptFrames = false;
      showMessage("⚠️ WebSocket 連接已斷開", "warning");
    };
    
    this.ws.onerror = (error) => {
      console.error("WebSocket error:", error);
      showMessage("❌ WebSocket 連接錯誤", "error");
    };
  }
  
  disconnect() {
    if (this.ws) {
      this.stop();
      this.ws.close();
      this.ws = null;
      this.connected = false;
      this.decoderReady = false;
      this.shouldAcceptFrames = false;
    }
  }
  
  // 🔥 修正:參數改為 msg(已解析的對象)
  handleMessage(msg) {
    const now = performance.now();
    
    // 🔥 過濾暫停/停止後的殘留幀
    if ((msg.type === 'frame_data' || msg.type === 'frame_data_all')) {
      if (!this.shouldAcceptFrames) {
        console.log(`[WS] 🚫 過濾殘留幀數據: frame ${msg.frame}`);
        return;  // 丟棄
      }
      
      // 🔥 檢查是否是舊數據(控制後 100ms 內)
      const msgAge = now - this.lastControlTimestamp;
      if (msgAge < 100 && !this.playing) {
        console.log(`[WS] 🚫 過濾控制後 ${msgAge.toFixed(0)}ms 內的幀數據`);
        return;
      }
    }
    
    switch (msg.type) {
      case 'connection':
        console.log('[WS] 📡 連接訊息:', msg.message);
        break;
      
      case 'playback_ready':
        this.decoderReady = true;
        this.totalFrames = msg.total_frames;
        this.fps = msg.fps;
        this.allSlaveIds = msg.slave_ids || [];
        console.log(`[WS] ✅ 播放器就緒: ${this.totalFrames} 幀, ${this.fps} FPS`);
        console.log(`[WS] 所有 Slave IDs: ${this.allSlaveIds.join(', ')}`);
        showMessage(`✅ 播放器就緒: ${this.totalFrames} 幀 @ ${this.fps} FPS`, 'success');
        break;
      
      case 'playback_started':
        this.playing = true;
        this.shouldAcceptFrames = true;  // 🔥 重新接受幀數據
        this.lastControlTimestamp = now;
        console.log(`[WS] ▶️ 播放開始: frame ${msg.frame}`);
        showMessage('▶️ 播放中...', 'success');
        break;
      
      case 'playback_paused':
        this.playing = false;
        this.shouldAcceptFrames = false;  // 🔥 停止接受幀數據
        this.lastControlTimestamp = now;
        this.currentFrame = msg.frame || this.currentFrame;
        console.log(`[WS] ⏸️ 播放暫停: frame ${this.currentFrame}`);
        showMessage('⏸️ 已暫停', 'info');
        break;
      
      case 'playback_stopped':
        this.playing = false;
        this.shouldAcceptFrames = false;  // 🔥 停止接受幀數據
        this.lastControlTimestamp = now;
        this.currentFrame = 0;
        ST.frame = 0;
        if (DOM.frameSlider) DOM.frameSlider.value = '0';
        if (DOM.frameInfo) DOM.frameInfo.textContent = 'frame: 0';
        console.log('[WS] ⏹️ 播放停止');
        showMessage('⏹️ 已停止', 'info');
        redraw();
        break;
      
      case 'frame_data_all':
        // 🔥 處理總畫板數據
        this.updatePerformanceStats(now);
        this.currentFrame = msg.frame;
        ST.frame = msg.frame;
        
        if (DOM.frameSlider) DOM.frameSlider.value = String(msg.frame);
        if (DOM.frameInfo) {
          DOM.frameInfo.textContent = `frame: ${msg.frame} (${this.performance.avgFps.toFixed(1)} fps)`;
        }
        
        // 更新所有 slave 的 RGBW 數據
        if (msg.slaves && Array.isArray(msg.slaves)) {
          for (const slaveData of msg.slaves) {
            const sid = slaveData.slave_id;
            const rgbwBytes = b64ToU8(slaveData.rgbw_b64);
            ST.allSlavesRGBW[sid] = rgbwBytes;
            FRAME_CACHE.set(`${sid}_${msg.frame}`, rgbwBytes);
          }
        }
        
        redraw();
        break;
      
      case 'frame_data':
        // 🔥 處理單個 slave 數據
        this.updatePerformanceStats(now);
        this.currentFrame = msg.frame;
        ST.frame = msg.frame;
        
        if (DOM.frameSlider) DOM.frameSlider.value = String(msg.frame);
        if (DOM.frameInfo) {
          DOM.frameInfo.textContent = `frame: ${msg.frame} (${this.performance.avgFps.toFixed(1)} fps)`;
        }
        
        const rgbwBytes = b64ToU8(msg.rgbw_b64);
        ST.rgbw[msg.slave_id] = rgbwBytes;
        FRAME_CACHE.set(`${msg.slave_id}_${msg.frame}`, rgbwBytes);
        
        redraw();
        break;
      
      case 'error':
        console.error('[WS] ❌ 伺服器錯誤:', msg.message);
        showMessage(`❌ ${msg.message}`, 'error');
        break;
      
      default:
        console.log('[WS] 未知訊息類型:', msg.type, msg);
    }
  }
  
  // 🔥 性能統計更新
  updatePerformanceStats(now) {
    if (this.performance.lastFrameTime > 0) {
      const frameTime = now - this.performance.lastFrameTime;
      this.performance.frameTimes.push(frameTime);
      
      // 保留最近 60 幀數據
      if (this.performance.frameTimes.length > 60) {
        this.performance.frameTimes.shift();
      }
      
      // 計算平均 FPS
      if (this.performance.frameTimes.length > 0) {
        const avgFrameTime = this.performance.frameTimes.reduce((a, b) => a + b) / this.performance.frameTimes.length;
        this.performance.avgFps = 1000 / avgFrameTime;
      }
    }
    
    this.performance.lastFrameTime = now;
  }
  
  async initPlayback(filename, slaveId = -1) {
    if (!this.connected) {
      showMessage("請先連接到 WebSocket", "warning");
      return false;
    }
    
    console.log(`[WS] 📤 初始化播放器: ${filename}, slave_id=${slaveId}`);
    
    this.ws.send(JSON.stringify({
      type: 'playback_init',
      filename: filename,
      slave_id: slaveId
    }));
    
    // 等待播放器就緒
    return new Promise((resolve) => {
      const timeout = setTimeout(() => {
        if (!this.decoderReady) {
          console.error('[WS] ❌ 初始化超時');
          showMessage('❌ 播放器初始化超時', 'error');
          resolve(false);
        }
      }, 5000);
      
      const checkReady = () => {
        if (this.decoderReady) {
          clearTimeout(timeout);
          console.log('[WS] ✅ 播放器初始化完成');
          resolve(true);
        } else {
          setTimeout(checkReady, 100);
        }
      };
      
      setTimeout(checkReady, 100);
    });
  }
  
  play(frame = 0) {
    if (!this.decoderReady) {
      showMessage("播放器尚未初始化", "warning");
      return;
    }
    
    // 🔥 立即更新本地狀態
    this.playing = true;
    this.shouldAcceptFrames = true;
    this.lastControlTimestamp = performance.now();
    
    this.ws.send(JSON.stringify({
      type: 'playback_play',
      frame: frame
    }));
    
    console.log(`[WS] 📤 開始播放: frame ${frame}`);
  }
  
  pause() {
    if (!this.connected || !this.decoderReady) return;
    
    // 🔥 立即設置本地狀態
    this.playing = false;
    this.shouldAcceptFrames = false;
    this.lastControlTimestamp = performance.now();
    
    this.ws.send(JSON.stringify({
      type: 'playback_pause'
    }));
    
    console.log('[WS] 📤 發送暫停指令');
  }
  
  stop() {
    if (!this.connected || !this.decoderReady) return;
    
    // 🔥 立即設置本地狀態
    this.playing = false;
    this.shouldAcceptFrames = false;
    this.lastControlTimestamp = performance.now();
    
    this.ws.send(JSON.stringify({
      type: 'playback_stop'
    }));
    
    console.log('[WS] 📤 發送停止指令');
  }
  
  seek(frame) {
    if (!this.decoderReady) return;
    
    this.ws.send(JSON.stringify({
      type: 'playback_seek',
      frame: frame
    }));
    
    console.log(`[WS] 📤 跳轉到: frame ${frame}`);
  }
  
  getFrame(frame, slaveId = -1) {
    if (!this.decoderReady) return;
    
    this.ws.send(JSON.stringify({
      type: 'playback_get_frame',
      frame: frame,
      slave_id: slaveId
    }));
  }
  
  getPerformanceStats() {
    return {
      fps: this.performance.avgFps.toFixed(1),
      latency: this.performance.latency.toFixed(1),
      frameCount: this.performance.frameTimes.length
    };
  }
}