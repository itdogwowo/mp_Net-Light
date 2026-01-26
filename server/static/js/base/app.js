/**
 * 主應用邏輯
 * 處理側邊欄伸縮、菜單摺疊、用戶菜單等
 */

class App {
    constructor() {
        this.csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
        // this.sidebar = document.getElementById('sidebar');
        // this.sidebarToggle = document.getElementById('sidebarToggle');
        this.userMenuToggle = document.getElementById('userMenuToggle');
        this.userMenuDropdown = document.getElementById('userMenuDropdown');
        // 使用解構賦值獲取常用節點
        this.nodes = {
            body: document.body,
            sidebar: document.getElementById('sidebar'),
            sidebarToggle: document.getElementById('sidebarToggle'),
        };
        this.storageKey = 'sidebarCollapsed';

        this.init();
    }

    init() {
        console.log('🚀 Application initialized');
        this.initSidebar();
        this.initUserMenu();
        this.initMessages();
        this.setupAjaxDefaults();
        this.updateFooterYear();
    }

    // ==================== 側邊欄功能 ====================
    initSidebar() {
        // 1. 恢復狀態 (從 EEPROM/LocalStorage 讀取)
        const isCollapsed = localStorage.getItem(this.storageKey) === 'true';
        if (isCollapsed && window.innerWidth > 1024) {
            this.nodes.body.classList.add('sidebar-collapsed');
        }

        // 2. 監聽切換按鈕
        this.nodes.sidebarToggle?.addEventListener('click', () => this.toggleSidebar());

        // 3. 子菜單處理 (優化：增加對收縮狀態的檢查)
        const hasSubmenuItems = document.querySelectorAll('.nav-item.has-submenu');
        
        hasSubmenuItems.forEach(item => {
            const link = item.querySelector('.nav-link');
            link?.addEventListener('click', (e) => {
                // 如果側邊欄處於收起狀態，不處理二級菜單摺疊，直接跳轉或失效
                if (this.nodes.body.classList.contains('sidebar-collapsed')) {
                    return; 
                }

                e.preventDefault();
                const isOpen = item.classList.contains('open');
                
                // 關閉其他已打開的菜單 (保持 UI 整潔，類似單一中斷觸發)
                hasSubmenuItems.forEach(el => el.classList.remove('open'));
                
                if (!isOpen) {
                    item.classList.add('open');
                }
                
                this.saveSubmenuState();
            });
        });
    }

    toggleSidebar() {
        const isMobile = window.innerWidth <= 1024;
        
        if (isMobile) {
            this.nodes.body.classList.toggle('sidebar-open');
        } else {
            // 切換時移除所有 open 類，避免展開時子菜單雜亂
            if (!this.nodes.body.classList.contains('sidebar-collapsed')) {
                document.querySelectorAll('.nav-item.has-submenu.open')
                    .forEach(el => el.classList.remove('open'));
            }
            
            this.nodes.body.classList.toggle('sidebar-collapsed');
            
            // 寫入緩存 (Persistence)
            const currentState = this.nodes.body.classList.contains('sidebar-collapsed');
            localStorage.setItem(this.storageKey, currentState);
        }
    }

    closeSidebar() {
        document.body.classList.remove('sidebar-open');
    }

