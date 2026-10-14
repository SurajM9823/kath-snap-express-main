from rest_framework import serializers
from django.utils import timezone
from .order_models import (
    Order, OrderItem, DeliveryRider, OrderDelivery, OrderStatusHistory,
    PaymentTransaction, OrderReview, OrderRefund, OrderNotification
)
from .models import Product, CustomUser, VendorProfile
from .serializers import CustomerProductSerializer, UserSerializer

class OrderItemSerializer(serializers.ModelSerializer):
    product_details = CustomerProductSerializer(source='product', read_only=True)
    
    class Meta:
        model = OrderItem
        fields = [
            'id', 'product', 'product_details', 'quantity', 'unit_price', 
            'total_price', 'delivery_fee', 'product_name', 'product_description', 
            'vendor_name', 'product_selections'
        ]
        read_only_fields = ['id', 'total_price', 'product_name', 'product_description', 'vendor_name']

class DeliveryRiderSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryRider
        fields = [
            'id', 'name', 'phone', 'vehicle_type', 'vehicle_number', 
            'rating', 'total_deliveries', 'current_latitude', 'current_longitude'
        ]
        read_only_fields = ['id', 'rating', 'total_deliveries']

class OrderDeliverySerializer(serializers.ModelSerializer):
    rider_details = DeliveryRiderSerializer(source='rider', read_only=True)
    
    class Meta:
        model = OrderDelivery
        fields = [
            'id', 'rider', 'rider_details', 'status', 'pickup_latitude', 'pickup_longitude',
            'current_latitude', 'current_longitude', 'assigned_at', 'picked_up_at',
            'delivered_at', 'estimated_pickup_time', 'estimated_delivery_time',
            'pickup_notes', 'delivery_notes', 'delivery_photo'
        ]
        read_only_fields = ['id', 'assigned_at']

class OrderStatusHistorySerializer(serializers.ModelSerializer):
    changed_by_name = serializers.CharField(source='changed_by.username', read_only=True)
    
    class Meta:
        model = OrderStatusHistory
        fields = ['id', 'status', 'changed_by', 'changed_by_name', 'changed_at', 'notes']
        read_only_fields = ['id', 'changed_at']

class PaymentTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentTransaction
        fields = [
            'id', 'transaction_type', 'status', 'amount', 'payment_method',
            'gateway_transaction_id', 'gateway_reference', 'created_at',
            'processed_at', 'notes', 'refund_reason'
        ]
        read_only_fields = ['id', 'created_at', 'processed_at']

class OrderReviewSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.username', read_only=True)
    
    class Meta:
        model = OrderReview
        fields = [
            'id', 'customer', 'customer_name', 'overall_rating', 'food_quality_rating',
            'delivery_rating', 'vendor_rating', 'review_text', 'review_photos',
            'created_at', 'updated_at', 'is_approved', 'is_featured'
        ]
        read_only_fields = ['id', 'customer', 'created_at', 'updated_at']
    
    def validate_overall_rating(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError("Rating must be between 1 and 5")
        return value

class OrderRefundSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.username', read_only=True)
    processed_by_name = serializers.CharField(source='processed_by.username', read_only=True)
    
    class Meta:
        model = OrderRefund
        fields = [
            'id', 'customer', 'customer_name', 'refund_type', 'status',
            'requested_amount', 'approved_amount', 'reason', 'customer_notes',
            'admin_notes', 'evidence_photos', 'vendor_supporting_docs', 'refund_method', 'esewa_number',
            'khalti_number', 'bank_account_name', 'bank_account_number', 'bank_branch',
            'requested_at', 'approved_at', 'processed_at', 'completed_at', 'appeal_at',
            'processed_by', 'processed_by_name', 'customer_received_refund', 
            'customer_received_at', 'support_contacted', 'support_contacted_at', 'support_notes'
        ]
        read_only_fields = [
            'id', 'customer', 'requested_at', 'approved_at', 'processed_at', 
            'completed_at', 'appeal_at', 'processed_by', 'customer_received_at', 'support_contacted_at'
        ]


class OrderNotificationSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    order_number = serializers.CharField(source='order.order_number', read_only=True)
    
    # Optional but very useful for frontend
    customer_username = serializers.CharField(source='order.customer.username', read_only=True)
    vendor_business_name = serializers.CharField(source='order.vendor.business_name', read_only=True)

    class Meta:
        model = OrderNotification
        fields = [
            'id',
            'notification_type',
            'title',
            'message',
            'is_sent',
            'is_read',
            'sent_at',
            'read_at',
            'created_at',
            'role',                  # ← New: tells frontend if it's customer or vendor notification
            'order_number',          # ← Helpful
            'customer_username',     # ← Shows who placed the order (for vendor)
            'vendor_business_name',  # ← Shows which shop (for customer)
        ]
        read_only_fields = [
            'id', 'notification_type', 'title', 'message', 'is_sent',
            'is_read', 'sent_at', 'read_at', 'created_at',
            'role', 'order_number', 'customer_username', 'vendor_business_name'
        ]

    def get_role(self, obj: OrderNotification) -> str:
        """
        Determines whether this notification is for the user as 'customer' or 'vendor'
        """
        user = self.context['request'].user

        # If the logged-in user is the customer of this order → customer role
        if obj.order.customer == user:
            return 'customer'

        # If the logged-in user is the vendor (via VendorProfile.user)
        if obj.order.vendor.user == user:
            return 'vendor'

        # Fallback (should rarely happen)
        return 'unknown'
    
class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    customer_details = UserSerializer(source='customer', read_only=True)
    vendor_details = serializers.SerializerMethodField()
    delivery = OrderDeliverySerializer(read_only=True)
    status_history = OrderStatusHistorySerializer(many=True, read_only=True)
    transactions = PaymentTransactionSerializer(many=True, read_only=True)
    review = OrderReviewSerializer(read_only=True)
    refunds = OrderRefundSerializer(many=True, read_only=True)
    notifications = OrderNotificationSerializer(many=True, read_only=True)
    
    # Computed fields
    can_be_cancelled = serializers.ReadOnlyField()
    can_be_reviewed = serializers.ReadOnlyField()
    
    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'customer', 'customer_details', 'vendor', 'vendor_details',
            'status', 'payment_status', 'payment_method', 'delivery_name', 'delivery_phone',
            'delivery_address', 'delivery_latitude', 'delivery_longitude', 'delivery_instructions',
            'delivery_distance', 'subtotal', 'delivery_fee', 'tax_amount', 'discount_amount',
            'total_amount', 'transaction_id', 'payment_reference', 'paid_amount',
            'created_at', 'confirmed_at', 'prepared_at', 'out_for_delivery_at',
            'delivered_at', 'cancelled_at', 'estimated_preparation_time',
            'estimated_delivery_time', 'delivery_boy_phone', 'vehicle_number', 'vehicle_color',
            'cancellation_reason', 'notes',
            'items', 'delivery', 'status_history', 'transactions', 'review', 'refunds',
            'notifications', 'can_be_cancelled', 'can_be_reviewed'
        ]
        read_only_fields = [
            'id', 'order_number', 'created_at', 'confirmed_at', 'prepared_at',
            'out_for_delivery_at', 'delivered_at', 'cancelled_at'
        ]
    
    def get_vendor_details(self, obj):
        from .serializers import VendorProfileSerializer
        return VendorProfileSerializer(obj.vendor, context=self.context).data

