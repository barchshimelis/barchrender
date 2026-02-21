#!/usr/bin/env bash
set -e

echo "=== Install dependencies ==="
pip install -r requirements.txt

echo "=== Run migrations ==="
python manage.py migrate --noinput

echo "=== Collect static files ==="
python manage.py collectstatic --noinput

# Copy repo media into the container media folder so preloaded images are available
if [ -d "media" ]; then
  echo "=== Copying repo media into container media folder ==="
  cp -R media/* media/ || true
fi

# Create superuser from env vars (Option A: using django.setup())
echo "=== Create superuser from env vars if provided ==="
python - <<'PY'
import os
import django

# Initialize Django apps
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AmazonProject.settings')
django.setup()  # Fixes AppRegistryNotReady

from django.contrib.auth import get_user_model
User = get_user_model()

username = os.environ.get('DJANGO_SUPERUSER_USERNAME')
password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')

if username and password:
    if not User.objects.filter(username=username).exists():
        try:
            User.objects.create_superuser(username=username, email='', password=password)
        except TypeError:
            User.objects.create_superuser(username=username, password=password)
        print("Superuser created:", username)
    else:
        print("Superuser already exists:", username)
else:
    print("DJANGO_SUPERUSER_USERNAME or DJANGO_SUPERUSER_PASSWORD not set; skipping superuser creation")
PY

echo "Build finished"
exit 0
