from decimal import Decimal
from django.test import TestCase
from django.urls import reverse

from .models import PricingGroup, Product, CustomUser, VendorProfile, Cart, CartItem
from .serializers import CustomerProductSerializer, CartSerializer
from .pricing_admin import PricingGroupForm
from .catalog import filter_catalog


class PricingGroupTests(TestCase):
    def setUp(self):
        self.group = PricingGroup.objects.create(name='Weekly discount', adjustment_percent=Decimal('-15'))
        self.product = Product.objects.create(name='Rice', category='Food', price=Decimal('100'),
                                              is_universal=True, pricing_group=self.group, quantity=10)
        self.other = Product.objects.create(name='Milk', category='Food', price=Decimal('90'), is_universal=True)

    def test_discount_markup_and_deactivation_preserve_base(self):
        self.assertEqual(self.product.selling_price, Decimal('85.00'))
        data = CustomerProductSerializer(self.product).data
        self.assertEqual((data['price'], data['base_price'], data['has_discount']), ('85.00', '100.00', True))
        self.group.adjustment_percent = Decimal('25')
        self.group.save()
        self.product.refresh_from_db()
        data = CustomerProductSerializer(self.product).data
        self.assertEqual((data['price'], data['base_price'], data['has_discount']), ('125.00', '100.00', False))
        self.group.is_active = False
        self.group.save()
        self.product.refresh_from_db()
        self.assertEqual(self.product.selling_price, Decimal('100.00'))
        self.assertEqual(self.product.price, Decimal('100.00'))

    def test_rounding_zero_full_discount_and_changed_base(self):
        self.product.price = Decimal('19.99')
        self.group.adjustment_percent = Decimal('-50')
        self.assertEqual(self.product.selling_price, Decimal('10.00'))
        self.group.adjustment_percent = Decimal('-100')
        self.assertEqual(self.product.selling_price, Decimal('0.00'))
        self.group.adjustment_percent = Decimal('0')
        self.assertEqual(self.product.selling_price, Decimal('19.99'))
        self.assertFalse(self.product.has_discount)

    def test_cart_uses_selling_price_and_recalculates_after_group_change(self):
        user = CustomUser.objects.create_user(username='cart_customer')
        cart = Cart.objects.create(user=user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=3)
        data = CartSerializer(cart).data
        self.assertEqual(data['subtotal'], '255.00')
        self.assertEqual(data['items'][0]['total_price'], '255.00')
        self.group.adjustment_percent = Decimal('20')
        self.group.save()
        self.assertEqual(CartSerializer(cart).data['subtotal'], '360.00')

    def test_sort_uses_selling_prices(self):
        self.assertEqual(list(filter_catalog({'sort': 'price_low'}).values_list('name', flat=True)), ['Rice', 'Milk'])
        self.group.adjustment_percent = Decimal('20')
        self.group.save()
        self.assertEqual(list(filter_catalog({'sort': 'price_low'}).values_list('name', flat=True)), ['Milk', 'Rice'])

    def test_vendor_inventory_is_unaffected(self):
        user = CustomUser.objects.create_user(username='vendor')
        vendor = VendorProfile.objects.create(user=user, business_name='POS')
        product = Product.objects.create(name='POS rice', vendor=vendor, price=Decimal('100'), pricing_group=self.group)
        self.assertEqual(product.selling_price, Decimal('100.00'))
        self.assertNotIn(product, PricingGroupForm(instance=self.group).fields['products'].queryset)

    def test_superadmin_can_assign_remove_and_disable_group(self):
        admin = CustomUser.objects.create_superuser(username='pricing_admin', password='test')
        self.client.force_login(admin)
        url = reverse('edit_pricing_group', args=[self.group.pk])
        self.assertContains(self.client.get(url), 'Weekly discount')
        response = self.client.post(url, {'name': self.group.name, 'direction': 'increase', 'percentage': '12.50',
                                         'is_active': 'on', 'products': [self.other.pk]})
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.other.refresh_from_db()
        self.assertIsNone(self.product.pricing_group_id)
        self.assertEqual(self.product.selling_price, Decimal('100.00'))
        self.assertEqual(self.other.selling_price, Decimal('101.25'))
        self.assertEqual(self.other.price, Decimal('90.00'))
        self.client.post(url, {'name': self.group.name, 'direction': 'increase', 'percentage': '12.50', 'products': [self.other.pk]})
        self.other.refresh_from_db()
        self.assertEqual(self.other.selling_price, Decimal('90.00'))

    def test_invalid_percentages_overlap_and_access(self):
        for direction, percentage in [('decrease', '100.01'), ('decrease', '-1'), ('increase', '1000.01')]:
            form = PricingGroupForm({'name': 'Invalid', 'direction': direction, 'percentage': percentage})
            self.assertFalse(form.is_valid())
            self.assertIn('percentage', form.errors)
        form = PricingGroupForm({'name': 'Other group', 'direction': 'decrease', 'percentage': '10', 'products': [self.product.pk]})
        self.assertFalse(form.is_valid())
        self.assertIn('products', form.errors)
        self.client.force_login(CustomUser.objects.create_user(username='customer'))
        self.assertEqual(self.client.post(reverse('manage_pricing_groups'), {'name': 'Unauthorized'}).status_code, 403)

    def test_deleting_group_restores_base(self):
        self.group.delete()
        self.product.refresh_from_db()
        self.assertIsNone(self.product.pricing_group_id)
        self.assertEqual(self.product.selling_price, Decimal('100.00'))