class CreateOrderSerializer(serializers.Serializer):
    # Order items
    items = serializers.ListField(
        child=serializers.DictField(),
        write_only=True
    )
    
    # Delivery information
    delivery_name = serializers.CharField(max_length=200)
    delivery_phone = serializers.CharField(max_length=15)
    delivery_address = serializers.CharField()
    delivery_latitude = serializers.FloatField()
    delivery_longitude = serializers.FloatField()
    delivery_instructions = serializers.CharField(required=False, allow_blank=True)
    
    # Payment information
    payment_method = serializers.ChoiceField(choices=Order.PAYMENT_METHOD_CHOICES)
    
    # Optional fields
    notes = serializers.CharField(required=False, allow_blank=True)
    
    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("At least one item is required")
        
        for item in value:
            if 'product_id' not in item or 'quantity' not in item:
                raise serializers.ValidationError("Each item must have product_id and quantity")
            
            try:
                product = Product.objects.get(id=item['product_id'], status='active')
                if int(item['quantity']) <= 0:
                    raise serializers.ValidationError("Quantity must be greater than 0")
                if int(item['quantity']) > product.quantity:
                    raise serializers.ValidationError(f"Not enough stock for {product.name}")
                    
                # Validate product_selections if present
                if 'product_selections' in item and item['product_selections']:
                    if not isinstance(item['product_selections'], dict):
                        raise serializers.ValidationError("Product selections must be a valid object")
                        
            except Product.DoesNotExist:
                raise serializers.ValidationError(f"Product with id {item['product_id']} not found")
            except ValueError:
                raise serializers.ValidationError("Invalid quantity")
        
        return value
    
    def validate_delivery_phone(self, value):
        # Nepali phone number validation
        import re
        if not re.match(r'^(98|97)\d{8}$', value.replace(' ', '')):
            raise serializers.ValidationError("Invalid Nepali phone number")
        return value
    
    def create(self, validated_data):
        items_data = validated_data.pop('items')
        customer = self.context['request'].user
        
        # Group items by vendor
        vendor_items = {}
        for item_data in items_data:
            product = Product.objects.get(id=item_data['product_id'])
            vendor_id = product.vendor.id
            
            if vendor_id not in vendor_items:
                vendor_items[vendor_id] = {
                    'vendor': product.vendor,
                    'items': []
                }
            
            quantity = int(item_data['quantity'])
            unit_price = product.selling_price
            total_price = unit_price * quantity
            
            vendor_items[vendor_id]['items'].append({
                'product': product,
                'quantity': quantity,
                'unit_price': unit_price,
                'total_price': total_price,
                'delivery_fee': item_data.get('delivery_fee', 0),
                'product_selections': item_data.get('product_selections', {}),
                'product_name': item_data.get('product_name', product.name),
                'vendor_name': item_data.get('vendor_name', product.vendor.business_name)
            })
        
        # Create separate orders for each vendor
        created_orders = []
        from decimal import Decimal
        
        for vendor_data in vendor_items.values():
            vendor = vendor_data['vendor']
            order_items = vendor_data['items']
            
            # Calculate totals for this vendor
            subtotal = sum(item['total_price'] for item in order_items)
            delivery_fee = Decimal('0')  # No delivery fee in bill
            tax_amount = Decimal('0')  # No tax
            total_amount = subtotal  # Subtotal only
            
            # Create order for this vendor
            order = Order.objects.create(
                customer=customer,
                vendor=vendor,
                delivery_name=validated_data['delivery_name'],
                delivery_phone=validated_data['delivery_phone'],
                delivery_address=validated_data['delivery_address'],
                delivery_latitude=validated_data['delivery_latitude'],
                delivery_longitude=validated_data['delivery_longitude'],
                delivery_instructions=validated_data.get('delivery_instructions', ''),
                delivery_distance=validated_data.get('delivery_distance', 0.0),
                payment_method=validated_data['payment_method'],
                subtotal=subtotal,
                delivery_fee=delivery_fee,
                tax_amount=tax_amount,
                total_amount=total_amount,
                notes=validated_data.get('notes', '')
            )
            
            # Create order items for this vendor
            for item_data in order_items:
                OrderItem.objects.create(
                    order=order,
                    **item_data
                )
            
            # Create status history
            OrderStatusHistory.objects.create(
                order=order,
                status='pending',
                changed_by=customer,
                notes='Order placed'
            )
            
            # Update product quantities
            for item_data in order_items:
                product = item_data['product']
                product.quantity -= item_data['quantity']
                product.save()
            
            created_orders.append(order)
        
        # Return the first order (for backward compatibility)
        # The frontend should handle multiple orders in the response
        return created_orders[0] if created_orders else None

class UpdateOrderStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Order.ORDER_STATUS_CHOICES)
    notes = serializers.CharField(required=False, allow_blank=True)
    
    # Delivery information (for out_for_delivery status)
    delivery_boy_phone = serializers.CharField(required=False, max_length=15)
    vehicle_number = serializers.CharField(required=False, max_length=20)
    vehicle_color = serializers.CharField(required=False, max_length=50)
    estimated_delivery_time = serializers.CharField(required=False)
    delivery_fee = serializers.DecimalField(required=False, max_digits=10, decimal_places=2)
    
    def validate(self, attrs):
        status = attrs.get('status')
        
        if status == 'out_for_delivery':
            if not attrs.get('delivery_boy_phone'):
                raise serializers.ValidationError("Delivery boy phone is required for shipping")
            if not attrs.get('vehicle_number'):
                raise serializers.ValidationError("Vehicle number is required for shipping")
            if not attrs.get('delivery_fee'):
                raise serializers.ValidationError("Delivery fee is required for shipping")
        
        return attrs