from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0002_alter_userproducttask_unique_together_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="product",
            name="product_code",
            field=models.CharField(max_length=11, unique=True, blank=True),
        ),
    ]
