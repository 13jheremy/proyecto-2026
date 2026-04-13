from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0022_categorias_nombre_normalizado'),
    ]

    operations = [
        migrations.AddField(
            model_name='categoria',
            name='nombre_sin_espacios',
            field=models.CharField(blank=True, editable=False, max_length=100, unique=True),
        ),
        migrations.AddField(
            model_name='categoriaservicio',
            name='nombre_sin_espacios',
            field=models.CharField(blank=True, editable=False, max_length=100, unique=True),
        ),
    ]