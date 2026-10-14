from django import forms
from prestamos.models import Prestamo, MovimientoDescuento

class PrestamoForm(forms.ModelForm):
    class Meta:
        model = Prestamo
        # Quitamos 'num_incidencia' de los campos
        fields = ['afiliado', 'importe_original', 'num_periodos', 'inicia_qna']
        widgets = {
            'afiliado': forms.Select(attrs={'class': 'form-select'}),
            'importe_original': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'num_periodos': forms.NumberInput(attrs={'class': 'form-control', 'value': '20'}),
            'inicia_qna': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej. 18-2026'}),
        }
        labels = {
            'afiliado': 'Afiliado Solicitante',
            'importe_original': 'Monto Solicitado (DEBE)',
            'num_periodos': 'Plazo (Quincenas)',
            'inicia_qna': 'Quincena de Inicio Estimada',
        }


class AbonoManualForm(forms.ModelForm):
    concepto_ajuste = forms.CharField(
        max_length=150, required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej. Abono en efectivo / Corrección de nómina'})
    )

    class Meta:
        model = MovimientoDescuento
        fields = ['monto_descontado', 'concepto_ajuste']
        widgets = {
            'monto_descontado': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }
        labels = {
            'monto_descontado': 'Monto del Abono / Ajuste (+/-)',
        }
