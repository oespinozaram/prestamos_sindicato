from django.db.models import Max
from django.views.generic import ListView, CreateView, DetailView
from django.contrib.auth.mixins import UserPassesTestMixin
from prestamos.models import Prestamo, Afiliado, MovimientoDescuento
from .forms import PrestamoForm, AbonoManualForm
from django.urls import reverse_lazy
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone


class PrestamoCreateView(CreateView):
    model = Prestamo
    form_class = PrestamoForm
    template_name = "prestamos/prestamo_form.html"
    success_url = reverse_lazy("prestamos:dashboard")

    def form_valid(self, form):
        prestamo = form.save(commit=False)

        # Generar 'num_incidencia' automático e invisible para el usuario
        max_inc = Prestamo.objects.filter(afiliado=prestamo.afiliado).aggregate(
            maximo=Max('num_incidencia')
        )['maximo'] or 0
        prestamo.num_incidencia = max_inc + 1

        # Cálculo matemático automático del descuento quincenal
        if prestamo.num_periodos > 0:
            prestamo.monto_descontar_qna = prestamo.importe_original / prestamo.num_periodos

        prestamo.saldo_actual = prestamo.importe_original
        prestamo.save()
        return super().form_valid(form)


class HistorialAfiliadoView(DetailView):
    model = Afiliado
    template_name = "prestamos/historial.html"
    context_object_name = "afiliado"
    pk_url_kwarg = "codigo"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        afiliado = self.get_object()

        # Traemos los préstamos ordenados del más reciente al más antiguo
        prestamos = afiliado.prestamos.all().order_by('-id')

        libros_mayores = []

        for p in prestamos:
            entradas = []

            # 1. Fila inicial: El Cargo (DEBE)
            saldo_corriente = p.importe_original
            entradas.append({
                'fecha': f"Qna {p.inicia_qna}",
                'concepto': f"Otorgamiento de Préstamo (Folio {p.num_incidencia})",
                'debe': p.importe_original,
                'haber': 0,
                'saldo': saldo_corriente
            })

            # 2. Filas subsecuentes: Los Abonos (HABER) importados de Anexos (Clave 68)
            abonos = p.abonos.filter(clave=68, lote__revertido=False).order_by('anio', 'quincena')

            for abono in abonos:
                saldo_corriente -= abono.monto_descontado
                entradas.append({
                    'fecha': f"Qna {abono.quincena:02d}-{abono.anio}",
                    'concepto': "Descuento por Nómina (Anexos - Clave 68)",
                    'debe': 0,
                    'haber': abono.monto_descontado,
                    'saldo': saldo_corriente
                })

            libros_mayores.append({
                'prestamo': p,
                'entradas': entradas,
                'saldo_final_calculado': saldo_corriente
            })

        context['libros_mayores'] = libros_mayores
        return context


class DashboardPrestamosView(ListView):
    model = Prestamo
    template_name = "prestamos/dashboard.html"
    context_object_name = "prestamos"

    def get_queryset(self):
        # Excluimos los liquidados para ver VIGENTES y CONGELADOS
        return Prestamo.objects.exclude(
            estado_prestamo=Prestamo.EstadoPrestamo.LIQUIDADO
        ).select_related('afiliado').order_by('afiliado__nombre_completo')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        cartera = self.get_queryset()

        # El resto del código se queda exactamente igual
        total_adeudado = sum(p.saldo_actual for p in cartera)

        activos = [p for p in cartera if p.afiliado.tipo_personal_nomina == 'N']
        jubilados = [p for p in cartera if p.afiliado.tipo_personal_nomina == 'J']

        context['dashboard'] = {
            'total_adeudado': total_adeudado,
            'total_prestamos': len(cartera),
            'deuda_activos': sum(p.saldo_actual for p in activos),
            'casos_activos': len(activos),
            'deuda_jubilados': sum(p.saldo_actual for p in jubilados),
            'casos_jubilados': len(jubilados),
        }
        return context


class AbonoManualCreateView(UserPassesTestMixin, CreateView):
    model = MovimientoDescuento
    form_class = AbonoManualForm
    template_name = "prestamos/abono_manual_form.html"

    def test_func(self):
        # Antigravity restringe esto: Solo superusuarios o personal con permiso explícito
        return self.request.user.is_superuser or self.request.user.has_perm('prestamos.add_movimientodescuento')

    def form_valid(self, form):
        prestamo_id = self.kwargs.get('prestamo_id')
        prestamo = get_object_or_404(Prestamo, id=prestamo_id)

        abono = form.save(commit=False)
        abono.prestamo = prestamo
        abono.afiliado = prestamo.afiliado
        abono.clave = 99  # Clave 99 para identificar que es un movimiento manual interno

        # Guardamos la fecha actual como quincena/año referencial
        hoy = timezone.now()
        abono.anio = hoy.year
        # Cálculo simple de quincena (1 a 24) basado en el mes y día
        abono.quincena = (hoy.month * 2) - (1 if hoy.day <= 15 else 0)

        abono.save()

        # El modelo Prestamo (por el save() que modificamos antes) recalculará su saldo automáticamente
        prestamo.save()

        return super().form_valid(form)

    def get_success_url(self):
        # Regresar al expediente del afiliado
        afiliado_codigo = Prestamo.objects.get(id=self.kwargs.get('prestamo_id')).afiliado.codigo
        return reverse('prestamos:historial', kwargs={'codigo': afiliado_codigo})
