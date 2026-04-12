from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0019_lote'),
    ]

    operations = [
        migrations.AddField(
            model_name='servicio',
            name='nombre_normalizado',
            field=models.CharField(blank=True, editable=False, max_length=200, unique=True),
        ),
    ]