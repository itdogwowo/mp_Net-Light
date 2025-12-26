# light_control/urls.py

from django.urls import path
from . import views

app_name = 'light_control'

urlpatterns = [
    path('', views.index, name='index'),  # 修正:應該用 name 參數,而不是 view
    path('dashboard/', views.dashboard, name='dashboard'),
]