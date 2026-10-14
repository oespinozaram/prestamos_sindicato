from django.db import models
from django.core.validators import RegexValidator


class Afiliado(models.Model):
    """
    Padrón Maestro de Afiliados (SETUAN).
    Diseñado bajo principios de minimización de datos (ISO 27001 A.8.10 y A.5.34).
    """
    class SexoChoices(models.TextChoices):
        FEMENINO = 'F', 'Femenino'
        MASCULINO = 'M', 'Masculino'

    class TipoPersonalChoices(models.TextChoices):
        NOMINA_BASE = 'N', 'Nómina / Base'
        JUBILADO = 'J', 'Jubilado'
        PENSIONADO = 'P', 'Pensionado / Contrato'

    # --- 1. Identificadores Institucionales ---
    # En los PDFs de descuento viene como 'no_plaza', en el recibo es 'CODIGO' (Ej. 60590)
    codigo = models.PositiveIntegerField(
        primary_key=True,
        verbose_name="Código / No. Plaza en Reportes",
        help_text="Identificador principal que cruza con los reportes de nómina (Ej. 60590)"
    )
    numero_trabajador = models.PositiveIntegerField(
        unique=True, null=True, blank=True, db_index=True,
        verbose_name="Número de Trabajador (NO.TRAB.)",
        help_text="Obtenido del recibo de nómina (Ej. 4813)"
    )

    # --- 2. Datos de Identidad ---
    nombre_completo = models.CharField(
        max_length=200, db_index=True,
        verbose_name="Nombre Completo"
    )
    sexo = models.CharField(
        max_length=1, choices=SexoChoices.choices, null=True, blank=True,
        verbose_name="Sexo"
    )

    # --- 3. Datos Personales Sensibles (PII - Control ISO 27001 A.5.34) ---
    # Nota: En producción se recomienda envolver estos 3 campos con django-fernet-encrypted-fields
    rfc = models.CharField(
        max_length=13, unique=True, null=True, blank=True,
        validators=[RegexValidator(r'^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$', 'Formato de RFC inválido')],
        verbose_name="RFC"
    )
    curp = models.CharField(
        max_length=18, unique=True, null=True, blank=True,
        validators=[RegexValidator(r'^[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d$', 'Formato de CURP inválido')],
        verbose_name="CURP"
    )
    imss = models.CharField(
        max_length=11, unique=True, null=True, blank=True,
        validators=[RegexValidator(r'^\d{11}$', 'El NSS del IMSS debe tener 11 dígitos')],
        verbose_name="Número de Seguro Social (IMSS)"
    )

    # --- 4. Datos Laborales (Mapeados del Recibo y CSV de Anexos) ---
    plaza = models.CharField(
        max_length=100, null=True, blank=True,
        verbose_name="Plaza",
        help_text="Ej. TIEMPO COMPLETO, MEDIO TIEMPO"
    )
    area_codigo = models.CharField(
        max_length=10, null=True, blank=True, db_index=True,
        verbose_name="Código de Área",
        help_text="Extraído de Anexos o Recibo (Ej. 846)"
    )
    area_nombre = models.CharField(
        max_length=150, null=True, blank=True,
        verbose_name="Nombre del Área",
        help_text="Ej. DIRECCION DE COMPRAS Y ADQUISICIONES"
    )
    actividad = models.CharField(
        max_length=100, null=True, blank=True,
        verbose_name="Actividad",
        help_text="Ej. ADMINISTRATIVO"
    )
    puesto_codigo = models.CharField(
        max_length=20, null=True, blank=True,
        verbose_name="Código de Puesto",
        help_text="Ej. 185"
    )
    puesto_nombre = models.CharField(
        max_length=120, null=True, blank=True,
        verbose_name="Descripción del Puesto",
        help_text="Ej. SECRETARIA"
    )
    personal = models.CharField(
        max_length=100, null=True, blank=True,
        verbose_name="Personal",
        help_text="Ej. ADMINISTRATIVO"
    )
    tipo_personal_nomina = models.CharField(
        max_length=1, choices=TipoPersonalChoices.choices, default=TipoPersonalChoices.NOMINA_BASE,
        verbose_name="Clave Tipo Personal (N/J/P)"
    )

    # --- 5. Gobernanza y Privacidad (ISO 27001 A.5.34 / A.8.15) ---
    consentimiento_expreso = models.BooleanField(
        default=False,
        verbose_name="Consentimiento Expreso Firmado",
        help_text="Requerido para recolectar datos adicionales fuera del padrón base."
    )
    fecha_consentimiento = models.DateTimeField(null=True, blank=True)
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "padron_afiliados"
        verbose_name = "Afiliado"
        verbose_name_plural = "Padrón de Afiliados"
        ordering = ["nombre_completo"]
        permissions = [
            ("view_pii_afiliado", "Puede visualizar RFC, CURP e IMSS sin enmascarar (ISO A.8.11)"),
        ]

    def __str__(self):
        return f"{self.codigo} - {self.nombre_completo}"

    # Control ISO 27001 A.8.11: Enmascaramiento de datos por defecto
    @property
    def rfc_enmascarado(self) -> str:
        if not self.rfc or len(self.rfc) < 10:
            return "No registrado"
        return f"{self.rfc[:4]}******{self.rfc[-3:]}"

    @property
    def curp_enmascarada(self) -> str:
        if not self.curp or len(self.curp) < 10:
            return "No registrado"
        return f"{self.curp[:4]}**********{self.curp[-4:]}"
