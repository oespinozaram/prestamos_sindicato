from django.contrib import admin
from django.utils.safestring import mark_safe
from prestamos.models import LoteImportacion, Prestamo
from django_q.tasks import async_task


@admin.register(Prestamo)
class PrestamoAdmin(admin.ModelAdmin):
    list_display = (
        "num_incidencia", "afiliado", "inicia_qna",
        "formato_original", "formato_pagado", "formato_restante",
        "estado_visual"
    )
    search_fields = ("^afiliado__codigo", "afiliado__nombre_completo", "=num_incidencia")
    list_filter = ("estado_prestamo", "afiliado__tipo_personal_nomina")  # Cambiado a estado_prestamo
    autocomplete_fields = ["afiliado"]

    fields = (
        "afiliado", "num_incidencia", "importe_original",
        "inicia_qna", "termina_qna", "num_periodos"
    )

    def has_add_permission(self, request):
        return True

    def save_model(self, request, obj, form, change):
        if not change:
            if obj.num_periodos > 0:
                obj.monto_descontar_qna = obj.importe_original / obj.num_periodos
            obj.saldo_actual = obj.importe_original
        super().save_model(request, obj, form, change)

    @admin.display(description="Importe Solicitado (DEBE)")
    def formato_original(self, obj):
        valor = obj.importe_original or 0
        return f"${valor:,.2f}"

    @admin.display(description="Monto Pagado (HABER)")
    def formato_pagado(self, obj):
        valor = obj.acumulado_pagado or 0
        return f"${valor:,.2f}"

    @admin.display(description="Monto Restante (SALDO)")
    def formato_restante(self, obj):
        valor = obj.saldo_actual or 0
        return f"${valor:,.2f}"

    @admin.display(description="Estatus")
    def estado_visual(self, obj: Prestamo):
        # Nueva máquina de estados
        if obj.estado_prestamo == Prestamo.EstadoPrestamo.LIQUIDADO:
            return mark_safe('<span style="color: green; font-weight: bold;">✔ LIQUIDADO</span>')
        elif obj.estado_prestamo == Prestamo.EstadoPrestamo.CONGELADO:
            return mark_safe('<span style="color: #FF9800; font-weight: bold;">❄ CONGELADO</span>')
        return mark_safe('<span style="color: #d9534f; font-weight: bold;">● VIGENTE</span>')


@admin.register(LoteImportacion)
class LoteImportacionAdmin(admin.ModelAdmin):
    list_display = (
        "id", "tipo_lote", "quincena", "anio",
        "estado_lote", "registros_procesados", "fecha_carga"
    )
    list_filter = ("tipo_lote", "estado", "anio", "quincena")

    fieldsets = (
        ("Cargar Reporte Quincenal", {
            "fields": ("tipo_lote", ("anio", "quincena"), "archivo_origen"),
        }),
        ("Orquestación en Segundo Plano", {
            "fields": ("estado", "task_id", "registros_procesados", "log_procesamiento"),
            "classes": ("collapse",),
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ("tipo_lote", "anio", "quincena", "archivo_origen", "estado", "task_id", "registros_procesados",
                    "log_procesamiento")
        return ("estado", "task_id", "registros_procesados", "log_procesamiento")

    @admin.display(description="Estatus de Extracción")
    def estado_lote(self, obj: LoteImportacion):
        if obj.estado == LoteImportacion.EstadoProcesamiento.COMPLETADO:
            return mark_safe('<span style="color: green; font-weight: bold;">✔ COMPLETADO</span>')
        elif obj.estado == LoteImportacion.EstadoProcesamiento.ERROR:
            return mark_safe('<span style="color: red; font-weight: bold;">✖ ERROR</span>')
        elif obj.estado == LoteImportacion.EstadoProcesamiento.PROCESANDO:
            return mark_safe('<span style="color: #2196F3; font-weight: bold;">↻ EXTRAYENDO...</span>')
        return mark_safe('<span style="color: #888;">⏳ EN COLA</span>')

    def save_model(self, request, obj, form, change):
        es_nuevo = obj.pk is None
        super().save_model(request, obj, form, change)

        if es_nuevo:
            task_id = async_task('prestamos.tasks.ejecutar_etl_lote', obj.id)
            obj.task_id = task_id
            obj.save(update_fields=['task_id'])
            self.message_user(request,
                              f"El archivo fue encolado para extracción en segundo plano. (Task ID: {task_id[:8]})")

