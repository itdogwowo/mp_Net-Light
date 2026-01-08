// static/netlight/js/mapping-single.js
(() => {
    'use strict';
    
    console.log('✅ mapping-single.js 加載成功');
    
    // ==================== 工具函數 ====================
    function keyXY(x, y) { 
        return `${x},${y}`; 
    }
    
    function getCookie(name) {
        let val = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    val = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return val;
    }
    
    async function jget(url) {
        const r = await fetch(url);
        return r.json();
    }
    
    async function jpost(url, obj) {
        const csrftoken = getCookie('csrftoken');
        const r = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrftoken,
            },
            body: JSON.stringify(obj)
        });
        return r.json();
    }
    
    function b64ToU8(b64) {
        const bin = atob(b64);
        const out = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
        return out;
    }
    
    function defaultPxldId(x, y, w, h) {
        return (y * w) + x;
    }
    
    function autoWH(pixelCount) {
        const w = Math.min(20, Math.max(1, pixelCount));
        const h = Math.ceil(pixelCount / w);
        return { w, h };
    }
    
    function showMessage(text, type = "info") {
        const msgEl = document.getElementById("msg");
        if (!msgEl) return;
        
        const colors = {
            success: "#059669",
            error: "#dc2626",
            info: "#6b7280",
            warning: "#d97706"
        };
        
        msgEl.textContent = text;
        msgEl.style.color = colors[type] || colors.info;
        
        setTimeout(() => {
            if (msgEl.textContent === text) {
                msgEl.textContent = "";
            }
        }, 3000);
    }
    
    // ==================== 狀態 ====================
    const ST = {
        cell: 12,
        grid_w: 140,
        grid_h: 80,
        fps: 30,
        totalFrames: 0,
        frame: 0,
        slaves: [],
        wh: {},
        layout: {},
        maps: {},
        rgbw: {},
        mode: "board",
        activeSlave: -1,
        picked: null,
        playing: false,
        _raf: 0,
        showGrid: true,
        dpr: window.devicePixelRatio || 1,
        allSlavesRGBW: {},
    };
    
    const FRAME_CACHE = new Map();
    
    // ==================== DOM 元素 ====================
    let BOARD, CTX, PXLD_NAME_EL, SLAVE_SELECT, PICKED_INFO_EL, PXLD_ID_EL, MCU_ID_EL, 
        MSG_EL, PLAY_BTN, PAUSE_BTN, STOP_BTN, FRAME_SLIDER, FRAME_INFO;
    
    function initDOM() {
        BOARD = document.getElementById("board");
        CTX = BOARD.getContext("2d");
        PXLD_NAME_EL = document.getElementById("pxldName");
        SLAVE_SELECT = document.getElementById("slaveSelect");
        PICKED_INFO_EL = document.getElementById("pickedInfo");
        PXLD_ID_EL = document.getElementById("pxldId");
        MCU_ID_EL = document.getElementById("mcuId");
        MSG_EL = document.getElementById("msg");
        PLAY_BTN = document.getElementById("playBtn");
        PAUSE_BTN = document.getElementById("pauseBtn");
        STOP_BTN = document.getElementById("stopBtn");
        FRAME_SLIDER = document.getElementById("frameSlider");
        FRAME_INFO = document.getElementById("frameInfo");
    }
    
    // ==================== 簡單畫布功能 ====================
    function resizeCanvas() {
        let w, h;
        if (ST.mode === "board") {
            w = ST.grid_w * ST.cell;
            h = ST.grid_h * ST.cell;
        } else {
            const wh = ST.wh[ST.activeSlave];
            w = wh.w * ST.cell;
            h = wh.h * ST.cell;
        }
    
        BOARD.style.width = `${w}px`;
        BOARD.style.height = `${h}px`;
        BOARD.width = w * ST.dpr;
        BOARD.height = h * ST.dpr;
        CTX.scale(ST.dpr, ST.dpr);
        CTX.imageSmoothingEnabled = false;
    }
    
    function drawBackground() {
        CTX.fillStyle = "#0f1419";
        CTX.fillRect(0, 0, BOARD.width / ST.dpr, BOARD.height / ST.dpr);
    }
    
    function drawSlaveRectsOnBoard() {
        for (const s of ST.slaves) {
            const sid = s.slave_id;
            const layout = ST.layout[sid] || { ox: 0, oy: 0 };
            const wh = ST.wh[sid] || { w: 1, h: 1 };
            
            CTX.strokeStyle = "rgba(99,179,237,0.7)";
            CTX.lineWidth = 1;
            CTX.strokeRect(
                layout.ox * ST.cell + 0.5, 
                layout.oy * ST.cell + 0.5, 
                wh.w * ST.cell, 
                wh.h * ST.cell
            );
            
            CTX.fillStyle = "rgba(255,255,255,0.9)";
            CTX.font = "10px monospace";
            CTX.fillText(`S${sid}`, layout.ox * ST.cell + 3, layout.oy * ST.cell + 12);
        }
    }
    
    function drawGrid(cols, rows) {
        CTX.strokeStyle = "rgba(255,255,255,0.12)";
        CTX.lineWidth = 0.5;
        
        for (let x = 0; x <= cols; x++) {
            CTX.beginPath();
            CTX.moveTo(x * ST.cell + 0.5, 0);
            CTX.lineTo(x * ST.cell + 0.5, rows * ST.cell);
            CTX.stroke();
        }
        for (let y = 0; y <= rows; y++) {
            CTX.beginPath();
            CTX.moveTo(0, y * ST.cell + 0.5);
            CTX.lineTo(cols * ST.cell, y * ST.cell + 0.5);
            CTX.stroke();
        }
    }
    
    function redraw() {
        resizeCanvas();
        CTX.clearRect(0, 0, BOARD.width / ST.dpr, BOARD.height / ST.dpr);
        drawBackground();
        
        if (ST.mode === "board") {
            drawSlaveRectsOnBoard();
            drawGrid(ST.grid_w, ST.grid_h);
        } else {
            const { w, h } = ST.wh[ST.activeSlave];
            drawGrid(w, h);
        }
    }
    
    // ==================== 事件處理 ====================
    function eventToGrid(ev) {
        const rect = BOARD.getBoundingClientRect();
        const rx = (ev.clientX - rect.left) / rect.width;
        const ry = (ev.clientY - rect.top) / rect.height;
        const px = rx * BOARD.width;
        const py = ry * BOARD.height;
        return { 
            gx: Math.floor(px / ST.cell), 
            gy: Math.floor(py / ST.cell) 
        };
    }
    
    function hitBoard(gx, gy) {
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
    
    function handleCanvasClick(ev) {
        const { gx, gy } = eventToGrid(ev);
        
        if (ST.mode === "board") {
            const hit = hitBoard(gx, gy);
            if (!hit) {
                ST.picked = null;
                PICKED_INFO_EL.textContent = `未命中：(${gx},${gy})`;
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
        
        PICKED_INFO_EL.textContent =
            `slave=${sid} (${lx},${ly})` +
            (ST.mode === "board" ? ` global=(${gx},${gy})` : "") +
            (cur ? ` pxld=${cur.pxld_id} mcu=${cur.mcu_id}` : "");
        
        if (cur) {
            PXLD_ID_EL.value = cur.pxld_id;
            MCU_ID_EL.value = cur.mcu_id;
        } else {
            const def = defaultPxldId(lx, ly, w, h);
            PXLD_ID_EL.value = def;
            MCU_ID_EL.value = def;
        }
        
        redraw();
    }
    
    async function loadMapping(slaveId, pixelCount = 0) {
        try {
            const name = PXLD_NAME_EL.value;
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
                }
                return true;
            }
            return false;
        } catch (error) {
            console.error(`❌ Slave ${slaveId}: 載入異常`, error);
            return false;
        }
    }
    
    async function loadAllSlavesRGBW(frame) {
        const name = PXLD_NAME_EL.value;
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
    
    function updateSlaveSelect() {
        SLAVE_SELECT.innerHTML = "";
        const o0 = document.createElement("option");
        o0.value = "-1";
        o0.textContent = "總畫板";
        SLAVE_SELECT.appendChild(o0);
        
        for (const s of ST.slaves) {
            const opt = document.createElement("option");
            opt.value = String(s.slave_id);
            const { w, h } = ST.wh[s.slave_id];
            const layout = ST.layout[s.slave_id] || { ox: 0, oy: 0 };
            opt.textContent = `Slave ${s.slave_id} (${s.pixel_count} LED, ${w}x${h} @ ${layout.ox},${layout.oy})`;
            SLAVE_SELECT.appendChild(opt);
        }
    }
    
    function setupEventListeners() {
        BOARD.addEventListener("click", handleCanvasClick);
        
        document.getElementById("applyBtn").addEventListener("click", () => {
            if (!ST.picked) return;
            const { sid, lx, ly } = ST.picked;
            
            ST.maps[sid] = ST.maps[sid] || {};
            ST.maps[sid][keyXY(lx, ly)] = {
                pxld_id: parseInt(PXLD_ID_EL.value, 10) || 0,
                mcu_id: parseInt(MCU_ID_EL.value, 10) || 0,
            };
            
            showMessage(`✓ 已套用：S${sid} (${lx},${ly})`, 'success');
            redraw();
        });
        
        document.getElementById("saveBtn").addEventListener("click", async () => {
            const sid = ST.activeSlave;
            if (sid === -1) {
                showMessage("請先選擇一個 slave", "warning");
                return;
            }
            
            showMessage("💾 保存功能正在開發中...", "info");
        });
        
        SLAVE_SELECT.addEventListener("change", async () => {
            const sid = parseInt(SLAVE_SELECT.value, 10);
            
            ST.activeSlave = sid;
            ST.mode = (sid === -1) ? "board" : "slave";
            ST.picked = null;
            PICKED_INFO_EL.textContent = "點擊格子以選取";
            
            redraw();
        });
    }
    
    // ==================== 主初始化函數 ====================
    async function bootstrap() {
        initDOM();
        setupEventListeners();
        showMessage("⏳ 載入 PXLD...", "info");
        
        const name = PXLD_NAME_EL.value;
        
        try {
            const info = await jget(`/light/api/pxld/info/?name=${encodeURIComponent(name)}`);
            if (!info.ok) { 
                showMessage(`❌ 失敗：${info.err}`, 'error');
                return; 
            }
            
            ST.fps = info.info.fps;
            ST.totalFrames = info.info.total_frames;
            
            FRAME_SLIDER.max = String(Math.max(0, ST.totalFrames - 1));
            FRAME_SLIDER.value = "0";
            FRAME_INFO.textContent = `frame: 0`;
            
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
            
            updateSlaveSelect();
            ST.activeSlave = -1;
            ST.mode = "board";
            SLAVE_SELECT.value = "-1";
            
            showMessage(`✅ 完成！載入 ${ST.slaves.length} 個 slave`, 'success');
            redraw();
            
        } catch (error) {
            console.error('初始化錯誤:', error);
            showMessage(`❌ 初始化失敗: ${error.message}`, 'error');
        }
    }
    
    // ==================== 啟動 ====================
    document.addEventListener('DOMContentLoaded', bootstrap);
    window.addEventListener('resize', redraw);
    
})();