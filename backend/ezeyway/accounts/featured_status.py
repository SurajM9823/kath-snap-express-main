from datetime import timedelta

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from .models import Product, ProductFeaturedPurchase


def sync_featured_products(products=None):
    """Keep purchased promotions in sync with their dates; preserve manual flags."""
    today = timezone.localdate()
    purchases = ProductFeaturedPurchase.objects.filter(product_id=OuterRef('pk'))
    current = purchases.filter(is_active=True, start_date__lte=today, end_date__gte=today)
    products = Product.objects.all() if products is None else products
    managed = products.filter(is_universal=False).annotate(has_purchase=Exists(purchases), has_current=Exists(current)).filter(has_purchase=True)
    managed.filter(has_current=True, featured=False).update(featured=True)
    managed.filter(has_current=False, featured=True).update(featured=False)


@transaction.atomic
def reschedule_paid_feature(product_id, user, start_date):
    """Move only remaining paid time, without charging or extending used time."""
    today = timezone.localdate()
    if start_date < today:
        raise ValueError('Start date cannot be in the past')
    product = Product.objects.select_for_update().get(pk=product_id, vendor__user=user)
    purchase = ProductFeaturedPurchase.objects.select_for_update().filter(
        product=product, is_active=True, end_date__gte=today,
    ).order_by('-end_date', '-pk').first()
    if purchase is None:
        raise ValueError('No unexpired paid package found. Please purchase a new package.')
    # Keep today's remaining entitlement, but never restore days already used.
    remaining = purchase.end_date - max(purchase.start_date, today)
    purchase.start_date = start_date
    purchase.end_date = start_date + remaining
    purchase.save(update_fields=['start_date', 'end_date'])
    sync_featured_products(Product.objects.filter(pk=product.pk))
    product.refresh_from_db(fields=['featured'])
    return product, purchase
