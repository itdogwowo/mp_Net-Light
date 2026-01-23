/**
 * 主題切換系統
 * 支持深色/淺色模式切換
 */

class ThemeManager {
    constructor() {
        this.currentTheme = localStorage.getItem('theme') || 'dark';
        this.themeToggle = document.getElementById('themeToggle');
        this.themeIcon = this.themeToggle?.querySelector('.theme-icon');
        
        this.init();
    }

    init() {
        this.applyTheme(this.currentTheme);
        this.bindEvents();
    }

    bindEvents() {
        this.themeToggle?.addEventListener('click', () => {
            this.toggleTheme();
        });
    }

    toggleTheme() {
        this.currentTheme = this.currentTheme === 'light' ? 'dark' : 'light';
        this.applyTheme(this.currentTheme);
        
        // 通知用戶
        app?.showNotification(
            `已切換到${this.currentTheme === 'dark' ? '深色' : '淺色'}模式`, 
            'success'
        );
    }

    applyTheme(theme) {
        // 設置 HTML 屬性
        document.documentElement.setAttribute('data-theme', theme);
        
        // 保存到 localStorage
        localStorage.setItem('theme', theme);
        
        // 更新圖標
        if (this.themeIcon) {
            this.themeIcon.className = theme === 'dark' 
                ? 'bi bi-sun theme-icon' 
                : 'bi bi-moon-stars-fill theme-icon';
        }
        
        // 添加過渡動畫
        document.body.classList.add('theme-transition');
        setTimeout(() => {
            document.body.classList.remove('theme-transition');
        }, 300);
        
        console.log(`🎨 Theme switched to: ${theme}`);
    }
}

// 初始化主題管理器
const themeManager = new ThemeManager();

// 主題切換動畫
const style = document.createElement('style');
style.textContent = `
    .theme-transition * {
        transition: background-color 0.3s ease, color 0.3s ease, border-color 0.3s ease !important;
    }
`;
document.head.appendChild(style);