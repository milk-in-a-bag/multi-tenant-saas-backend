"""
URL patterns for authentication API
"""
from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login, name='auth-login'),
]