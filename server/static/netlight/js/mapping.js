// static/netlight/js/mapping.js - 簡化版本
console.log('✅ mapping.js 加載成功');

// 顯示初始訊息
document.addEventListener('DOMContentLoaded', function() {
    const msgEl = document.getElementById('msg');
    if (msgEl) {
        msgEl.textContent = '⏳ 正在初始化模塊化版本...';
        msgEl.style.color = '#6b7280';
    }
    
    // 設置一個延遲，給模塊加載時間
    setTimeout(async () => {
        try {
            // 動態導入所有模塊
            const core = await import('./mapping/core.js');
            const canvas = await import('./mapping/canvas.js');
            const mapping = await import('./mapping/mapping.js');
            const ui = await import('./mapping/ui.js');
            const websocket = await import('./mapping/websocket.js');
            
            console.log('✅ 所有模塊加載成功');
            
            // 初始化核心DOM
            core.initDOM();
            
            // 啟動應用
            await bootstrap();
            
        } catch (error) {
            console.error('❌ 模塊加載失敗:', error);
            
            if (msgEl) {
                msgEl.textContent = `❌ 模塊加載失敗: ${error.message}`;
                msgEl.style.color = '#dc2626';
            }
            
            // 嘗試加載備用版本
            loadFallbackVersion();
        }
    }, 100);
});

// 加載備用版本
function loadFallbackVersion() {
    console.log('🔄 嘗試加載備用版本...');
    
    // 創建script標籤加載單文件版本
    const script = document.createElement('script');
    script.src = '/static/netlight/js/mapping-single.js';
    script.onload = () => console.log('✅ 備用版本加載成功');
    script.onerror = () => console.error('❌ 備用版本也加載失敗');
    document.head.appendChild(script);
}

// 主初始化函數
async function bootstrap() {
    try {
        const { ST, DOM, showMessage, jget, autoWH } = await import('./mapping/core.js');
        const { loadMapping, loadAllSlavesRGBW } = await import('./mapping/mapping.js');
        const { redraw } = await import('./mapping/canvas.js');
        
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
        
        // 初始化每個 slave
        for (const s of ST.slaves) {
            const slaveId = s.slave_id;
            const pixelCount = s.pixel_count;
            
            ST.wh[slaveId] = autoWH(pixelCount);
            ST.layout[slaveId] = { ox: 0, oy: 0 };
            
            await loadMapping(slaveId, pixelCount);
        }
        
        // 載入總畫板數據
        await loadAllSlavesRGBW(0);
        
        // 更新 slave 選擇下拉選單
        updateSlaveSelect();
        
        showMessage(`✅ 初始化完成！載入 ${ST.slaves.length} 個 slave`, 'success');
        redraw();
        
    } catch (error) {
        console.error('初始化錯誤:', error);
        showMessage(`❌ 初始化失敗: ${error.message}`, 'error');
    }
}

function updateSlaveSelect() {
    const { ST, DOM } = window; // 假設 ST 和 DOM 是全局的或從模塊獲取
    
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