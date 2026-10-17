import logging
from django.db import transaction
from pdfminer.high_level import extract_text
from prestamos.models import LoteImportacion
from .services.etl_service import procesar_saldos, procesar_pagados, procesar_anexos

logger = logging.getLogger(__name__)


def ejecutar_etl_lote(lote_id):
    try:
        lote = LoteImportacion.objects.get(id=lote_id)
        lote.estado = LoteImportacion.EstadoProcesamiento.PROCESANDO
        lote.save(update_fields=['estado'])

        # Extracción pura de texto del PDF
        texto_crudo = extract_text(lote.archivo_origen.path)

        with transaction.atomic():
            if lote.tipo_lote == LoteImportacion.TipoLote.SALDOS:
                registros = procesar_saldos(texto_crudo, lote)
            elif lote.tipo_lote == LoteImportacion.TipoLote.PAGADOS:
                registros = procesar_pagados(texto_crudo, lote)
            elif lote.tipo_lote == LoteImportacion.TipoLote.ANEXOS:
                registros = procesar_anexos(texto_crudo, lote)

        lote.registros_procesados = registros
        lote.estado = LoteImportacion.EstadoProcesamiento.COMPLETADO
        lote.log_procesamiento = f"Extracción exitosa. {registros} registros procesados."
        lote.save(update_fields=['estado', 'registros_procesados', 'log_procesamiento'])

    except Exception as e:
        logger.error(f"Error en Lote {lote_id}: {str(e)}")
        lote.estado = LoteImportacion.EstadoProcesamiento.ERROR
        lote.log_procesamiento = f"Error crítico: {str(e)}"
        lote.save(update_fields=['estado', 'log_procesamiento'])