"""The customer catalog never includes vendor POS inventory."""
from django.db.models import Q

from .models import Product


def customer_products():
    return Product.objects.filter(is_universal=True, status='active').prefetch_related('images').order_by('-created_at', '-pk')


def filter_catalog(params):
    products = customer_products()
    search = params.get('search', '').strip()
    if search:
        products = products.filter(
            Q(name__icontains=search) | Q(description__icontains=search) |
            Q(category__icontains=search) | Q(subcategory__icontains=search) |
            Q(tags__icontains=search)
        )
    for field in ('category', 'subcategory'):
        if params.get(field):
            products = products.filter(**{field: params[field]})
    if params.get('categories'):
        products = products.filter(category__in=params['categories'].split(','))
    if params.get('featured', '').lower() in ('true', '1', 'yes'):
        products = products.filter(featured=True)
    # Legacy shop screens must not display universal products as a vendor's stock.
    if params.get('vendor_id') or params.get('vendor'):
        return products.none()
    ordering = {'price_asc': 'price', 'price_desc': '-price', 'newest': '-created_at'}
    if params.get('sort') in ordering:
        products = products.order_by(ordering[params['sort']], '-pk')
    return products
