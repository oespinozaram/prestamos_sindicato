import re
from decimal import Decimal
from prestamos.models import Prestamo, LoteImportacion
from afiliados.models import Afiliado


def procesar_saldos(texto: str, lote: LoteImportacion) -> int:
    """Paso 1: Fotografía de la cartera. Actualiza saldos e identifica liquidaciones directas."""
    # Regex genérico: [Plaza] [Folio] [Importe Original] [Abono] [Saldo Restante]
    patron = re.compile(
        r'(?P<plaza>\d{4,6})\s+(?P<folio>\d+)\s+(?P<importe>[\d,]+\.\d{2})\s+(?P<descuento>[\d,]+\.\d{2})\s+(?P<saldo>[\d,]+\.\d{2})')

    registros = 0
    for match in patron.finditer(texto):
        datos = match.groupdict()
        plaza = datos['plaza']
        folio = int(datos['folio'])
        saldo_pdf = Decimal(datos['saldo'].replace(',', ''))

        prestamos = Prestamo.objects.filter(
            afiliado__numero_trabajador=plaza,
            num_incidencia=folio,
            estado_prestamo__in=[Prestamo.EstadoPrestamo.VIGENTE, Prestamo.EstadoPrestamo.CONGELADO]
        )

        if prestamos.exists():
            p = prestamos.first()
            p.saldo_actual = saldo_pdf
            if p.saldo_actual <= 0:
                p.estado_prestamo = Prestamo.EstadoPrestamo.LIQUIDADO
            p.save(update_fields=['saldo_actual', 'estado_prestamo'])
            registros += 1

    return registros


def procesar_pagados(texto: str, lote: LoteImportacion) -> int:
    """Paso 2: Cierre de expedientes."""
    patron = re.compile(r'(?P<plaza>\d{4,6})\s+(?P<folio>\d+)')

    registros = 0
    for match in patron.finditer(texto):
        plaza = match.group('plaza')
        folio = int(match.group('folio'))

        actualizados = Prestamo.objects.filter(
            afiliado__numero_trabajador=plaza,
            num_incidencia=folio
        ).update(
            estado_prestamo=Prestamo.EstadoPrestamo.LIQUIDADO,
            saldo_actual=0
        )
        if actualizados:
            registros += 1

    return registros


def procesar_anexos(texto: str, lote: LoteImportacion) -> int:
    """Paso 3: Heartbeat del padrón (Mov. 67) y auditoría de abonos (Mov. 68)."""
    patron = re.compile(r'(?P<plaza>\d{4,6})\s+(?P<clave>67|68)\s+(?P<monto>[\d,]+\.\d{2})')

    plazas_activas = set()
    registros = 0

    for match in patron.finditer(texto):
        plaza = match.group('plaza')
        clave = match.group('clave')
        monto = Decimal(match.group('monto').replace(',', ''))

        afiliado = Afiliado.objects.filter(numero_trabajador=plaza).first()
        if not afiliado:
            continue

        if clave == '67':
            plazas_activas.add(plaza)
            if not afiliado.activo:
                afiliado.activo = True
                afiliado.save(update_fields=['activo'])

        elif clave == '68':
            prestamo = afiliado.prestamos.filter(estado_prestamo=Prestamo.EstadoPrestamo.VIGENTE).first()
            if prestamo:
                prestamo.abonos.create(
                    lote=lote,
                    afiliado=afiliado,
                    clave=68,
                    monto_descontado=monto,
                    anio=lote.anio,
                    quincena=lote.quincena
                )
        registros += 1

    # Detectar inactivos: Tienen registro previo pero perdieron el latido 67 en esta quincena
    afiliados_inactivos = Afiliado.objects.filter(activo=True).exclude(numero_trabajador__in=plazas_activas)
    for afi in afiliados_inactivos:
        afi.activo = False
        afi.save(update_fields=['activo'])
        # Congelar deuda
        afi.prestamos.filter(estado_prestamo=Prestamo.EstadoPrestamo.VIGENTE).update(
            estado_prestamo=Prestamo.EstadoPrestamo.CONGELADO
        )

    return registros