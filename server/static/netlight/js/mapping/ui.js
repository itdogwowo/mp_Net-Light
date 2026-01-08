// static/netlight/js/mapping/ui.js
import { ST, DOM, showMessage, keyXY, jpost, defaultPxldId } from './core.js';
import { redraw } from './canvas.js';
import { loadMapping, loadSlaveRGBW, saveOneSlave, updateSaveButtonText } from './mapping.js';

export class UIHandler {
    constructor(wsPlayer) {
        this.wsPlayer = wsPlayer;
        this.setupEventListeners();
    }
    
    setupEventListeners() {
        // 畫布點擊事件
        DOM.board.addEventListener("click", (ev) => this.handleCanvasClick(ev));
        
        // 應用按鈕
        document.getElementById("applyBtn").addEventListener("click", () => this.handleApply());
        
        // 保存按鈕
        document.getElementById("saveBtn").addEventListener("click", () => this.handleSave());
        
        // Slave 選擇
        DOM.slaveSelect.addEventListener("change", (ev) => this.handleSlaveChange(ev));
        
        // 播放控制
        DOM.playBtn && DOM.playBtn.addEventListener("click", () => this.handlePlay());
        DOM.pauseBtn && DOM.pauseBtn.addEventListener("click", () => this.handlePause());
        DOM.stopBtn && DOM.stopBtn.addEventListener("click", () => this.handleStop());
        
        // 幀滑塊
        DOM.frameSlider && DOM.frameSlider.addEventListener("input", (ev) => this.handleFrameSlider(ev));
    }
    
    eventToGrid(ev) {
        const rect = DOM.board.getBoundingClientRect();
        const rx = (ev.clientX - rect.left) / rect.width;
        const ry = (ev.clientY - rect.top) / rect.height;
        const px = rx * DOM.board.width;
        const py = ry * DOM.board.height;
        return { 
            gx: Math.floor(px / ST.cell), 
            gy: Math.floor(py / ST.cell) 
        };
    }
    
    hitBoard(gx, gy) {
        for (const s of ST.slaves) {
            const sid = s.slave_id;
            const { w, h } = ST.wh[sid] || { w: 1, h: 1 };
            const layout = ST.layout[sid] || { ox: 0, oy: 0 };
            if (gx >= layout.ox && gy >= layout.oy && gx < layout.ox + w && gy < layout.oy + h) {
                return { sid, lx: gx - layout.ox, ly: gy - layout.oy };
            }
        }
        return null;
    }
    
    async handleCanvasClick(ev) {
        const { gx, gy } = this.eventToGrid(ev);

        if (ST.mode === "board") {
            const hit = this.hitBoard(gx, gy);
            if (!hit) {
                ST.picked = null;
                DOM.pickedInfoEl.textContent = `未命中：(${gx},${gy})`;
                redraw();
                return;
            }
            ST.picked = { gx, gy, ...hit };
        } else {
            const sid = ST.activeSlave;
            const { w, h } = ST.wh[sid] || { w: 1, h: 1 };
            if (gx < 0 || gy < 0 || gx >= w || gy >= h) return;
            ST.picked = { sid, lx: gx, ly: gy, gx, gy };
        }

        const { sid, lx, ly } = ST.picked;
        const mapKey = keyXY(lx, ly);
        const cur = (ST.maps[sid] || {})[mapKey];
        const { w, h } = ST.wh[sid] || { w: 1, h: 1 };

        DOM.pickedInfoEl.textContent =
            `slave=${sid} (${lx},${ly})` +
            (ST.mode === "board" ? ` global=(${gx},${gy})` : "") +
            (cur ? ` pxld=${cur.pxld_id} mcu=${cur.mcu_id}` : "");

        if (cur) {
            DOM.pxldIdEl.value = cur.pxld_id;
            DOM.mcuIdEl.value = cur.mcu_id;
        } else {
            const def = defaultPxldId(lx, ly, w, h);
            DOM.pxldIdEl.value = def;
            DOM.mcuIdEl.value = def;
        }

        redraw();
    }
    
    handleApply() {
        if (!ST.picked) return;
        const { sid, lx, ly } = ST.picked;

        const pxldId = parseInt(DOM.pxldIdEl.value, 10) || 0;
        const mcuId = parseInt(DOM.mcuIdEl.value, 10) || 0;
        
        if (mcuId !== -1) {
            const existingMcuIds = new Set();
            const m = ST.maps[sid] || {};
            
            for (const key in m) {
                if (key !== keyXY(lx, ly)) {
                    const existingMcuId = m[key].mcu_id;
                    if (existingMcuId !== -1) {
                        existingMcuIds.add(existingMcuId);
                    }
                }
            }
            
            if (existingMcuIds.has(mcuId)) {
                showMessage(`❌ mcu_id ${mcuId} 已存在！請使用其他值或 -1`, "error");
                return;
            }
        }
        
        ST.maps[sid] = ST.maps[sid] || {};
        ST.maps[sid][keyXY(lx, ly)] = {
            pxld_id: pxldId,
            mcu_id: mcuId,
        };
        
        showMessage(`✓ 已套用：S${sid} (${lx},${ly})`, 'success');
        redraw();
    }
    
