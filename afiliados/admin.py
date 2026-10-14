from django.contrib import admin
from afiliados.models import Afiliado
from prestamos.models import Prestamo


class PrestamoInline(admin.TabularInline):
    """
    Muestra el estado de cuenta (cartera de préstamos) directamente
    dentro del expediente del afiliado. Bloqueado contra edición manual.
    """
    model = Prestamo
    extra = 0
    can_delete = False
    fields = (
        "num_incidencia", "clave_descuento", "num_periodos",
        "monto_descontar_qna", "inicia_qna", "termina_qna",
        "importe_original", "acumulado_pagado", "saldo_actual", "liquidado"
    )
    readonly_fields = fields
    verbose_name = "Préstamo / Incidencia"
    verbose_name_plural = "Estado de Cuenta (Préstamos Registrados)"

    def has_add_permission(self, request, obj=None):
        # Los préstamos solo nacen por ingesta de lotes CSV/PDF, no a mano
        return False


@admin.register(Afiliado)
class AfiliadoAdmin(admin.ModelAdmin):
    list_display = (
        "codigo",
        "numero_trabajador",
        "nombre_completo",
        "tipo_personal_nomina",
        "area_codigo",
        "mostrar_rfc_seguro",
        "consentimiento_expreso",
        "activo",
    )
    list_filter = (
        "tipo_personal_nomina",
        "activo",
        "consentimiento_expreso",
        "sexo",
        "personal",
    )
    search_fields = (
        "^codigo",              # Búsqueda exacta/prefijo rápida por código (Ej. 60590)
        "^numero_trabajador",   # Búsqueda rápida por No. Trabajador (Ej. 4813)
        "nombre_completo",
        "area_codigo",
    )
    ordering = ("nombre_completo",)
    list_per_page = 50
    inlines = [PrestamoInline]

    # Agrupación lógica del expediente siguiendo el Recibo de Nómina e ISO 27001
    fieldsets = (
        ("Identificación Institucional (UAN / SETUAN)", {
            "fields": (
                ("codigo", "numero_trabajador"),
                ("nombre_completo", "sexo"),
                ("tipo_personal_nomina", "activo"),
            )
        }),
        ("Datos Personales Sensibles (PII - ISO 27001 A.5.34)", {
            "description": "Información protegida. Su visualización y edición requiere privilegios especiales.",
            "fields": ("rfc", "curp", "imss"),
        }),
        ("Adscripción y Datos Laborales", {
            "fields": (
                ("plaza", "personal", "actividad"),
                ("area_codigo", "area_nombre"),
                ("puesto_codigo", "puesto_nombre"),
            )
        }),
        ("Gobernanza y Privacidad (ISO 27001 A.8.10)", {
            "fields": (
                ("consentimiento_expreso", "fecha_consentimiento"),
                ("creado_en", "actualizado_en"),
            ),
            "classes": ("collapse",),
        }),
    )

    readonly_fields = ("creado_en", "actualizado_en")

    @admin.display(description="RFC (Enmascarado)")
    def mostrar_rfc_seguro(self, obj: Afiliado) -> str:
        return obj.rfc_enmascarado

    def get_readonly_fields(self, request, obj=None):
        """
        Control ISO 27001 A.5.15:
        Si el usuario edita un registro existente, 'codigo' es inmutable.
        Si no tiene permiso 'view_pii_afiliado', no puede editar PII.
        """
        ro_fields = list(super().get_readonly_fields(request, obj))
        if obj:
            ro_fields.append("codigo")

        if not request.user.has_perm("padron.view_pii_afiliado") and not request.user.is_superuser:
            ro_fields.extend(["rfc_enmascarado", "curp_enmascarada"])

        return ro_fields

    def get_fieldsets(self, request, obj=None):
        """
        Control ISO 27001 A.8.11:
        Reemplaza los campos reales de RFC/CURP/IMSS por las propiedades enmascaradas
        si el operador no cuenta con el permiso explícito para ver datos sensibles.
        """
        fieldsets = super().get_fieldsets(request, obj)
        if not request.user.has_perm("padron.view_pii_afiliado") and not request.user.is_superuser:
            return (
                fieldsets[0],
                ("Datos Personales Sensibles (Enmascarados - ISO 27001 A.8.11)", {
                    "description": "No cuenta con permisos para visualizar ni editar PII en texto claro.",
                    "fields": ("rfc_enmascarado", "curp_enmascarada"),
                }),
                fieldsets[2],
                fieldsets[3],
            )
        return fieldsets
