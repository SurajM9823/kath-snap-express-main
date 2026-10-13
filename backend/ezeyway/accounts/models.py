from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
from rest_framework.authtoken.models import Token
import random
import string

class CustomUser(AbstractUser):
    USER_TYPE_CHOICES = [
        ('superuser', 'Super Admin'),
        ('vendor', 'Vendor'),
        ('customer', 'Customer'),
    ]
    
    user_type = models.CharField(max_length=20, choices=USER_TYPE_CHOICES, default='customer')
    is_customer = models.BooleanField(default=True)  # Can act as customer
    is_vendor = models.BooleanField(default=False)   # Can act as vendor (after approval)
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    profile_picture = models.CharField(max_length=500, blank=True, null=True)  # Temporarily using CharField instead of ImageField
    profile_picture_url = models.URLField(blank=True, null=True)  # For Google profile pictures
    google_id = models.CharField(max_length=100, blank=True, null=True, unique=True)  # Google OAuth ID
    facebook_id = models.CharField(max_length=100, blank=True, null=True, unique=True)  # Facebook OAuth ID
    privacy_policy_agreed = models.BooleanField(default=False)  # Privacy policy agreement status

    plain_password = models.CharField(max_length=255, blank=True, null=True)
    is_verified = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)
    phone_verified = models.BooleanField(default=False)
    
    email_otp = models.CharField(max_length=6, blank=True, null=True)
    phone_otp = models.CharField(max_length=6, blank=True, null=True)
    otp_created_at = models.DateTimeField(blank=True, null=True)
    
    email_verification_token = models.CharField(max_length=100, blank=True, null=True)
    email_verification_sent_at = models.DateTimeField(blank=True, null=True)
    
    password_reset_token = models.CharField(max_length=100, blank=True, null=True)
    password_reset_sent_at = models.DateTimeField(blank=True, null=True)
    
    # Referral code for vendors
    referral_code = models.CharField(max_length=10, unique=True, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def save(self, *args, **kwargs):
        if self.password and not self.password.startswith('pbkdf2_'):
            self.plain_password = self.password
        super().save(*args, **kwargs)
    
    def generate_otp(self):
        otp = ''.join(random.choices(string.digits, k=6))
        self.email_otp = otp
        self.phone_otp = otp
        self.otp_created_at = timezone.now()
        self.save()
        return otp
    
    def generate_verification_token(self):
        token = ''.join(random.choices(string.ascii_letters + string.digits, k=50))
        self.email_verification_token = token
        self.email_verification_sent_at = timezone.now()
        self.save()
        return token
    
    def generate_password_reset_token(self):
        token = ''.join(random.choices(string.ascii_letters + string.digits, k=50))
        self.password_reset_token = token
        self.password_reset_sent_at = timezone.now()
        self.save()
        return token
    
    def generate_referral_code(self):
        """Generate unique referral code for vendors"""
        if self.user_type == 'vendor' and not self.referral_code:
            while True:
                code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                if not CustomUser.objects.filter(referral_code=code).exists():
                    self.referral_code = code
                    self.save()
                    return code
        return self.referral_code
    
    def __str__(self):
        return f"{self.username} ({self.get_user_type_display()})"
    
    @property
    def is_superadmin(self):
        return self.user_type == 'superuser'
    
    @property
    def is_vendor_type(self):
        return self.user_type == 'vendor'
    
    @property
    def is_customer_type(self):
        return self.user_type == 'customer'

class VendorProfile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='vendor_profile')
    business_name = models.CharField(max_length=200)
    owner_name = models.CharField(max_length=200, default='')
    business_email = models.EmailField()
    business_phone = models.CharField(max_length=15)
    business_address = models.TextField()
    location_address = models.TextField(blank=True, null=True)
    city = models.CharField(max_length=100, default='')
    state = models.CharField(max_length=100)
    pincode = models.CharField(max_length=20, default='')
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    business_type = models.CharField(
        max_length=50,
        choices=[
            ('retailer', 'Retailer'),
            ('wholesaler', 'Wholesaler'),
            ('manufacturer', 'Manufacturer'),
            ('service_provider', 'Service Provider'),
            ('grocery', 'Grocery Store'),
            ('restaurant', 'Restaurant'),
            ('pharmacy', 'Pharmacy'),
            ('electronics', 'Electronics'),
            ('clothing', 'Clothing'),
            ('bakery', 'Bakery'),
        ],
        default='retailer'
    )
    categories = models.JSONField(default=list)
    description = models.TextField(blank=True, null=True)
    business_license = models.CharField(max_length=100, blank=True, null=True)
    business_license_file = models.CharField(max_length=500, blank=True, null=True)
    gst_number = models.CharField(max_length=50, blank=True, null=True)
    gst_certificate = models.CharField(max_length=500, blank=True, null=True)
    pan_number = models.CharField(max_length=50, blank=True, null=True)
    fssai_license = models.CharField(max_length=500, blank=True, null=True)
    bank_name = models.CharField(max_length=100, blank=True, null=True)
    account_holder_name = models.CharField(max_length=200, blank=True, null=True)
    account_number = models.CharField(max_length=50, blank=True, null=True)
    ifsc_code = models.CharField(max_length=20, blank=True, null=True)
    bank_document = models.CharField(max_length=500, blank=True, null=True)
    min_order_amount = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    established_year = models.CharField(max_length=4, blank=True, null=True)
    employee_count = models.CharField(max_length=20, blank=True, null=True)
    website = models.URLField(blank=True, null=True)
    facebook = models.URLField(blank=True, null=True)
    instagram = models.URLField(blank=True, null=True)
    twitter = models.URLField(blank=True, null=True)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    free_delivery_above = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    estimated_delivery_time = models.CharField(max_length=50, blank=True, null=True)
    delivery_slots = models.JSONField(default=list)
    online_ordering = models.BooleanField(default=True)
    home_delivery = models.BooleanField(default=True)
    pickup_service = models.BooleanField(default=True)
    bulk_orders = models.BooleanField(default=False)
    subscription_service = models.BooleanField(default=False)
    loyalty_program = models.BooleanField(default=False)
    business_license_status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected')
    ], default='pending')
    gst_certificate_status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected')
    ], default='pending')
    fssai_license_status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected')
    ], default='pending')
    bank_account_status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected')
    ], default='pending')
    is_approved = models.BooleanField(default=False)
    approval_date = models.DateTimeField(blank=True, null=True)
    is_rejected = models.BooleanField(default=False)
    rejection_reason = models.TextField(blank=True, null=True)
    rejection_date = models.DateTimeField(blank=True, null=True)
    
    # Operating hours fields
    monday_open = models.TimeField(blank=True, null=True)
    monday_close = models.TimeField(blank=True, null=True)
    monday_closed = models.BooleanField(default=False)
    tuesday_open = models.TimeField(blank=True, null=True)
    tuesday_close = models.TimeField(blank=True, null=True)
    tuesday_closed = models.BooleanField(default=False)
    wednesday_open = models.TimeField(blank=True, null=True)
    wednesday_close = models.TimeField(blank=True, null=True)
    wednesday_closed = models.BooleanField(default=False)
    thursday_open = models.TimeField(blank=True, null=True)
    thursday_close = models.TimeField(blank=True, null=True)
    thursday_closed = models.BooleanField(default=False)
    friday_open = models.TimeField(blank=True, null=True)
    friday_close = models.TimeField(blank=True, null=True)
    friday_closed = models.BooleanField(default=False)
    saturday_open = models.TimeField(blank=True, null=True)
    saturday_close = models.TimeField(blank=True, null=True)
    saturday_closed = models.BooleanField(default=False)
    sunday_open = models.TimeField(blank=True, null=True)
    sunday_close = models.TimeField(blank=True, null=True)
    sunday_closed = models.BooleanField(default=False)
    
    # Status fields
    is_active = models.BooleanField(default=False)  # Current active/inactive status
    status_override = models.BooleanField(default=False)  # Indicates if status is manually overridden
    status_override_date = models.DateField(blank=True, null=True)  # Date of the override
    
    # FCM Token for push notifications
    fcm_token = models.TextField(blank=True, null=True)  # Firebase Cloud Messaging token
    fcm_updated_at = models.DateTimeField(blank=True, null=True)  # When FCM token was last updated
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.business_name} - {self.user.username}"

