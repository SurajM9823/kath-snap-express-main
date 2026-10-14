from decimal import Decimal
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q, Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_protect

from .models import PricingGroup, Product


class PricingProductCheckboxes(forms.CheckboxSelectMultiple):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if hasattr(value, 'instance'):
            option['attrs']['data-featured'] = 'true' if value.instance.featured else 'false'
        return option


class PricingProductChoice(forms.ModelMultipleChoiceField):
    def label_from_instance(self, product):
        badge = ' [Featured]' if product.featured else ''
        return f'{product.name}{badge} — {product.category} — Base NPR {product.price}'


class PricingGroupForm(forms.ModelForm):
    direction = forms.ChoiceField(choices=[('decrease', 'Decrease prices'), ('increase', 'Increase prices')])
    percentage = forms.DecimalField(min_value=0, max_value=1000, max_digits=7, decimal_places=2,
                                    label='Percentage', widget=forms.NumberInput(attrs={'step': '0.01'}))
    products = PricingProductChoice(queryset=Product.objects.none(), required=False,
                                   widget=PricingProductCheckboxes)

    class Meta:
        model = PricingGroup
        fields = ['name', 'is_active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        group = self.instance
        available = Q(pricing_group__isnull=True)
        if group.pk:
            available |= Q(pricing_group=group)
            self.initial['products'] = group.products.values_list('pk', flat=True)
        self.fields['products'].queryset = Product.objects.filter(available, is_universal=True).order_by('category', 'name', 'pk')
        self.initial['direction'] = 'increase' if group.adjustment_percent > 0 else 'decrease'
        self.initial['percentage'] = abs(group.adjustment_percent)
        for name, field in self.fields.items():
            field.widget.attrs['class'] = ('form-check-input' if name == 'is_active' else
                                          'product-choices' if name == 'products' else
                                          'form-select' if name == 'direction' else 'form-control')

    def clean(self):
        data = super().clean()
        percentage = data.get('percentage')
        if percentage is not None:
            if data.get('direction') == 'decrease' and percentage > 100:
                self.add_error('percentage', 'A decrease cannot exceed 100%.')
            self.instance.adjustment_percent = percentage * (Decimal('-1') if data.get('direction') == 'decrease' else Decimal('1'))
        return data


@login_required
@csrf_protect
def manage_pricing_groups(request, group_id=None):
    if not request.user.is_superuser:
        raise PermissionDenied
    group = get_object_or_404(PricingGroup, pk=group_id) if group_id else PricingGroup()
    form = PricingGroupForm(request.POST if request.method == 'POST' else None, instance=group)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            selected_ids = list(form.cleaned_data['products'].values_list('pk', flat=True))
            # Lock both old and new members before changing assignments.
            membership = Q(pk__in=selected_ids)
            if group.pk:
                membership |= Q(pricing_group=group)
            locked = list(Product.objects.select_for_update().filter(membership))
            conflicts = [p for p in locked if p.pk in selected_ids and p.pricing_group_id not in (None, group.pk)]
            if conflicts:
                form.add_error('products', 'Some products were assigned to another group. Reload and select again.')
            else:
                group = form.save()
                group.products.exclude(pk__in=selected_ids).update(pricing_group=None)
                Product.objects.filter(pk__in=selected_ids, is_universal=True).update(pricing_group=group)
                return redirect('manage_pricing_groups')
    return render(request, 'accounts/manage_pricing_groups.html', {
        'form': form, 'editing': group.pk,
        'groups': PricingGroup.objects.annotate(product_count=Count('products')),
    })
