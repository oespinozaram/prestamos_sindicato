import csv
import io
import re
from decimal import Decimal
from django.db import transaction
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer

from afiliados.models import Afiliado
from prestamos.models import LoteImportacion, Prestamo, MovimientoDescuento


def limpiar_decimal(valor) -> Decimal:
    limpio = re.sub(r'[^0-9\.\-]', '', str(valor or ''))
    return Decimal(limpio) if limpio else Decimal('0.00')


def parsear_pdf_en_memoria(ruta_pdf: str, tipo_lote: str) -> list[dict]:
    """Si el usuario sube el PDF directo en el Admin, lo convierte a diccionarios limpios."""
    filas = []
    tolerancia = 3.0 if tipo_lote == 'ANEXOS' else 3.5

    for pagina in extract_pages(ruta_pdf):
        cajas = [e for e in pagina if isinstance(e, LTTextContainer)]
        lineas = {}
        for caja in cajas:
            y = caja.y0
            encontrado = False
            for k in lineas:
                if abs(k - y) < tolerancia:
                    lineas[k].append(caja)
                    encontrado = True
                    break
            if not encontrado:
                lineas[y] = [caja]

        for y in sorted(lineas.keys(), reverse=True):
            items = sorted(lineas[y], key=lambda c: c.x0)
            if not items:
                continue

            if tipo_lote == 'ANEXOS':
                texto_ini = items[0].get_text().strip()
                partes = texto_ini.split(None, 1)
                if not partes or not partes[0].isdigit() or not (4 <= len(partes[0]) <= 6):
                    continue
                reg = {
                    'no_plaza': partes[0],
                    'nombre': partes[1].replace('\n', ' ').strip() if len(partes) > 1 else '',
                    'clave': '68', 'tipo_personal': 'N', 'incide': '1', 'per': 'A',
                    'area': '', 'batch': '476C', 'anio': '2026', 'quincena': '18',
                    'programado': '0.00', 'descontado': '0.00', 'diferencia': '0.00'
                }
                for item in items[1:]:
                    x, txt = item.x0, item.get_text().strip()
                    if not txt:
                        continue
                    if x < 268: reg['clave'] = txt
                    elif x < 290: reg['tipo_personal'] = txt
                    elif x < 322: reg['incide'] = txt
                    elif x < 345: reg['per'] = txt
                    elif x < 375: reg['area'] = txt
                    elif x < 408: reg['batch'] = txt
                    elif x < 442: reg['anio'] = txt
                    elif x < 475: reg['quincena'] = txt
                    elif x < 548: reg['programado'] = txt
                    elif x < 615: reg['descontado'] = txt
                    elif x < 680: reg['diferencia'] = txt
                filas.append(reg)

            else:  # SALDOS o PAGADOS
                reg = {
                    'per': '', 'no_plaza': '', 'nombre': '', 'clave': '68',
                    'tipo_personal': 'N', 'num_inc': '1', 'num_per': '20',
                    'monto_descontar': '0.00', 'inicia_qna': '', 'termina_qna': '',
                    'batch': '476C', 'importe': '0.00', 'acumulado': '0.00', 'saldo': '0.00'
                }
                for item in items:
                    x, txt = item.x0, item.get_text().strip()
                    if not txt:
                        continue
                    if x < 60:
                        reg['per'] = txt
                    elif x < 290:
                        partes = txt.split(None, 1)
                        if partes and partes[0].isdigit() and (4 <= len(partes[0]) <= 6):
                            reg['no_plaza'] = partes[0]
                            nom_raw = partes[1].replace('\n', ' ').strip() if len(partes) > 1 else ''
                            m_clv = re.search(r'^(.*?)\s+(67|68)$', nom_raw)
                            if m_clv:
                                reg['nombre'], reg['clave'] = m_clv.group(1).strip(), m_clv.group(2)
                            else:
                                reg['nombre'] = nom_raw
                    elif x < 315: reg['clave'] = txt
                    elif x < 327: reg['tipo_personal'] = txt
                    elif x < 355: reg['num_inc'] = txt
                    elif x < 385: reg['num_per'] = txt
                    elif x < 440: reg['monto_descontar'] = txt
                    elif x < 490: reg['inicia_qna'] = txt.replace(" ", "")
                    elif x < 550: reg['termina_qna'] = txt.replace(" ", "")
                    elif x < 590: reg['batch'] = txt
                    elif x < 650: reg['importe'] = txt
                    elif x < 705: reg['acumulado'] = txt
                    else: reg['saldo'] = txt

                if reg['per'] == 'A' and reg['no_plaza'] != '':
                    filas.append(reg)

    return filas