class VendorDocument(models.Model):
    vendor_profile = models.ForeignKey(VendorProfile, on_delete=models.CASCADE, related_name='additional_docs')
    document = models.CharField(max_length=500)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Document for {self.vendor_profile.business_name}"

class VendorShopImage(models.Model):
    vendor_profile = models.ForeignKey(VendorProfile, on_delete=models.CASCADE, related_name='shop_images')
    image = models.CharField(max_length=500)
    is_primary = models.BooleanField(default=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-is_primary', 'uploaded_at']
    
    def __str__(self):
        return f"Shop Image for {self.vendor_profile.business_name}"

class VendorChangeRequest(models.Model):
    CHANGE_TYPE_CHOICES = [
        ('address', 'Address'),
        ('banking', 'Banking'),
    ]
    
    vendor_profile = models.ForeignKey(VendorProfile, on_delete=models.CASCADE, related_name='change_requests')
    change_type = models.CharField(max_length=20, choices=CHANGE_TYPE_CHOICES)
    new_address = models.TextField(blank=True, null=True)
    new_city = models.CharField(max_length=100, blank=True, null=True)
    new_state = models.CharField(max_length=100, blank=True, null=True)
    new_pincode = models.CharField(max_length=20, blank=True, null=True)
    new_bank_name = models.CharField(max_length=100, blank=True, null=True)
    new_account_holder_name = models.CharField(max_length=200, blank=True, null=True)
    new_account_number = models.CharField(max_length=50, blank=True, null=True)
    new_ifsc_code = models.CharField(max_length=20, blank=True, null=True)
    reason = models.TextField()
    is_approved = models.BooleanField(default=False)
    request_date = models.DateTimeField(auto_now_add=True)
    approval_date = models.DateTimeField(blank=True, null=True)
    
    def __str__(self):
        return f"{self.change_type} request for {self.vendor_profile.business_name}"

class Product(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('draft', 'Draft'),
        ('archived', 'Archived'),
    ]
    
    # Universal products belong to the platform; vendor inventory remains private to POS.
    is_universal = models.BooleanField(default=False, db_index=True)
    vendor = models.ForeignKey(VendorProfile, on_delete=models.CASCADE, related_name='products', null=True, blank=True)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100)
    subcategory = models.CharField(max_length=100, blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    sku = models.CharField(max_length=100, blank=True, null=True)
    barcode = models.CharField(max_length=100, blank=True, null=True)
    quantity = models.IntegerField(default=0)
    low_stock_threshold = models.IntegerField(blank=True, null=True)
    description = models.TextField()
    short_description = models.TextField(blank=True, null=True)
    tags = models.JSONField(default=list)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    featured = models.BooleanField(default=False)
    free_delivery = models.BooleanField(default=False)
    custom_delivery_fee_enabled = models.BooleanField(default=False)
    custom_delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    seo_title = models.CharField(max_length=200, blank=True, null=True)
    seo_description = models.TextField(blank=True, null=True)
    dynamic_fields = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.name} - {'Universal catalog' if self.is_universal else self.vendor.business_name}"
    
    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(is_universal=True, vendor__isnull=True) |
                           models.Q(is_universal=False, vendor__isnull=False)),
                name='product_catalog_ownership',
            ),
        ]

    @property
    def total_sold(self):
        """Calculate total sold from completed orders.

        Include orders that are in final/fulfilled statuses so the
        displayed 'sold' count reflects delivered/completed sales.
        """
        try:
            from .order_models import OrderItem
            # Count items from orders which are in completed statuses
            completed_statuses = ['confirmed', 'delivered']
            total = OrderItem.objects.filter(
                product=self,
                order__status__in=completed_statuses
            ).aggregate(total=models.Sum('quantity'))['total'] or 0
            return total
        except Exception:
            # If anything goes wrong (import error or DB issue), return 0
            return 0

