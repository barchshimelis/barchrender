#!/usr/bin/env bash
set -e

echo "=== Install dependencies ==="
pip install -r requirements.txt

echo "=== Run migrations ==="
python manage.py migrate --noinput

echo "=== Collect static files ==="
python manage.py collectstatic --noinput

echo "=== Preparing media directory ==="
mkdir -p /opt/render/project/media

if [ -d "media" ]; then
  echo "=== Copying repo media to runtime media directory ==="
  cp -r media/* /opt/render/project/media/ || true
else
  echo "No repo media directory found"
fi

echo "=== Create superuser from env vars if provided ==="
python - <<'PY'
import os
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
