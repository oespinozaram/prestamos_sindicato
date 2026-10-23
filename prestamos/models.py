from django.db import models
from afiliados.models import Afiliado
from django.core.validators import FileExtensionValidator
from django.conf import settings


class LoteImportacion(models.Model):
    class TipoLote(models.TextChoices):
        SALDOS = 'SALDOS', '1. Saldos de Descuento (Fotografía Cartera)'
        PAGADOS = 'PAGADOS', '2. Préstamos Pagados (Cierre Expedientes)'
        ANEXOS = 'ANEXOS', '3. Anexos de Descuento (Abonos y Estatus Padrón)'

    class EstadoProcesamiento(models.TextChoices):
        PENDIENTE = 'PENDIENTE', 'En Cola de Espera'
        PROCESANDO = 'PROCESANDO', 'Extrayendo PDF...'
        COMPLETADO = 'COMPLETADO', 'Completado con Éxito'
        ERROR = 'ERROR', 'Falló la Extracción'

    tipo_lote = models.CharField(max_length=15, choices=TipoLote.choices)
    anio = models.PositiveSmallIntegerField()
    quincena = models.PositiveSmallIntegerField()
    archivo_origen = models.FileField(
        upload_to="lotes_nomina/%Y/%m/",
        validators=[FileExtensionValidator(allowed_extensions=["csv"])]
    )

    # Nuevos campos para orquestación en segundo plano
    estado = models.CharField(
        max_length=15, choices=EstadoProcesamiento.choices, default=EstadoProcesamiento.PENDIENTE
    )
    task_id = models.CharField(max_length=100, null=True, blank=True, help_text="ID de la tarea en Django-Q")
    log_procesamiento = models.TextField(null=True, blank=True, help_text="Registro de errores o resumen del ETL")

    registros_procesados = models.PositiveIntegerField(default=0)
    revertido = models.BooleanField(default=False)
    subido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    fecha_carga = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "prestamos_lotes"
        ordering = ["-fecha_carga"]


class Prestamo(models.Model):
    class EstadoPrestamo(models.TextChoices):
        VIGENTE = 'VIGENTE', 'Vigente (Descontando)'
        LIQUIDADO = 'LIQUIDADO', 'Liquidado'
        CONGELADO = 'CONGELADO', 'Congelado (Afiliado Inactivo)'

    afiliado = models.ForeignKey(Afiliado, on_delete=models.PROTECT, related_name="prestamos")
    num_incidencia = models.PositiveIntegerField()
    num_periodos = models.PositiveSmallIntegerField(default=20)
    monto_descontar_qna = models.DecimalField(max_digits=10, decimal_places=2)
    inicia_qna = models.CharField(max_length=10)
    termina_qna = models.CharField(max_length=10, null=True, blank=True)

    importe_original = models.DecimalField(max_digits=12, decimal_places=2)
    acumulado_pagado = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    saldo_actual = models.DecimalField(max_digits=12, decimal_places=2)

    # Nueva máquina de estados
    estado_prestamo = models.CharField(
        max_length=15, choices=EstadoPrestamo.choices, default=EstadoPrestamo.VIGENTE
    )
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "prestamos_cartera"
        constraints = [
            models.UniqueConstraint(
                fields=["afiliado", "num_incidencia", "inicia_qna"],
                name="uq_afiliado_incidencia_inicio"
            )
        ]

    def save(self, *args, **kwargs):
        # Auto-transición a LIQUIDADO si el saldo llega a 0 y estaba vigente o congelado
        if self.saldo_actual <= 0 and self.estado_prestamo != self.EstadoPrestamo.LIQUIDADO:
            self.estado_prestamo = self.EstadoPrestamo.LIQUIDADO
            self.saldo_actual = 0

        # Si el afiliado se desactiva (pierde el movimiento 67), congelamos si hay saldo
        if not self.afiliado.activo and self.saldo_actual > 0:
            self.estado_prestamo = self.EstadoPrestamo.CONGELADO

        super().save(*args, **kwargs)


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
