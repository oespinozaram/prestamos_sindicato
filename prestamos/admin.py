from django.contrib import admin, messages
from django.db import transaction
from django.utils.html import format_html
from prestamos.models import LoteImportacion, Prestamo, MovimientoDescuento
from django.db.models import Sum, Count, Q
from django.utils.safestring import mark_safe
from prestamos.services.ingesta_service import procesar_lote_desde_admin


class MovimientoAbonoInline(admin.TabularInline):
    """Muestra los descuentos quincenales aplicados a un préstamo específico."""
    model = MovimientoDescuento
    extra = 0
    can_delete = False
    fields = ("anio", "quincena", "lote", "monto_programado", "monto_descontado", "diferencia")
    readonly_fields = fields
    verbose_name = "Abono Quincenal Aplicado"
    verbose_name_plural = "Historial de Abonos (Anexos)"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Prestamo)
class PrestamoAdmin(admin.ModelAdmin):
    list_display = (
        "num_incidencia", "afiliado", "inicia_qna",
        "formato_original", "formato_pagado", "formato_restante",
        "progreso_quincenas", "estado_visual"
    )
    search_fields = ("^afiliado__codigo", "afiliado__nombre_completo", "=num_incidencia")
    list_filter = ("liquidado", "afiliado__tipo_personal_nomina")
    autocomplete_fields = ["afiliado"]  # Buscador rápido de afiliados con lupa

    # Al crear un préstamo manual, solo pedimos lo básico:
    fields = (
        "afiliado", "num_incidencia", "importe_original",
        "inicia_qna", "termina_qna", "num_periodos"
    )

    def has_add_permission(self, request):
        return True  # Habilitamos que el operador pueda crear préstamos a mano

    def save_model(self, request, obj, form, change):
        """Al crear la solicitud, calculamos el descuento quincenal (Total / Quincenas)"""
        if not change:  # Si es un préstamo nuevo
            if obj.num_periodos > 0:
                # Calcula cuánto le van a descontar por quincena
                obj.monto_descontar_qna = obj.importe_original / obj.num_periodos
            obj.saldo_actual = obj.importe_original
        super().save_model(request, obj, form, change)

    # --- Columnas Visuales para el Admin ---
    @admin.display(description="Importe Solicitado (DEBE)")
    def formato_original(self, obj):
        valor = obj.importe_original or 0
        return f"${valor:,.2f}"

    @admin.display(description="Monto Pagado (HABER)")
    def formato_pagado(self, obj):
        valor = obj.monto_pagado or 0
        return f"${valor:,.2f}"

    @admin.display(description="Monto Restante (SALDO)")
    def formato_restante(self, obj):
        valor = obj.monto_restante or 0
        return f"${valor:,.2f}"

    @admin.display(description="Avance (Quincenas)")
    def progreso_quincenas(self, obj):
        return f"{obj.quincenas_pagadas} de {obj.num_periodos} (Faltan {obj.quincenas_restantes})"

    @admin.display(description="Estatus")
    def estado_visual(self, obj: Prestamo):
        if obj.liquidado or obj.saldo_actual <= 0:
            return mark_safe('<span style="color: green; font-weight: bold;">✔ LIQUIDADO</span>')
        return mark_safe('<span style="color: #d9534f; font-weight: bold;">● VIGENTE</span>')


    def changelist_view(self, request, extra_context=None):
        """Inyecta un Dashboard financiero arriba de la tabla de préstamos"""

        # 1. Total Global Adeudado (Cartera Vigente)
        cartera = Prestamo.objects.filter(liquidado=False)
        total_adeudado = cartera.aggregate(total=Sum('saldo_actual'))['total'] or 0
        total_prestamos = cartera.count()

        # 2. Desglose por Jubilados ('J') vs Activos/Nómina ('N')
        desglose = cartera.aggregate(
            deuda_activos=Sum('saldo_actual', filter=Q(afiliado__tipo_personal_nomina='N')),
            deuda_jubilados=Sum('saldo_actual', filter=Q(afiliado__tipo_personal_nomina='J')),
            casos_activos=Count('id', filter=Q(afiliado__tipo_personal_nomina='N')),
            casos_jubilados=Count('id', filter=Q(afiliado__tipo_personal_nomina='J'))
        )

        # Pasamos las variables al template
        extra_context = extra_context or {}
        extra_context['dashboard'] = {
            'total_adeudado': f"${total_adeudado:,.2f}",
            'total_prestamos': total_prestamos,
            'deuda_activos': f"${desglose['deuda_activos'] or 0:,.2f}",
            'casos_activos': desglose['casos_activos'],
            'deuda_jubilados': f"${desglose['deuda_jubilados'] or 0:,.2f}",
            'casos_jubilados': desglose['casos_jubilados'],
        }

        return super().changelist_view(request, extra_context=extra_context)


