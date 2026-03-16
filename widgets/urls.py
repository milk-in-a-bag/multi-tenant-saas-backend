"""
URL patterns for Widget API
"""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.widget_list, name="widget-list"),
    path("<uuid:widget_id>/", views.widget_detail, name="widget-detail"),
]
