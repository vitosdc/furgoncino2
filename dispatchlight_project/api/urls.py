# api/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

app_name = 'api'

router = DefaultRouter()
# I ViewSets verranno aggiunti nelle prossime fasi

urlpatterns = [
    path('', include(router.urls)),
    path('auth/', include('rest_framework.urls')),
]