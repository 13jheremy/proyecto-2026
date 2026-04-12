from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0021_proveedor_nombre_normalizado'),
    ]

    operations = [
        migrations.AddField(
            model_name='categoria',
            name='nombre_normalizado',
            field=models.CharField(blank=True, editable=False, max_length=100, unique=True),
        ),
        migrations.AddField(
            model_name='categoriaservicio',
            name='nombre_normalizado',
            field=models.CharField(blank=True, editable=False, max_length=100, unique=True),
        ),
    ]