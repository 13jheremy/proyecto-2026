from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0020_servicio_nombre_normalizado'),
    ]

    operations = [
        migrations.AddField(
            model_name='proveedor',
            name='nombre_normalizado',
            field=models.CharField(blank=True, editable=False, max_length=200, unique=True),
        ),
    ]