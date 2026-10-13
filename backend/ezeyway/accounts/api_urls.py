from django.urls import path, include
from . import api_views
from . import order_views
from . import complete_onboarding_view
from . import fcm_test_views
from . import call_api_views
from . import call_actions_api
from . import call_status_api

urlpatterns = [
    path('catalog/products/', api_views.CustomerProductSearchView.as_view(), name='customer_catalog'),
    path('catalog/products/<int:pk>/', api_views.CustomerProductDetailView.as_view(), name='customer_catalog_detail'),
    # Authentication
    path('register/', api_views.register_api, name='register'),
    path('login/', api_views.login_api, name='login'),
    path('logout/', api_views.logout_api, name='logout'),
    path('profile/', api_views.profile_api, name='profile'),
    path('profile/upload-picture/', api_views.upload_picture_api, name='upload_picture'),
    path('setup-password/', api_views.setup_password_api, name='setup_password'),
    path('change-password/simple/', api_views.SimpleChangePasswordView.as_view(), name='simple_change_password'),
    path('auth/google/', api_views.google_oauth_api, name='google_oauth'),
    path('auth/facebook/', api_views.facebook_oauth_api, name='facebook_oauth'),
    path('agree-privacy-policy/', api_views.agree_privacy_policy_api, name='agree_privacy_policy'),
    path('check-password-setup/', api_views.check_password_setup_api, name='check_password_setup'),
    path('send-otp/', api_views.send_otp_api, name='send_otp'),
    path('verify-otp/', api_views.verify_otp_api, name='verify_otp'),
    path('verify-email/<str:token>/', api_views.verify_email_api, name='verify_email'),
    path('update-email/', api_views.update_email_api, name='update_email'),
    path('resend-verification/', api_views.resend_verification_api, name='resend_verification'),

    # FCM Token Registration
    path('register-fcm-token/', api_views.register_fcm_token_api, name='register_fcm_token'),
    path('fcm-token/update/', fcm_test_views.update_fcm_token, name='update_fcm_token_main'),

    # Call APIs - Frontend Compatible
    path('create-call/', call_api_views.create_call_api, name='create_call_api'),
    path('calls/<str:call_id>/accept/', call_actions_api.accept_call_api, name='accept_call_api'),
    path('calls/<str:call_id>/reject/', call_actions_api.reject_call_api, name='reject_call_api'),
    path('calls/<str:call_id>/end/', call_actions_api.end_call_api, name='end_call_api'),
    path('calls/<str:call_id>/status/', call_status_api.get_call_status_api, name='get_call_status_api'),
    path('calls/<str:call_id>/sync/', call_status_api.sync_call_status_api, name='sync_call_status_api'),
    path('calls/<str:call_id>/reconnect/', call_status_api.reconnect_call_api, name='reconnect_call_api'),
    path('calls/pending/', call_api_views.get_pending_calls_api, name='get_pending_calls_api'),
    path('agora-token/', call_api_views.generate_agora_token_api, name='generate_agora_token_api'),
    path('update-fcm-token/', call_api_views.update_fcm_token_api, name='update_fcm_token_api'),

    # Role Switching
    path('switch-role/', api_views.switch_role_api, name='switch_role'),

    # Vendor Profiles
    path('vendor-profiles/', api_views.VendorProfileListCreateView.as_view(), name='vendor_profiles'),
    path('vendor-profiles/<int:pk>/', api_views.VendorProfileDetailView.as_view(), name='vendor_profile_detail'),
    path('vendor-profiles/<int:pk>/toggle-status/', api_views.vendor_toggle_status_api, name='vendor_toggle_status_detail'),
    path('complete-onboarding/', complete_onboarding_view.complete_vendor_onboarding, name='complete_onboarding'),
    path('vendor-profiles/shop-images/<int:pk>/', api_views.VendorShopImageDetailView.as_view(), name='vendor_shop_image_detail'),
    path('vendor-profiles/<int:pk>/shop-images/', api_views.VendorProfileShopImagesView.as_view(), name='vendor_profile_shop_images'),

    # Vendor Orders - Dedicated endpoint for vendor orders page
    path('vendor/orders/', order_views.VendorOrderListView.as_view(), name='vendor_orders_direct'),
    path('vendor/orders/<int:order_id>/ship/', order_views.update_order_status_api, name='vendor_ship_order'),
    path('vendor/orders/<int:order_id>/update-status/', order_views.update_order_status_api, name='vendor_update_order_status'),

    # Vendor Refund Processing
    path('vendor/refunds/<int:refund_id>/process/', order_views.vendor_process_refund_api, name='vendor_process_refund'),
    path('vendor/refunds/<int:refund_id>/approve/', order_views.vendor_process_refund_api, name='vendor_approve_refund'),
    path('vendor/refunds/<int:refund_id>/reject/', order_views.vendor_process_refund_api, name='vendor_reject_refund'),

    # Order Management (customer orders)
    path('orders/', include('accounts.order_urls')),

    # Direct Order Accept/Reject endpoints (for frontend compatibility)
    path('orders/<int:order_id>/accept/', order_views.vendor_accept_order_api, name='direct_vendor_accept_order'),
    path('orders/<int:order_id>/reject/', order_views.vendor_reject_order_api, name='direct_vendor_reject_order'),

    # Vendor Status
    path('vendor/toggle-status/', api_views.toggle_vendor_status_api, name='toggle_vendor_status'),
    path('vendor/status/', api_views.vendor_status_api, name='vendor_status'),

    # Notifications
    path('notifications/', api_views.notification_status_api, name='notifications'),

    # Messaging
    path('messaging/', include('accounts.message_urls')),

    # Vendor Notifications
    path('vendor-notifications/', include('accounts.notification_urls')),

    # Vendor Wallet
    path('vendor-wallet/', api_views.vendor_wallet_api, name='vendor_wallet'),
    path('wallet/transactions/', api_views.wallet_transactions_api, name='wallet_transactions'),

    # Web Push Notifications
    path('send-web-push-notification/', api_views.send_web_push_notification_api, name='send_web_push_notification'),

    # Favorites
    path('favorites/', api_views.UserFavoriteListView.as_view(), name='favorites'),
    path('favorites/toggle/', api_views.toggle_favorite_api, name='toggle_favorite'),

    # Cart Management
    path('cart/', api_views.get_cart_api, name='get_cart'),
    path('cart/add/', api_views.add_to_cart_api, name='add_to_cart'),
    path('cart/item/<int:item_id>/update/', api_views.update_cart_item_api, name='update_cart_item'),
    path('cart/item/<int:item_id>/remove/', api_views.remove_from_cart_api, name='remove_from_cart'),
    path('cart/items/<int:item_id>/remove/', api_views.remove_from_cart_api, name='remove_from_cart_alias'),  # Alias for frontend compatibility
    path('cart/items/<int:item_id>/update/', api_views.update_cart_item_api, name='update_cart_item_alias'),  # Alias for frontend compatibility
    path('cart/clear/', api_views.clear_cart_api, name='clear_cart'),

    # Search Vendors
    path('search/vendors/', api_views.CustomerVendorSearchView.as_view(), name='search_vendors'),
    path('vendors/<int:vendor_id>/', api_views.CustomerVendorProfileView.as_view(), name='customer_vendor_profile'),

    # Review URLs (direct access for frontend compatibility)
    path('orders/<int:order_id>/review/', order_views.get_order_reviews_api, name='get_order_reviews_direct'),
    path('orders/<int:order_id>/reviews/', order_views.get_order_reviews_api, name='get_order_reviews_plural'),
    path('products/<int:product_id>/reviews/', order_views.get_product_reviews_api, name='get_product_reviews_direct'),
    path('vendors/<int:vendor_id>/reviews/', order_views.get_vendor_reviews_api, name='get_vendor_reviews_direct'),

    # Categories and Products
    path('categories/', api_views.categories_api, name='categories'),
    path('categories/<str:category_name>/subcategories/', api_views.get_subcategories_api, name='get_subcategories'),
    path('categories/parameters/', api_views.get_category_parameters_compat_api, name='get_category_parameters_compat'),
    path('accounts/categories/parameters/', api_views.get_category_parameters_compat_api, name='accounts_category_parameters'),
    path('products/', api_views.ProductListCreateView.as_view(), name='products'),
    path('products/<int:pk>/', api_views.ProductDetailView.as_view(), name='product_detail'),
    path('products/<int:product_id>/images/<int:image_id>/', api_views.delete_product_image, name='delete_product_image'),
    path('sliders/', api_views.get_sliders_api, name='sliders'),
    path('search/products/', api_views.search_products_api, name='search_products'),
    path('search/image/', api_views.image_search_api, name='image_search'),

    # Featured Packages
    path('featured-packages/', api_views.get_featured_packages_api, name='get_featured_packages'),
    path('featured-packages/purchase/', api_views.purchase_featured_package_api, name='purchase_featured_package'),
    path('products/<int:product_id>/featured-info/', api_views.get_product_featured_info_api, name='get_product_featured_info'),
    path('products/<int:product_id>/reschedule-featured/', api_views.reschedule_featured_package_api, name='reschedule_featured_package'),

    # Admin Vendor Actions (for AJAX calls)
    path('admin/vendors/<int:vendor_id>/approve/', api_views.admin_approve_vendor_api, name='api_admin_approve_vendor'),
    path('admin/vendors/<int:vendor_id>/reject/', api_views.admin_reject_vendor_api, name='api_admin_reject_vendor'),

    # Test endpoints
    path('test/', api_views.test_api, name='test'),
    path('health/', api_views.health_check, name='health'),
]
