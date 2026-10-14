from .catalog import customer_products, filter_catalog
from .featured_status import sync_featured_products, reschedule_paid_feature
from rest_framework import status, generics, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from django.utils import timezone
from django.conf import settings
from datetime import timedelta
from django.views.decorators.csrf import csrf_exempt
from decimal import Decimal
from django.db.models import Q
import smtplib
from rest_framework.pagination import PageNumberPagination
from django.db import transaction
import logging
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed
import uuid

logger = logging.getLogger(__name__)
from .models import CustomUser, VendorProfile, VendorDocument, VendorShopImage, Product, ProductImage, VendorWallet, WalletTransaction, UserFavorite, Cart, CartItem, Category, SubCategory, Slider, FeaturedProductPackage, ProductFeaturedPurchase
from .parameter_models import CategoryParameter, SubCategoryParameter
from datetime import timedelta
from .complete_onboarding_view import complete_vendor_onboarding
from .serializers import (
    UserSerializer, RegisterSerializer, LoginSerializer,
    ChangePasswordSerializer, ForgotPasswordSerializer,
    ResetPasswordSerializer, OTPSerializer, VendorProfileSerializer,
    VendorDocumentSerializer, VendorShopImageSerializer, AdminUserCreateSerializer,
    AdminUserUpdateSerializer, UserStatsSerializer, SimpleChangePasswordSerializer,
    ProductSerializer, ProductImageSerializer, VendorWalletSerializer,
    WalletTransactionSerializer, AddMoneySerializer, CustomerProductSerializer,
    UserFavoriteSerializer, CartSerializer, CartItemSerializer, CategorySerializer
)