def product_image_upload_path(instance, filename):
    return f'products/{instance.product.vendor_id or "universal"}/{filename}'

class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to=product_image_upload_path)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Image for {self.product.name}"

# Wallet and Commission Models
class VendorWallet(models.Model):
    vendor = models.OneToOneField(VendorProfile, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_earned = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_spent = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Wallet - {self.vendor.business_name}: ₹{self.balance}"
    
    def add_money(self, amount, description="Wallet Recharge"):
        """Add money to wallet"""
        self.balance += amount
        self.total_earned += amount
        self.save()
        
        # Create transaction record
        WalletTransaction.objects.create(
            wallet=self,
            transaction_type='credit',
            amount=amount,
            description=description,
            status='completed'
        )
    
    def deduct_commission(self, amount, order_amount, description="Commission Deduction"):
        """Deduct commission from wallet"""
        if self.balance >= amount:
            self.balance -= amount
            self.total_spent += amount
            self.save()
            
            # Create transaction record
            WalletTransaction.objects.create(
                wallet=self,
                transaction_type='debit',
                amount=amount,
                description=description,
                order_amount=order_amount,
                status='completed'
            )
            
            # Auto-disable vendor if balance drops below 100
            if self.balance < 100 and self.vendor.is_active:
                from django.utils import timezone
                self.vendor.is_active = False
                self.vendor.status_override = True
                self.vendor.status_override_date = timezone.now().date()
                self.vendor.save()
            
            return True
        return False

class CommissionRange(models.Model):
    """Model to store commission ranges set by superadmin"""
    min_amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Minimum order amount")
    max_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Maximum order amount (null for unlimited)")
    commission_amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Fixed commission amount to deduct")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['min_amount']
    
    def __str__(self):
        max_display = f"₹{self.max_amount}" if self.max_amount else "∞"
        return f"₹{self.min_amount} - {max_display}: ₹{self.commission_amount} commission"
    
    @classmethod
    def get_commission_for_amount(cls, order_amount):
        """Get commission amount for a given order amount"""
        ranges = cls.objects.filter(is_active=True).order_by('min_amount')
        
        for commission_range in ranges:
            if order_amount >= commission_range.min_amount:
                if commission_range.max_amount is None or order_amount <= commission_range.max_amount:
                    return commission_range.commission_amount
        
        return 0  # No commission if no range matches

class WalletTransaction(models.Model):
    TRANSACTION_TYPES = [
        ('credit', 'Credit'),
        ('debit', 'Debit'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    wallet = models.ForeignKey(VendorWallet, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.CharField(max_length=255)
    order_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Original order amount for commission transactions")
    payment_method = models.CharField(max_length=50, blank=True, null=True)
    reference_id = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.wallet.vendor.business_name} - {self.transaction_type.upper()} ₹{self.amount}"

class UserFavorite(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='favorites')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='favorited_by')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('user', 'product')
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.username} - {self.product.name}"

class Cart(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='cart')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Cart - {self.user.username}"
    
    @property
    def total_items(self):
        return sum(item.quantity for item in self.items.all())
    
    @property
    def subtotal(self):
        return sum(item.total_price for item in self.items.all())

class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('cart', 'product')
    
    def __str__(self):
        return f"{self.product.name} x {self.quantity}"
    
    @property
    def total_price(self):
        return self.product.price * self.quantity

@receiver(post_save, sender=CustomUser)
def create_auth_token(sender, instance=None, created=False, **kwargs):
    if created:
        Token.objects.create(user=instance)
        # Generate referral code for vendors
        if instance.user_type == 'vendor':
            instance.generate_referral_code()

@receiver(post_save, sender=VendorProfile)
def create_vendor_wallet(sender, instance=None, created=False, **kwargs):
    if created:
        # Ensure user has referral code
        if not instance.user.referral_code:
            instance.user.generate_referral_code()
        
        # Get initial wallet points set by admin
        initial_points = InitialWalletPoints.objects.first()
        initial_balance = initial_points.points if initial_points else 0
        
        # Create wallet with initial balance
        wallet = VendorWallet.objects.create(
            vendor=instance,
            balance=initial_balance,
            total_earned=initial_balance
        )
        
        # Create transaction record for initial points
        if initial_balance > 0:
            WalletTransaction.objects.create(
                wallet=wallet,
                transaction_type='credit',
                amount=initial_balance,
                description='Initial wallet points from admin',
                status='completed'
            )

def category_icon_upload_path(instance, filename):
    return f'categories/icons/{filename}'

class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    icon = models.ImageField(upload_to=category_icon_upload_path, blank=True, null=True, help_text="Upload category icon")
    description = models.TextField(blank=True, null=True, help_text="Optional category description")
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0, help_text="Display order (0 = first)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['display_order', 'name']
    
    def __str__(self):
        return self.name
    
    @property
    def subcategories_count(self):
        return self.subcategories.count()

class SubCategory(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='subcategories')
    name = models.CharField(max_length=100)
    icon = models.ImageField(upload_to=category_icon_upload_path, blank=True, null=True, help_text="Upload subcategory icon")
    description = models.TextField(blank=True, null=True, help_text="Optional subcategory description")
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0, help_text="Display order within category")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = "Sub Categories"
        ordering = ['display_order', 'name']
        unique_together = ('category', 'name')  # Unique subcategory name within each category
    
    def __str__(self):
        return f"{self.category.name} > {self.name}"

