// static/netlight/js/mapping/websocket.js
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
    
    this.ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      this.handleMessage(data);
    };
    
    this.ws.onclose = () => {
      console.log("WebSocket disconnected");
      this.connected = false;
      this.playing = false;
      this.decoderReady = false;
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
    }
  }
  
  handleMessage(data) {
    switch (data.type) {
      case 'connection':
        console.log("Connected:", data.message);
        break;
        
      case 'playback_ready':
        this.totalFrames = data.total_frames;
        this.fps = data.fps;
        this.decoderReady = true;
        console.log(`播放器就緒: ${this.totalFrames} 幀, ${this.fps} FPS`);
        showMessage(`✅ 播放器就緒: ${this.totalFrames} 幀 @ ${this.fps} FPS`, "success");
        break;
        
      case 'frame_data':
        this.handleFrameData(data);
        break;
        
      case 'playback_started':
        this.playing = true;
        console.log("播放開始");
        break;
        
      case 'playback_paused':
        this.playing = false;
        console.log("播放暫停");
        break;
        
      case 'playback_stopped':
        this.playing = false;
        this.currentFrame = 0;
        console.log("播放停止");
        break;
        
      case 'playback_error':
        console.error("Playback error:", data.message);
        showMessage(`❌ 播放錯誤: ${data.message}`, "error");
        break;
        
      case 'error':
        console.error("WebSocket error:", data.message);
        break;
    }
  }
  
  handleFrameData(data) {
    this.updatePerformanceStats();
    
    this.currentFrame = data.frame;
    ST.frame = data.frame;
    
    if (DOM.frameSlider) DOM.frameSlider.value = String(data.frame);
    if (DOM.frameInfo) {
      DOM.frameInfo.textContent = `frame: ${data.frame} (${this.performance.avgFps.toFixed(1)} fps)`;
    }
    
    const slaveId = data.slave_id;
    const rgbwBytes = b64ToU8(data.rgbw_b64);
    
    if (slaveId === -1) {
      ST.allSlavesRGBW[0] = rgbwBytes;
    } else {
      ST.rgbw[slaveId] = rgbwBytes;
    }
    
    FRAME_CACHE.set(`${slaveId}_${data.frame}`, rgbwBytes);
    redraw();
  }
  
  updatePerformanceStats() {
    const now = performance.now();
    
    if (this.performance.lastFrameTime > 0) {
      const frameTime = now - this.performance.lastFrameTime;
      this.performance.frameTimes.push(frameTime);
      
      if (this.performance.frameTimes.length > 60) {
        this.performance.frameTimes.shift();
      }
      
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
    
    this.ws.send(JSON.stringify({
      type: 'playback_init',
      filename: filename,
      slave_id: slaveId
    }));
    
    return new Promise((resolve) => {
      const checkReady = () => {
        if (this.decoderReady) {
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
    
    this.ws.send(JSON.stringify({
      type: 'playback_play',
      frame: frame
    }));
    
    console.log("開始播放");
  }
  
  pause() {
    if (!this.decoderReady) return;
    
    this.ws.send(JSON.stringify({
      type: 'playback_pause'
    }));
    
    console.log("暫停播放");
  }
  
  stop() {
    if (!this.decoderReady) return;
    
    this.ws.send(JSON.stringify({
      type: 'playback_stop'
    }));
    
    console.log("停止播放");
  }
  
  seek(frame) {
    if (!this.decoderReady) return;
    
    this.ws.send(JSON.stringify({
      type: 'playback_seek',
      frame: frame
    }));
    
    console.log(`跳轉到幀 ${frame}`);
  }
  
  getFrame(frame, slaveId = -1) {
    if (!this.decoderReady) return;
    
    this.ws.send(JSON.stringify({
      type: 'playback_get_frame',
      frame: frame,
      slave_id: slaveId
    }));
  }
}