@admin.register(LoteImportacion)
class LoteImportacionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tipo_lote",
        "quincena",
        "anio",
        "registros_procesados",
        "subido_por",
        "fecha_carga",
        "estado_lote",
    )
    list_filter = ("tipo_lote", "anio", "quincena", "revertido")
    actions = ["revertir_lotes_seleccionados"]

    fieldsets = (
        ("Subir Reporte Quincenal (PDF o CSV)", {
            "description": (
                "Seleccione el tipo de reporte y suba el archivo PDF original de la UAN "
                "o el archivo CSV. El sistema actualizará el Padrón y los Estados de Cuenta automáticamente."
            ),
            "fields": ("tipo_lote", ("anio", "quincena"), "archivo_origen"),
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        # Si el lote ya fue creado y procesado, bloqueamos su edición para proteger la auditoría
        if obj:
            return ("tipo_lote", "anio", "quincena", "archivo_origen", "registros_procesados", "subido_por", "fecha_carga")
        return ()

    @admin.display(description="Estatus")
    def estado_lote(self, obj: LoteImportacion):
        if obj.revertido:
            return mark_safe('<span style="color: #888; text-decoration: line-through;">REVERTIDO</span>')
        return mark_safe('<span style="color: green; font-weight: bold;">✔ APLICADO</span>')

    def save_model(self, request, obj: LoteImportacion, form, change):
        """Se dispara automáticamente cuando el usuario hace clic en 'Guardar' en el Admin."""
        if not change:  # Solo al crear un lote nuevo
            obj.subido_por = request.user
            super().save_model(request, obj, form, change)
            try:
                total = procesar_lote_desde_admin(obj)
                self.message_user(
                    request,
                    f"¡Éxito! El lote {obj.get_tipo_lote_display()} se procesó correctamente: "
                    f"{total} registros sincronizados en el Padrón y Estado de Cuenta.",
                    level=messages.SUCCESS,
                )
            except Exception as e:
                # Si ocurre un error en el archivo, borramos el registro del lote fallido y avisamos al usuario
                obj.delete()
                self.message_user(
                    request,
                    f"Error al procesar el archivo: {str(e)}. Verifique que el formato corresponda a {obj.tipo_lote}.",
                    level=messages.ERROR,
                )
        else:
            super().save_model(request, obj, form, change)

    @admin.action(description="⟲ Revertir lotes seleccionados (Deshacer movimientos)")
    def revertir_lotes_seleccionados(self, request, queryset):
        revertidos = 0
        with transaction.atomic():
            for lote in queryset.filter(revertido=False):
                # Eliminar los movimientos generados por este lote y marcarlo como revertido
                lote.movimientos.all().delete()
                lote.revertido = True
                lote.save(update_fields=["revertido"])
                revertidos += 1

        self.message_user(
            request,
            f"Se revirtieron {revertidos} lotes y se limpiaron sus movimientos asociados.",
            level=messages.WARNING,
        )
