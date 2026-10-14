from django.test import TestCase
from django.urls import reverse

from .catalog_admin import UniversalProductForm
from .models import Category, SubCategory, CustomUser, Product
from .parameter_models import CategoryParameter, SubCategoryParameter


class CatalogProductFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name='Groceries')
        cls.other = Category.objects.create(name='Clothes')
        cls.subcategory = SubCategory.objects.create(category=cls.category, name='Milk')
        cls.inactive = Category.objects.create(name='Hidden', is_active=False)
        CategoryParameter.objects.create(category=cls.category, name='brand', label='Brand', is_required=True)
        CategoryParameter.objects.create(category=cls.category, name='weight', label='Weight', field_type='number', min_value=1, max_value=10, step=0.5)
        SubCategoryParameter.objects.create(subcategory=cls.subcategory, name='size', label='Size', field_type='select', options=['Small', 'Large'])
        SubCategoryParameter.objects.create(subcategory=cls.subcategory, name='organic', label='Organic', field_type='boolean', is_required=True)
        SubCategoryParameter.objects.create(subcategory=cls.subcategory, name='features', label='Features', field_type='multiselect', options=['Fresh', 'Local'])
        SubCategoryParameter.objects.create(subcategory=cls.subcategory, name='expires', label='Expiry', field_type='date')
        cls.admin = CustomUser.objects.create_superuser(username='form_admin', password='test')

    def data(self, **changes):
        values = dict(name='Milk', category='Groceries', subcategory='Milk', price='100', quantity='20',
                      description='Fresh milk', status='active', tags='fresh, local, fresh',
                      attribute_brand='Dairy', attribute_weight='1.5', attribute_size='Large',
                      attribute_organic='false', attribute_features=['Fresh', 'Local'], attribute_expires='2026-12-01')
        values.update(changes)
        return values

    def form(self, **changes):
        return UniversalProductForm(self.data(**changes), instance=Product(is_universal=True))

    def test_form_saves_typed_attributes_and_simple_tags(self):
        form = self.form()
        self.assertTrue(form.is_valid(), form.errors)
        product = form.save()
        self.assertEqual(product.tags, ['fresh', 'local'])
        self.assertEqual(product.dynamic_fields, {'brand': 'Dairy', 'weight': 1.5, 'size': 'Large',
                                                'organic': False, 'features': ['Fresh', 'Local'], 'expires': '2026-12-01'})

    def test_invalid_taxonomy_and_parameter_values_are_rejected(self):
        for values, error in [({'category': 'Hidden'}, 'category'), ({'category': 'Invented'}, 'category'),
                              ({'category': 'Clothes', 'subcategory': 'Milk'}, 'subcategory'),
                              ({'attribute_brand': ''}, 'attribute_brand'),
                              ({'attribute_size': 'Bad'}, 'attribute_size'),
                              ({'attribute_features': ['Bad']}, 'attribute_features'),
                              ({'attribute_weight': '11'}, 'attribute_weight'),
                              ({'attribute_weight': '1.2'}, 'attribute_weight'),
                              ({'attribute_organic': ''}, 'attribute_organic'),
                              ({'attribute_expires': 'bad'}, 'attribute_expires')]:
            with self.subTest(values=values):
                form = self.form(**values)
                self.assertFalse(form.is_valid())
                self.assertIn(error, form.errors)

    def test_custom_fee_visibility_is_enforced_on_server(self):
        for values in ({'custom_delivery_fee': 'bad'},
                       {'free_delivery': 'on', 'custom_delivery_fee_enabled': 'on', 'custom_delivery_fee': 'bad'}):
            form = self.form(**values)
            self.assertTrue(form.is_valid(), form.errors)
            product = form.save()
            self.assertFalse(product.custom_delivery_fee_enabled)
            self.assertIsNone(product.custom_delivery_fee)
        self.assertIn('custom_delivery_fee', self.form(custom_delivery_fee_enabled='on').errors)
        self.assertIn('custom_delivery_fee', self.form(custom_delivery_fee_enabled='on', custom_delivery_fee='-1').errors)

    def test_edit_initial_values_and_taxonomy_change(self):
        form = self.form()
        self.assertTrue(form.is_valid(), form.errors)
        product = form.save()
        edit = UniversalProductForm(instance=product)
        self.assertEqual(edit['attribute_organic'].value(), 'false')
        self.assertEqual(edit['tags'].value(), 'fresh, local')
        changed = UniversalProductForm(self.data(category='Clothes', subcategory=''), instance=product)
        self.assertTrue(changed.is_valid(), changed.errors)
        self.assertEqual(changed.save().dynamic_fields, {})

    def test_subcategory_parameters_override_category_parameters(self):
        SubCategoryParameter.objects.create(subcategory=self.subcategory, name='brand', label='Milk brand', field_type='select', options=['Dairy'])
        form = self.form()
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form['attribute_brand'].label, 'Milk brand')

    def test_dashboard_and_background_fields(self):
        self.client.force_login(self.admin)
        url = reverse('manage_universal_products')
        response = self.client.get(url)
        self.assertContains(response, 'Pricing & stock', html=False)
        self.assertContains(response, 'Groceries')
        self.assertNotContains(response, 'name="dynamic_fields"')
        response = self.client.get(url, {'form_options': '1', 'category': 'Groceries', 'subcategory': 'Milk'})
        self.assertContains(response, 'name="attribute_brand"')
        self.assertContains(response, 'name="attribute_organic"')
        self.assertContains(response, 'value="Milk"')
        response = self.client.post(url, self.data())
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Product.objects.get(name='Milk').is_universal)

    def test_background_fields_require_superadmin(self):
        user = CustomUser.objects.create_user(username='customer')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('manage_universal_products'), {'form_options': '1'}).status_code, 403)
