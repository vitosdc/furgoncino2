# api/apps.py
from django.apps import AppConfig

class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'

# api/views.py (file vuoto per ora)
from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.decorators import api_view

@api_view(['GET'])
def api_root(request):
    """
    Endpoint di base per verificare che l'API funzioni
    """
    return Response({
        'message': 'DispatchLight API is running',
        'version': '1.0.0'
    })

# api/__init__.py (file vuoto)
# Questo file deve esistere per far riconoscere la directory come package Python