    // 子菜單摺疊功能
    initSubmenuToggle() {
        const menuItemsWithSubmenu = document.querySelectorAll('.nav-item.has-submenu > .nav-link');
        
        menuItemsWithSubmenu.forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                
                const parentItem = link.parentElement;
                const isOpen = parentItem.classList.contains('open');
                
                // 如果側邊欄是收起狀態,則不處理摺疊
                if (document.body.classList.contains('sidebar-collapsed')) {
                    return;
                }
                
                // 關閉其他打開的子菜單 (可選)
                // document.querySelectorAll('.nav-item.has-submenu.open').forEach(item => {
                //     if (item !== parentItem) {
                //         item.classList.remove('open');
                //     }
                // });
                
                // 切換當前子菜單
                parentItem.classList.toggle('open');
                
                // 保存狀態到 localStorage
                this.saveSubmenuState();
            });
        });
        
        // 恢復子菜單狀態
        this.restoreSubmenuState();
    }

    saveSubmenuState() {
        const openMenus = [];
        document.querySelectorAll('.nav-item.has-submenu.open').forEach(item => {
            const link = item.querySelector('.nav-link');
            const text = link.querySelector('.nav-text')?.textContent.trim();
            if (text) openMenus.push(text);
        });
        localStorage.setItem('openSubmenus', JSON.stringify(openMenus));
    }

    restoreSubmenuState() {
        const savedState = localStorage.getItem('openSubmenus');
        if (!savedState) return;
        
        try {
            const openMenus = JSON.parse(savedState);
            openMenus.forEach(menuText => {
                const menuItem = Array.from(document.querySelectorAll('.nav-item.has-submenu')).find(item => {
                    const text = item.querySelector('.nav-text')?.textContent.trim();
                    return text === menuText;
                });
                if (menuItem) {
                    menuItem.classList.add('open');
                }
            });
        } catch (e) {
            console.error('Failed to restore submenu state:', e);
        }
    }

    // ==================== 用戶菜單 ====================
    initUserMenu() {
        this.userMenuToggle?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.userMenuDropdown?.classList.toggle('show');
            this.userMenuToggle.parentElement?.classList.toggle('open');
        });

        // 點擊外部關閉
        document.addEventListener('click', (e) => {
            if (!this.userMenuToggle?.contains(e.target) && 
                !this.userMenuDropdown?.contains(e.target)) {
                this.userMenuDropdown?.classList.remove('show');
                this.userMenuToggle?.parentElement?.classList.remove('open');
            }
        });
    }

    // ==================== 消息自動消失 ====================
    initMessages() {
        const messages = document.querySelectorAll('.alert');
        messages.forEach(msg => {
            setTimeout(() => {
                msg.style.opacity = '0';
                setTimeout(() => msg.remove(), 300);
            }, 5000);
        });
    }

    // ==================== AJAX 默認設置 ====================
    setupAjaxDefaults() {
        const originalFetch = window.fetch;
        window.fetch = (...args) => {
            if (args[1]?.method && args[1].method !== 'GET') {
                args[1].headers = {
                    ...args[1].headers,
                    'X-CSRFToken': this.csrfToken
                };
            }
            return originalFetch.apply(window, args);
        };
    }

    // ==================== 工具方法 ====================
    showNotification(message, type = 'info') {
        // 1. 獲取或創建容器 (確保唯一性)
        let container = document.getElementById('messagesContainer') || (() => {
            const c = document.createElement('div');
            c.id = 'messagesContainer';
            c.className = 'messages-container';
            document.querySelector('.content-body')?.prepend(c);
            return c;
        })();
    
        const iconMap = {
            success: 'check-circle',
            error: 'x-circle',
            warning: 'exclamation-triangle',
            info: 'info-circle'
        };
    
        // 2. 建立通知節點
        const alert = document.createElement('div');
        alert.className = `alert alert-${type} fade show`; // 加入 fade show 類別以支援 CSS 過渡
        alert.innerHTML = `
            <i class="bi bi-${iconMap[type] || 'info-circle'}"></i>
            <span>${message}</span>
            <button type="button" class="btn-close" onclick="closeAlert(this.parentElement)">
                <i class="bi bi-x"></i>
            </button>
        `;
    
        container.appendChild(alert);
    
        // 3. 自動銷毀邏輯 (TTL 控管)
        // 使用 Promise 或簡潔的延遲執行
        const delay = (ms) => new Promise(res => setTimeout(res, ms));
    
        (async () => {
            await delay(5000);
            if (alert.parentNode) {
                alert.classList.remove('show'); // 觸發 CSS 漸隱
                await delay(300);              // 等待動畫結束
                alert.remove();                // 從內存釋放資產
            }
        })();
    }

    updateFooterYear() {
        const yearElement = document.getElementById('currentYear');
        if (yearElement) {
            yearElement.textContent = new Date().getFullYear();
        }
    }

    // 響應式處理
    handleResize() {
        const isMobile = window.innerWidth <= 1024;
        
        if (!isMobile && document.body.classList.contains('sidebar-open')) {
            document.body.classList.remove('sidebar-open');
        }
    }
}

// 初始化應用
const app = new App();

// 響應式監聽
window.addEventListener('resize', () => app.handleResize());