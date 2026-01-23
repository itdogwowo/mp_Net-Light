/**
 * 實用工具函數庫
 */

const Utils = {
    /**
     * 防抖函數
     * @param {Function} func - 要執行的函數
     * @param {number} wait - 延遲時間(毫秒)
     */
    debounce(func, wait = 300) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    },

    /**
     * 節流函數
     * @param {Function} func - 要執行的函數
     * @param {number} limit - 限制時間(毫秒)
     */
    throttle(func, limit = 300) {
        let inThrottle;
        return function(...args) {
            if (!inThrottle) {
                func.apply(this, args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
        };
    },

    /**
     * 格式化日期
     * @param {Date|string} date - 日期對象或字符串
     * @param {string} format - 格式化模板
     */
    formatDate(date, format = 'YYYY-MM-DD HH:mm:ss') {
        const d = new Date(date);
        const year = d.getFullYear();
        const month = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        const hour = String(d.getHours()).padStart(2, '0');
        const minute = String(d.getMinutes()).padStart(2, '0');
        const second = String(d.getSeconds()).padStart(2, '0');

        return format
            .replace('YYYY', year)
            .replace('MM', month)
            .replace('DD', day)
            .replace('HH', hour)
            .replace('mm', minute)
            .replace('ss', second);
    },

    /**
     * 格式化文件大小
     * @param {number} bytes - 字節數
     */
    formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
    },

    /**
     * 複製到剪貼板
     * @param {string} text - 要複製的文本
     */
    async copyToClipboard(text) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (err) {
            // 降級方案
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.select();
            const result = document.execCommand('copy');
            document.body.removeChild(textarea);
            return result;
        }
    },

    /**
     * 獲取 URL 參數
     * @param {string} name - 參數名
     */
    getUrlParam(name) {
        const urlParams = new URLSearchParams(window.location.search);
        return urlParams.get(name);
    },

    /**
     * 設置 URL 參數
     * @param {string} name - 參數名
     * @param {string} value - 參數值
     */
    setUrlParam(name, value) {
        const url = new URL(window.location);
        url.searchParams.set(name, value);
        window.history.pushState({}, '', url);
    },

    /**
     * 生成隨機ID
     * @param {number} length - ID長度
     */
    generateId(length = 8) {
        return Math.random().toString(36).substring(2, length + 2);
    },

    /**
     * 延遲執行
     * @param {number} ms - 延遲時間(毫秒)
     */
    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    },

    /**
     * 深拷貝對象
     * @param {Object} obj - 要拷貝的對象
     */
    deepClone(obj) {
        return JSON.parse(JSON.stringify(obj));
    },

    /**
     * 檢測是否為移動設備
     */
    isMobile() {
        return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
    },

    /**
     * 平滑滾動到元素
     * @param {string|Element} target - 目標元素或選擇器
     */
    scrollTo(target, offset = 0) {
        const element = typeof target === 'string' 
            ? document.querySelector(target) 
            : target;
        
        if (element) {
            const top = element.getBoundingClientRect().top + window.pageYOffset - offset;
            window.scrollTo({ top, behavior: 'smooth' });
        }
    },

    /**
     * 本地存儲封裝
     */
    storage: {
        set(key, value) {
            try {
                localStorage.setItem(key, JSON.stringify(value));
                return true;
            } catch (e) {
                console.error('Storage set error:', e);
                return false;
            }
        },
        get(key, defaultValue = null) {
            try {
                const item = localStorage.getItem(key);
                return item ? JSON.parse(item) : defaultValue;
            } catch (e) {
                console.error('Storage get error:', e);
                return defaultValue;
            }
        },
        remove(key) {
            localStorage.removeItem(key);
        },
        clear() {
            localStorage.clear();
        }
    },

    /**
     * 表單驗證
     */
    validate: {
        email(email) {
            const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            return re.test(email);
        },
        phone(phone) {
            const re = /^[\d\s\-\+\(\)]+$/;
            return re.test(phone) && phone.replace(/\D/g, '').length >= 8;
        },
        required(value) {
            return value !== null && value !== undefined && value.toString().trim() !== '';
        },
        minLength(value, length) {
            return value.length >= length;
        },
        maxLength(value, length) {
            return value.length <= length;
        }
    },

    /**
     * AJAX 請求封裝
     */
    async request(url, options = {}) {
        const defaultOptions = {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || ''
            }
        };

        const config = { ...defaultOptions, ...options };

        if (config.body && typeof config.body === 'object') {
            config.body = JSON.stringify(config.body);
        }

        try {
            const response = await fetch(url, config);
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.message || 'Request failed');
            }
            
            return { success: true, data };
        } catch (error) {
            console.error('Request error:', error);
            return { success: false, error: error.message };
        }
    }
};

// 導出到全局
window.Utils = Utils;