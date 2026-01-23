# webUI/views.py
from django.shortcuts import render

def index(request):
    return render(request, 'index.html')


def examples(request):
    """組件示例頁面"""
    return render(request, 'pages/examples.html')