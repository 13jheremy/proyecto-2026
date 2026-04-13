from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0023_categorias_nombre_sin_espacios'),
    ]

    operations = [
        migrations.AddField(
            model_name='servicio',
            name='nombre_sin_espacios',
            field=models.CharField(blank=True, editable=False, max_length=200, unique=True),
        ),
    ]