# Add password setup API for Google OAuth users
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def setup_password_api(request):
    """Allow Google OAuth users to set up password for traditional login"""
    try:
        user = request.user
        new_password = request.data.get('password')
        
        if not new_password:
            return Response({'error': 'Password is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        if len(new_password) < 6:
            return Response({'error': 'Password must be at least 6 characters'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Set password for the user
        user.set_password(new_password)
        user.plain_password = new_password  # Store plain password as per existing pattern
        user.save()
        
        # Generate new token
        Token.objects.filter(user=user).delete()
        token = Token.objects.create(user=user)
        
        return Response({
            'success': True,
            'message': 'Password set successfully. You can now login with email and password.',
            'token': token.key
        })
        
    except Exception as e:
        logger.error(f"Password setup error: {str(e)}")
        return Response({'error': 'Failed to set password'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
from .utils import send_otp_email, send_verification_email, send_password_reset_email
from accounts import serializers
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.decorators import parser_classes

@csrf_exempt
@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def register_api(request):
    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        otp = user.generate_otp()

        email_sent = False
        try:
            send_otp_email(user, otp)
            email_sent = True
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"OTP email auth failed for user {user.email}: {e}")
        except Exception as e:
            logger.exception(f"Failed to send OTP email to {user.email}: {e}")

        response = {
            'message': 'Registration successful.',
            'user_id': user.id,
            'email': user.email,
            'otp_sent': email_sent
        }

        if not email_sent:
            response['warning'] = 'OTP could not be sent. Please verify email settings or contact support.'

        return Response(response, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@csrf_exempt
@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def login_api(request):
    serializer = LoginSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.validated_data['user']
        needs_verification = serializer.validated_data.get('needs_verification', False)

        if needs_verification:
            otp = user.generate_otp()
            send_otp_email(user, otp)
            return Response({
                'needs_verification': True,
                'user_id': user.id,
                'message': 'Email not verified. OTP sent to your email.'
            }, status=status.HTTP_200_OK)

        # Check if vendor profile exists and approval status
        try:
            vendor_profile = VendorProfile.objects.get(user=user)
            profile_exists = True
            is_approved = vendor_profile.is_approved
            is_rejected = vendor_profile.is_rejected
            rejection_reason = vendor_profile.rejection_reason
            rejection_date = vendor_profile.rejection_date
        except VendorProfile.DoesNotExist:
            profile_exists = False
            is_approved = False
            is_rejected = False
            rejection_reason = None
            rejection_date = None

        # Check privacy policy agreement - only show if user has vendor profile or is customer
        needs_privacy_agreement = False
        if (profile_exists or user.user_type == 'customer') and not user.privacy_policy_agreed:
            needs_privacy_agreement = True

        if needs_privacy_agreement:
            return Response({
                'needs_privacy_agreement': True,
                'user_id': user.id,
                'user_type': user.user_type,
                'has_vendor_profile': profile_exists,
                'message': 'Privacy policy agreement required before login.'
            }, status=status.HTTP_200_OK)

        token, created = Token.objects.get_or_create(user=user)

        # Determine available roles - users can be both customer and vendor
        available_roles = ['customer']  # All users can be customers

        # Check if user can be a vendor (has approved profile)
        if profile_exists and is_approved:
            available_roles.append('vendor')

        return Response({
            'token': token.key,
            'user': UserSerializer(user).data,
            'available_roles': available_roles,
            'current_role': user.user_type,
            'profile_exists': profile_exists,
            'is_approved': is_approved,
            'is_rejected': is_rejected if is_rejected is not None else False,
            'rejection_reason': rejection_reason,
            'rejection_date': rejection_date.isoformat() if rejection_date else None,
            'message': 'Login successful'
        }, status=status.HTTP_200_OK)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def logout_api(request):
    try:
        request.user.auth_token.delete()
        return Response({'message': 'Logout successful'}, status=status.HTTP_200_OK)
    except:
        return Response({'error': 'Error logging out'}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PATCH'])  # <--- CHANGED: Added 'PATCH'
@permission_classes([permissions.IsAuthenticated])
def profile_api(request):
    try:
        user = request.user

        # --- HANDLE PROFILE UPDATE (PATCH) ---
        if request.method == 'PATCH':
            print(f"📝 Profile Update requested by: {user.username}")
            serializer = UserSerializer(user, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # --- EXISTING GET LOGIC ---
        print(f"🔑 Profile API called by user: {user.username}, authenticated: {user.is_authenticated}")

        # Ensure token exists and is valid
        token, created = Token.objects.get_or_create(user=user)
        if created:
            print(f"🔑 Created new token for user: {user.username}")

        # Check if vendor profile exists and approval status
        try:
            vendor_profile = VendorProfile.objects.get(user=user)
            profile_exists = True
            is_approved = vendor_profile.is_approved
        except VendorProfile.DoesNotExist:
            profile_exists = False
            is_approved = False

        # Determine available roles - users can be both customer and vendor
        available_roles = ['customer']  # All users can be customers

        # Check if user can be a vendor (has approved profile)
        if profile_exists and is_approved:
            available_roles.append('vendor')

        # Get user data
        serializer = UserSerializer(user)
        user_data = serializer.data

        # Add available_roles to response
        user_data['available_roles'] = available_roles
        user_data['current_role'] = user.user_type
        user_data['token'] = token.key  # Include token in response

        return Response(user_data)
    except Exception as e:
        print(f"🔑 Profile API error: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def upload_picture_api(request):
    """Upload user profile picture (accepts either 'picture' or 'profile_picture' form field)"""
    try:
        user = request.user

        # Accept either 'picture' or 'profile_picture' to be compatible with frontend variations
        picture = None
        if 'picture' in request.FILES:
            picture = request.FILES['picture']
        elif 'profile_picture' in request.FILES:
            picture = request.FILES['profile_picture']

        if not picture:
            return Response({'error': 'No picture provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate file size (max 5MB)
        if picture.size > 5 * 1024 * 1024:
            return Response({'error': 'File size too large. Max 5MB allowed'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate file type
        allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
        if picture.content_type not in allowed_types:
            return Response({'error': 'Invalid file type. Only JPEG, PNG, GIF, WebP allowed'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Save file to media directory
        import os
        from django.conf import settings
        
        media_dir = os.path.join(settings.MEDIA_ROOT, 'profile_pictures')
        os.makedirs(media_dir, exist_ok=True)
        
        # Generate unique filename
        import uuid
        ext = os.path.splitext(picture.name)[1]
        filename = f"{user.id}_{uuid.uuid4()}{ext}"
        filepath = os.path.join(media_dir, filename)
        
        # Save file
        with open(filepath, 'wb') as f:
            for chunk in picture.chunks():
                f.write(chunk)
        
        # Store relative path in database
        relative_path = f"profile_pictures/{filename}"
        user.profile_picture = relative_path
        user.save()
        
        # Get full URL
        picture_url = f"{settings.MEDIA_URL}{relative_path}"
        
        return Response({
            'success': True,
            'message': 'Profile picture uploaded successfully',
            'profile_picture': picture_url
        }, status=status.HTTP_200_OK)
    
    except Exception as e:
        print(f"❌ Upload picture error: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def test_api(request):
    return Response({
        'success': True,
        'message': 'API is working',
        'host': request.get_host(),
        'headers': dict(request.headers)
    })

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def health_check(request):
    from django.http import JsonResponse
    return JsonResponse({
        'status': 'ok',
        'message': 'Server is running',
        'timestamp': timezone.now().isoformat()
    })

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def vendor_status_test(request):
    from django.http import JsonResponse
    # Test endpoint to check if vendor status API structure works
    return JsonResponse({
        'success': True,
        'profile_exists': True,
        'is_approved': True,
        'business_name': 'Test Business',
        'is_active': True,
        'message': 'This is a test response'
    })

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def notification_status_api(request):
    # Simple notification status endpoint to replace WebSocket
    return Response({
        'success': True,
        'notifications_enabled': True,
        'unread_count': 0,
        'message': 'Notifications working via HTTP'
    })

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def conversations_api(request):
    # Simple conversations endpoint to replace WebSocket
    return Response({
        'success': True,
        'conversations': [],
        'message': 'Conversations working via HTTP'
    })

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def toggle_vendor_status_api(request):
    try:
        vendor_profile = VendorProfile.objects.get(user=request.user, is_approved=True)
        
        # Toggle the status
        vendor_profile.is_active = not vendor_profile.is_active
        vendor_profile.status_override = True
        vendor_profile.status_override_date = timezone.now().date()
        vendor_profile.save()
        
        return Response({
            'success': True,
            'is_active': vendor_profile.is_active,
            'message': f'Status changed to {"Active" if vendor_profile.is_active else "Inactive"}'
        })
    except VendorProfile.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Vendor profile not found'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def vendor_status_api(request):
    from django.http import JsonResponse
    try:
        vendor_profile = VendorProfile.objects.get(user=request.user, is_approved=True)
        return JsonResponse({
            'success': True,
            'profile_exists': True,
            'is_approved': vendor_profile.is_approved,
            'business_name': vendor_profile.business_name,
            'is_active': vendor_profile.is_active,
            'approval_date': vendor_profile.approval_date.isoformat() if vendor_profile.approval_date else None
        })
    except VendorProfile.DoesNotExist:
        return JsonResponse({
            'success': True,
            'profile_exists': False,
            'is_approved': False,
            'business_name': None,
            'is_active': False,
            'approval_date': None
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e),
            'profile_exists': False,
            'is_approved': False
        })

@api_view(['PUT'])
@permission_classes([permissions.IsAuthenticated])
def update_profile_api(request):
    serializer = UserSerializer(request.user, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def upload_profile_picture_api(request):
    if 'profile_picture' not in request.FILES:
        return Response({'error': 'No profile picture provided'}, status=status.HTTP_400_BAD_REQUEST)

    user = request.user
    uploaded_file = request.FILES['profile_picture']

    # Save the file to media directory
    import os
    from django.conf import settings
    from django.core.files.storage import default_storage

    # Create filename
    file_extension = os.path.splitext(uploaded_file.name)[1]
    filename = f"profile_pics/{user.id}_profile{file_extension}"

    # Save file
    file_path = default_storage.save(filename, uploaded_file)

    # Update user profile with file path
    user.profile_picture = file_path
    user.save()

    # Return full URL
    full_url = request.build_absolute_uri(f'/media/{file_path}')

    return Response({
        'message': 'Profile picture updated successfully',
        'profile_picture': full_url
    }, status=status.HTTP_200_OK)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def change_password_api(request):
    serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
    if serializer.is_valid():
        user = request.user
        user.set_password(serializer.validated_data['new_password'])
        user.plain_password = serializer.validated_data['new_password']
        user.save()
        
        Token.objects.filter(user=user).delete()
        token = Token.objects.create(user=user)
        
        return Response({
            'message': 'Password changed successfully',
            'token': token.key
        })
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.authtoken.models import Token
from .serializers import SimpleChangePasswordSerializer

class SimpleChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SimpleChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        # Update password
        user.set_password(serializer.validated_data['new_password'])
        user.plain_password = serializer.validated_data['new_password']
        user.save()

        # Delete old tokens and generate new one
        Token.objects.filter(user=user).delete()
        token = Token.objects.create(user=user)

        return Response({
            'message': 'Password changed successfully',
            'token': token.key
        }, status=status.HTTP_200_OK)

        
@csrf_exempt
@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def forgot_password_api(request):
    serializer = ForgotPasswordSerializer(data=request.data)
    if serializer.is_valid():
        email = serializer.validated_data['email']
        user = CustomUser.objects.get(email=email)
        token = user.generate_password_reset_token()
        send_password_reset_email(user, token)
        
        return Response({'message': 'Password reset link sent to your email'})
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@csrf_exempt
@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def reset_password_api(request):
    serializer = ResetPasswordSerializer(data=request.data)
    if serializer.is_valid():
        token = serializer.validated_data['token']
        password = serializer.validated_data['password']
        
        try:
            user = CustomUser.objects.get(password_reset_token=token)
            
            if user.password_reset_sent_at:
                expiry_time = user.password_reset_sent_at + timedelta(hours=settings.PASSWORD_RESET_TOKEN_EXPIRY_HOURS)
                if timezone.now() > expiry_time:
                    return Response({'error': 'Token expired'}, status=status.HTTP_400_BAD_REQUEST)
            
            user.set_password(password)
            user.plain_password = password
            user.password_reset_token = None
            user.save()
            
            return Response({'message': 'Password reset successful'})
            
        except CustomUser.DoesNotExist:
            return Response({'error': 'Invalid token'}, status=status.HTTP_400_BAD_REQUEST)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@csrf_exempt
@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def send_otp_api(request):
    email = request.data.get('email')
    if not email:
        return Response({'error': 'Email required'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        user = CustomUser.objects.get(email=email)
        otp = user.generate_otp()
        send_otp_email(user, otp)
        
        return Response({'message': 'OTP sent successfully'})
    except CustomUser.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

@csrf_exempt
@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def verify_otp_api(request):
    serializer = OTPSerializer(data=request.data)
    if serializer.is_valid():
        email = serializer.validated_data['email']
        otp = serializer.validated_data['otp']
        
        try:
            user = CustomUser.objects.get(email=email)
            
            if user.otp_created_at:
                expiry_time = user.otp_created_at + timedelta(minutes=settings.OTP_EXPIRY_MINUTES)
                if timezone.now() > expiry_time:
                    return Response({'error': 'OTP expired'}, status=status.HTTP_400_BAD_REQUEST)
            
            if user.email_otp == otp:
                user.email_verified = True
                user.is_verified = True
                user.email_otp = None
                user.phone_otp = None
                user.save()

                # Check if vendor profile exists and approval status
                try:
                    vendor_profile = VendorProfile.objects.get(user=user)
                    profile_exists = True
                    is_approved = vendor_profile.is_approved
                    is_rejected = vendor_profile.is_rejected
                    rejection_reason = vendor_profile.rejection_reason
                    rejection_date = vendor_profile.rejection_date
                except VendorProfile.DoesNotExist:
                    profile_exists = False
                    is_approved = False
                    is_rejected = False
                    rejection_reason = None
                    rejection_date = None

                # Check privacy policy agreement - only show if user has vendor profile or is customer
                needs_privacy_agreement = False
                if (profile_exists or user.user_type == 'customer') and not user.privacy_policy_agreed:
                    needs_privacy_agreement = True

                if needs_privacy_agreement:
                    return Response({
                        'needs_privacy_agreement': True,
                        'user_id': user.id,
                        'user_type': user.user_type,
                        'has_vendor_profile': profile_exists,
                        'message': 'OTP verified. Privacy policy agreement required before login.'
                    })

                token, created = Token.objects.get_or_create(user=user)

                # Determine available roles
                available_roles = ['customer']
                if profile_exists and is_approved:
                    available_roles.append('vendor')

                return Response({
                    'message': 'OTP verified successfully',
                    'token': token.key,
                    'user': UserSerializer(user).data,
                    'available_roles': available_roles,
                    'current_role': user.user_type,
                    'profile_exists': profile_exists,
                    'is_approved': is_approved,
                    'is_rejected': is_rejected,
                    'rejection_reason': rejection_reason,
                    'rejection_date': rejection_date.isoformat() if rejection_date else None
                })
            else:
                return Response({'error': 'Invalid OTP'}, status=status.HTTP_400_BAD_REQUEST)
                
        except CustomUser.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def verify_email_api(request, token):
    try:
        user = CustomUser.objects.get(email_verification_token=token)
        
        if user.email_verification_sent_at:
            expiry_time = user.email_verification_sent_at + timedelta(hours=settings.VERIFICATION_TOKEN_EXPIRY_HOURS)
            if timezone.now() > expiry_time:
                return Response({'error': 'Verification link expired'}, status=status.HTTP_400_BAD_REQUEST)
        
        user.email_verified = True
        user.is_verified = True
        user.email_verification_token = None
        user.save()
        
        return Response({'message': 'Email verified successfully'})
        
    except CustomUser.DoesNotExist:
        return Response({'error': 'Invalid verification link'}, status=status.HTTP_400_BAD_REQUEST)

@csrf_exempt
@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def update_email_api(request):
    user_id = request.data.get('user_id')
    email = request.data.get('email')
    if not user_id or not email:
        return Response({'error': 'User ID and email required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user = CustomUser.objects.get(id=user_id)
        user.email = email
        user.email_verified = False
        user.save()

        token = user.generate_verification_token()
        send_verification_email(user, token)

        return Response({'message': 'Email updated. Verification email sent.'})
    except CustomUser.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

@csrf_exempt
@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def resend_verification_api(request):
    user_id = request.data.get('user_id')
    if not user_id:
        return Response({'error': 'User ID required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user = CustomUser.objects.get(id=user_id)
        if user.email_verified:
            return Response({'message': 'Email already verified'})

        token = user.generate_verification_token()
        send_verification_email(user, token)

        return Response({'message': 'Verification email sent'})
    except CustomUser.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

# Vendor API Views
class VendorProfileListCreateView(generics.ListCreateAPIView):
    serializer_class = VendorProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        if self.request.user.is_superuser:
            return VendorProfile.objects.all()
        return VendorProfile.objects.filter(user=self.request.user)

    @transaction.atomic
    def perform_create(self, serializer):
        from rest_framework import serializers as drf_serializers
        # Prevent duplicate profiles
        if VendorProfile.objects.filter(user=self.request.user).exists():
            raise drf_serializers.ValidationError({'user': 'Vendor profile already exists.'})
        
        
        # Handle referral code
        referral_code = serializer.validated_data.pop('referral_code', None)
        
        # Save vendor profile first
        vendor_profile = serializer.save(user=self.request.user)
        
        # Process referral code if provided
        if referral_code:
            self.process_referral_code(referral_code, vendor_profile)
    
    def process_referral_code(self, referral_code, new_vendor_profile):
        """Process referral code and award points to both vendors"""
        try:
            # Find the referring vendor
            referring_user = CustomUser.objects.get(referral_code=referral_code, user_type='vendor')
            referring_vendor = VendorProfile.objects.get(user=referring_user, is_approved=True)
            
            # Get or create wallets
            new_wallet, _ = VendorWallet.objects.get_or_create(vendor=new_vendor_profile)
            referring_wallet, _ = VendorWallet.objects.get_or_create(vendor=referring_vendor)
            
            # Award 200 points to both vendors
            new_wallet.add_money(200, "Referral bonus - New vendor signup")
            referring_wallet.add_money(200, f"Referral bonus - Referred {new_vendor_profile.business_name}")
            
        except CustomUser.DoesNotExist:
            # Invalid referral code - silently ignore
            pass
        except VendorProfile.DoesNotExist:
            # Referring vendor not approved - silently ignore
            pass

class VendorProfileDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = VendorProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    
    def dispatch(self, request, *args, **kwargs):
        logger.debug(f"VendorProfileDetailView dispatch called with method: {request.method}, path: {request.path}")
        logger.debug(f"URL kwargs: {kwargs}")
        return super().dispatch(request, *args, **kwargs)
    
    def get_object(self):
        pk = self.kwargs.get('pk')
        user = self.request.user
        logger.debug(f"VendorProfileDetailView get_object called by user: {user.username}, is_superuser: {user.is_superuser}, pk: {pk}")
        
        # Check if profile exists at all
        all_profiles = VendorProfile.objects.all().values_list('id', flat=True)
        logger.debug(f"All existing profile IDs: {list(all_profiles)}")
        
        try:
            if user.is_superuser:
                # Superuser can access any profile
                profile = VendorProfile.objects.get(pk=pk)
                logger.debug(f"Superuser found profile: {profile.id} for business: {profile.business_name}")
                return profile
            else:
                # Check if user owns this profile first
                try:
                    profile = VendorProfile.objects.get(pk=pk, user=user)
                    logger.debug(f"User found their own profile: {profile.id}")
                    return profile
                except VendorProfile.DoesNotExist:
                    # If not owner, allow access to approved profiles for public viewing
                    profile = VendorProfile.objects.get(pk=pk, is_approved=True)
                    logger.debug(f"Public access to approved profile: {profile.id} for business: {profile.business_name}")
                    return profile
        except VendorProfile.DoesNotExist:
            logger.error(f"Profile with pk={pk} not found or not accessible. Available IDs: {list(all_profiles)}")
            from rest_framework.exceptions import NotFound
            raise NotFound('Vendor profile not found')
    
    def retrieve(self, request, *args, **kwargs):
        logger.debug(f"VendorProfileDetailView retrieve called with args: {args}, kwargs: {kwargs}")
        logger.debug(f"Request path: {request.path}")
        logger.debug(f"Request method: {request.method}")
        logger.debug(f"Request user: {request.user.username} (authenticated: {request.user.is_authenticated})")
        try:
            instance = self.get_object()
            logger.debug(f"Retrieved profile: {instance.id}, serializing...")
            serializer = self.get_serializer(instance)
            data = serializer.data
            logger.debug(f"Serialized data keys: {list(data.keys())}")
            logger.debug(f"Documents count: {len(data.get('documents', []))}")
            logger.debug(f"Shop images count: {len(data.get('shop_images', []))}")
            return Response(data)
        except Exception as e:
            logger.error(f"Error in VendorProfileDetailView retrieve: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    


class VendorDocumentListCreateView(generics.ListCreateAPIView):
    serializer_class = VendorDocumentSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        if self.request.user.is_superuser:
            return VendorDocument.objects.all()
        return VendorDocument.objects.filter(vendor_profile__user=self.request.user)

    @transaction.atomic
    def perform_create(self, serializer):
        # Ensure vendor profile exists and belongs to the user
        vendor_profile_id = self.request.data.get('vendor_profile')
        try:
            vendor_profile = VendorProfile.objects.get(id=vendor_profile_id, user=self.request.user)
        except VendorProfile.DoesNotExist:
            from rest_framework import serializers as drf_serializers
            raise drf_serializers.ValidationError({'vendor_profile': 'Invalid vendor profile or access denied.'})
        
        # Handle file upload
        uploaded_file = serializer.validated_data.get('document')
        if uploaded_file:
            import os
            from django.conf import settings
            from django.core.files.storage import default_storage
            
            # Create filename
            file_extension = os.path.splitext(uploaded_file.name)[1]
            filename = f"documents/{vendor_profile.id}_{timezone.now().timestamp()}{file_extension}"
            
            # Save file
            file_path = default_storage.save(filename, uploaded_file)
            # Remove the file from validated_data and add the path
            serializer.validated_data.pop('document')
            serializer.save(vendor_profile=vendor_profile, document=file_path)
        else:
            from rest_framework import serializers as drf_serializers
            raise drf_serializers.ValidationError({'document': 'Document file is required.'})

class VendorShopImageListCreateView(generics.ListCreateAPIView):
    serializer_class = VendorShopImageSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        if self.request.user.is_superuser:
            return VendorShopImage.objects.all()
        return VendorShopImage.objects.filter(vendor_profile__user=self.request.user)

    @transaction.atomic
    def perform_create(self, serializer):
        vendor_profile_id = self.request.data.get('vendor_profile')
        try:
            vendor_profile = VendorProfile.objects.get(id=vendor_profile_id, user=self.request.user)
        except VendorProfile.DoesNotExist:
            from rest_framework import serializers as drf_serializers
            raise drf_serializers.ValidationError({'vendor_profile': 'Invalid vendor profile or access denied.'})
        
        # Handle file upload
        uploaded_file = self.request.FILES.get('image')
        if uploaded_file:
            import os
            from django.conf import settings
            from django.core.files.storage import default_storage
            
            # Create filename
            file_extension = os.path.splitext(uploaded_file.name)[1]
            filename = f"shop_images/{vendor_profile.id}_{timezone.now().timestamp()}{file_extension}"
            
            # Save file
            file_path = default_storage.save(filename, uploaded_file)
            serializer.save(vendor_profile=vendor_profile, image=file_path)
        else:
            from rest_framework import serializers as drf_serializers
            raise drf_serializers.ValidationError({'image': 'Image file is required.'})

class VendorShopImageDetailView(generics.RetrieveDestroyAPIView):
    """
    View to retrieve or delete a specific shop image.
    Vendors can only delete their own images.
    """
    serializer_class = VendorShopImageSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        if self.request.user.is_superuser:
            return VendorShopImage.objects.all()
        return VendorShopImage.objects.filter(vendor_profile__user=self.request.user)

    def perform_destroy(self, instance):
        # Delete the actual file from storage
        try:
            import os
            from django.conf import settings
            from django.core.files.storage import default_storage
            
            if instance.image:
                # Assuming instance.image contains the relative path like 'shop_images/filename.ext'
                if default_storage.exists(instance.image):
                    default_storage.delete(instance.image)
        except Exception as e:
            logger.error(f"Error deleting shop image file: {str(e)}")
            # Continue to delete DB record even if file deletion fails
            
        instance.delete()

class VendorProfileShopImagesView(generics.ListCreateAPIView):
    """
    View to list all images for a specific vendor profile or upload a new one.
    URL: /api/vendor-profiles/<int:pk>/shop-images/
    """
    serializer_class = VendorShopImageSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        vendor_pk = self.kwargs.get('pk')
        return VendorShopImage.objects.filter(vendor_profile_id=vendor_pk)

    @transaction.atomic
    def perform_create(self, serializer):
        vendor_pk = self.kwargs.get('pk')
        try:
            # Ensure the user owns this vendor profile
            vendor_profile = VendorProfile.objects.get(id=vendor_pk, user=self.request.user)
        except VendorProfile.DoesNotExist:
             from rest_framework import serializers as drf_serializers
             from rest_framework.exceptions import PermissionDenied
             if VendorProfile.objects.filter(id=vendor_pk).exists():
                 raise PermissionDenied("You do not have permission to add images to this vendor profile.")
             raise drf_serializers.ValidationError({'vendor_profile': 'Vendor profile not found.'})

        # Handle file upload
        uploaded_file = self.request.FILES.get('image')
        if uploaded_file:
            import os
            from django.conf import settings
            from django.core.files.storage import default_storage
            
            # Create filename
            file_extension = os.path.splitext(uploaded_file.name)[1]
            filename = f"shop_images/{vendor_profile.id}_{timezone.now().timestamp()}{file_extension}"
            
            # Save file
            file_path = default_storage.save(filename, uploaded_file)
            serializer.save(vendor_profile=vendor_profile, image=file_path)
        else:
            from rest_framework import serializers as drf_serializers
            raise drf_serializers.ValidationError({'image': 'Image file is required.'})

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def vendor_toggle_status_api(request, pk):
    try:
        # Get the vendor profile
        if request.user.is_superuser:
            vendor_profile = VendorProfile.objects.get(id=pk)
        else:
            # For regular vendors, get their own profile regardless of pk
            vendor_profile = VendorProfile.objects.get(user=request.user)

        # Validate request data
        is_active = request.data.get('is_active')
        if not isinstance(is_active, bool):
            return Response({'error': 'is_active must be a boolean'}, status=status.HTTP_400_BAD_REQUEST)

        # Check wallet balance if trying to go online
        if is_active:
            wallet, created = VendorWallet.objects.get_or_create(vendor=vendor_profile)
            if wallet.balance < 100:
                # Force offline and disable toggle
                vendor_profile.is_active = False
                vendor_profile.status_override = True
                vendor_profile.status_override_date = timezone.now().date()
                vendor_profile.save()
                
                return Response({
                    'error': 'Insufficient wallet balance. Minimum 100 points required to go online.',
                    'wallet_balance': float(wallet.balance),
                    'required_balance': 100,
                    'is_active': False,
                    'can_toggle': False
                }, status=status.HTTP_400_BAD_REQUEST)

        # Update status
        vendor_profile.is_active = is_active
        vendor_profile.status_override = True
        vendor_profile.status_override_date = timezone.now().date()
        vendor_profile.save()

        status_text = 'activated' if is_active else 'deactivated'

        return Response({
            'message': f'Vendor {vendor_profile.business_name} {status_text} successfully',
            'vendor': VendorProfileSerializer(vendor_profile, context={'request': request}).data
        })

    except VendorProfile.DoesNotExist:
        return Response({'error': 'Vendor profile not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

# Admin API Views
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def admin_dashboard_api(request):
    if not request.user.is_superuser:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    total_users = CustomUser.objects.count()
    total_customers = CustomUser.objects.filter(user_type='customer').count()
    total_vendors = CustomUser.objects.filter(user_type='vendor').count()
    pending_vendors = VendorProfile.objects.filter(is_approved=False).count()
    
    return Response({
        'total_users': total_users,
        'total_customers': total_customers,
        'total_vendors': total_vendors,
        'pending_vendors': pending_vendors,
        'recent_users': UserSerializer(CustomUser.objects.order_by('-date_joined')[:10], many=True).data
    })

class UserListView(generics.ListAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        if not self.request.user.is_superuser:
            return CustomUser.objects.none()
        return CustomUser.objects.all().order_by('-date_joined')

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def admin_stats_api(request):
    if not request.user.is_superuser:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    total_users = CustomUser.objects.count()
    total_customers = CustomUser.objects.filter(user_type='customer').count()
    total_vendors = CustomUser.objects.filter(user_type='vendor').count()
    total_superusers = CustomUser.objects.filter(user_type='superuser').count()
    pending_vendors = VendorProfile.objects.filter(is_approved=False).count()
    verified_users = CustomUser.objects.filter(email_verified=True).count()
    unverified_users = CustomUser.objects.filter(email_verified=False).count()
    
    stats_data = {
        'total_users': total_users,
        'total_customers': total_customers,
        'total_vendors': total_vendors,
        'total_superusers': total_superusers,
        'pending_vendors': pending_vendors,
        'verified_users': verified_users,
        'unverified_users': unverified_users,
    }
    
    serializer = UserStatsSerializer(stats_data)
    return Response(serializer.data)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def admin_create_user_api(request):
    if not request.user.is_superuser:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    serializer = AdminUserCreateSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        return Response({
            'message': 'User created successfully',
            'user': UserSerializer(user).data
        }, status=status.HTTP_201_CREATED)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['PUT'])
@permission_classes([permissions.IsAuthenticated])
def admin_update_user_api(request, user_id):
    if not request.user.is_superuser:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        user = CustomUser.objects.get(id=user_id)
    except CustomUser.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
    
    serializer = AdminUserUpdateSerializer(user, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response({
            'message': 'User updated successfully',
            'user': UserSerializer(user).data
        })
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
def admin_delete_user_api(request, user_id):
    if not request.user.is_superuser:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        user = CustomUser.objects.get(id=user_id)
        if user.is_superuser and CustomUser.objects.filter(user_type='superuser').count() <= 1:
            return Response({'error': 'Cannot delete the last superuser'}, status=status.HTTP_400_BAD_REQUEST)
        
        username = user.username
        user.delete()
        return Response({'message': f'User {username} deleted successfully'})
    except CustomUser.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def admin_toggle_user_status_api(request, user_id):
    if not request.user.is_superuser:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        user = CustomUser.objects.get(id=user_id)
        user.is_active = not user.is_active
        user.save()
        
        status_text = 'activated' if user.is_active else 'deactivated'
        return Response({
            'message': f'User {user.username} {status_text} successfully',
            'user': UserSerializer(user).data
        })
    except CustomUser.DoesNotExist:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def admin_approve_vendor_api(request, vendor_id):
    if not request.user.is_superuser:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        vendor_profile = VendorProfile.objects.get(id=vendor_id)
        vendor_profile.is_approved = True
        vendor_profile.approval_date = timezone.now()
        vendor_profile.is_rejected = False
        vendor_profile.rejection_reason = None
        vendor_profile.rejection_date = None
        vendor_profile.save()
        
        # Send approval email
        from .email_notifications import send_vendor_approval_email
        send_vendor_approval_email(vendor_profile)
        
        return Response({
            'message': f'Vendor {vendor_profile.business_name} approved successfully',
            'vendor': VendorProfileSerializer(vendor_profile, context={'request': request}).data
        })
    except VendorProfile.DoesNotExist:
        return Response({'error': 'Vendor profile not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def admin_reject_vendor_api(request, vendor_id):
    if not request.user.is_superuser:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)

    try:
        vendor_profile = VendorProfile.objects.get(id=vendor_id)
        rejection_reason = request.data.get('reason', '')
        
        vendor_profile.is_rejected = True
        vendor_profile.is_approved = False
        vendor_profile.rejection_reason = rejection_reason
        vendor_profile.rejection_date = timezone.now()
        vendor_profile.save()
        
        # Send rejection email
        from .email_notifications import send_vendor_rejection_email
        send_vendor_rejection_email(vendor_profile)

        return Response({
            'message': f'Vendor "{vendor_profile.business_name}" has been rejected successfully'
        })
    except VendorProfile.DoesNotExist:
        return Response({'error': 'Vendor profile not found'}, status=status.HTTP_404_NOT_FOUND)

# Product API Views
class ProductListCreateView(generics.ListCreateAPIView):
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    pagination_class = PageNumberPagination

    def get_queryset(self):
        sync_featured_products(Product.objects.filter(vendor__user=self.request.user))
        if self.request.user.is_superuser:
            return Product.objects.all().order_by('-created_at')
        try:
            vendor_profile = VendorProfile.objects.get(user=self.request.user)
            return Product.objects.filter(vendor=vendor_profile).order_by('-created_at')
        except VendorProfile.DoesNotExist:
            return Product.objects.none()

    def perform_create(self, serializer):
        try:
            vendor_profile = VendorProfile.objects.get(user=self.request.user)
            serializer.save(vendor=vendor_profile)
        except VendorProfile.DoesNotExist:
            raise serializers.ValidationError({'vendor': 'Vendor profile not found.'})

class ProductDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        sync_featured_products(Product.objects.filter(vendor__user=self.request.user))
        if self.request.user.is_superuser:
            return Product.objects.all()
        try:
            vendor_profile = VendorProfile.objects.get(user=self.request.user)
            return Product.objects.filter(vendor=vendor_profile)
        except VendorProfile.DoesNotExist:
            return Product.objects.none()

@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
def delete_product_image(request, product_id, image_id):
    try:
        if request.user.is_superuser:
            product = Product.objects.get(id=product_id)
        else:
            vendor_profile = VendorProfile.objects.get(user=request.user)
            product = Product.objects.get(id=product_id, vendor=vendor_profile)
        
        image = ProductImage.objects.get(id=image_id, product=product)
        image.delete()
        
        return Response({'message': 'Image deleted successfully'})
    except (Product.DoesNotExist, ProductImage.DoesNotExist, VendorProfile.DoesNotExist):
        return Response({'error': 'Image not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def set_primary_image(request, product_id, image_id):
    try:
        if request.user.is_superuser:
            product = Product.objects.get(id=product_id)
        else:
            vendor_profile = VendorProfile.objects.get(user=request.user)
            product = Product.objects.get(id=product_id, vendor=vendor_profile)
        
        # Set all images to non-primary
        ProductImage.objects.filter(product=product).update(is_primary=False)
        
        # Set the selected image as primary
        image = ProductImage.objects.get(id=image_id, product=product)
        image.is_primary = True
        image.save()
        
        return Response({'message': 'Primary image set successfully'})
    except (Product.DoesNotExist, ProductImage.DoesNotExist, VendorProfile.DoesNotExist):
        return Response({'error': 'Image not found'}, status=status.HTTP_404_NOT_FOUND)

# Wallet API Views
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def vendor_wallet_api(request):
    try:
        vendor_profile = VendorProfile.objects.get(user=request.user, is_approved=True)
        wallet, created = VendorWallet.objects.get_or_create(vendor=vendor_profile)
        
        serializer = VendorWalletSerializer(wallet, context={'request': request})
        return Response(serializer.data)
    except VendorProfile.DoesNotExist:
        return Response({'error': 'Vendor profile not found or not approved'}, status=status.HTTP_403_FORBIDDEN)

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def wallet_transactions_api(request):
    try:
        vendor_profile = VendorProfile.objects.get(user=request.user, is_approved=True)
        wallet = VendorWallet.objects.get(vendor=vendor_profile)
        
        # Get query parameters for filtering
        date_filter = request.GET.get('date_filter', 'all')
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))
        
        transactions = wallet.transactions.all()
        
        # Apply date filtering
        if date_filter == 'today':
            from datetime import date
            transactions = transactions.filter(created_at__date=date.today())
        elif date_filter == 'week':
            from datetime import date, timedelta
            week_ago = date.today() - timedelta(days=7)
            transactions = transactions.filter(created_at__date__gte=week_ago)
        elif date_filter == 'custom':
            date_from = request.GET.get('date_from')
            date_to = request.GET.get('date_to')
            if date_from and date_to:
                transactions = transactions.filter(
                    created_at__date__gte=date_from,
                    created_at__date__lte=date_to
                )
        
        # Pagination
        total_count = transactions.count()
        start_index = (page - 1) * page_size
        end_index = start_index + page_size
        transactions = transactions[start_index:end_index]
        
        serializer = WalletTransactionSerializer(transactions, many=True)
        
        return Response({
            'transactions': serializer.data,
            'total_count': total_count,
            'page': page,
            'page_size': page_size,
            'total_pages': (total_count + page_size - 1) // page_size
        })
    except VendorProfile.DoesNotExist:
        return Response({'error': 'Vendor profile not found or not approved'}, status=status.HTTP_403_FORBIDDEN)
    except VendorWallet.DoesNotExist:
        return Response({'error': 'Wallet not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def initiate_khalti_payment(request):
    import requests
    import json
    
    try:
        vendor_profile = VendorProfile.objects.get(user=request.user, is_approved=True)
        amount = float(request.data.get('amount', 0))
        
        if amount <= 0:
            return Response({'error': 'Invalid amount'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Khalti payment initiation
        amount_in_paisa = int(amount * 100)
        return_url = "http://localhost:8080/vendor/wallet?payment_complete=1"
        
        payload = {
            "return_url": return_url,
            "website_url": request.build_absolute_uri('/')[:-1],
            "amount": amount_in_paisa,
            "purchase_order_id": f"Wallet_{vendor_profile.id}_{timezone.now().timestamp()}",
            "purchase_order_name": "Wallet Recharge",
            "customer_info": {
                "name": vendor_profile.owner_name or request.user.username,
                "email": vendor_profile.business_email or request.user.email,
                "phone": vendor_profile.business_phone or "9800000000"
            }
        }
        
        headers = {
            'Authorization': 'key eee666a6159b46a89eda9a4dde2a785b',
            'Content-Type': 'application/json',
        }
        
        response = requests.post(
            'https://a.khalti.com/api/v2/epayment/initiate/',
            data=json.dumps(payload),
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            response_data = response.json()
            if 'pidx' in response_data and 'payment_url' in response_data:
                return Response({
                    'success': True,
                    'payment_url': response_data['payment_url'],
                    'pidx': response_data['pidx']
                })
            else:
                return Response({'error': 'Invalid response from Khalti'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({'error': 'Failed to initiate payment'}, status=status.HTTP_400_BAD_REQUEST)
            
    except VendorProfile.DoesNotExist:
        return Response({'error': 'Vendor profile not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def add_money_api(request):
    serializer = AddMoneySerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        vendor_profile = VendorProfile.objects.get(user=request.user, is_approved=True)
        wallet, created = VendorWallet.objects.get_or_create(vendor=vendor_profile)
        
        amount = serializer.validated_data['amount']
        payment_method = serializer.validated_data['payment_method']
        reference_id = serializer.validated_data.get('reference_id', '')
        
        # Add money to wallet
        wallet.add_money(
            amount=amount,
            description=f"Wallet Recharge via {payment_method}"
        )
        
        # Update the transaction with payment details
        latest_transaction = wallet.transactions.first()
        if latest_transaction:
            latest_transaction.payment_method = payment_method
            latest_transaction.reference_id = reference_id
            latest_transaction.save()
        
        return Response({
            'message': 'Money added successfully',
            'new_balance': wallet.balance,
            'transaction_id': latest_transaction.id if latest_transaction else None
        })
    except VendorProfile.DoesNotExist:
        return Response({'error': 'Vendor profile not found'}, status=status.HTTP_404_NOT_FOUND)

# Customer Search Views
class SearchPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50
    
    def paginate_queryset(self, queryset, request, view=None):
        """Paginate queryset but return empty list instead of raising 404 for out-of-range pages."""
        try:
            return super().paginate_queryset(queryset, request, view)
        except Exception as e:
            # If the paginator would raise NotFound for an out-of-range page,
            # return an empty list and keep internal state so get_paginated_response can work.
            from rest_framework.exceptions import NotFound
            if isinstance(e, NotFound):
                # Mark that page is out of range
                self.page = None
                self.request = request
                return []
            # Re-raise other exceptions
            raise

    def get_paginated_response(self, data):
        # If paginate_queryset returned [] due to out-of-range page, return a safe empty paginated response
        if getattr(self, 'page', None) is None:
            return Response({
                'count': 0,
                'next': None,
                'previous': None,
                'results': data
            })
        return super().get_paginated_response(data)

class CustomerProductSearchView(generics.ListAPIView):
    serializer_class = CustomerProductSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = SearchPagination
    
    def get_queryset(self):
        return filter_catalog(self.request.query_params)

class CustomerProductDetailView(generics.RetrieveAPIView):
    serializer_class = CustomerProductSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return customer_products()


class CustomerVendorSearchView(generics.ListAPIView):
    serializer_class = VendorProfileSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = SearchPagination
    
    def get_queryset(self):
        print("\nVENDOR SEARCH DEBUG - Starting query")
        print(f"Query params: {dict(self.request.query_params)}")
        
        # Get current time and day for vendor availability check
        current_time = timezone.now().time()
        current_day = timezone.now().strftime('%A').lower()
        current_date = timezone.now().date()
        
        # Initial filter - only approved vendors
        queryset = VendorProfile.objects.filter(is_approved=True)
        
        # TEMPORARILY DISABLE BUSINESS HOURS FILTERING FOR TESTING
        # Filter for online vendors only - simplified to just check is_active
        online_vendors = []
        for vendor in queryset:
            # Only check if vendor is manually set to active, ignore business hours
            if vendor.is_active:
                online_vendors.append(vendor.id)
        
        queryset = queryset.filter(id__in=online_vendors)
        
        initial_count = queryset.count()
        print(f"Initial vendors (approved & online): {initial_count}")
        
        # Search query
        search = self.request.query_params.get('search', '')
        if search:
            print(f"Applying search filter: '{search}'")
            queryset = queryset.filter(
                Q(business_name__icontains=search) |
                Q(description__icontains=search) |
                Q(business_type__icontains=search) |
                Q(categories__icontains=search)
            )
            search_count = queryset.count()
            print(f"After search filter: {search_count} vendors")
        
        final_count = queryset.count()
        print(f"Final result: {final_count} vendors")
        print("VENDOR SEARCH DEBUG - Complete\n")
        
        return queryset.order_by('business_name')

# Customer Vendor Profile View
class CustomerVendorProfileView(generics.RetrieveAPIView):
    serializer_class = VendorProfileSerializer
    permission_classes = [permissions.AllowAny]
    
    def get_queryset(self):
        return VendorProfile.objects.filter(
            is_approved=True,
            is_active=True
        )
    
    def get_object(self):
        vendor_id = self.kwargs.get('vendor_id')
        try:
            return self.get_queryset().get(id=vendor_id)
        except VendorProfile.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound('Vendor not found or not available')

# Favorite API Views
class UserFavoriteListView(generics.ListAPIView):
    serializer_class = UserFavoriteSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return UserFavorite.objects.filter(
            user=self.request.user, product__in=customer_products(),
        ).select_related('product__pricing_group').prefetch_related('product__images')

@csrf_exempt
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def toggle_favorite_api(request):
    product_id = request.data.get('product_id')
    if not product_id:
        return Response({'error': 'Product ID is required'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        product = customer_products().get(id=product_id)
        favorite, created = UserFavorite.objects.get_or_create(
            user=request.user,
            product=product
        )
        
        if not created:
            favorite.delete()
            return Response({
                'is_favorite': False,
                'message': 'Product removed from favorites'
            })
        else:
            return Response({
                'is_favorite': True,
                'message': 'Product added to favorites'
            })
    except Product.DoesNotExist:
        return Response({'error': 'Product not found'}, status=status.HTTP_404_NOT_FOUND)

# Cart API Views
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_cart_api(request):
    cart, created = Cart.objects.get_or_create(user=request.user)
    
    serializer = CartSerializer(cart, context={'request': request})
    return Response(serializer.data)

@csrf_exempt
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def add_to_cart_api(request):
    cart, created = Cart.objects.get_or_create(user=request.user)
    
    product_id = request.data.get('product_id')
    quantity = request.data.get('quantity', 1)
    
    if not product_id:
        return Response({'error': 'Product ID is required'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        product = customer_products().get(id=product_id)
        
        # Check if item already exists in cart
        cart_item, created = CartItem.objects.get_or_create(
            cart=cart,
            product=product,
            defaults={'quantity': quantity}
        )
        
        if not created:
            # Update quantity if item already exists
            cart_item.quantity += quantity
            cart_item.save()
        
        return Response({
            'message': 'Product added to cart successfully',
            'cart': CartSerializer(cart, context={'request': request}).data
        })
    except Product.DoesNotExist:
        return Response({'error': 'Product not found or inactive'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['PUT'])
@permission_classes([permissions.IsAuthenticated])
def update_cart_item_api(request, item_id):
    try:
        cart_item = CartItem.objects.get(id=item_id, cart__user=request.user, product__in=customer_products())
        quantity = request.data.get('quantity')
        
        if quantity is None:
            return Response({'error': 'Quantity is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        if quantity <= 0:
            cart_item.delete()
            return Response({'message': 'Item removed from cart'})
        
        cart_item.quantity = quantity
        cart_item.save()
        
        return Response({
            'message': 'Cart item updated successfully',
            'cart': CartSerializer(cart_item.cart, context={'request': request}).data
        })
    except CartItem.DoesNotExist:
        return Response({'error': 'Cart item not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
def remove_from_cart_api(request, item_id):
    try:
        cart_item = CartItem.objects.get(id=item_id, cart__user=request.user, product__in=customer_products())
        cart_item.delete()
        
        cart = Cart.objects.get(user=request.user)
        return Response({
            'message': 'Item removed from cart successfully',
            'cart': CartSerializer(cart, context={'request': request}).data
        })
    except CartItem.DoesNotExist:
        return Response({'error': 'Cart item not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
def clear_cart_api(request):
    try:
        cart = Cart.objects.get(user=request.user)
        cart.items.all().delete()
        return Response({'message': 'Cart cleared successfully'})
    except Cart.DoesNotExist:
        return Response({'message': 'Cart is already empty'})

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_categories_api(request):
    categories = Category.objects.filter(is_active=True).order_by('display_order', 'name')
    serializer = CategorySerializer(categories, many=True, context={'request': request})
    return Response({
        'categories': serializer.data
    })

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_subcategories_api(request, category_name):
    try:
        category = Category.objects.get(name=category_name, is_active=True)
        subcategories = category.subcategories.filter(is_active=True).order_by('display_order', 'name')
        subcategory_names = [sub.name for sub in subcategories]
        return Response({
            'subcategories': subcategory_names
        })
    except Category.DoesNotExist:
        return Response({
            'subcategories': []
        })


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_subcategories_detailed_api(request, category_name):
    """Return detailed subcategory objects (id, name) for a category"""
    try:
        category = Category.objects.get(name=category_name, is_active=True)
        subcategories = category.subcategories.filter(is_active=True).order_by('display_order', 'name')
        subcats = []
        for sub in subcategories:
            subcats.append({
                'id': sub.id,
                'name': sub.name
            })
        return Response({
            'subcategories': subcats
        })
    except Category.DoesNotExist:
        return Response({
            'subcategories': []
        })

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_category_parameters_api(request, category_id):
    """Get parameters for a specific category"""
    try:
        category = Category.objects.get(id=category_id, is_active=True)
        parameters = CategoryParameter.objects.filter(category=category)
        
        parameters_data = []
        for param in parameters:
            # Normalize options: some records store options as list (JSONField), others as comma-separated string
            if isinstance(param.options, list):
                options_list = param.options
            elif isinstance(param.options, str):
                options_list = [opt.strip() for opt in param.options.split(',') if opt.strip()]
            else:
                options_list = []

            param_data = {
                'id': param.id,
                'name': param.name,
                'label': param.label,
                'field_type': param.field_type,
                'is_required': param.is_required,
                'description': param.description,
                'placeholder': param.placeholder,
                'min_value': param.min_value,
                'max_value': param.max_value,
                'step': param.step,
                'options': options_list
            }
            parameters_data.append(param_data)
            
        return Response({
            'success': True,
            'parameters': parameters_data
        })
    except Category.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Category not found'
        }, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_subcategory_parameters_api(request, subcategory_id):
    """Get parameters for a specific subcategory"""
    try:
        subcategory = SubCategory.objects.get(id=subcategory_id)
        parameters = SubCategoryParameter.objects.filter(subcategory=subcategory)

        parameters_data = []
        for param in parameters:
            # Normalize options: some records store options as list (JSONField), others as comma-separated string
            if isinstance(param.options, list):
                options_list = param.options
            elif isinstance(param.options, str):
                options_list = [opt.strip() for opt in param.options.split(',') if opt.strip()]
            else:
                options_list = []

            param_data = {
                'id': param.id,
                'name': param.name,
                'label': param.label,
                'field_type': param.field_type,
                'is_required': param.is_required,
                'description': param.description,
                'placeholder': param.placeholder,
                'min_value': param.min_value,
                'max_value': param.max_value,
                'step': param.step,
                'options': options_list
            }
            parameters_data.append(param_data)

        return Response({
            'success': True,
            'parameters': parameters_data
        })
    except SubCategory.DoesNotExist:
        return Response({
            'success': False,
            'error': 'Subcategory not found'
        }, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_category_parameters_compat_api(request):
    """Compatibility endpoint for old frontend requests using query params:
    /api/accounts/categories/parameters/?target_id=3&target_type=category
    """
    target_id = request.GET.get('target_id')
    target_type = request.GET.get('target_type')

    if not target_id or not target_type:
        return Response({'error': 'Missing parameters'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        if target_type == 'category':
            parameters = CategoryParameter.objects.filter(category_id=target_id, is_active=True).order_by('display_order', 'name')
        elif target_type == 'subcategory':
            parameters = SubCategoryParameter.objects.filter(subcategory_id=target_id, is_active=True).order_by('display_order', 'name')
        else:
            return Response({'error': 'Invalid target type'}, status=status.HTTP_400_BAD_REQUEST)

        params_data = []
        for param in parameters:
            params_data.append({
                'id': param.id,
                'name': param.name,
                'label': param.label,
                'field_type': param.field_type,
                'is_required': param.is_required,
                'options': param.options,
                'placeholder': param.placeholder,
                'description': param.description,
                'display_order': param.display_order
            })

        return Response({'parameters': params_data})
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def switch_role_api(request):
    new_role = request.data.get('role')

    if new_role not in ['customer', 'vendor']:
        return Response({'error': 'Invalid role'}, status=status.HTTP_400_BAD_REQUEST)

    user = request.user

    # Check if user can switch to vendor role
    if new_role == 'vendor':
        try:
            vendor_profile = VendorProfile.objects.get(user=user)
            if not vendor_profile.is_approved:
                return Response({'error': 'Vendor profile not approved'}, status=status.HTTP_400_BAD_REQUEST)
        except VendorProfile.DoesNotExist:
            return Response({'error': 'Vendor role not available'}, status=status.HTTP_400_BAD_REQUEST)

    # Update user type using database update to avoid property conflicts
    CustomUser.objects.filter(id=user.id).update(user_type=new_role)
    user.refresh_from_db()

    # Get updated available roles
    available_roles = ['customer']
    if new_role == 'vendor' or VendorProfile.objects.filter(user=user, is_approved=True).exists():
        available_roles.append('vendor')

    return Response({
        'message': f'Switched to {new_role}',
        'current_role': new_role,
        'available_roles': available_roles,
        'user': UserSerializer(user).data
    })

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def verify_khalti_payment(request):
    import requests
    import json
    
    try:
        pidx = request.data.get('pidx')
        if not pidx:
            return Response({'error': 'Payment ID (pidx) is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Verify payment with Khalti
        headers = {
            'Authorization': 'key eee666a6159b46a89eda9a4dde2a785b',
            'Content-Type': 'application/json',
        }
        
        response = requests.post(
            'https://a.khalti.com/api/v2/epayment/lookup/',
            data=json.dumps({'pidx': pidx}),
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            payment_data = response.json()
            
            if payment_data.get('status') == 'Completed':
                vendor_profile = VendorProfile.objects.get(user=request.user, is_approved=True)
                wallet, created = VendorWallet.objects.get_or_create(vendor=vendor_profile)
                
                from decimal import Decimal
                amount = Decimal(str(payment_data.get('total_amount', 0))) / 100  # Convert from paisa
                
                # Check if transaction already exists
                existing_transaction = WalletTransaction.objects.filter(
                    wallet=wallet,
                    reference_id=pidx
                ).first()
                
                if not existing_transaction:
                    # Add money to wallet
                    wallet.add_money(
                        amount=amount,
                        description=f"Khalti Payment - {pidx}"
                    )
                    
                    # Update transaction with payment details
                    latest_transaction = wallet.transactions.first()
                    if latest_transaction:
                        latest_transaction.payment_method = 'khalti'
                        latest_transaction.reference_id = pidx
                        latest_transaction.status = 'completed'
                        latest_transaction.save()
                    
                    return Response({
                        'success': True,
                        'message': 'Payment verified and wallet updated',
                        'amount': amount,
                        'new_balance': wallet.balance
                    })
                else:
                    return Response({
                        'success': True,
                        'message': 'Payment already processed',
                        'new_balance': wallet.balance
                    })
            else:
                return Response({'error': 'Payment not completed'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({'error': 'Payment verification failed'}, status=status.HTTP_400_BAD_REQUEST)
            
    except VendorProfile.DoesNotExist:
        return Response({'error': 'Vendor profile not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

# Slider API Views
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def register_fcm_token_api(request):
    """Register FCM token for push notifications"""
    try:
        fcm_token = request.data.get('fcm_token')
        platform = request.data.get('platform', 'android')
        
        if not fcm_token:
            return Response({'error': 'FCM token is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Update vendor profile with FCM token
        try:
            vendor_profile = VendorProfile.objects.get(user=request.user, is_approved=True)
            vendor_profile.fcm_token = fcm_token
            vendor_profile.fcm_updated_at = timezone.now()
            vendor_profile.save()
            
            return Response({
                'success': True,
                'message': 'FCM token registered successfully',
                'platform': platform
            })
        except VendorProfile.DoesNotExist:
            # For customers, you can store FCM token in user profile or separate model
            return Response({
                'success': True,
                'message': 'FCM token registered for customer',
                'platform': platform
            })
            
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def test_fcm_notification_api(request):
    """Send test FCM notification to current vendor"""
    try:
        vendor_profile = VendorProfile.objects.get(user=request.user, is_approved=True)
        
        if not vendor_profile.fcm_token:
            return Response({
                'error': 'No FCM token found. Please restart the app.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get test data from request
        title = request.data.get('title', 'Test Notification')
        message = request.data.get('message', 'This is a test notification!')
        order_id = request.data.get('orderId', 999)
        order_number = request.data.get('orderNumber', 'TEST-999')
        amount = request.data.get('amount', '500')
        
        # Send FCM notification
        from .firebase_init import send_data_only_message
        success = send_data_only_message(
            token=vendor_profile.fcm_token,
            data={
                "autoOpen": "true",
                "orderId": str(order_id),
                "orderNumber": order_number,
                "amount": str(amount),
                "action": "autoOpenOrder",
                "forceOpen": "true"
            }
        )
        
        if success:
            return Response({
                'success': True,
                'message': 'Test notification sent successfully!'
            })
        else:
            return Response({
                'error': 'Failed to send notification'
            }, status=status.HTTP_400_BAD_REQUEST)
            
    except VendorProfile.DoesNotExist:
        return Response({
            'error': 'Vendor profile not found'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'error': str(e)
        }, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_featured_packages_api(request):
    """Get all active featured product packages"""
    from .models import FeaturedProductPackage
    
    packages = FeaturedProductPackage.objects.filter(is_active=True).order_by('duration_days', 'amount')
    
    packages_data = []
    for package in packages:
        package_data = {
            'id': package.id,
            'name': package.name,
            'duration_days': package.duration_days,
            'amount': float(package.amount),
            'package_type': package.package_type,
            'description': package.description,
        }
        packages_data.append(package_data)
    
    return Response({
        'success': True,
        'packages': packages_data
    })

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_product_featured_info_api(request, product_id):
    """Get featured package info for a product"""
    from .models import Product, ProductFeaturedPurchase, VendorProfile
    from datetime import date
    
    try:
        vendor_profile = VendorProfile.objects.get(user=request.user)
        product = Product.objects.get(id=product_id, vendor=vendor_profile)
        
        # Get active featured purchase
        featured_purchase = ProductFeaturedPurchase.objects.filter(
            product=product,
            is_active=True
        ).first()
        
        if not featured_purchase:
            return Response({
                'has_featured': False,
                'can_modify': True
            })
        
        today = date.today()
        can_modify = featured_purchase.start_date > today  # Can modify if not started yet
        
        return Response({
            'has_featured': True,
            'can_modify': can_modify,
            'start_date': featured_purchase.start_date.isoformat(),
            'end_date': featured_purchase.end_date.isoformat(),
            'package_name': featured_purchase.package.name,
            'is_active': featured_purchase.start_date <= today <= featured_purchase.end_date
        })
        
    except (VendorProfile.DoesNotExist, Product.DoesNotExist):
        return Response({'error': 'Product not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def reschedule_featured_package_api(request, product_id):
    """Reschedule featured package start date (no wallet charge)"""
    from .models import Product, ProductFeaturedPurchase, VendorProfile
    from datetime import datetime, timedelta
    
    try:
        start_date_str = request.data.get('start_date')
        
        if not start_date_str:
            return Response({'error': 'Start date is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Get vendor profile and product
        vendor_profile = VendorProfile.objects.get(user=request.user)
        product = Product.objects.get(id=product_id, vendor=vendor_profile)
        
        # Get active featured purchase
        featured_purchase = ProductFeaturedPurchase.objects.filter(
            product=product,
            is_active=True
        ).first()
        
        if not featured_purchase:
            return Response({'error': 'No active featured package found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Parse new start date
        new_start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        
        # Calculate new end date based on package duration
        duration_days = (featured_purchase.end_date - featured_purchase.start_date).days
        new_end_date = new_start_date + timedelta(days=duration_days)
        
        # Update dates
        featured_purchase.start_date = new_start_date
        featured_purchase.end_date = new_end_date
        featured_purchase.save()
        
        return Response({
            'success': True,
            'message': 'Featured package rescheduled successfully',
            'start_date': new_start_date.isoformat(),
            'end_date': new_end_date.isoformat()
        })
        
    except VendorProfile.DoesNotExist:
        return Response({'error': 'Vendor profile not found'}, status=status.HTTP_404_NOT_FOUND)
    except Product.DoesNotExist:
        return Response({'error': 'Product not found'}, status=status.HTTP_404_NOT_FOUND)
    except ValueError:
        return Response({'error': 'Invalid date format'}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def purchase_featured_package_api(request):
    """Purchase a featured package for a product"""
    from .models import Product, FeaturedProductPackage, ProductFeaturedPurchase, VendorProfile, VendorWallet
    from datetime import datetime, timedelta
    
    try:
        product_id = request.data.get('product_id')
        package_id = request.data.get('package_id')
        start_date_str = request.data.get('start_date')
        
        if not all([product_id, package_id, start_date_str]):
            return Response({'error': 'Missing required fields'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Get vendor profile
        vendor_profile = VendorProfile.objects.get(user=request.user)
        
        # Get product and package
        product = Product.objects.get(id=product_id, vendor=vendor_profile)
        package = FeaturedProductPackage.objects.get(id=package_id, is_active=True)
        
        # Parse start date
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = start_date + timedelta(days=package.duration_days)
        
        # Get vendor wallet
        wallet, created = VendorWallet.objects.get_or_create(vendor=vendor_profile)
        
        # Check wallet balance
        if wallet.balance < package.amount:
            return Response({
                'error': 'Insufficient wallet balance',
                'required': float(package.amount),
                'available': float(wallet.balance)
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Deduct amount from wallet
        success = wallet.deduct_commission(
            amount=package.amount,
            order_amount=package.amount,
            description=f"Featured Package: {package.name} for {product.name}"
        )
        
        if not success:
            return Response({'error': 'Failed to deduct amount from wallet'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Create featured purchase record
        featured_purchase = ProductFeaturedPurchase.objects.create(
            product=product,
            vendor=vendor_profile,
            package=package,
            amount_paid=package.amount,
            start_date=start_date,
            end_date=end_date
        )
        
        # Mark product as featured
        product.featured = True
        product.save()
        
        return Response({
            'success': True,
            'message': 'Featured package purchased successfully',
            'purchase_id': featured_purchase.id,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'amount_paid': float(package.amount),
            'new_wallet_balance': float(wallet.balance)
        })
        
    except VendorProfile.DoesNotExist:
        return Response({'error': 'Vendor profile not found'}, status=status.HTTP_404_NOT_FOUND)
    except Product.DoesNotExist:
        return Response({'error': 'Product not found'}, status=status.HTTP_404_NOT_FOUND)
    except FeaturedProductPackage.DoesNotExist:
        return Response({'error': 'Package not found'}, status=status.HTTP_404_NOT_FOUND)
    except ValueError:
        return Response({'error': 'Invalid date format'}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def get_sliders_api(request):
    from .models import Slider
    from django.db.models import Q

    # Determine user type
    if request.user.is_authenticated:
        user_type = request.user.user_type
    else:
        user_type = 'customer'

    # Allow override via query param
    requested_type = request.GET.get('user_type')
    if requested_type in ['customer', 'vendor']:
        user_type = requested_type

    # 🔥 NO DATE FILTERS
    queryset = Slider.objects.filter(
        is_active=True
    ).filter(
        Q(visibility='both') | Q(visibility=user_type)
    ).order_by('display_order', 'created_at')

    sliders_data = []
    for slider in queryset:
        sliders_data.append({
            'id': slider.id,
            'title': slider.title,
            'description': slider.description,
            'image_url': request.build_absolute_uri(slider.image.url) if slider.image else None,
            'link_url': slider.link_url,
            'visibility': slider.visibility,
            'display_order': slider.display_order,
            'created_at': slider.created_at.isoformat()
        })

    return Response({
        'success': True,
        'sliders': sliders_data,
        'user_type': user_type,
        'count': len(sliders_data)
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def vendor_notifications_api(request):
    """Get vendor notifications (orders, refunds, stock alerts, status changes)"""
    try:
        vendor_profile = VendorProfile.objects.get(user=request.user, is_approved=True)
        
        # Return empty notifications - real notifications will be created by actual events
        notifications = []
        
        return Response({
            'success': True,
            'results': notifications
        })
        
    except VendorProfile.DoesNotExist:
        return Response({'error': 'Vendor profile not found or not approved'}, status=status.HTTP_403_FORBIDDEN)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@csrf_exempt
@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def facebook_oauth_api(request):
    """Handle Facebook OAuth authentication - follows existing login flow completely"""
    try:
        import json
        
        data = json.loads(request.body)
        user_info = data.get('user_info')
        
        if not user_info:
            return Response({'error': 'Facebook user info required'}, status=status.HTTP_400_BAD_REQUEST)
        
        facebook_id = user_info.get('facebook_id')
        email = user_info.get('email')
        name = user_info.get('name', '')
        picture = user_info.get('picture', '')
        
        logger.info(f"Processing Facebook OAuth for user: {email}")
        
        if not email or not facebook_id:
            return Response({'error': 'Missing required Facebook user data'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if user exists by email or facebook_id
        user_created = False
        user = None
        
        # First try to find by facebook_id
        if facebook_id:
            try:
                user = CustomUser.objects.get(facebook_id=facebook_id)
            except CustomUser.DoesNotExist:
                pass
        
        # If not found by facebook_id, try by email
        if not user:
            try:
                user = CustomUser.objects.get(email=email)
                # Link Facebook account to existing user
                if not user.facebook_id:
                    user.facebook_id = facebook_id
                    user.save()
            except CustomUser.DoesNotExist:
                pass
        
        # Create new user if not found
        if not user:
            # Generate unique username from email
            username = email.split('@')[0]
            counter = 1
            original_username = username
            while CustomUser.objects.filter(username=username).exists():
                username = f"{original_username}{counter}"
                counter += 1
            
            # Create user following exact registration flow
            user = CustomUser.objects.create_user(
                username=username,
                email=email,
                password=None,  # No password initially - user can set later
                first_name=name.split(' ')[0] if name else '',
                last_name=' '.join(name.split(' ')[1:]) if len(name.split(' ')) > 1 else '',
                facebook_id=facebook_id,
                profile_picture_url=picture,
                email_verified=True,  # Facebook emails are verified
                is_verified=True,
                user_type='customer'  # Default to customer
            )
            # Set database fields directly after creation to avoid property conflicts
            CustomUser.objects.filter(id=user.id).update(is_customer=True, is_vendor=False)
            user.refresh_from_db()
            user_created = True
            logger.info(f"Created new Facebook OAuth user: {user.email}")
        else:
            # Update existing user info
            updated = False
            if picture and user.profile_picture_url != picture:
                user.profile_picture_url = picture
                updated = True
            if not user.first_name and name:
                user.first_name = name.split(' ')[0]
                user.last_name = ' '.join(name.split(' ')[1:]) if len(name.split(' ')) > 1 else ''
                updated = True
            if not user.email_verified:
                user.email_verified = True
                user.is_verified = True
                updated = True
            if updated:
                user.save()
                logger.info(f"Updated existing Facebook OAuth user: {user.email}")
        
        # Generate or get auth token (same as login flow)
        token, created = Token.objects.get_or_create(user=user)
        
        # Check vendor profile status (EXACT same logic as login_api)
        try:
            vendor_profile = VendorProfile.objects.get(user=user)
            profile_exists = True
            is_approved = vendor_profile.is_approved
            is_rejected = vendor_profile.is_rejected
            rejection_reason = vendor_profile.rejection_reason
            rejection_date = vendor_profile.rejection_date
        except VendorProfile.DoesNotExist:
            profile_exists = False
            is_approved = False
            is_rejected = False
            rejection_reason = None
            rejection_date = None
        
        # Check privacy policy agreement - only show if user has vendor profile or is customer
        needs_privacy_agreement = False
        if (profile_exists or user.user_type == 'customer') and not user.privacy_policy_agreed:
            needs_privacy_agreement = True

        if needs_privacy_agreement:
            return Response({
                'needs_privacy_agreement': True,
                'user_id': user.id,
                'user_type': user.user_type,
                'has_vendor_profile': profile_exists,
                'user_created': user_created,
                'facebook_login': True,
                'message': 'Privacy policy agreement required before login.'
            })
        
        # Determine available roles (EXACT same logic as login_api)
        available_roles = ['customer']  # All users can be customers
        
        # Check if user can be a vendor (has approved profile)
        if profile_exists and is_approved:
            available_roles.append('vendor')
        
        # Get user serialized data and add available_roles to it
        user_data = UserSerializer(user).data
        user_data['available_roles'] = available_roles
        
        # Return EXACT same structure as login_api
        return Response({
            'success': True,
            'token': token.key,
            'user': user_data,
            'available_roles': available_roles,
            'current_role': user.user_type,
            'profile_exists': profile_exists,
            'is_approved': is_approved,
            'is_rejected': is_rejected if is_rejected is not None else False,
            'rejection_reason': rejection_reason,
            'rejection_date': rejection_date.isoformat() if rejection_date else None,
            'message': 'Facebook OAuth login successful',
            'user_created': user_created,  # Additional flag for new users
            'needs_password_setup': not user.has_usable_password(),  # Flag for password setup
            'facebook_login': True,  # Flag to indicate Facebook login
            'needs_profile_completion': user_created or not user.phone_number  # Flag for profile completion
        })
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {str(e)}")
        return Response({'error': 'Invalid JSON data'}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Facebook OAuth error: {str(e)}")
        import traceback
        logger.error(f"Facebook OAuth traceback: {traceback.format_exc()}")
        return Response({'error': f'Authentication failed: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@csrf_exempt
@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def google_oauth_api(request):
    """Handle Google OAuth authentication - follows existing login flow completely"""
    try:
        import json
        
        data = json.loads(request.body)
        user_info = data.get('user_info')
        
        if not user_info:
            return Response({'error': 'Google user info required'}, status=status.HTTP_400_BAD_REQUEST)
        
        google_id = user_info.get('google_id')
        email = user_info.get('email')
        name = user_info.get('name', '')
        picture = user_info.get('picture', '')
        
        logger.info(f"Processing Google OAuth for user: {email}")
        
        if not email or not google_id:
            return Response({'error': 'Missing required Google user data'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if user exists by email or google_id
        user_created = False
        user = None
        
        # First try to find by google_id
        if google_id:
            try:
                user = CustomUser.objects.get(google_id=google_id)
            except CustomUser.DoesNotExist:
                pass
        
        # If not found by google_id, try by email
        if not user:
            try:
                user = CustomUser.objects.get(email=email)
                # Link Google account to existing user
                if not user.google_id:
                    user.google_id = google_id
                    user.save()
            except CustomUser.DoesNotExist:
                pass
        
        # Create new user if not found
        if not user:
            # Generate unique username from email
            username = email.split('@')[0]
            counter = 1
            original_username = username
            while CustomUser.objects.filter(username=username).exists():
                username = f"{original_username}{counter}"
                counter += 1
            
            # Create user following exact registration flow
            user = CustomUser.objects.create_user(
                username=username,
                email=email,
                password=None,  # No password initially - user can set later
                first_name=name.split(' ')[0] if name else '',
                last_name=' '.join(name.split(' ')[1:]) if len(name.split(' ')) > 1 else '',
                google_id=google_id,
                profile_picture_url=picture,
                email_verified=True,  # Google emails are verified
                is_verified=True,
                user_type='customer'  # Default to customer
            )
            # Set database fields directly after creation to avoid property conflicts
            CustomUser.objects.filter(id=user.id).update(is_customer=True, is_vendor=False)
            user.refresh_from_db()
            user_created = True
            logger.info(f"Created new Google OAuth user: {user.email}")
        else:
            # Update existing user info
            updated = False
            if picture and user.profile_picture_url != picture:
                user.profile_picture_url = picture
                updated = True
            if not user.first_name and name:
                user.first_name = name.split(' ')[0]
                user.last_name = ' '.join(name.split(' ')[1:]) if len(name.split(' ')) > 1 else ''
                updated = True
            if not user.email_verified:
                user.email_verified = True
                user.is_verified = True
                updated = True
            if updated:
                user.save()
                logger.info(f"Updated existing Google OAuth user: {user.email}")
        
        # Generate or get auth token (same as login flow)
        token, created = Token.objects.get_or_create(user=user)
        
        # Check vendor profile status (EXACT same logic as login_api)
        try:
            vendor_profile = VendorProfile.objects.get(user=user)
            profile_exists = True
            is_approved = vendor_profile.is_approved
            is_rejected = vendor_profile.is_rejected
            rejection_reason = vendor_profile.rejection_reason
            rejection_date = vendor_profile.rejection_date
        except VendorProfile.DoesNotExist:
            profile_exists = False
            is_approved = False
            is_rejected = False
            rejection_reason = None
            rejection_date = None
        
        # Check privacy policy agreement - only show if user has vendor profile or is customer
        needs_privacy_agreement = False
        if (profile_exists or user.user_type == 'customer') and not user.privacy_policy_agreed:
            needs_privacy_agreement = True

        if needs_privacy_agreement:
            return Response({
                'needs_privacy_agreement': True,
                'user_id': user.id,
                'user_type': user.user_type,
                'has_vendor_profile': profile_exists,
                'user_created': user_created,
                'google_login': True,
                'message': 'Privacy policy agreement required before login.'
            })
        
        # Determine available roles (EXACT same logic as login_api)
        available_roles = ['customer']  # All users can be customers
        
        # Check if user can be a vendor (has approved profile)
        if profile_exists and is_approved:
            available_roles.append('vendor')
        
        # Note: We don't update is_vendor/is_customer database fields here
        # because they conflict with computed properties in the model
        # The role logic is handled by available_roles and user_type
        
        # Get user serialized data and add available_roles to it
        user_data = UserSerializer(user).data
        user_data['available_roles'] = available_roles
        
        # Return EXACT same structure as login_api
        return Response({
            'success': True,
            'token': token.key,
            'user': user_data,
            'available_roles': available_roles,
            'current_role': user.user_type,
            'profile_exists': profile_exists,
            'is_approved': is_approved,
            'is_rejected': is_rejected if is_rejected is not None else False,
            'rejection_reason': rejection_reason,
            'rejection_date': rejection_date.isoformat() if rejection_date else None,
            'message': 'Google OAuth login successful',
            'user_created': user_created,  # Additional flag for new users
            'needs_password_setup': not user.has_usable_password(),  # Flag for password setup
            'google_login': True,  # Flag to indicate Google login
            'needs_profile_completion': user_created or not user.phone_number  # Flag for profile completion
        })
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {str(e)}")
        return Response({'error': 'Invalid JSON data'}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Google OAuth error: {str(e)}")
        import traceback
        logger.error(f"Google OAuth traceback: {traceback.format_exc()}")
        return Response({'error': f'Authentication failed: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def check_password_setup_api(request):
    """Check if user needs to set up password (for Google OAuth users)"""
    try:
        user = request.user
        return Response({
            'needs_password_setup': not user.has_usable_password(),
            'has_google_account': bool(user.google_id),
            'email': user.email
        })
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def agree_privacy_policy_api(request):
    """Handle privacy policy agreement and complete login"""
    try:
        user_id = request.data.get('user_id')
        agreed = request.data.get('agreed', False)
        
        if not user_id:
            return Response({'error': 'User ID is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        if not agreed:
            return Response({'error': 'Privacy policy agreement is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            user = CustomUser.objects.get(id=user_id)
        except CustomUser.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Update privacy policy agreement
        user.privacy_policy_agreed = True
        user.save()
        
        # Generate token and complete login
        token, created = Token.objects.get_or_create(user=user)
        
        # Check vendor profile status
        try:
            vendor_profile = VendorProfile.objects.get(user=user)
            profile_exists = True
            is_approved = vendor_profile.is_approved
            is_rejected = vendor_profile.is_rejected
            rejection_reason = vendor_profile.rejection_reason
            rejection_date = vendor_profile.rejection_date
        except VendorProfile.DoesNotExist:
            profile_exists = False
            is_approved = False
            is_rejected = False
            rejection_reason = None
            rejection_date = None
        
        # Determine available roles
        available_roles = ['customer']
        if profile_exists and is_approved:
            available_roles.append('vendor')
        
        return Response({
            'success': True,
            'token': token.key,
            'user': UserSerializer(user).data,
            'available_roles': available_roles,
            'current_role': user.user_type,
            'profile_exists': profile_exists,
            'is_approved': is_approved,
            'is_rejected': is_rejected if is_rejected is not None else False,
            'rejection_reason': rejection_reason,
            'rejection_date': rejection_date.isoformat() if rejection_date else None,
            'message': 'Privacy policy agreed and login successful'
        })
        
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def check_wallet_balance_api(request):
    """Check wallet balance and auto-disable if needed"""
    try:
        if not request.user.is_superuser:
            vendor_profile = VendorProfile.objects.get(user=request.user, is_approved=True)
            wallet, created = VendorWallet.objects.get_or_create(vendor=vendor_profile)
            
            can_be_active = wallet.balance >= 100
            
            # Auto-disable if balance is low and currently active
            if not can_be_active and vendor_profile.is_active:
                vendor_profile.is_active = False
                vendor_profile.status_override = True
                vendor_profile.status_override_date = timezone.now().date()
                vendor_profile.save()
            
            return Response({
                'wallet_balance': float(wallet.balance),
                'can_be_active': can_be_active,
                'is_active': vendor_profile.is_active,
                'required_balance': 100
            })
        else:
            # Admin endpoint to check all vendors
            from .wallet_monitor import check_and_disable_low_balance_vendors
            disabled_count = check_and_disable_low_balance_vendors()
            return Response({
                'message': f'Checked all vendors, disabled {disabled_count} due to low balance'
            })
            
    except VendorProfile.DoesNotExist:
        return Response({'error': 'Vendor profile not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def validate_referral_code_api(request):
    """Validate if a referral code exists and belongs to an approved vendor"""
    referral_code = request.data.get('referral_code', '').strip().upper()
    
    if not referral_code:
        return Response({
            'valid': False,
            'message': 'Referral code is required'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        referring_user = CustomUser.objects.get(referral_code=referral_code, user_type='vendor')
        try:
            referring_vendor = VendorProfile.objects.get(user=referring_user, is_approved=True)
            return Response({
                'valid': True,
                'message': f'Valid referral code from {referring_vendor.business_name}',
                'vendor_name': referring_vendor.business_name
            })
        except VendorProfile.DoesNotExist:
            return Response({
                'valid': False,
                'message': 'Referral code belongs to an unapproved vendor'
            })
    except CustomUser.DoesNotExist:
        return Response({
            'valid': False,
            'message': 'Invalid referral code'
        })

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def generate_referral_code_api(request):
    """Generate referral code for the current vendor user if they don't have one"""
    try:
        user = request.user
        if user.user_type == 'vendor':
            if not user.referral_code:
                referral_code = user.generate_referral_code()
                return Response({
                    'success': True,
                    'referral_code': referral_code,
                    'message': 'Referral code generated successfully'
                })
            else:
                return Response({
                    'success': True,
                    'referral_code': user.referral_code,
                    'message': 'Referral code already exists'
                })
        else:
            return Response({
                'success': False,
                'message': 'Only vendors can have referral codes'
            }, status=status.HTTP_403_FORBIDDEN)
    except Exception as e:
        return Response({
            'success': False,
            'message': f'Failed to generate referral code: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Direct order accept/reject functions (backup for URL routing issues)
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def vendor_accept_order_direct(request, order_id):
    """Direct vendor accept order function - backup for routing issues"""
    print(f"🔥 DIRECT VENDOR ACCEPT ORDER CALLED - Order ID: {order_id}, User: {request.user}")
    
    # Import the function from order_views and call it
    from .order_views import vendor_accept_order_api
    return vendor_accept_order_api(request, order_id)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def vendor_reject_order_direct(request, order_id):
    """Direct vendor reject order function - backup for routing issues"""
    print(f"🔥 DIRECT VENDOR REJECT ORDER CALLED - Order ID: {order_id}, User: {request.user}")

    # Import the function from order_views and call it
    from .order_views import vendor_reject_order_api
    return vendor_reject_order_api(request, order_id)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def send_web_push_notification_api(request):
    """Send web push notification for orders that works when browser is closed"""
    try:
        order_id = request.data.get('orderId')
        order_number = request.data.get('orderNumber', 'Unknown')
        amount = request.data.get('amount', '0')
        title = request.data.get('title', f'New Order #{order_number}')
        body = request.data.get('body', f'Order received - ₹{amount}')
        icon = request.data.get('icon')
        badge = request.data.get('badge')

        if not order_id:
            return Response({'error': 'orderId is required'}, status=status.HTTP_400_BAD_REQUEST)

        # Get vendor profile and FCM token
        try:
            vendor_profile = VendorProfile.objects.get(user=request.user, is_approved=True)
        except VendorProfile.DoesNotExist:
            return Response({'error': 'Vendor profile not found or not approved'}, status=status.HTTP_403_FORBIDDEN)

        if not vendor_profile.fcm_token:
            return Response({'error': 'No FCM token found. Please restart the app.'}, status=status.HTTP_400_BAD_REQUEST)

        # Send web push notification
        from .fcm_service import fcm_service
        success = fcm_service.send_order_notification(vendor_profile.fcm_token, {
            'orderId': str(order_id),
            'orderNumber': order_number,
            'amount': str(amount)
        })

        if success:
            return Response({
                'success': True,
                'message': 'Web push notification sent successfully'
            })
        else:
            return Response({
                'error': 'Failed to send web push notification'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    except Exception as e:
        return Response({
            'error': f'Failed to send web push notification: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Missing API endpoints that frontend is calling
@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def categories_api(request):
    """Get all active categories"""
    try:
        categories = Category.objects.filter(is_active=True).order_by('display_order', 'name')
        serializer = CategorySerializer(categories, many=True, context={'request': request})
        return Response({
            'success': True,
            'categories': serializer.data
        })
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@parser_classes([MultiPartParser, FormParser])
def image_search_api(request):
    """Search products using image similarity (basic implementation)"""
    try:
        if 'image' not in request.FILES:
            return Response({'error': 'Image file is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        uploaded_image = request.FILES['image']
        
        # Basic validation
        if uploaded_image.size > 5 * 1024 * 1024:  # 5MB limit
            return Response({'error': 'Image file too large (max 5MB)'}, status=status.HTTP_400_BAD_REQUEST)
        
        # For now, implement a simple keyword-based search
        # In a real implementation, you would use AI/ML for image recognition
        # This is a placeholder that returns random products for demo
        
        queryset = customer_products()

        # For demo purposes, return first 10 products
        # In real implementation, use image recognition AI to find similar products
        results = queryset[:10]
        
        # Serialize results
        from .serializers import CustomerProductSerializer
        serializer = CustomerProductSerializer(results, many=True, context={'request': request})
        
        return Response({
            'success': True,
            'results': serializer.data,
            'count': len(serializer.data),
            'message': f'Found {len(serializer.data)} products matching your image'
        })
        
    except Exception as e:
        logger.error(f"Image search error: {str(e)}")
        return Response({
            'error': 'Image search failed. Please try again.'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def search_products_api(request):
    """Public universal catalog, independent of vendor availability."""
    queryset = filter_catalog(request.query_params)
    final_count = queryset.count()
    try:
        page = max(1, int(request.query_params.get('page', 1)))
        page_size = min(100, max(1, int(request.query_params.get('page_size', 20))))
    except (TypeError, ValueError):
        return Response({'error': 'Invalid pagination'}, status=400)
    start_index = (page - 1) * page_size
    paginated_queryset = queryset[start_index:start_index + page_size]

    # Serialize results
    from .serializers import CustomerProductSerializer
    serializer = CustomerProductSerializer(paginated_queryset, many=True, context={'request': request})

    return Response({
        'success': True,
        'results': serializer.data,
        'count': final_count,
        'page': page,
        'page_size': page_size,
        'total_pages': (final_count + page_size - 1) // page_size
    })

# =============================================================================
# CALL MANAGEMENT API VIEWS - WhatsApp-like Real-time Calling System
# =============================================================================

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def initiate_call_api(request):
    """Initiate a call to another user"""
    try:
        recipient_id = request.data.get('recipient_id')
        call_type = request.data.get('call_type', 'audio')  # 'audio' or 'video'

        if not recipient_id:
            return Response({'error': 'recipient_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        if call_type not in ['audio', 'video']:
            return Response({'error': 'call_type must be audio or video'}, status=status.HTTP_400_BAD_REQUEST)

        # Get target user
        try:
            to_user = CustomUser.objects.get(id=recipient_id)
        except CustomUser.DoesNotExist:
            return Response({'error': 'Target user not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Generate unique call ID
        call_id = f"call_{uuid.uuid4().hex[:16]}"
        
        # Create call record
        call = Call.objects.create(
            call_id=call_id,
            caller=request.user,
            receiver=to_user,
            call_type=call_type,
            status='initiated',
            initiated_at=timezone.now()
        )
        
        # Use WebSocket fallback mechanism
        from .websocket_fallback import send_call_with_fallback
        
        call_data = {
            'call_id': call_id,
            'caller_name': f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username,
            'caller_id': str(request.user.id),
            'call_type': call_type,
            'action': 'incoming_call'
        }
        
        # Send call notification with fallback
        success = send_call_with_fallback(to_user.id, call_data)
        
        if success:
            logger.info(f"✅ Call notification sent successfully to user {to_user.id}")
        else:
            logger.warning(f"⚠️ Call notification failed for user {to_user.id}")
        
        return Response({
            'success': True,
            'call_id': call_id,
            'status': 'initiated',
            'notification_sent': success,
            'message': 'Call initiated successfully'
        })
        
    except Exception as e:
        logger.error(f"Error initiating call: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def answer_call_api(request):
    """Answer an incoming call"""
    try:
        call_id = request.data.get('call_id')
        
        if not call_id:
            return Response({'error': 'call_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Get call record
        try:
            call = Call.objects.get(call_id=call_id)
        except Call.DoesNotExist:
            return Response({'error': 'Call not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Verify user is the callee
        if call.receiver != request.user:
            return Response({'error': 'Unauthorized to answer this call'}, status=status.HTTP_403_FORBIDDEN)
        
        # Check call status
        if call.status != 'initiated':
            return Response({'error': 'Call is not in a state to be answered'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Update call status
        call.status = 'answered'
        call.answered_at = timezone.now()
        call.save()
        
        # Send WebSocket notification to caller
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f"user_{call.caller.id}",
                {
                    'type': 'call_answered',
                    'call_id': call_id,
                    'callee_name': f"{request.user.first_name} {request.user.last_name}".strip(),
                    'callee_id': str(request.user.id)
                }
            )
        
        return Response({
            'success': True,
            'call_id': call_id,
            'status': 'answered',
            'message': 'Call answered successfully'
        })
        
    except Exception as e:
        logger.error(f"Error answering call: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def end_call_api(request):
    """End a call (either by caller or callee)"""
    try:
        call_id = request.data.get('call_id')
        
        if not call_id:
            return Response({'error': 'call_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Get call record
        try:
            call = Call.objects.get(call_id=call_id)
        except Call.DoesNotExist:
            return Response({'error': 'Call not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Verify user is part of this call
        if request.user not in [call.caller, call.receiver]:
            return Response({'error': 'Unauthorized to end this call'}, status=status.HTTP_403_FORBIDDEN)
        
        # Calculate call duration
        start_time = call.answered_at if call.answered_at else call.initiated_at
        call_duration = (timezone.now() - start_time).total_seconds()
        
        # Update call status
        call.status = 'ended'
        call.ended_at = timezone.now()
        call.duration = call_duration
        call.save()
        
        # Send WebSocket notification to other party
        other_user = call.receiver if call.caller == request.user else call.caller
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f"user_{other_user.id}",
                {
                    'type': 'call_ended',
                    'call_id': call_id,
                    'duration': call_duration,
                    'ended_by': str(request.user.id)
                }
            )
        
        return Response({
            'success': True,
            'call_id': call_id,
            'status': 'ended',
            'duration': call_duration,
            'message': 'Call ended successfully'
        })
        
    except Exception as e:
        logger.error(f"Error ending call: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def reject_call_api(request):
    """Reject an incoming call"""
    try:
        call_id = request.data.get('call_id')
        
        if not call_id:
            return Response({'error': 'call_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Get call record
        try:
            call = Call.objects.get(call_id=call_id)
        except Call.DoesNotExist:
            return Response({'error': 'Call not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Verify user is the callee
        if call.receiver != request.user:
            return Response({'error': 'Unauthorized to reject this call'}, status=status.HTTP_403_FORBIDDEN)
        
        # Check call status
        if call.status != 'initiated':
            return Response({'error': 'Call is not in a state to be rejected'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Update call status
        call.status = 'rejected'
        call.ended_at = timezone.now()
        call.duration = 0
        call.save()
        
        # Send WebSocket notification to caller
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f"user_{call.caller.id}",
                {
                    'type': 'call_rejected',
                    'call_id': call_id,
                    'rejected_by': str(request.user.id)
                }
            )
        
        return Response({
            'success': True,
            'call_id': call_id,
            'status': 'rejected',
            'message': 'Call rejected successfully'
        })
        
    except Exception as e:
        logger.error(f"Error rejecting call: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def update_call_quality_api(request):
    """Update call quality metrics"""
    try:
        call_id = request.data.get('call_id')
        connection_quality = request.data.get('connection_quality', 'good')
        network_info = request.data.get('network_info', {})
        
        if not call_id:
            return Response({'error': 'call_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Get call record
        try:
            call = Call.objects.get(call_id=call_id)
        except Call.DoesNotExist:
            return Response({'error': 'Call not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Verify user is part of this call
        if request.user not in [call.caller, call.receiver]:
            return Response({'error': 'Unauthorized to update this call'}, status=status.HTTP_403_FORBIDDEN)
        
        # Update call quality
        call.connection_quality = connection_quality
        call.network_info = network_info
        call.save()
        
        # Send WebSocket notification to other party about quality change
        other_user = call.receiver if call.caller == request.user else call.caller
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f"user_{other_user.id}",
                {
                    'type': 'call_quality_update',
                    'call_id': call_id,
                    'connection_quality': connection_quality,
                    'updated_by': str(request.user.id)
                }
            )
        
        return Response({
            'success': True,
            'call_id': call_id,
            'connection_quality': connection_quality,
            'message': 'Call quality updated successfully'
        })
        
    except Exception as e:
        logger.error(f"Error updating call quality: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def call_history_api(request):
    """Get call history for current user"""
    try:
        # Get user's calls (both as caller and callee)
        calls = Call.objects.filter(
            Q(caller=request.user) | Q(receiver=request.user)
        ).order_by('-initiated_at')
        
        # Apply filters
        status_filter = request.GET.get('status')
        if status_filter:
            calls = calls.filter(status=status_filter)
        
        call_type_filter = request.GET.get('call_type')
        if call_type_filter:
            calls = calls.filter(call_type=call_type_filter)
        
        # Pagination
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))
        start_index = (page - 1) * page_size
        end_index = start_index + page_size
        
        total_count = calls.count()
        paginated_calls = calls[start_index:end_index]
        
        # Serialize call history
        call_history = []
        for call in paginated_calls:
            other_user = call.receiver if call.caller == request.user else call.caller
            other_user_name = f"{other_user.first_name} {other_user.last_name}".strip() or other_user.username
            
            call_data = {
                'call_id': call.call_id,
                'call_type': call.call_type,
                'status': call.status,
                'initiated_at': call.initiated_at.isoformat(),
                'answered_at': call.answered_at.isoformat() if call.answered_at else None,
                'ended_at': call.ended_at.isoformat() if call.ended_at else None,
                'duration': call.duration,
                'other_user': {
                    'id': other_user.id,
                    'name': other_user_name,
                    'username': other_user.username
                },
                'is_outgoing': call.caller == request.user
            }
            call_history.append(call_data)
        
        return Response({
            'success': True,
            'call_history': call_history,
            'total_count': total_count,
            'page': page,
            'page_size': page_size,
            'total_pages': (total_count + page_size - 1) // page_size
        })
        
    except Exception as e:
        logger.error(f"Error fetching call history: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def active_calls_api(request):
    """Get currently active calls for current user"""
    try:
        # Get user's active calls
        active_calls = Call.objects.filter(
            Q(caller=request.user) | Q(receiver=request.user),
            status__in=['initiated', 'answered']
        )
        
        active_calls_list = []
        for call in active_calls:
            other_user = call.receiver if call.caller == request.user else call.caller
            other_user_name = f"{other_user.first_name} {other_user.last_name}".strip() or other_user.username
            
            call_data = {
                'call_id': call.call_id,
                'call_type': call.call_type,
                'status': call.status,
                'initiated_at': call.initiated_at.isoformat(),
                'other_user': {
                    'id': other_user.id,
                    'name': other_user_name,
                    'username': other_user.username
                },
                'is_outgoing': call.caller == request.user
            }
            active_calls_list.append(call_data)
        
        return Response({
            'success': True,
            'active_calls': active_calls_list,
            'count': len(active_calls_list)
        })
        
    except Exception as e:
        logger.error(f"Error fetching active calls: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def send_call_invite_api(request):
    """Send call invite to multiple users (group calling feature)"""
    try:
        user_ids = request.data.get('user_ids', [])
        call_type = request.data.get('call_type', 'audio')
        
        if not user_ids:
            return Response({'error': 'user_ids list is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        if len(user_ids) > 8:  # Limit group size
            return Response({'error': 'Maximum 8 users allowed in group call'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Generate unique call ID
        call_id = f"group_call_{uuid.uuid4().hex[:16]}"
        
        # Create call record for group
        call = Call.objects.create(
            call_id=call_id,
            caller=request.user,
            receiver=None,  # Group call
            call_type=call_type,
            status='initiated',
            initiated_at=timezone.now(),
            participants=[request.user.id]  # Creator is first participant
        )
        
        # Use WebSocket fallback for each participant
        from .websocket_fallback import send_call_with_fallback
        
        participant_list = [request.user.id]
        successful_invites = 0
        
        for user_id in user_ids:
            try:
                user = CustomUser.objects.get(id=user_id)
                participant_list.append(user_id)
                
                call_data = {
                    'call_id': call_id,
                    'caller_name': f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username,
                    'caller_id': str(request.user.id),
                    'call_type': call_type,
                    'is_group_call': True,
                    'participant_count': len(participant_list),
                    'action': 'incoming_group_call'
                }
                
                # Send call notification with fallback
                if send_call_with_fallback(user_id, call_data):
                    successful_invites += 1
                    
            except CustomUser.DoesNotExist:
                logger.warning(f"User {user_id} not found for group call invite")
        
        # Update participants field
        call.participants = participant_list
        call.save()
        
        return Response({
            'success': True,
            'call_id': call_id,
            'status': 'initiated',
            'participant_count': len(participant_list),
            'successful_invites': successful_invites,
            'message': 'Group call initiated successfully'
        })
        
    except Exception as e:
        logger.error(f"Error sending group call invite: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# ---------------------------
# Featured Package APIs
# ---------------------------

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_featured_packages_api(request):
    """Get list of active featured packages"""
    packages = FeaturedProductPackage.objects.filter(is_active=True).values(
        'id', 'name', 'duration_days', 'amount', 'package_type', 'description'
    )
    return Response({'packages': list(packages)})

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def purchase_featured_package_api(request):
    """Purchase a featured package for a product"""
    try:
        user = request.user
        data = request.data
        product_id = data.get('product_id')
        package_id = data.get('package_id')
        start_date_str = data.get('start_date')
        
        if not all([product_id, package_id, start_date_str]):
            return Response({'error': 'Missing required fields'}, status=status.HTTP_400_BAD_REQUEST)
            
        # Get vendor profile
        try:
            vendor = VendorProfile.objects.get(user=user, is_approved=True)
        except VendorProfile.DoesNotExist:
            return Response({'error': 'Vendor profile not found or not active'}, status=status.HTTP_404_NOT_FOUND)
            
        # Get product and verify ownership
        try:
            product = Product.objects.get(id=product_id, vendor=vendor)
        except Product.DoesNotExist:
            return Response({'error': 'Product not found'}, status=status.HTTP_404_NOT_FOUND)
            
        # Get package
        try:
            package = FeaturedProductPackage.objects.get(id=package_id, is_active=True)
        except FeaturedProductPackage.DoesNotExist:
            return Response({'error': 'Package not found'}, status=status.HTTP_404_NOT_FOUND)
            
        # Parse start date
        try:
            from datetime import datetime, date
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            if start_date < timezone.localdate():
                return Response({'error': 'Start date cannot be in the past'}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError:
            return Response({'error': 'Invalid date format'}, status=status.HTTP_400_BAD_REQUEST)
            
        # Calculate end date
        end_date = start_date + timedelta(days=package.duration_days)
        
        # Check wallet balance
        wallet, _ = VendorWallet.objects.get_or_create(vendor=vendor)
        if wallet.balance < package.amount:
            return Response({'error': 'Insufficient wallet balance'}, status=status.HTTP_400_BAD_REQUEST)
            
        with transaction.atomic():
            # Deduct from wallet
            wallet.deduct_commission(
                amount=package.amount,
                order_amount=package.amount,
                description=f"Featured package purchase: {package.name} for {product.name}"
            )
            
            # Create purchase record (model imports are at top of file, assuming available)
            purchase = ProductFeaturedPurchase.objects.create(
                product=product,
                vendor=vendor,
                package=package,
                amount_paid=package.amount,
                start_date=start_date,
                end_date=end_date,
                is_active=True
            )
            
            # Mark product as featured if starting today
            if start_date <= timezone.localdate() <= end_date:
                product.featured = True
                product.save()
            
            return Response({
                'success': True,
                'message': 'Package purchased successfully',
                'new_wallet_balance': wallet.balance,
                'end_date': end_date
            })
            
    except Exception as e:
        logger.error(f"Error buying featured package: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_product_featured_info_api(request, product_id):
    """Get featured info and check modification rights"""
    try:
        product = Product.objects.get(id=product_id, vendor__user=request.user)
        sync_featured_products(Product.objects.filter(pk=product.pk))
        product.refresh_from_db(fields=['featured'])
        
        # Find active purchase
        purchase = ProductFeaturedPurchase.objects.filter(
            product=product,
            is_active=True,
            end_date__gte=timezone.localdate()
        ).order_by('-end_date', '-pk').first()
        
        can_modify = True
        current_purchase = None
        
        if purchase:
            # Existing packages can move their remaining paid time.
            can_modify = True
                
            current_purchase = {
                'id': purchase.id,
                'package_name': purchase.package.name,
                'start_date': purchase.start_date,
                'end_date': purchase.end_date
            }
            
        return Response({
            'can_modify': can_modify,
            'featured': product.featured,
            'server_date': timezone.localdate(),
            'current_purchase': current_purchase
        })
        
    except Product.DoesNotExist:
        return Response({'error': 'Product not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def reschedule_featured_package_api(request, product_id):
    """Reschedule remaining paid time or feature now, without another charge."""
    from datetime import date
    try:
        new_start = date.fromisoformat(request.data.get('start_date', ''))
    except (ValueError, TypeError):
        return Response({'error': 'A valid start date (YYYY-MM-DD) is required'}, status=400)
    try:
        product, purchase = reschedule_paid_feature(product_id, request.user, new_start)
    except Product.DoesNotExist:
        return Response({'error': 'Product not found'}, status=404)
    except ValueError as error:
        return Response({'error': str(error)}, status=400)
    return Response({
        'success': True,
        'message': 'Featured promotion updated. No additional charge.',
        'featured': product.featured,
        'new_start_date': purchase.start_date,
        'new_end_date': purchase.end_date,
    })