    async handleSave() {
        const sid = ST.activeSlave;
        
        if (sid === -1) {
            if (!confirm("確定要保存所有 slave 的 mapping 嗎？")) return;
            
            showMessage("⏳ 正在保存所有 slave...", "info");
            
            try {
                const batchData = {
                    batch: true,
                    mappings: []
                };
                
                for (const s of ST.slaves) {
                    const slaveId = s.slave_id;
                    try {
                        const mappingData = await saveOneSlave(slaveId);
                        batchData.mappings.push(mappingData);
                    } catch (error) {
                        showMessage(`❌ Slave ${slaveId}: ${error.message}`, "error");
                        return;
                    }
                }
                
                const res = await jpost("/light/api/mapping/set/", batchData);
                
                if (res.ok) {
                    showMessage(`✅ 所有 slave (${ST.slaves.length}個) 保存成功`, 'success');
                } else {
                    showMessage(`❌ 保存失敗: ${res.err}`, 'error');
                }
            } catch (error) {
                showMessage(`❌ 保存過程中發生錯誤: ${error.message}`, 'error');
            }
        } else {
            try {
                const mappingData = await saveOneSlave(sid);
                const res = await jpost("/light/api/mapping/set/", mappingData);
                
                if (res.ok) {
                    showMessage(`💾 保存成功：mapping_slave_${sid}.json`, 'success');
                } else {
                    showMessage(`❌ 失敗：${res.err}`, 'error');
                }
            } catch (error) {
                showMessage(`❌ 保存失敗: ${error.message}`, 'error');
            }
        }
    }
    
    async handleSlaveChange(ev) {
        const sid = parseInt(DOM.slaveSelect.value, 10);
        
        ST.activeSlave = sid;
        ST.mode = (sid === -1) ? "board" : "slave";
        ST.picked = null;
        DOM.pickedInfoEl.textContent = "點擊格子以選取";
        
        updateSaveButtonText();
        redraw();
        
        if (sid !== -1) {
            showMessage("載入中...", "info");
            await loadMapping(sid);
            await loadSlaveRGBW(ST.frame, sid);
            showMessage("");
        }
        redraw();
    }
    
    handlePlay() {
        if (ST.totalFrames <= 0) {
            showMessage("請先載入 PXLD 文件", "warning");
            return;
        }
        
        if (!this.wsPlayer.connected) {
            showMessage("正在連接到播放伺服器...", "info");
            this.wsPlayer.connect('playback');
            
            setTimeout(async () => {
                if (this.wsPlayer.connected) {
                    const name = DOM.pxldNameEl.value;
                    const sid = ST.mode === "board" ? -1 : ST.activeSlave;
                    
                    const initialized = await this.wsPlayer.initPlayback(name, sid);
                    if (initialized) {
                        this.wsPlayer.play(ST.frame);
                        ST.playing = true;
                        showMessage("✅ 使用 WebSocket 播放中...", "success");
                    }
                } else {
                    showMessage("WebSocket 連接失敗，切換到 HTTP 模式", "warning");
                    this.playHTTP();
                }
            }, 1000);
        } else if (!this.wsPlayer.decoderReady) {
            const name = DOM.pxldNameEl.value;
            const sid = ST.mode === "board" ? -1 : ST.activeSlave;
            
            this.wsPlayer.initPlayback(name, sid).then(() => {
                this.wsPlayer.play(ST.frame);
                ST.playing = true;
                showMessage("✅ 使用 WebSocket 播放中...", "success");
            });
        } else {
            this.wsPlayer.play(ST.frame);
            ST.playing = true;
            showMessage("✅ 播放中...", "success");
        }
    }
    
    playHTTP() {
        if (ST.playing || ST.totalFrames <= 0) return;
        ST.playing = true;
        const lastRef = { last: performance.now() };
        ST._raf = requestAnimationFrame(t => this.tickHTTP(t, lastRef));
        showMessage("ℹ️ 使用 HTTP 模式播放（較慢）", "info");
    }
    
    async tickHTTP(now, lastRef) {
        if (!ST.playing) return;

        const dt = now - lastRef.last;
        const frameTime = 1000 / ST.fps;

        if (dt >= frameTime) {
            ST.frame = (ST.frame + 1) % ST.totalFrames;
            DOM.frameSlider.value = String(ST.frame);
            DOM.frameInfo.textContent = `frame: ${ST.frame}`;

            if (ST.mode === "slave" && ST.activeSlave !== -1) {
                await loadSlaveRGBW(ST.frame, ST.activeSlave);
            } else if (ST.mode === "board") {
                await loadAllSlavesRGBW(ST.frame);
            }
            redraw();
            lastRef.last = now - (dt % frameTime);
        }

        ST._raf = requestAnimationFrame(t => this.tickHTTP(t, lastRef));
    }
    
    handlePause() {
        if (this.wsPlayer.connected && this.wsPlayer.decoderReady) {
            this.wsPlayer.pause();
        }
        ST.playing = false;
        if (ST._raf) cancelAnimationFrame(ST._raf);
        ST._raf = 0;
        showMessage("⏸️ 已暫停", "info");
    }
    
    handleStop() {
        if (this.wsPlayer.connected && this.wsPlayer.decoderReady) {
            this.wsPlayer.stop();
        }
        
        this.handlePause();
        ST.frame = 0;
        DOM.frameSlider.value = "0";
        DOM.frameInfo.textContent = `frame: 0`;
        redraw();
        showMessage("⏹️ 已停止", "info");
    }
    
    async handleFrameSlider(ev) {
        const v = parseInt(ev.target.value, 10) || 0;
        ST.frame = v;
        DOM.frameInfo.textContent = `frame: ${v}`;
        
        if (this.wsPlayer.connected && this.wsPlayer.decoderReady) {
            const sid = ST.mode === "board" ? -1 : ST.activeSlave;
            this.wsPlayer.getFrame(v, sid);
        } else {
            if (ST.mode === "slave" && ST.activeSlave !== -1) {
                await loadSlaveRGBW(ST.frame, ST.activeSlave);
            } else if (ST.mode === "board") {
                await loadAllSlavesRGBW(ST.frame);
            }
            redraw();
        }
    }
}