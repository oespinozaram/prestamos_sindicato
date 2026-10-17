from django.contrib import admin
from afiliados.models import Afiliado
from prestamos.models import Prestamo


class PrestamoInline(admin.TabularInline):
    """Muestra el estado de cuenta dentro del expediente del afiliado."""
    model = Prestamo
    extra = 0
    can_delete = False
    fields = (
        "num_incidencia", "num_periodos", "monto_descontar_qna",
        "inicia_qna", "termina_qna", "importe_original",
        "acumulado_pagado", "saldo_actual", "estado_prestamo"
    )
    readonly_fields = fields
    verbose_name = "Préstamo / Incidencia"
    verbose_name_plural = "Estado de Cuenta (Préstamos Registrados)"

    def has_add_permission(self, request, obj=None):
        return False

@admin.register(Afiliado)
class AfiliadoAdmin(admin.ModelAdmin):
    list_display = (
        "codigo", "numero_trabajador", "nombre_completo",
        "tipo_personal_nomina", "area_codigo", "mostrar_rfc_seguro",
        "consentimiento_expreso", "activo",
    )
    list_filter = (
        "tipo_personal_nomina", "activo", "consentimiento_expreso", "sexo", "personal",
    )
    search_fields = ("^codigo", "^numero_trabajador", "nombre_completo", "area_codigo")
    ordering = ("nombre_completo",)
    list_per_page = 50
    inlines = [PrestamoInline]

    fieldsets = (
        ("Identificación Institucional", {
            "fields": (("codigo", "numero_trabajador"), ("nombre_completo", "sexo"), ("tipo_personal_nomina", "activo"))
        }),
        ("Datos Personales Sensibles (PII)", {
            "fields": ("rfc", "curp", "imss"),
        }),
        ("Adscripción y Datos Laborales", {
            "fields": (("plaza", "personal", "actividad"), ("area_codigo", "area_nombre"), ("puesto_codigo", "puesto_nombre"))
        }),
        ("Gobernanza y Privacidad", {
            "fields": (("consentimiento_expreso", "fecha_consentimiento"), ("creado_en", "actualizado_en")),
            "classes": ("collapse",),
        }),
    )

    readonly_fields = ("creado_en", "actualizado_en")

    @admin.display(description="RFC (Enmascarado)")
    def mostrar_rfc_seguro(self, obj: Afiliado) -> str:
        return obj.rfc_enmascarado

    def get_readonly_fields(self, request, obj=None):
        ro_fields = list(super().get_readonly_fields(request, obj))
        if obj:
            ro_fields.append("codigo")
        # Aquí puedes agregar validación de permisos si la necesitas
        return ro_fields
