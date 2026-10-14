from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_protect

from .models import Category, Product, ProductImage
from .parameter_models import CategoryParameter, SubCategoryParameter


class UniversalProductForm(forms.ModelForm):
    image = forms.ImageField(required=False, label='Product image', help_text='Upload a clear JPG, PNG or WebP image.')
    category = forms.ChoiceField(choices=())
    subcategory = forms.ChoiceField(choices=(), required=False)
    tags = forms.CharField(required=False, help_text='Separate tags with commas, for example: fresh, organic, local.')

    class Meta:
        model = Product
        fields = ['name', 'category', 'subcategory', 'price', 'quantity',
                  'description', 'short_description', 'tags',
                  'status', 'featured', 'free_delivery',
                  'custom_delivery_fee_enabled', 'custom_delivery_fee']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'short_description': forms.Textarea(attrs={'rows': 2}),
            'price': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'quantity': forms.NumberInput(attrs={'min': 0, 'step': 1}),
            'custom_delivery_fee': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
        }
        labels = {'price': 'Base price (NPR)', 'quantity': 'Available stock',
                  'custom_delivery_fee_enabled': 'Set a custom delivery fee',
                  'custom_delivery_fee': 'Delivery fee (NPR)', 'featured': 'Feature on the homepage'}

    def __init__(self, data=None, *args, **kwargs):
        # Ignore hidden/stale delivery values, including malformed fee input.
        if data is not None:
            data = data.copy()
            free = forms.BooleanField(required=False).to_python(data.get('free_delivery'))
            custom = forms.BooleanField(required=False).to_python(data.get('custom_delivery_fee_enabled'))
            if free or not custom:
                data['custom_delivery_fee'] = ''
            if free:
                data['custom_delivery_fee_enabled'] = ''
        super().__init__(data, *args, **kwargs)
        categories = list(Category.objects.filter(is_active=True))
        self.fields['category'].choices = [('', 'Choose a category')] + [(c.name, c.name) for c in categories]
        category_name = self.data.get('category', '') if self.is_bound else self.initial.get('category', '')
        subcategory_name = self.data.get('subcategory', '') if self.is_bound else self.initial.get('subcategory', '')
        category = next((c for c in categories if c.name == category_name), None)
        subcategories = list(category.subcategories.filter(is_active=True)) if category else []
        self.fields['subcategory'].choices = [('', 'No subcategory')] + [(c.name, c.name) for c in subcategories]
        subcategory = next((c for c in subcategories if c.name == subcategory_name), None)
        if not subcategories:
            # Do not set disabled on the Django field: forged values must still fail validation.
            self.fields['subcategory'].widget.attrs['disabled'] = True
        else:
            self.fields['subcategory'].widget.attrs.pop('disabled', None)
        self.initial['tags'] = ', '.join(str(tag) for tag in (self.instance.tags or []))
        self.parameter_fields = {}
        if category:
            for parameter in CategoryParameter.objects.filter(category=category, is_active=True):
                self.parameter_fields[parameter.name] = parameter
        if subcategory:
            for parameter in SubCategoryParameter.objects.filter(subcategory=subcategory, is_active=True):
                self.parameter_fields[parameter.name] = parameter
        self.same_taxonomy = (category_name == self.instance.category and
                              (subcategory_name or '') == (self.instance.subcategory or ''))
        saved_values = (self.instance.dynamic_fields or {}) if self.same_taxonomy else {}
        for name, parameter in self.parameter_fields.items():
            self.fields['attribute_' + name] = self.parameter_field(parameter)
            value = saved_values.get(name)
            if parameter.field_type == 'boolean' and isinstance(value, bool):
                value = 'true' if value else 'false'
            self.initial['attribute_' + name] = value
        for name, field in self.fields.items():
            field.widget.attrs['class'] = ('form-check-input' if isinstance(field.widget, forms.CheckboxInput)
                                            else 'attribute-options' if isinstance(field.widget, forms.CheckboxSelectMultiple)
                                            else 'form-select' if isinstance(field.widget, forms.Select)
                                            else 'form-control')
        self.fields['name'].widget.attrs['placeholder'] = 'e.g. Fresh whole milk, 1 litre'
        self.fields['tags'].widget.attrs['placeholder'] = 'fresh, dairy, local'
        self.fields['image'].widget.attrs['accept'] = 'image/*'

    @staticmethod
    def parameter_field(parameter):
        common = {'label': parameter.label, 'required': parameter.is_required,
                  'help_text': parameter.description or ''}
        attrs = {'placeholder': parameter.placeholder or ''}
        kind = parameter.field_type
        if kind in ('number', 'range'):
            field = forms.FloatField(min_value=parameter.min_value, max_value=parameter.max_value,
                                     step_size=parameter.step, **common)
            field.widget.attrs.update(attrs, step=parameter.step or 'any')
            return field
        if kind in ('select', 'multiselect'):
            choices = []
            for option in parameter.options or []:
                if isinstance(option, dict):
                    value = option.get('value', option.get('label', ''))
                    choices.append((str(value), str(option.get('label', value))))
                else:
                    choices.append((str(option), str(option)))
            if kind == 'multiselect':
                return forms.MultipleChoiceField(choices=choices, widget=forms.CheckboxSelectMultiple, **common)
            return forms.ChoiceField(choices=[('', 'Choose an option')] + choices, **common)
        if kind == 'boolean':
            return forms.TypedChoiceField(choices=[('', 'Choose yes or no'), ('true', 'Yes'), ('false', 'No')],
                                          coerce=lambda value: str(value).lower() == 'true', empty_value=None, **common)
        if kind == 'date':
            return forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'), **common)
        if kind == 'color':
            return forms.RegexField(regex=r'^#[0-9a-fA-F]{6}$',
                                    widget=forms.TextInput(attrs={'placeholder': '#000000', 'type': 'color'}), **common)
        widget = forms.Textarea(attrs={**attrs, 'rows': 3}) if kind == 'textarea' else forms.TextInput(attrs=attrs)
        return forms.CharField(widget=widget, **common)

    @property
    def attribute_fields(self):
        return [self['attribute_' + name] for name in self.parameter_fields]

    def clean_tags(self):
        return list(dict.fromkeys(tag.strip() for tag in self.cleaned_data['tags'].split(',') if tag.strip()))

    def clean(self):
        data = super().clean()
        for field in ('price', 'quantity', 'custom_delivery_fee'):
            if data.get(field) is not None and data[field] < 0:
                self.add_error(field, 'Must be zero or greater.')
        if data.get('custom_delivery_fee_enabled') and data.get('custom_delivery_fee') is None:
            self.add_error('custom_delivery_fee', 'Enter a delivery fee.')
        values = dict(self.instance.dynamic_fields or {}) if self.same_taxonomy else {}
        for name, parameter in self.parameter_fields.items():
            value = data.get('attribute_' + name)
            if parameter.field_type == 'date' and value:
                value = value.isoformat()
            if value is None or value == '' or value == []:
                values.pop(name, None)
            else:
                values[name] = value
        self.instance.dynamic_fields = values
        return data