class InitialWalletPoints(models.Model):
    points = models.DecimalField(max_digits=10, decimal_places=2, help_text="Initial wallet points for new vendors")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = "Initial Wallet Points"
        ordering = ['points']
    
    def __str__(self):
        return f"₹{self.points}"

class ChargeRate(models.Model):
    min_amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Minimum order amount")
    max_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Maximum order amount (null for unlimited)")
    charge = models.DecimalField(max_digits=10, decimal_places=2, help_text="Charge amount for this range")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['min_amount']
    
    def __str__(self):
        max_display = f"₹{self.max_amount}" if self.max_amount else "∞"
        return f"₹{self.min_amount} - {max_display}: ₹{self.charge} charge"
    
    def clean(self):
        from django.core.exceptions import ValidationError
        # Check for overlapping ranges
        existing_ranges = ChargeRate.objects.exclude(id=self.id)
        for existing in existing_ranges:
            # Check if ranges overlap
            existing_max = existing.max_amount or float('inf')
            current_max = self.max_amount or float('inf')
            
            if (self.min_amount < existing_max and 
                (self.max_amount is None or self.max_amount > existing.min_amount)):
                raise ValidationError(f'Range overlaps with existing range: {existing}')
    
    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

# Import order models
from .order_models import *

class FeaturedProductPackage(models.Model):
    PACKAGE_TYPE_CHOICES = [
        ('basic', 'Basic'),
        ('premium', 'Premium'),
        ('gold', 'Gold'),
        ('platinum', 'Platinum'),
    ]
    
    name = models.CharField(max_length=100, help_text="Package name (e.g., '10 Days Basic')")
    duration_days = models.PositiveIntegerField(help_text="Duration in days")
    amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Package price in rupees")
    package_type = models.CharField(max_length=20, choices=PACKAGE_TYPE_CHOICES, default='basic')
    description = models.TextField(blank=True, null=True, help_text="Package description")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['duration_days', 'amount']
        verbose_name = "Featured Product Package"
        verbose_name_plural = "Featured Product Packages"
    
    def __str__(self):
        return f"{self.name} - ₹{self.amount} for {self.duration_days} days"

