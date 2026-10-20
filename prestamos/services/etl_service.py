import csv
import re
from decimal import Decimal
from django.utils import timezone
from prestamos.models import Prestamo, LoteImportacion
from afiliados.models import Afiliado


def limpiar_monto(texto):
    texto_limpio = re.sub(r'[^0-9\.\-]', '', str(texto))
    return Decimal(texto_limpio) if texto_limpio else Decimal('0.00')


def procesar_saldos(csv_path: str, lote: LoteImportacion) -> int:
    registros = 0
    # Usamos utf-8-sig por si el CSV fue manipulado en Excel y guardó el BOM
    with open(csv_path, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for fila in reader:
            if not fila.get('no_plaza') or not fila.get('num_inc'):
                continue

            plaza = str(fila['no_plaza']).strip()
            folio = int(fila['num_inc'])
            tipo_nomina = fila.get('tipo_personal', 'N')

            # 1. UPSERT Afiliado
            afiliado, creado = Afiliado.objects.get_or_create(
                codigo=plaza,
                defaults={
                    'numero_trabajador': plaza,
                    'nombre_completo': fila.get('nombre', f"TRABAJADOR {plaza}"),
                    'tipo_personal_nomina': tipo_nomina if tipo_nomina in ['J', 'N'] else 'N',
                    'activo': True
                }
            )
            if not creado and not afiliado.activo:
                afiliado.activo = True
                afiliado.save(update_fields=['activo'])

            # 2. UPSERT Préstamo
            saldo_csv = limpiar_monto(fila.get('saldo'))
            prestamo, p_creado = Prestamo.objects.get_or_create(
                afiliado=afiliado,
                num_incidencia=folio,
                inicia_qna=fila.get('inicia_qna', '00-0000'),
                defaults={
                    'num_periodos': int(fila.get('num_per', 20)),
                    'monto_descontar_qna': limpiar_monto(fila.get('monto_descontar')),
                    'termina_qna': fila.get('termina_qna', ''),
                    'importe_original': limpiar_monto(fila.get('importe')),
                    'acumulado_pagado': limpiar_monto(fila.get('acumulado')),
                    'saldo_actual': saldo_csv,
                    'estado_prestamo': Prestamo.EstadoPrestamo.LIQUIDADO if saldo_csv <= 0 else Prestamo.EstadoPrestamo.VIGENTE
                }
            )

            if not p_creado:
                prestamo.acumulado_pagado = limpiar_monto(fila.get('acumulado'))
                prestamo.saldo_actual = saldo_csv
                if prestamo.saldo_actual <= 0:
                    prestamo.estado_prestamo = Prestamo.EstadoPrestamo.LIQUIDADO
                prestamo.save(update_fields=['acumulado_pagado', 'saldo_actual', 'estado_prestamo', 'actualizado_en'])

            registros += 1

    return registros


def procesar_pagados(csv_path: str, lote: LoteImportacion) -> int:
    registros = 0
    with open(csv_path, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for fila in reader:
            if not fila.get('no_plaza') or not fila.get('num_inc'):
                continue

            plaza = str(fila['no_plaza']).strip()
            folio = int(fila['num_inc'])
            inicia = fila.get('inicia_qna', '')

            filtro = {'afiliado__codigo': plaza, 'num_incidencia': folio}
            if inicia:
                filtro['inicia_qna'] = inicia

            actualizados = Prestamo.objects.filter(**filtro).update(
                estado_prestamo=Prestamo.EstadoPrestamo.LIQUIDADO,
                saldo_actual=0,
                actualizado_en=timezone.now()
            )
            if actualizados:
                registros += 1

    return registros

# procesar_anexos requeriría una lógica similar adaptada a las columnas de su respectivo CSV.