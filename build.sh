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

# Create superuser from env vars (no email required)
echo "=== Create superuser from env vars if provided ==="
python - <<'PY'
import os
from django.contrib.auth import get_user_model
User = get_user_model()

username = os.environ.get('DANGO_SUPERUSER_USERNAME')
password = os.environ.get('DANGO_SUPERUSER_PASSWORD')

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
    print("DANGO_SUPERUSER_USERNAME or DANGO_SUPERUSER_PASSWORD not set; skipping superuser creation")
PY

echo "Build finished"
exit 0
