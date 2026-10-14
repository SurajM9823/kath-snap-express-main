from django.db import models
from django.utils import timezone
from decimal import Decimal, ROUND_DOWN
from .models import CustomUser, VendorProfile, Product

class Order(models.Model):
    ORDER_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('preparing', 'Preparing'),
        ('ready_for_pickup', 'Ready for Pickup'),
        ('out_for_delivery', 'Out for Delivery'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
        ('returned', 'Returned'),
        ('refunded', 'Refunded'),
    ]
    
    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
        ('partially_refunded', 'Partially Refunded'),
    ]
    
    PAYMENT_METHOD_CHOICES = [
        ('esewa', 'eSewa'),
        ('khalti', 'Khalti'),
        ('cash_on_delivery', 'Cash on Delivery'),
    ]
    
    # Basic Order Info
    order_number = models.CharField(max_length=20, unique=True)
    customer = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='orders')
    vendor = models.ForeignKey(VendorProfile, on_delete=models.CASCADE, related_name='orders')
    
    # Order Status
    status = models.CharField(max_length=20, choices=ORDER_STATUS_CHOICES, default='pending')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    
    # Delivery Information
    delivery_name = models.CharField(max_length=200)
    delivery_phone = models.CharField(max_length=15)
    delivery_address = models.TextField()
    delivery_latitude = models.FloatField()
    delivery_longitude = models.FloatField()
    delivery_instructions = models.TextField(blank=True, null=True)
    delivery_distance = models.FloatField(help_text="Distance in km from vendor")
    
    # Order Amounts
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Payment Information
    transaction_id = models.CharField(max_length=100, blank=True, null=True)
    payment_reference = models.CharField(max_length=100, blank=True, null=True)
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(blank=True, null=True)
    prepared_at = models.DateTimeField(blank=True, null=True)
    out_for_delivery_at = models.DateTimeField(blank=True, null=True)
    delivered_at = models.DateTimeField(blank=True, null=True)
    cancelled_at = models.DateTimeField(blank=True, null=True)
    
    # Estimated times
    estimated_preparation_time = models.IntegerField(blank=True, null=True, help_text="Minutes")
    estimated_delivery_time = models.IntegerField(blank=True, null=True, help_text="Minutes")
    
    # Delivery Boy Information
    delivery_boy_phone = models.CharField(max_length=15, blank=True, null=True)
    vehicle_number = models.CharField(max_length=20, blank=True, null=True)
    vehicle_color = models.CharField(max_length=50, blank=True, null=True)
    
    # Additional Info
    cancellation_reason = models.TextField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Order #{self.order_number} - {self.customer.username}"
    
    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = self.generate_order_number()
        super().save(*args, **kwargs)
    
    def generate_order_number(self):
        import random
        import string
        while True:
            order_number = 'ORD' + ''.join(random.choices(string.digits, k=8))
            if not Order.objects.filter(order_number=order_number).exists():
                return order_number
    
    @property
    def can_be_cancelled(self):
        return self.status in ['pending', 'confirmed', 'preparing']
    
    @property
    def can_be_reviewed(self):
        return self.status == 'delivered' and not hasattr(self, 'review')

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Product snapshot at time of order
    product_name = models.CharField(max_length=200)
    product_description = models.TextField(blank=True, null=True)
    vendor_name = models.CharField(max_length=200)
    
    # Product variant selections (color, size, etc.)
    product_selections = models.JSONField(default=dict, blank=True)
    
    def __str__(self):
        return f"{self.product_name} x {self.quantity}"
    
    def save(self, *args, **kwargs):
        if not self.product_name:
            self.product_name = self.product.name
            self.product_description = self.product.description
            self.vendor_name = self.product.vendor.business_name
        self.unit_price = Decimal(self.unit_price).quantize(Decimal('1'), rounding=ROUND_DOWN)
        self.total_price = self.unit_price * self.quantity
        super().save(*args, **kwargs)

class DeliveryRider(models.Model):
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=15)
    vehicle_type = models.CharField(max_length=50, choices=[
        ('bike', 'Bike'),
        ('scooter', 'Scooter'),
        ('car', 'Car'),
        ('bicycle', 'Bicycle'),
    ])
    vehicle_number = models.CharField(max_length=20)
    license_number = models.CharField(max_length=50, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    total_deliveries = models.IntegerField(default=0)
    
    # Location tracking
    current_latitude = models.FloatField(blank=True, null=True)
    current_longitude = models.FloatField(blank=True, null=True)
    last_location_update = models.DateTimeField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.name} - {self.vehicle_type} ({self.vehicle_number})"

class OrderDelivery(models.Model):
    DELIVERY_STATUS_CHOICES = [
        ('assigned', 'Assigned'),
        ('picked_up', 'Picked Up'),
        ('in_transit', 'In Transit'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed'),
        ('returned', 'Returned'),
    ]
    
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='delivery')
    rider = models.ForeignKey(DeliveryRider, on_delete=models.CASCADE, related_name='deliveries')
    
    status = models.CharField(max_length=20, choices=DELIVERY_STATUS_CHOICES, default='assigned')
    
    # Tracking Information
    pickup_latitude = models.FloatField(blank=True, null=True)
    pickup_longitude = models.FloatField(blank=True, null=True)
    current_latitude = models.FloatField(blank=True, null=True)
    current_longitude = models.FloatField(blank=True, null=True)
    
    # Timestamps
    assigned_at = models.DateTimeField(auto_now_add=True)
    picked_up_at = models.DateTimeField(blank=True, null=True)
    delivered_at = models.DateTimeField(blank=True, null=True)
    
    # Estimated times
    estimated_pickup_time = models.DateTimeField(blank=True, null=True)
    estimated_delivery_time = models.DateTimeField(blank=True, null=True)
    
    # Additional info
    pickup_notes = models.TextField(blank=True, null=True)
    delivery_notes = models.TextField(blank=True, null=True)
    delivery_photo = models.CharField(max_length=500, blank=True, null=True)
    
    def __str__(self):
        return f"Delivery for Order #{self.order.order_number} by {self.rider.name}"

