from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SuperAdminWalletCredential',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('password_hash', models.CharField(max_length=255)),
                ('set_at', models.DateTimeField(auto_now_add=True)),
                ('notes', models.CharField(blank=True, max_length=255)),
                ('is_active', models.BooleanField(default=True)),
                ('set_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='wallet_credentials_set', to=settings.AUTH_USER_MODEL)),
                ('wallet', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='credential', to='accounts.superadminwallet')),
            ],
            options={
                'verbose_name': 'Super Admin Wallet Credential',
                'verbose_name_plural': 'Super Admin Wallet Credentials',
            },
        ),
    ]
