"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from core.views import PrayerLogViewSet, ProfileViewSet, health_check, register_device

router = DefaultRouter()
router.register(r'profiles', ProfileViewSet, basename='profile')
router.register(r'prayer-logs', PrayerLogViewSet, basename='prayer-log')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/health/', health_check, name='health-check'),
    path('api/register/', register_device, name='register-device'),
    path('api/', include(router.urls)),
    path('api-auth/', include('rest_framework.urls')),  # browsable API login/logout
]
