#!/bin/bash
echo "==> Starting build..."

# ---------------------------------------------------------------------
# 1. Install dependencies
# ---------------------------------------------------------------------
echo "=== Install dependencies ==="
pip install --upgrade pip
pip install -r requirements.txt

# ---------------------------------------------------------------------
# 2. Run migrations
# ---------------------------------------------------------------------
echo "=== Run migrations ==="
python manage.py migrate --noinput

# ---------------------------------------------------------------------
# 3. Collect static files
# ---------------------------------------------------------------------
echo "=== Collect static files ==="
python manage.py collectstatic --noinput

# ---------------------------------------------------------------------
# 4. Prepare media directories
# ---------------------------------------------------------------------
echo "=== Prepare media directories ==="
# Runtime media path on Render (can be overridden by env var RENDER_MEDIA)
RENDER_MEDIA="${RENDER_MEDIA:-/opt/render/project/media}"

# Make sure base media folder exists
mkdir -p "$RENDER_MEDIA"

# Copy preloaded images into runtime media so `/media/` URLs work in
# production the same as locally. These files are part of the repo and
# remain read-only; user uploads will still go to MEDIA_ROOT at runtime
# and remain ephemeral on Render as intended.
if [ -d "media/products" ]; then
    mkdir -p "$RENDER_MEDIA/products"
    cp -r media/products/* "$RENDER_MEDIA/products/" || true
fi

# Ensure upload folders exist (vouchers, etc.)
mkdir -p "$RENDER_MEDIA/vouchers"

# ---------------------------------------------------------------------
# 5. Create superuser from environment variables (if provided)
# ---------------------------------------------------------------------
echo "=== Create superuser if env vars provided ==="
if [[ -n "$DJANGO_SUPERUSER_USERNAME" && -n "$DJANGO_SUPERUSER_EMAIL" && -n "$DJANGO_SUPERUSER_PASSWORD" ]]; then
    python manage.py createsuperuser --noinput || true
fi

echo "==> Build finished successfully!"
