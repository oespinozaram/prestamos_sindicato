import csv
from django.core.management.base import BaseCommand
from django.db import transaction
from afiliados.models import Afiliado


class Command(BaseCommand):
    help = "Genera o actualiza el Padrón de Afiliados a partir del CSV de Anexos de Descuento"

    def add_arguments(self, parser):
        parser.add_argument('csv_path', type=str, help="Ruta del archivo CSV de Anexos")

    def handle(self, *args, **options):
        csv_path = options['csv_path']
        afiliados_dict = {}

        with open(csv_path, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                codigo = int(row['no_plaza'])
                # Si el empleado aparece varias veces (clave 67 y 68), conservamos sus datos únicos
                if codigo not in afiliados_dict:
                    afiliados_dict[codigo] = {
                        'nombre_completo': row['nombre'].strip(),
                        'tipo_personal_nomina': row['tipo_personal'].strip() or 'N',
                        'area_codigo': row['area'].strip(),
                    }

        creados = 0
        actualizados = 0

        with transaction.atomic():
            for codigo, datos in afiliados_dict.items():
                _, created = Afiliado.objects.update_or_create(
                    codigo=codigo,
                    defaults=datos
                )
                if created:
                    creados += 1
                else:
                    actualizados += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Padrón sincronizado: {creados} afiliados nuevos, {actualizados} actualizados."
            )
        )