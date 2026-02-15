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
    this.playbackMode = 'all_slaves'; // 'all_slaves' 或 'single_slave'
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
    
    console.log(`[WebSocket] 連接至: ${wsUrl}`);
    this.ws = new WebSocket(wsUrl);
    
    this.ws.onopen = () => {
      console.log("[WebSocket] 連接成功");
      this.connected = true;
      showMessage("✅ WebSocket 連接成功", "success");
      
      // 發送心跳包
      this.startHeartbeat();
    };
    
    this.ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      this.handleMessage(data);
    };
    
    this.ws.onclose = () => {
      console.log("[WebSocket] 連接已斷開");
      this.connected = false;
      this.playing = false;
      this.decoderReady = false;
      this.stopHeartbeat();
      showMessage("⚠️ WebSocket 連接已斷開", "warning");
    };
    
    this.ws.onerror = (error) => {
      console.error("[WebSocket] 連接錯誤:", error);
      showMessage("❌ WebSocket 連接錯誤", "error");
    };
  }
  
  disconnect() {
    if (this.ws) {
      this.stop();
      this.stopHeartbeat();
      this.ws.close();
      this.ws = null;
      this.connected = false;
      this.decoderReady = false;
      console.log("[WebSocket] 手動斷開連接");
    }
  }
  
  startHeartbeat() {
    // 每30秒發送一次心跳包
    this.heartbeatInterval = setInterval(() => {
      if (this.connected) {
        this.ws.send(JSON.stringify({
          type: 'ping',
          timestamp: new Date().toISOString()
        }));
      }
    }, 30000);
  }
  
  stopHeartbeat() {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
  }
  
  handleMessage(data) {
    console.log(`[WebSocket] 收到消息類型: ${data.type}`, data);
    
    switch (data.type) {
      case 'connection':
        console.log("[WebSocket] 連接確認:", data.message);
        showMessage(`✅ ${data.message}`, "success");
        break;
        
      case 'playback_ready':
        this.totalFrames = data.total_frames;
        this.fps = data.fps;
        this.decoderReady = true;
        this.playbackMode = data.mode || 'single_slave';
        ST.isAllSlavesMode = (this.playbackMode === 'all_slaves');
        ST.totalFrames = this.totalFrames;
        
        console.log(`[Playback] 播放器就緒: ${this.totalFrames} 幀, ${this.fps} FPS, 模式=${this.playbackMode}`);
        showMessage(`✅ 播放器就緒: ${this.totalFrames} 幀 @ ${this.fps} FPS`, "success");
        
        // 更新 UI
        if (DOM.totalFrames) DOM.totalFrames.textContent = this.totalFrames;
        if (DOM.fpsInfo) DOM.fpsInfo.textContent = this.fps;
        break;
        
      case 'frame_data':
        this.handleFrameData(data);
        break;
        
      case 'frame_data_all':  // 新增的處理類型
        this.handleAllSlavesFrameData(data);
        break;
        
      case 'playback_started':
        this.playing = true;
        console.log("[Playback] 播放開始");
        showMessage("▶️ 播放開始", "info");
        break;
        
      case 'playback_paused':
        this.playing = false;
        console.log("[Playback] 播放暫停");
        showMessage("⏸️ 播放暫停", "info");
        break;
        
      case 'playback_stopped':
        this.playing = false;
        this.currentFrame = 0;
        console.log("[Playback] 播放停止");
        showMessage("⏹️ 播放停止", "info");
        
        // 重置 UI
        if (DOM.frameSlider) DOM.frameSlider.value = "0";
        if (DOM.frameInfo) DOM.frameInfo.textContent = "frame: 0 (0 fps)";
        break;
        
      case 'playback_seeked':
        console.log(`[Playback] 跳轉到幀: ${data.frame}`);
        showMessage(`⏩ 跳轉到幀 ${data.frame}`, "info");
        break;
        
      case 'playback_error':
        console.error("[Playback] 播放錯誤:", data.message);
        showMessage(`❌ 播放錯誤: ${data.message}`, "error");
        break;
        
      case 'test_response':
        console.log("[WebSocket] 測試回應:", data.message);
        showMessage(`✅ ${data.message}`, "success");
        break;
        
      case 'pong':
        // 心跳回應
        const latency = new Date() - new Date(data.timestamp);
        this.performance.latency = latency;
        console.log(`[WebSocket] 心跳回應延遲: ${latency}ms`);
        break;
        
      case 'error':
        console.error("[WebSocket] 錯誤:", data.message);
        showMessage(`❌ 錯誤: ${data.message}`, "error");
        break;
        
      default:
        console.warn("[WebSocket] 未知消息類型:", data.type);
    }
  }
  
  handleFrameData(data) {
    // 更新性能統計
    this.updatePerformanceStats();
    
    // 更新當前幀
    this.currentFrame = data.frame;
    ST.frame = data.frame;
    
    // 更新 UI 控件
    if (DOM.frameSlider) {
      DOM.frameSlider.value = String(data.frame);
      DOM.frameSlider.max = this.totalFrames - 1;
    }
    
    if (DOM.frameInfo) {
      DOM.frameInfo.textContent = `frame: ${data.frame} (${this.performance.avgFps.toFixed(1)} fps)`;
    }
    
    if (DOM.frameNumber) {
      DOM.frameNumber.textContent = data.frame;
    }
    
    // 處理 RGBW 數據
    const slaveId = data.slave_id;
    const rgbwBytes = b64ToU8(data.rgbw_b64);
    
    if (slaveId === -1) {
      // 總畫板模式，但使用 frame_data 消息（舊模式）
      ST.allSlavesRGBW[-1] = rgbwBytes;
    } else {
      // 單個 slave 模式
      ST.rgbw[slaveId] = rgbwBytes;
    }
    
    // 緩存幀數據
    FRAME_CACHE.set(`${slaveId}_${data.frame}`, rgbwBytes);
    
    // 觸發重繪
    redraw();
    
    // 如果正在播放，自動請求下一幀
    if (this.playing && this.playbackMode === 'single_slave') {
      const nextFrame = (this.currentFrame + 1) % this.totalFrames;
      const delay = Math.max(1, 1000 / this.fps - this.performance.latency);
      
      setTimeout(() => {
        if (this.playing && this.connected) {
          this.getFrame(nextFrame, slaveId);
        }
      }, delay);
    }
  }
  
  handleAllSlavesFrameData(data) {
    console.log(`[Playback] 收到所有 slave 幀數據: frame=${data.frame}, slave_count=${data.slaves.length}`);
    
    // 更新性能統計
    this.updatePerformanceStats();
    
    // 更新當前幀信息
    this.currentFrame = data.frame;
    ST.frame = data.frame;
    
    // 更新 UI 控件
    if (DOM.frameSlider) {
      DOM.frameSlider.value = String(data.frame);
      DOM.frameSlider.max = this.totalFrames - 1;
    }
    
    if (DOM.frameInfo) {
      DOM.frameInfo.textContent = `frame: ${data.frame} (${this.performance.avgFps.toFixed(1)} fps)`;
    }
    
    if (DOM.frameNumber) {
      DOM.frameNumber.textContent = data.frame;
    }
    
    // 清空現有的 RGBW 數據
    ST.allSlavesRGBW = {};
    
    // 處理所有 slave 的數據
    for (const slaveData of data.slaves) {
      const sid = slaveData.slave_id;
      const rgbwBytes = b64ToU8(slaveData.rgbw_b64);
      
      // 存儲到全局狀態
      ST.allSlavesRGBW[sid] = rgbwBytes;
      
      // 如果有 pixel_count 信息，也存儲起來
      if (slaveData.pixel_count) {
        if (!ST.slavePixelCounts) ST.slavePixelCounts = {};
        ST.slavePixelCounts[sid] = slaveData.pixel_count;
      }
      
      // 緩存幀數據（用於快速重繪）
      FRAME_CACHE.set(`${sid}_${data.frame}`, rgbwBytes);
    }
    
    // 標記總畫板模式
    ST.isAllSlavesMode = true;
    
    // 觸發重繪
    redraw();
    
    // 如果正在播放，自動請求下一幀
    if (this.playing && this.playbackMode === 'all_slaves') {
      const nextFrame = (this.currentFrame + 1) % this.totalFrames;
      const delay = Math.max(1, 1000 / this.fps - this.performance.latency);
      
      setTimeout(() => {
        if (this.playing && this.connected) {
          this.getFrame(nextFrame, -1); // -1 表示總畫板模式
        }
      }, delay);
    }
  }
  
  updatePerformanceStats() {
    const now = performance.now();
    
    if (this.performance.lastFrameTime > 0) {
      const frameTime = now - this.performance.lastFrameTime;
      this.performance.frameTimes.push(frameTime);
      
      // 保持最近 60 個幀時間記錄
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
    
    // 更新 UI 顯示性能信息
    if (DOM.performanceInfo) {
      DOM.performanceInfo.textContent = 
        `FPS: ${this.performance.avgFps.toFixed(1)} | 延遲: ${this.performance.latency}ms`;
    }
  }
  
  async initPlayback(filename, slaveId = -1) {
    if (!this.connected) {
      showMessage("請先連接到 WebSocket", "warning");
      return false;
    }
    
    // 重置狀態
    this.decoderReady = false;
    this.playing = false;
    this.currentFrame = 0;
    
    // 發送初始化請求
    this.ws.send(JSON.stringify({
      type: 'playback_init',
      filename: filename,
      slave_id: slaveId
    }));
    
    // 等待播放器就緒
    return new Promise((resolve, reject) => {
      const checkReady = () => {
        if (this.decoderReady) {
          resolve(true);
        } else {
          setTimeout(checkReady, 100);
        }
      };
      
      // 設置超時
      setTimeout(() => {
        if (!this.decoderReady) {
          reject(new Error("播放器初始化超時"));
          showMessage("❌ 播放器初始化超時", "error");
        }
      }, 5000);
      
      setTimeout(checkReady, 100);
    });
  }
  
  play(frame = 0) {
    if (!this.decoderReady) {
      showMessage("播放器尚未初始化", "warning");
      return;
    }
    
    // 設置播放模式
    const slaveId = ST.isAllSlavesMode ? -1 : ST.selectedSlaveId;
    
    this.ws.send(JSON.stringify({
      type: 'playback_play',
      frame: frame,
      slave_id: slaveId
    }));
    
    console.log("[Playback] 開始播放，模式:", ST.isAllSlavesMode ? "總畫板" : "單一 slave");
  }
  
  pause() {
    if (!this.decoderReady) return;
    
    this.ws.send(JSON.stringify({
      type: 'playback_pause'
    }));
    
    console.log("[Playback] 暫停播放");
  }
  
  stop() {
    if (!this.decoderReady) return;
    
    this.ws.send(JSON.stringify({
      type: 'playback_stop'
    }));
    
    console.log("[Playback] 停止播放");
  }
  
  seek(frame) {
    if (!this.decoderReady) return;
    
    // 設置播放模式
    const slaveId = ST.isAllSlavesMode ? -1 : ST.selectedSlaveId;
    
    this.ws.send(JSON.stringify({
      type: 'playback_seek',
      frame: frame,
      slave_id: slaveId
    }));
    
    console.log(`[Playback] 跳轉到幀 ${frame}`);
  }
  
  getFrame(frame, slaveId = -1) {
    if (!this.decoderReady) return;
    
    this.ws.send(JSON.stringify({
      type: 'playback_get_frame',
      frame: frame,
      slave_id: slaveId
    }));
  }
  
  sendTestMessage(message = "Hello WebSocket!") {
    if (!this.connected) {
      showMessage("WebSocket 未連接", "warning");
      return;
    }
    
    this.ws.send(JSON.stringify({
      type: 'test_message',
      message: message,
      timestamp: new Date().toISOString()
    }));
    
    console.log(`[WebSocket] 發送測試消息: ${message}`);
  }
}