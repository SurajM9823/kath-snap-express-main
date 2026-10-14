# Universal product pricing groups

Open **Superadmin → Pricing groups** (`/accounts/superadmin/pricing-groups/`).

1. Name the group, such as “Weekend discount” or “Premium items”.
2. Choose **Decrease prices** or **Increase prices** and enter a percentage.
3. Search products by name or catalog category. Select individual products or use **Select visible**.
4. Enable the group and save. Edit the group later to change the percentage or membership.

These are independent pricing groups, not replacements for catalog categories.
Each universal product can belong to only one group; products already in another
group are excluded from selection. Uncheck a product in its current group before
moving it. Unchecking products or disabling a group restores their base prices.
There is no compounding: percentages always apply to the unchanged base price.

Examples for a base price of NPR 100:

| Group setting | Selling price | Customer display |
|---|---:|---|
| Decrease 15% | 85.00 | Crossed-out 100.00 beside 85.00 |
| Increase 15% | 115.00 | 115.00 only |
| Disabled or 0% | 100.00 | 100.00 only |

Decreases support 0–100%; increases support 0–1000%. Calculations use decimal
arithmetic, rounded half-up to two decimal places. Vendor POS prices are unaffected.

## Backend and Flutter behavior

`Product.price` remains the base price. `Product.selling_price` applies the active
group adjustment. Customer APIs return `price` (selling price), `base_price`, and
`has_discount`. Customer price sorting and cart totals use selling prices. The
order creation serializer takes its unit price from the server, not the submitted
client price. Existing order line snapshots are not rewritten by pricing changes.

Flutter uses a shared price widget on home/featured cards, category and product
lists, related products, wishlist, product details, cart, and checkout items. It
shows a crossed base price only when the selling price is lower, and preserves
decimal amounts. The cart refresh fingerprint includes price changes. Catalog
cache keys were updated; users see new pricing on their next catalog refresh.

## Release

Apply the new schema migration before running the changed backend:

```sh
python manage.py migrate accounts
```

Migration `0018_pricing_groups` adds only the group table and nullable product
membership. Its dependency is 0015, the last migration currently present in this
checkout; it does not recreate missing earlier universal-catalog migrations or
repair unrelated migration drift. Deploy the backend and updated Flutter build.
No production/development database was migrated during this work.

Validation: nineteen backend regression tests (including eight pricing tests), fifteen Flutter pricing/catalog tests,
an actual migration-state check preserving existing prices/stock, and headless
admin browser checks for search, selection, previews, and mobile layout.
