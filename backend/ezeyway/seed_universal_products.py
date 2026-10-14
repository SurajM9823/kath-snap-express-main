"""Run with the project's Python environment: python seed_universal_products.py.

Creates 20 demo products (7 featured) using bundled, verified product photos.
No network access is needed. Existing seeded products are left unchanged.
Use --dry-run to check the database and files without changing anything.
"""
import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'seed_data' / 'universal_products'


def seed_catalog(dry_run=False):
    from django.core.files.base import ContentFile
    from django.db import connection, transaction
    from PIL import Image
    from accounts.models import Category, Product, ProductImage

    records = json.loads((DATA / 'products.json').read_text(encoding='utf-8'))
    if len(records) != 20 or sum(row['featured'] for row in records) != 7:
        raise ValueError('The sample catalog must contain 20 products, with 7 featured.')
    if len({row['sku'] for row in records}) != len(records):
        raise ValueError('Duplicate SKUs in the sample catalog.')
    # Validate everything before making any database/storage changes.
    photos = {}
    for row in records:
        photo_path = (DATA / row['image']).resolve()
        if photo_path.parent != DATA.resolve():
            raise ValueError('Invalid image path in the sample catalog.')
        with Image.open(photo_path) as photo:
            photo.verify()
        photos[row['sku']] = photo_path.read_bytes()
        if Decimal(row['price']) < 0 or row['quantity'] < 0:
            raise ValueError('Invalid sample price or stock.')
    with connection.cursor() as cursor:
        tables = connection.introspection.table_names(cursor)
        for model in (Category, Product, ProductImage):
            table = model._meta.db_table
            if table not in tables:
                raise ValueError(f'Missing table {table}. Apply your project migrations first.')
            columns = {column.name for column in connection.introspection.get_table_description(cursor, table)}
            missing = {field.column for field in model._meta.local_concrete_fields} - columns
            if missing:
                raise ValueError(f'{table} is missing columns: {", ".join(sorted(missing))}. '
                                 'Apply/reconcile your migrations, including 0017_universal_catalog, first.')

    saved_files = []
    created = skipped = featured_created = 0
    try:
        with transaction.atomic():
            for row in records:
                existing = list(Product.objects.filter(sku=row['sku']))
                if len(existing) > 1:
                    raise ValueError(f'Duplicate database SKU {row["sku"]}; resolve it before running again.')
                if existing:
                    if not existing[0].is_universal or existing[0].vendor_id is not None:
                        raise ValueError(f'SKU {row["sku"]} belongs to vendor inventory; nothing was changed.')
                    skipped += 1
                    continue
                category = Category.objects.filter(name=row['category']).first()
                if category and not category.is_active:
                    raise ValueError(f'Category "{category.name}" is inactive. Activate it or adjust the sample catalog.')
                if dry_run:
                    created += 1
                    featured_created += int(row['featured'])
                    continue
                if category is None:
                    category = Category.objects.create(name=row['category'], is_active=True)
                product = Product.objects.create(
                    sku=row['sku'], name=row['name'], category=category.name,
                    subcategory=None, price=Decimal(row['price']), quantity=row['quantity'],
                    description=row['description'], short_description=row['name'],
                    tags=['demo'], dynamic_fields={}, status='active',
                    is_universal=True, vendor=None, featured=row['featured'],
                    free_delivery=False, custom_delivery_fee_enabled=False,
                    custom_delivery_fee=None,
                )
                photo = ProductImage(product=product, is_primary=True)
                photo.image.save(f'{row["sku"].lower()}{Path(row["image"]).suffix}',
                                 ContentFile(photos[row['sku']]), save=False)
                saved_files.append((photo.image.storage, photo.image.name))
                photo.save()
                created += 1
                featured_created += int(row['featured'])
    except Exception:
        # Storage writes are not transactional; clean up only files from this run.
        for storage, filename in reversed(saved_files):
            try:
                storage.delete(filename)
            except Exception as cleanup_error:
                print(f'Could not remove new image {filename}: {cleanup_error}', file=sys.stderr)
        raise
    return {'created': created, 'featured_created': featured_created, 'skipped': skipped}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Validate files/schema and show counts without saving.')
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ezeyway.settings')
    try:
        import django
        django.setup()
        result = seed_catalog(dry_run=args.dry_run)
    except Exception as error:
        print(f'Seed failed: {error}', file=sys.stderr)
        print('Check your Python environment, database connection, migrations, and writable media storage. '
              'Keep seed_data/universal_products beside this script.', file=sys.stderr)
        return 1
    verb = 'Would create' if args.dry_run else 'Created'
    print(f'{verb} {result["created"]} universal products '
          f'({result["featured_created"]} featured); skipped {result["skipped"]} existing sample products.')
    if not args.dry_run:
        print('Open /accounts/superadmin/products/ to view them. Prices and stock are demo values.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
