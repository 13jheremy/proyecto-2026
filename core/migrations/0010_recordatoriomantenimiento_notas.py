# Generated migration for RecordatorioMantenimiento notas field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_detallemantenimiento_km_proximo_cambio_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='recordatoriomantenimiento',
            name='notas',
            field=models.TextField(blank=True, help_text='Notas adicionales del recordatorio'),
        ),
    ]
