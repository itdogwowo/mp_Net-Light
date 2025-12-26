# light_control/models.py

from django.db import models
from django.utils import timezone
import uuid

class Device(models.Model):
    """MicroPython 設備模型"""
    
    STATUS_CHOICES = [
        ('online', '在線'),
        ('offline', '離線'),
        ('error', '錯誤'),
    ]
    
    # 設備唯一標識
    device_id = models.CharField(max_length=100, unique=True, verbose_name='設備ID')
    name = models.CharField(max_length=100, verbose_name='設備名稱')
    
    # 設備信息
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name='IP地址')
    mac_address = models.CharField(max_length=17, null=True, blank=True, verbose_name='MAC地址')
    
    # 狀態
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='offline', verbose_name='狀態')
    last_seen = models.DateTimeField(default=timezone.now, verbose_name='最後在線時間')
    
    # 當前燈效
    current_effect = models.CharField(max_length=50, default='off', verbose_name='當前燈效')
    brightness = models.IntegerField(default=100, verbose_name='亮度 (0-100)')
    
    # 時間戳
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='創建時間')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新時間')
    
    class Meta:
        verbose_name = '設備'
        verbose_name_plural = '設備列表'
        ordering = ['-last_seen']
    
    def __str__(self):
        return f"{self.name} ({self.device_id})"


class LightEffect(models.Model):
    """燈效模式模型"""
    
    name = models.CharField(max_length=50, unique=True, verbose_name='效果名稱')
    display_name = models.CharField(max_length=100, verbose_name='顯示名稱')
    description = models.TextField(blank=True, verbose_name='描述')
    
    # 燈效參數 (JSON格式)
    parameters = models.JSONField(default=dict, verbose_name='參數')
    
    # 是否啟用
    is_active = models.BooleanField(default=True, verbose_name='啟用')
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='創建時間')
    
    class Meta:
        verbose_name = '燈效'
        verbose_name_plural = '燈效列表'
        ordering = ['name']
    
    def __str__(self):
        return self.display_name


class CommandLog(models.Model):
    """命令日誌"""
    
    device = models.ForeignKey(Device, on_delete=models.CASCADE, verbose_name='設備')
    command = models.CharField(max_length=50, verbose_name='命令')
    parameters = models.JSONField(default=dict, verbose_name='參數')
    
    success = models.BooleanField(default=False, verbose_name='成功')
    response = models.TextField(blank=True, verbose_name='響應')
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='執行時間')
    
    class Meta:
        verbose_name = '命令日誌'
        verbose_name_plural = '命令日誌'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.device.name} - {self.command} @ {self.created_at}"