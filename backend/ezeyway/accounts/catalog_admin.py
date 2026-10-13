from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_protect

from .models import Product, ProductImage


class UniversalProductForm(forms.ModelForm):
    image = forms.ImageField(required=False, help_text='Add a product image.')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tags'].required = False
        self.fields['dynamic_fields'].required = False

    class Meta:
        model = Product
        fields = ['name', 'category', 'subcategory', 'price', 'quantity',
                  'description', 'short_description', 'tags', 'dynamic_fields',
                  'status', 'featured', 'free_delivery',
                  'custom_delivery_fee_enabled', 'custom_delivery_fee']

    def clean(self):
        data = super().clean()
        data['tags'] = data.get('tags') or []
        data['dynamic_fields'] = data.get('dynamic_fields') or {}
        if not isinstance(data['tags'], list):
            self.add_error('tags', 'Enter a JSON list of tags.')
        if not isinstance(data['dynamic_fields'], dict):
            self.add_error('dynamic_fields', 'Enter a JSON object.')
        for field in ('price', 'quantity', 'custom_delivery_fee'):
            if data.get(field) is not None and data[field] < 0:
                self.add_error(field, 'Must be zero or greater.')
        if data.get('custom_delivery_fee_enabled') and data.get('custom_delivery_fee') is None:
            self.add_error('custom_delivery_fee', 'Enter a delivery fee.')
        return data


@login_required
@csrf_protect
def manage_universal_products(request, product_id=None):
    if not request.user.is_superuser:
        raise PermissionDenied
    product = (get_object_or_404(Product, pk=product_id, is_universal=True)
               if product_id else Product(is_universal=True))
    form = UniversalProductForm(request.POST or None, request.FILES or None, instance=product)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            product = form.save()
            if form.cleaned_data.get('image'):
                ProductImage.objects.create(product=product, image=form.cleaned_data['image'],
                                            is_primary=not product.images.exists())
            product.images.filter(pk__in=request.POST.getlist('remove_images')).delete()
        return redirect('manage_universal_products')
    products = Product.objects.filter(is_universal=True).order_by('-created_at', '-pk')
    if request.GET.get('search'):
        products = products.filter(name__icontains=request.GET['search'])
    return render(request, 'accounts/manage_universal_products.html', {
        'form': form, 'editing': product_id, 'product': product,
        'products': Paginator(products, 25).get_page(request.GET.get('page')),
    })