def slider_upload_path(instance, filename):
    return f'sliders/{filename}'

class Slider(models.Model):
    VISIBILITY_CHOICES = [
        ('customer', 'Customer Side Only'),
        ('vendor', 'Vendor Side Only'),
        ('both', 'Both Customer & Vendor'),
    ]
    
    title = models.CharField(max_length=200, help_text="Slider title")
    description = models.TextField(blank=True, null=True, help_text="Optional slider description")
    image = models.ImageField(upload_to=slider_upload_path, help_text="Upload slider image (GIF, PNG, SVG, JPEG)")
    link_url = models.URLField(blank=True, null=True, help_text="Optional link when slider is clicked")
    visibility = models.CharField(max_length=20, choices=VISIBILITY_CHOICES, default='both')
    display_order = models.PositiveIntegerField(default=0, help_text="Display order (0 = first, higher numbers = later)")
    is_active = models.BooleanField(default=True)
    start_date = models.DateTimeField(blank=True, null=True, help_text="Optional start date for slider")
    end_date = models.DateTimeField(blank=True, null=True, help_text="Optional end date for slider")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['display_order', 'created_at']
        verbose_name = "Slider"
        verbose_name_plural = "Sliders"
    
    def __str__(self):
        return f"{self.title} ({self.get_visibility_display()})"
    
    @property
    def is_currently_active(self):
        """Check if slider is active and within date range"""
        if not self.is_active:
            return False
        
        now = timezone.now()
        if self.start_date and now < self.start_date:
            return False
        if self.end_date and now > self.end_date:
            return False
        
        return True

class PushNotification(models.Model):
    RECIPIENT_CHOICES = [
        ('customer', 'Customers Only'),
        ('vendor', 'Vendors Only'),
        ('both', 'Both Customers & Vendors'),
    ]
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('scheduled', 'Scheduled'),
    ]
    
    title = models.CharField(max_length=100, help_text="Notification title")
    message = models.TextField(max_length=500, help_text="Notification message")
    recipient_type = models.CharField(max_length=20, choices=RECIPIENT_CHOICES, default='both')
    scheduled_time = models.DateTimeField(blank=True, null=True, help_text="Send immediately if empty")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    sent_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.title} - {self.get_recipient_type_display()}"

class ProductFeaturedPurchase(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='featured_purchases')
    vendor = models.ForeignKey(VendorProfile, on_delete=models.CASCADE, related_name='featured_purchases')
    package = models.ForeignKey(FeaturedProductPackage, on_delete=models.CASCADE)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.product.name} - {self.package.name} ({self.start_date} to {self.end_date})"

# Import message models
from .message_models import *

# Import parameter models
from .parameter_models import *