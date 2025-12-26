import os
import random
import re

import django
from django.core.files import File


# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "AmazonProject.settings")
django.setup()


from products.models import Product


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
ROLE_ORDER = ["referee", "referrer"]
IMAGE_FOLDER_NAME = "products"


def is_image(filename: str) -> bool:
    return filename.lower().endswith(IMAGE_EXTENSIONS)


def extract_sequence(filename: str) -> int:
    """Return numeric order from names like product (12).jpg or product(12).jpg; fallback to 0."""
    match = re.search(r"product\s*\((\d+)\)", filename, re.IGNORECASE)
    return int(match.group(1)) if match else 0


def get_media_root() -> str:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "media")


def product_exists(filename: str) -> bool:
    return Product.objects.filter(file=f"products/{filename}").exists()


def create_product(source_path: str, filename: str, role: str, sequence: int):
    with open(source_path, "rb") as file_handle:
        product = Product(
            price=round(random.uniform(10, 100), 2),
            is_active=True,
            cycle_number=1,
            role_pool=role,
            sequence_in_cycle=sequence,
        )
        product.file.save(filename, File(file_handle), save=True)
    print(f"Added {filename} (role {role}) with price {product.price}")


def main():
    media_root = get_media_root()
    images_dir = os.path.join(media_root, IMAGE_FOLDER_NAME)

    if not os.path.isdir(images_dir):
        print("Products image folder not found. Ensure files are under media/products.")
        return

    files = [f for f in os.listdir(images_dir) if is_image(f)]
    if not files:
        print("No images found in media/products.")
        return

    files.sort(key=lambda name: (extract_sequence(name), name.lower()))

    sequence = 1
    for idx, filename in enumerate(files):
        role = ROLE_ORDER[idx % len(ROLE_ORDER)]
        source_path = os.path.join(images_dir, filename)

        if not os.path.exists(source_path):
            print(f"Source file {source_path} missing, skipping.")
            continue

        if product_exists(filename):
            print(f"Product for {filename} already exists, skipping...")
            continue

        create_product(source_path, filename, role, sequence)
        sequence += 1


if __name__ == "__main__":
    main()
