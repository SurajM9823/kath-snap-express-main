from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase, override_settings
from PIL import Image

from accounts.models import Category, Product, ProductImage
from seed_universal_products import seed_catalog


class UniversalProductSeedTests(TestCase):
    def setUp(self):
        self.media = TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=self.media.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

    def test_creates_twenty_products_seven_featured_with_valid_images(self):
        Category.objects.create(name='Groceries')
        result = seed_catalog()
        self.assertEqual(result, {'created': 20, 'featured_created': 7, 'skipped': 0})
        self.assertEqual(Product.objects.filter(is_universal=True, vendor=None).count(), 20)
        self.assertEqual(Product.objects.filter(featured=True).count(), 7)
        self.assertEqual(ProductImage.objects.filter(is_primary=True).count(), 20)
        self.assertEqual(Category.objects.filter(name='Groceries').count(), 1)
        for photo in ProductImage.objects.all():
            with photo.image.open('rb') as file:
                with Image.open(file) as image:
                    image.verify()

    def test_rerun_preserves_existing_products_and_images(self):
        seed_catalog()
        product = Product.objects.first()
        product.price = 123
        product.save()
        self.assertEqual(seed_catalog(), {'created': 0, 'featured_created': 0, 'skipped': 20})
        product.refresh_from_db()
        self.assertEqual(product.price, 123)
        self.assertEqual(ProductImage.objects.count(), 20)

    def test_dry_run_does_not_write(self):
        self.assertEqual(seed_catalog(dry_run=True)['created'], 20)
        self.assertFalse(Product.objects.exists())
        self.assertFalse(Category.objects.exists())
        self.assertEqual(list(Path(self.media.name).rglob('*')), [])

    def test_failure_rolls_back_database_and_cleans_new_images(self):
        with patch.object(ProductImage, 'save', side_effect=RuntimeError('Storage record failed')):
            with self.assertRaisesRegex(RuntimeError, 'Storage record failed'):
                seed_catalog()
        self.assertFalse(Product.objects.exists())
        self.assertFalse(Category.objects.exists())
        self.assertEqual([p for p in Path(self.media.name).rglob('*') if p.is_file()], [])
