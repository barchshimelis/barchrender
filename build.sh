#!/bin/bash
echo "==> Starting build..."

# Activate virtual environment if not already
# source .venv/bin/activate  # Render usually auto-activates

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
# Runtime media path on Render
RENDER_MEDIA="/opt/render/project/media"

# Make sure base media folder exists
mkdir -p "$RENDER_MEDIA"

# Preloaded images from repo (products)
mkdir -p "$RENDER_MEDIA/products"
cp -r media/products/* "$RENDER_MEDIA/products/" || true

# Upload folders (vouchers)
mkdir -p "$RENDER_MEDIA/vouchers"

# ---------------------------------------------------------------------
# 5. Create superuser from environment variables (if provided)
# ---------------------------------------------------------------------
echo "=== Create superuser if env vars provided ==="
if [[ -n "$DJANGO_SUPERUSER_USERNAME" && -n "$DJANGO_SUPERUSER_EMAIL" && -n "$DJANGO_SUPERUSER_PASSWORD" ]]; then
    python manage.py createsuperuser --noinput || true
fi

echo "==> Build finished successfully!"
