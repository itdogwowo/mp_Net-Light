/**
 * 主應用邏輯
 * 處理側邊欄伸縮、菜單摺疊、用戶菜單等
 */

class App {
    constructor() {
        this.csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
        this.sidebar = document.getElementById('sidebar');
        this.sidebarToggle = document.getElementById('sidebarToggle');
        this.userMenuToggle = document.getElementById('userMenuToggle');
        this.userMenuDropdown = document.getElementById('userMenuDropdown');
        
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
        // 切換側邊欄伸縮
        this.sidebarToggle?.addEventListener('click', () => {
            this.toggleSidebar();
        });

        // 恢復側邊欄狀態
        const savedState = localStorage.getItem('sidebarCollapsed');
        if (savedState === 'true') {
            document.body.classList.add('sidebar-collapsed');
        }

        // 初始化子菜單摺疊
        this.initSubmenuToggle();
        
        // 移動端點擊外部關閉側邊欄
        if (window.innerWidth <= 1024) {
            document.addEventListener('click', (e) => {
                if (!this.sidebar?.contains(e.target) && 
                    !this.sidebarToggle?.contains(e.target) &&
                    document.body.classList.contains('sidebar-open')) {
                    this.closeSidebar();
                }
            });
        }
    }

    toggleSidebar() {
        const isMobile = window.innerWidth <= 1024;
        
        if (isMobile) {
            // 移動端：開關側邊欄
            document.body.classList.toggle('sidebar-open');
        } else {
            // 桌面端:收起/展開
            document.body.classList.toggle('sidebar-collapsed');
            const isCollapsed = document.body.classList.contains('sidebar-collapsed');
            localStorage.setItem('sidebarCollapsed', isCollapsed);
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
        let container = document.getElementById('messagesContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'messagesContainer';
            container.className = 'messages-container';
            document.querySelector('.content-body')?.prepend(container);
        }

        const iconMap = {
            success: 'check-circle',
            error: 'x-circle',
            warning: 'exclamation-triangle',
            info: 'info-circle'
        };

        const alert = document.createElement('div');
        alert.className = `alert alert-${type}`;
        alert.innerHTML = `
            <i class="bi bi-${iconMap[type] || 'info-circle'}"></i>
            <span>${message}</span>
            <button type="button" class="btn-close" onclick="this.parentElement.remove()">
                <i class="bi bi-x"></i>
            </button>
        `;
        container.appendChild(alert);

        setTimeout(() => {
            alert.style.opacity = '0';
            setTimeout(() => alert.remove(), 300);
        }, 5000);
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