class OrderStatusHistory(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='status_history')
    status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, null=True)
    
    class Meta:
        ordering = ['-changed_at']
    
    def __str__(self):
        return f"Order #{self.order.order_number} - {self.status} at {self.changed_at}"

class PaymentTransaction(models.Model):
    TRANSACTION_TYPE_CHOICES = [
        ('payment', 'Payment'),
        ('refund', 'Refund'),
        ('partial_refund', 'Partial Refund'),
    ]
    
    TRANSACTION_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=TRANSACTION_STATUS_CHOICES, default='pending')
    
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=Order.PAYMENT_METHOD_CHOICES)
    
    # Payment gateway details
    gateway_transaction_id = models.CharField(max_length=100, blank=True, null=True)
    gateway_reference = models.CharField(max_length=100, blank=True, null=True)
    gateway_response = models.JSONField(default=dict, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(blank=True, null=True)
    
    # Additional info
    notes = models.TextField(blank=True, null=True)
    refund_reason = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return f"{self.transaction_type.title()} - Order #{self.order.order_number} - ₹{self.amount}"

class OrderReview(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='review')
    customer = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    
    # Ratings (1-5 scale)
    overall_rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)])
    food_quality_rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)], blank=True, null=True)
    delivery_rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)], blank=True, null=True)
    vendor_rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)], blank=True, null=True)
    
    # Review text
    review_text = models.TextField(blank=True, null=True)
    
    # Review photos
    review_photos = models.JSONField(default=list, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Moderation
    is_approved = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    
    def __str__(self):
        return f"Review for Order #{self.order.order_number} - {self.overall_rating}★"

class OrderRefund(models.Model):
    REFUND_STATUS_CHOICES = [
        ('requested', 'Requested'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('appeal', 'Appeal'),
        ('processed', 'Processed'),
        ('completed', 'Completed'),
    ]
    
    REFUND_TYPE_CHOICES = [
        ('full', 'Full Refund'),
        ('partial', 'Partial Refund'),
        ('item_specific', 'Item Specific Refund'),
    ]
    
    REFUND_METHOD_CHOICES = [
        ('esewa', 'eSewa'),
        ('khalti', 'Khalti'),
        ('bank', 'Bank Transfer'),
    ]
    
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='refunds')
    customer = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    
    refund_type = models.CharField(max_length=20, choices=REFUND_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=REFUND_STATUS_CHOICES, default='requested')
    
    # Refund details
    requested_amount = models.DecimalField(max_digits=10, decimal_places=2)
    approved_amount = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    reason = models.TextField()
    customer_notes = models.TextField(blank=True, null=True)
    admin_notes = models.TextField(blank=True, null=True)
    
    # Refund method details
    refund_method = models.CharField(max_length=20, choices=REFUND_METHOD_CHOICES)
    esewa_number = models.CharField(max_length=15, blank=True, null=True)
    khalti_number = models.CharField(max_length=15, blank=True, null=True)
    bank_account_name = models.CharField(max_length=200, blank=True, null=True)
    bank_account_number = models.CharField(max_length=50, blank=True, null=True)
    bank_branch = models.CharField(max_length=200, blank=True, null=True)
    
    # Supporting documents
    evidence_photos = models.JSONField(default=list, blank=True)
    vendor_supporting_docs = models.JSONField(default=list, blank=True)  # Documents uploaded by vendor during processing
    
    # Timestamps
    requested_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(blank=True, null=True)
    processed_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    appeal_at = models.DateTimeField(blank=True, null=True)
    
    # Processing info
    processed_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='processed_refunds')
    
    # Customer actions after completion
    customer_received_refund = models.BooleanField(default=False)
    customer_received_at = models.DateTimeField(blank=True, null=True)
    support_contacted = models.BooleanField(default=False)
    support_contacted_at = models.DateTimeField(blank=True, null=True)
    support_notes = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return f"Refund for Order #{self.order.order_number} - ₹{self.requested_amount}"

class OrderNotification(models.Model):
    NOTIFICATION_TYPE_CHOICES = [
        ('order_placed', 'Order Placed'),
        ('order_confirmed', 'Order Confirmed'),
        ('order_preparing', 'Order Preparing'),
        ('order_ready', 'Order Ready'),
        ('order_out_for_delivery', 'Out for Delivery'),
        ('order_delivered', 'Order Delivered'),
        ('order_cancelled', 'Order Cancelled'),
        ('payment_received', 'Payment Received'),
        ('refund_processed', 'Refund Processed'),
    ]
    
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='notifications')
    recipient = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    notification_type = models.CharField(max_length=30, choices=NOTIFICATION_TYPE_CHOICES)
    
    title = models.CharField(max_length=200)
    message = models.TextField()
    
    # Delivery status
    is_sent = models.BooleanField(default=False)
    is_read = models.BooleanField(default=False)
    sent_at = models.DateTimeField(blank=True, null=True)
    read_at = models.DateTimeField(blank=True, null=True)
    
    # Delivery channels
    send_email = models.BooleanField(default=True)
    send_sms = models.BooleanField(default=False)
    send_push = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.notification_type} - Order #{self.order.order_number}"