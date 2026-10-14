from django.db import models
from afiliados.models import Afiliado
from django.core.validators import FileExtensionValidator
from django.conf import settings
from decimal import Decimal


class LoteImportacion(models.Model):
    class TipoLote(models.TextChoices):
        ANEXOS = 'ANEXOS', '1. Anexos de Descuento (Padrón y Abonos Qna)'
        SALDOS = 'SALDOS', '2. Saldos de Descuento (Cartera Vigente)'
        PAGADOS = 'PAGADOS', '3. Préstamos Pagados (Liquidaciones)'

    tipo_lote = models.CharField(
        max_length=15, choices=TipoLote.choices, verbose_name="Tipo de Reporte"
    )
    anio = models.PositiveSmallIntegerField(default=2026, verbose_name="Año")
    quincena = models.PositiveSmallIntegerField(default=18, verbose_name="Quincena")
    archivo_origen = models.FileField(
        upload_to="lotes_nomina/%Y/%m/",
        validators=[FileExtensionValidator(allowed_extensions=["csv", "pdf"])],
        verbose_name="Archivo (CSV o PDF)",
        help_text="Puedes subir directamente el PDF oficial de la UAN o el archivo CSV limpio."
    )
    registros_procesados = models.PositiveIntegerField(default=0, editable=False)
    revertido = models.BooleanField(default=False, editable=False)
    subido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, editable=False
    )
    fecha_carga = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "prestamos_lotes"
        verbose_name = "Lote de Importación"
        verbose_name_plural = "Carga de Lotes (PDF / CSV)"
        ordering = ["-fecha_carga"]

    def __str__(self):
        estado = "REVERTIDO" if self.revertido else "APLICADO"
        return f"Lote #{self.id} - {self.tipo_lote} (Qna {self.quincena}/{self.anio}) [{estado}]"


class Prestamo(models.Model):
    afiliado = models.ForeignKey(
        Afiliado, on_delete=models.PROTECT, related_name="prestamos"
    )
    clave_descuento = models.PositiveSmallIntegerField(default=68)
    num_incidencia = models.PositiveIntegerField(verbose_name="Folio de Incidencia (NUM. INC.)")
    num_periodos = models.PositiveSmallIntegerField(default=20, verbose_name="Plazo Quincenas (NUM. PER.)")
    monto_descontar_qna = models.DecimalField(max_digits=10, decimal_places=2)
    inicia_qna = models.CharField(max_length=10)  # Ej. "08-2026"
    termina_qna = models.CharField(max_length=10)  # Ej. "03-2027"
    batch = models.CharField(max_length=10, default="476C")

    importe_original = models.DecimalField(max_digits=12, decimal_places=2)
    acumulado_pagado = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    saldo_actual = models.DecimalField(max_digits=12, decimal_places=2)
    num_periodos = models.PositiveSmallIntegerField(default=20, verbose_name="Plazo Quincenas")
    liquidado = models.BooleanField(default=False)
    actualizado_en = models.DateTimeField(auto_now=True)

    @property
    def monto_pagado(self) -> Decimal:
        """Suma de todos los abonos (HABER) vinculados a este préstamo"""
        abonos = self.abonos.filter(lote__revertido=False).aggregate(
            total=models.Sum('monto_descontado')
        )['total']
        # Forzamos conversión segura a Decimal
        return Decimal(str(abonos)) if abonos else Decimal('0.00')

    @property
    def monto_restante(self) -> Decimal:
        """Lo que debe actualmente (DEBE - HABER)"""
        # Blindaje: Forzamos el importe original a Decimal por si la BD devuelve float (ej. SQLite)
        importe = Decimal(str(self.importe_original or '0.00'))
        return importe - self.monto_pagado

    @property
    def quincenas_pagadas(self) -> int:
        """Cuenta cuántos abonos quincenales válidos se han registrado"""
        return self.abonos.filter(lote__revertido=False, monto_descontado__gt=0).count()

    @property
    def quincenas_restantes(self) -> int:
        """Calcula cuántas quincenas le faltan"""
        periodos = self.num_periodos or 20
        restantes = periodos - self.quincenas_pagadas
        return restantes if restantes > 0 else 0

    def save(self, *args, **kwargs):
        # Auto-cálculo de seguridad antes de guardar
        if self.pk:
            self.acumulado_pagado = self.monto_pagado
            self.saldo_actual = self.monto_restante
            if self.saldo_actual <= 0:
                self.liquidado = True
        super().save(*args, **kwargs)

    class Meta:
        db_table = "prestamos_cartera"
        constraints = [
            models.UniqueConstraint(
                fields=["afiliado", "num_incidencia", "inicia_qna"],
                name="uq_afiliado_incidencia_inicio"
            )
        ]


class MovimientoDescuento(models.Model):
    """
    Registra tanto la aportación al fondo (Clave 67) como el abono quincenal
    al préstamo (Clave 68) extraídos del CSV de Anexos de Descuento.
    """
    lote = models.ForeignKey(LoteImportacion, on_delete=models.CASCADE, related_name="movimientos")
    afiliado = models.ForeignKey(Afiliado, on_delete=models.PROTECT, related_name="movimientos")
    prestamo = models.ForeignKey(
        Prestamo, on_delete=models.SET_NULL, null=True, blank=True, related_name="abonos"
    )
    clave = models.PositiveSmallIntegerField(help_text="67 = Aportación Fondo, 68 = Abono Préstamo")
    num_incidencia = models.PositiveIntegerField(default=1)
    anio = models.PositiveSmallIntegerField()
    quincena = models.PositiveSmallIntegerField()
    batch = models.CharField(max_length=10, default="476C")

    monto_programado = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    monto_descontado = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    diferencia = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        db_table = "prestamos_movimientos"
        verbose_name = "Movimiento / Descuento Quincenal"
        verbose_name_plural = "Movimientos y Abonos Quincenales"
