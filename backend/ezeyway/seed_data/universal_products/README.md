# Sample universal catalog

Run with the Django project's configured Python environment:

```sh
python seed_universal_products.py --dry-run
python seed_universal_products.py
```

Run those commands from `backend/ezeyway`, or pass the script's full path.
Keep this entire directory with the script. It includes 20 matching product
photos, so there are no runtime downloads or expiring remote image links.

The first run creates 20 active universal products with 7 featured. Existing
categories with matching names are reused; missing categories are created.
These samples have no subcategories or variants. Prices are sample NPR values,
not real market prices. Review them in the superadmin dashboard before use.
You can adjust `products.json` before the first run.

Existing demo products are identified by their `EZEY-DEMO-*` SKUs and skipped,
including any price/content edits you subsequently make. Other catalog products
and vendor inventory are not modified. Run only one copy of the script at a time.

The script checks image files and database columns before writing. A failed
database transaction rolls back its products/categories and attempts to delete
only the new image files from that run. It does not apply migrations or change
database settings. If schema checks fail, reconcile/apply the existing project
migrations first, including the universal-catalog migration.

Photo/title source: [DummyJSON demo product catalog](https://dummyjson.com/products).
Each entry in `products.json` includes its original image URL and source ID.
These third-party sample assets are for demonstration; they are not photos of
your own inventory.