@login_required
@csrf_protect
def manage_universal_products(request, product_id=None):
    if not request.user.is_superuser:
        raise PermissionDenied
    product = (get_object_or_404(Product, pk=product_id, is_universal=True)
               if product_id else Product(is_universal=True))
    if request.method == 'GET' and request.GET.get('form_options') == '1':
        form = UniversalProductForm(instance=product, initial={
            'category': request.GET.get('category', ''),
            'subcategory': request.GET.get('subcategory', ''),
        })
        return render(request, 'accounts/product_attributes.html', {'form': form})
    form = UniversalProductForm(request.POST if request.method == 'POST' else None,
                                request.FILES or None, instance=product)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            product = form.save()
            product.images.filter(pk__in=request.POST.getlist('remove_images')).delete()
            if form.cleaned_data.get('image'):
                ProductImage.objects.create(product=product, image=form.cleaned_data['image'],
                                            is_primary=not product.images.exists())
            if product.images.exists() and not product.images.filter(is_primary=True).exists():
                first_image = product.images.order_by('pk').first()
                first_image.is_primary = True
                first_image.save(update_fields=['is_primary'])
        return redirect('manage_universal_products')
    products = Product.objects.filter(is_universal=True).select_related('pricing_group').order_by('-created_at', '-pk')
    if request.GET.get('search'):
        products = products.filter(name__icontains=request.GET['search'])
    return render(request, 'accounts/manage_universal_products.html', {
        'form': form, 'editing': product_id, 'product': product,
        'products': Paginator(products, 25).get_page(request.GET.get('page')),
    })