@transaction.atomic
def procesar_lote_desde_admin(lote: LoteImportacion) -> int:
    """Lee el CSV o PDF subido en el Admin y actualiza Padrón y Cartera de Préstamos."""
    ruta_archivo = lote.archivo_origen.path
    es_pdf = ruta_archivo.lower().endswith('.pdf')

    if es_pdf:
        filas = parsear_pdf_en_memoria(ruta_archivo, lote.tipo_lote)
    else:
        with open(ruta_archivo, mode='r', encoding='utf-8-sig') as f:
            filas = list(csv.DictReader(f))

    procesados = 0

    for row in filas:
        codigo = int(row['no_plaza'])
        nombre = row['nombre'].strip()
        tipo_pers = (row.get('tipo_personal') or 'N').strip()

        # 1. Asegurar o actualizar el afiliado en el Padrón
        defaults_afiliado = {
            'nombre_completo': nombre,
            'tipo_personal_nomina': tipo_pers,
        }
        if row.get('area'):
            defaults_afiliado['area_codigo'] = row['area'].strip()

        afiliado, _ = Afiliado.objects.update_or_create(
            codigo=codigo,
            defaults=defaults_afiliado
        )

        # 2. Aplicar reglas de negocio según el tipo de lote
        if lote.tipo_lote in [LoteImportacion.TipoLote.SALDOS, LoteImportacion.TipoLote.PAGADOS]:
            num_inc = int(row.get('num_inc') or 1)
            inicia_qna = row.get('inicia_qna', '').strip()
            saldo = Decimal('0.00') if lote.tipo_lote == 'PAGADOS' else limpiar_decimal(row.get('saldo'))

            Prestamo.objects.update_or_create(
                afiliado=afiliado,
                num_incidencia=num_inc,
                inicia_qna=inicia_qna,
                defaults={
                    'clave_descuento': int(row.get('clave') or 68),
                    'num_periodos': int(row.get('num_per') or 20),
                    'monto_descontar_qna': limpiar_decimal(row.get('monto_descontar')),
                    'termina_qna': row.get('termina_qna', '').strip(),
                    'batch': row.get('batch', '476C').strip(),
                    'importe_original': limpiar_decimal(row.get('importe')),
                    'acumulado_pagado': limpiar_decimal(row.get('acumulado')),
                    'saldo_actual': saldo,
                    'liquidado': (saldo == Decimal('0.00') or lote.tipo_lote == 'PAGADOS'),
                }
            )

        elif lote.tipo_lote == LoteImportacion.TipoLote.ANEXOS:
            clave = int(row.get('clave') or 68)
            incide = int(row.get('incide') or 1)
            descontado = limpiar_decimal(row.get('descontado'))

            # Buscar si tiene un préstamo vigente con ese folio de incidencia para vincular el abono
            prestamo_activo = None
            if clave == 68:
                prestamo_activo = Prestamo.objects.filter(
                    afiliado=afiliado, num_incidencia=incide, liquidado=False
                ).order_by('-id').first()

            MovimientoDescuento.objects.create(
                lote=lote,
                afiliado=afiliado,
                prestamo=prestamo_activo,
                clave=clave,
                num_incidencia=incide,
                anio=int(row.get('anio') or lote.anio),
                quincena=int(row.get('quincena') or lote.quincena),
                batch=row.get('batch', '476C').strip(),
                monto_programado=limpiar_decimal(row.get('programado')),
                monto_descontado=descontado,
                diferencia=limpiar_decimal(row.get('diferencia')),
            )

        procesados += 1

    lote.registros_procesados = procesados
    lote.save(update_fields=['registros_procesados'])
    return procesados
