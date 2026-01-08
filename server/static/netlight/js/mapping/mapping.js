// static/netlight/js/mapping.js - 調試版本
// 簡單版本，用於確認基本功能
import { initDOM, showMessage } from './mapping/core.js';

async function bootstrapSimple() {
    try {
        initDOM();
        showMessage("正在初始化...", "info");
        
        // 直接檢查導入
        console.log('檢查導入狀態:');
        console.log('- initDOM:', typeof initDOM);
        console.log('- showMessage:', typeof showMessage);
        
        // 嘗試導入其他模塊
        try {
            const { autoWH } = await import('./mapping/core.js');
            console.log('- autoWH:', typeof autoWH);
            showMessage("✅ 核心模塊導入成功", "success");
        } catch (error) {
            console.error('導入錯誤:', error);
            showMessage(`❌ 導入錯誤: ${error.message}`, "error");
        }
        
    } catch (error) {
        console.error('初始化錯誤:', error);
        showMessage(`❌ 初始化失敗: ${error.message}`, "error");
    }
}

// 啟動調試版本
document.addEventListener('DOMContentLoaded', bootstrapSimple);