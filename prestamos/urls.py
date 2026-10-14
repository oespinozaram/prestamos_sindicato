from django.urls import path
from .views import DashboardPrestamosView, PrestamoCreateView, HistorialAfiliadoView, AbonoManualCreateView

app_name = 'prestamos'

urlpatterns = [
    path('dashboard/', DashboardPrestamosView.as_view(), name='dashboard'),
    path('nuevo/', PrestamoCreateView.as_view(), name='nuevo'),
    path('historial/<int:codigo>/', HistorialAfiliadoView.as_view(), name='historial'),
    path('prestamo/<int:prestamo_id>/abono-manual/', AbonoManualCreateView.as_view(), name='abono_manual'),
]
