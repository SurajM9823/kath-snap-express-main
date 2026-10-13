from rest_framework import status, generics, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.db.models import Q, Prefetch
from django.shortcuts import get_object_or_404
from django.core.files.storage import default_storage
from django.utils import timezone
import os
import logging
from django.db import OperationalError
logger = logging.getLogger(__name__)
from .models import CustomUser
from .message_models import Conversation, Message, MessageRead, Call
from .message_serializers import (
    ConversationSerializer, MessageSerializer, CallSerializer,
    SendMessageSerializer, InitiateCallSerializer
)

class ConversationListView(generics.ListAPIView):
    serializer_class = ConversationSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return Conversation.objects.filter(
            participants=self.request.user
        ).prefetch_related(
            'participants',
            'messages',
            'messages__sender',
            'messages__read_by__user'
        ).order_by('-updated_at')  # Latest chats on top

class ConversationDetailView(generics.RetrieveAPIView):
    serializer_class = ConversationSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return Conversation.objects.filter(participants=self.request.user)

class MessageListView(generics.ListAPIView):
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        conversation_id = self.kwargs['conversation_id']
        conversation = get_object_or_404(
            Conversation.objects.filter(participants=self.request.user),
            id=conversation_id
        )
        
        # Mark messages as read
        unread_messages = Message.objects.filter(
            conversation=conversation
        ).exclude(sender=self.request.user).exclude(
            read_by__user=self.request.user
        )
        
        for message in unread_messages:
            MessageRead.objects.get_or_create(message=message, user=self.request.user)
        
        return Message.objects.filter(conversation=conversation).order_by('-created_at')

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def send_message_api(request):
    # Handle special case for superadmin recipient_type
    if request.data.get('recipient_type') == 'superadmin':
        try:
            superadmin_user = CustomUser.objects.get(is_superuser=True)
        except CustomUser.DoesNotExist:
            return Response({'error': 'Superadmin not found'}, status=status.HTTP_404_NOT_FOUND)
        except CustomUser.MultipleObjectsReturned:
            # If multiple superusers exist, pick the first one
            superadmin_user = CustomUser.objects.filter(is_superuser=True).first()

        # Check if conversation already exists
        conversation = Conversation.objects.filter(
            participants=request.user
        ).filter(participants=superadmin_user).first()

        if not conversation:
            conversation = Conversation.objects.create()
            conversation.participants.add(request.user, superadmin_user)

        # Create message
        try:
            message = Message.objects.create(
                conversation=conversation,
                sender=request.user,
                message_type='text',
                content=request.data.get('message', '')
            )
        except OperationalError as e:
            logger.exception(f"Database error creating message for user {request.user.id}: {e}")
            return Response({
                'error': 'Failed to save message. The database may not support 4-byte UTF-8 characters (emojis). Please configure MySQL to use utf8mb4 charset/collation.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Mark as read by sender
        MessageRead.objects.create(message=message, user=request.user)

        # Update conversation timestamp
        conversation.save()

        return Response({
            'message': MessageSerializer(message, context={'request': request}).data,
            'conversation': ConversationSerializer(conversation, context={'request': request}).data
        }, status=status.HTTP_201_CREATED)

    # Original send_message_api logic
    serializer = SendMessageSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    data = serializer.validated_data
    
    # Get or create conversation
    if data.get('conversation_id'):
        conversation = get_object_or_404(
            Conversation.objects.filter(participants=request.user),
            id=data['conversation_id']
        )
    else:
        recipient = get_object_or_404(CustomUser, id=data['recipient_id'])
        
        # Check if conversation already exists
        conversation = Conversation.objects.filter(
            participants=request.user
        ).filter(participants=recipient).first()
        
        if not conversation:
            conversation = Conversation.objects.create()
            conversation.participants.add(request.user, recipient)
    
    # Handle file upload
    file_data = {}
    if data.get('file'):
        uploaded_file = data['file']
        
        if data['message_type'] == 'image':
            # Use image processor for images
            from .image_utils import ImageProcessor
            try:
                processed_data = ImageProcessor.process_message_image(
                    uploaded_file, conversation.id, request.user.id
                )
                file_data.update(processed_data)
            except ValueError as e:
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        else:
            # Handle regular files
            file_extension = os.path.splitext(uploaded_file.name)[1]
            filename = f"messages/{conversation.id}_{request.user.id}_{uploaded_file.name}"
            file_path = default_storage.save(filename, uploaded_file)
            file_data.update({
                'file_url': file_path,
                'file_name': uploaded_file.name,
                'file_size': uploaded_file.size
            })
    
    # Create message
    try:
        message = Message.objects.create(
            conversation=conversation,
            sender=request.user,
            message_type=data['message_type'],
            content=data.get('content', ''),
            **file_data
        )
    except OperationalError as e:
        logger.exception(f"Database error creating message for user {request.user.id}: {e}")
        return Response({
            'error': 'Failed to save message. The database may not support 4-byte UTF-8 characters (emojis). Please configure MySQL to use utf8mb4 charset/collation.'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # Mark as read by sender
    MessageRead.objects.create(message=message, user=request.user)
    
    # Update conversation timestamp
    conversation.save()
    
    return Response({
        'message': MessageSerializer(message, context={'request': request}).data,
        'conversation': ConversationSerializer(conversation, context={'request': request}).data
    }, status=status.HTTP_201_CREATED)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def mark_message_read_api(request, message_id):
    message = get_object_or_404(Message, id=message_id)
    
    # Check if user is participant in conversation
    if not message.conversation.participants.filter(id=request.user.id).exists():
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    MessageRead.objects.get_or_create(message=message, user=request.user)
    
    return Response({'message': 'Message marked as read'})

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def toggle_pin_message_api(request, message_id):
    message = get_object_or_404(Message, id=message_id)
    
    # Check if user is participant in conversation
    if not message.conversation.participants.filter(id=request.user.id).exists():
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    message.is_pinned = not message.is_pinned
    message.save()
    
    return Response({
        'message': 'Message pin toggled',
        'is_pinned': message.is_pinned
    })

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_or_create_conversation_api(request, user_id):
    other_user = get_object_or_404(CustomUser, id=user_id)
    
    # Check if conversation already exists
    conversation = Conversation.objects.filter(
        participants=request.user
    ).filter(participants=other_user).first()
    
    if not conversation:
        conversation = Conversation.objects.create()
        conversation.participants.add(request.user, other_user)
    
    return Response(ConversationSerializer(conversation, context={'request': request}).data)

# Call APIs
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def initiate_call_api(request):
    serializer = InitiateCallSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    recipient = get_object_or_404(CustomUser, id=serializer.validated_data['recipient_id'])
    
    # End any existing calls
    Call.objects.filter(
        Q(caller=request.user, receiver=recipient) | Q(caller=recipient, receiver=request.user),
        status__in=['initiated', 'ringing', 'answered']
    ).update(status='ended', ended_at=timezone.now())
    
    # Get or create conversation
    conversation = Conversation.objects.filter(
        participants=request.user
    ).filter(participants=recipient).first()
    
    if not conversation:
        conversation = Conversation.objects.create()
        conversation.participants.add(request.user, recipient)
    
    # Create call record with proper status
    call = Call.objects.create(
        conversation=conversation,
        caller=request.user,
        receiver=recipient,
        call_type=serializer.validated_data['call_type'],
        status='initiated'  # Start with initiated, not ringing
    )
    
    # Generate Agora token for caller
    from .agora_service import AgoraTokenGenerator
    try:
        token_generator = AgoraTokenGenerator()
        # 🔥 FIX: Use UID=0 for Agora compliance
        agora_token = token_generator.generate_channel_token(call.call_id, 0)
        agora_app_id = token_generator.app_id
        logger.info(f"✅ Generated Agora token for call {call.call_id}")
    except Exception as e:
        logger.error(f"❌ Failed to generate Agora token: {e}")
        agora_token = None
        agora_app_id = None
    
    # Send WebSocket notification to receiver via global WebSocket
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync

    channel_layer = get_channel_layer()
    if channel_layer:
        async_to_sync(channel_layer.group_send)(
            f"user_{recipient.id}",
            {
                'type': 'incoming_call',
                'call': {
                    'id': call.id,
                    'call_id': call.call_id,
                    'call_type': call.call_type,
                    'status': call.status,
                    'started_at': call.started_at.isoformat(),
                    'caller': {
                        'id': call.caller.id,
                        'display_name': f"{call.caller.first_name} {call.caller.last_name}".strip() or call.caller.username,
                    },
                    'receiver': {
                        'id': call.receiver.id,
                        'display_name': f"{call.receiver.first_name} {call.receiver.last_name}".strip() or call.receiver.username,
                    },
                    'agora_token': agora_token,
                    'agora_channel': call.call_id,
                    'agora_app_id': agora_app_id
                }
            }
        )
    
    # Send FCM notification for background app wake-up
    try:
        from .models import VendorProfile
        from .fcm_service import fcm_service
        vendor_profile = VendorProfile.objects.filter(user=recipient).first()
        if vendor_profile and vendor_profile.fcm_token:
            fcm_service.send_call_notification(
                fcm_token=vendor_profile.fcm_token,
                call_data={
                    'call_id': call.call_id,
                    'caller_id': call.caller.id,
                    'caller_name': f"{call.caller.first_name} {call.caller.last_name}".strip() or call.caller.username,
                    'call_type': call.call_type
                }
            )
    except Exception as e:
        logger.error(f"Failed to send FCM call notification: {e}")

    # Return response in format expected by frontend
    return Response({
        'call': {
            'id': call.id,
            'call_id': call.call_id,
            'caller': {
                'id': call.caller.id,
                'display_name': f"{call.caller.first_name} {call.caller.last_name}".strip() or call.caller.username,
            },
            'receiver': {
                'id': call.receiver.id,
                'display_name': f"{call.receiver.first_name} {call.receiver.last_name}".strip() or call.receiver.username,
            },
            'call_type': call.call_type,
            'status': call.status,
            'started_at': call.started_at.isoformat(),
            'agora_token': agora_token,
            'agora_channel': call.call_id,
            'agora_app_id': agora_app_id
        }
    }, status=status.HTTP_201_CREATED)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def answer_call_api(request, call_id):
    call = get_object_or_404(Call, id=call_id, receiver=request.user)
    
    if call.status not in ['initiated', 'ringing']:
        return Response({'error': 'Call cannot be answered'}, status=status.HTTP_400_BAD_REQUEST)
    
    call.status = 'answered'
    call.answered_at = timezone.now()
    call.save()
    
    # Generate ONE token for the channel (both users use same token)
    from .agora_service import AgoraTokenGenerator
    try:
        token_generator = AgoraTokenGenerator()
        # ✅ Generate ONE token for the channel
        shared_token = token_generator.generate_channel_token(call.call_id, 0)
        agora_app_id = token_generator.app_id
        logger.info(f"✅ Generated shared token for call {call.call_id}")
    except Exception as e:
        logger.error(f"❌ Failed to generate Agora token: {e}")
        shared_token = agora_app_id = None
    
    # Notify caller that call was answered
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync
    
    channel_layer = get_channel_layer()
    if channel_layer:
        async_to_sync(channel_layer.group_send)(
            f"user_{call.caller.id}",
            {
                'type': 'call_accepted',
                'call_id': call.call_id,
                'accepter_name': f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username,
                'accepter_id': request.user.id,
                'agora_token': shared_token,  # ✅ Same token
                'agora_channel': call.call_id,
                'agora_app_id': agora_app_id
            }
        )
    
    # Return response with same token for receiver
    response_data = CallSerializer(call).data
    response_data.update({
        'agora_token': shared_token,  # ✅ Same token
        'agora_channel': call.call_id,
        'agora_app_id': agora_app_id
    })
    
    return Response(response_data)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def end_call_api(request, call_id):
    call = get_object_or_404(
        Call.objects.filter(
            Q(caller=request.user) | Q(receiver=request.user)
        ),
        id=call_id
    )
    
    call.end_call()
    
    # Notify other participant that call ended
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync
    
    channel_layer = get_channel_layer()
    if channel_layer:
        async_to_sync(channel_layer.group_send)(
            f"call_{call.call_id}",
            {
                'type': 'call_status_update',
                'status': 'ended',
                'user_id': request.user.id,
                'call_id': call.call_id
            }
        )
    
    return Response(CallSerializer(call).data)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def decline_call_api(request, call_id):
    call = get_object_or_404(Call, id=call_id, receiver=request.user)
    
    if call.status not in ['initiated', 'ringing']:
        return Response({'error': 'Call cannot be declined'}, status=status.HTTP_400_BAD_REQUEST)
    
    call.status = 'declined'
    call.ended_at = timezone.now()
    call.save()
    
    # Notify caller that call was declined
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync
    
    channel_layer = get_channel_layer()
    if channel_layer:
        async_to_sync(channel_layer.group_send)(
            f"call_{call.call_id}",
            {
                'type': 'call_status_update',
                'status': 'declined',
                'user_id': request.user.id,
                'call_id': call.call_id
            }
        )
    
    return Response(CallSerializer(call).data)

class CallHistoryView(generics.ListAPIView):
    serializer_class = CallSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return Call.objects.filter(
            Q(caller=self.request.user) | Q(receiver=self.request.user)
        ).order_by('-started_at')

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def incoming_calls_api(request):
    # Auto-hangup calls older than 50 seconds
    timeout_calls = Call.objects.filter(
        receiver=request.user,
        status__in=['initiated', 'ringing'],
        started_at__lt=timezone.now() - timezone.timedelta(seconds=50)
    )
    timeout_calls.update(status='missed', ended_at=timezone.now())
    
    calls = Call.objects.filter(
        receiver=request.user,
        status__in=['initiated', 'ringing']
    ).order_by('-started_at')
    
    # Debug logging
    print(f"User {request.user.id} checking incoming calls")
    print(f"Found {calls.count()} calls with status: {[c.status for c in calls]}")
    
    return Response(CallSerializer(calls, many=True).data)

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def message_image_api(request, message_id):
    """Serve message images with access control"""
    message = get_object_or_404(Message, id=message_id, message_type='image')
    
    # Check if user has access to this conversation
    if not message.conversation.participants.filter(id=request.user.id).exists():
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    # Return image URLs
    return Response({
        'image_url': message.file_url,
        'thumbnail_url': message.thumbnail_url,
        'file_name': message.file_name,
        'file_size': message.file_size,
        'dimensions': {
            'width': message.image_width,
            'height': message.image_height
        } if message.image_width and message.image_height else None
    })

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_support_conversation_api(request):
    """Create a conversation with superadmin for support"""
    try:
        superadmin_user = CustomUser.objects.get(is_superuser=True)
    except CustomUser.DoesNotExist:
        return Response({'error': 'Support not available'}, status=status.HTTP_404_NOT_FOUND)
    except CustomUser.MultipleObjectsReturned:
        superadmin_user = CustomUser.objects.filter(is_superuser=True).first()
    # Check if conversation already exists
    conversation = Conversation.objects.filter(
        participants=request.user
    ).filter(participants=superadmin_user).first()

    if not conversation:
        conversation = Conversation.objects.create()
        conversation.participants.add(request.user, superadmin_user)

    # If message is provided, create it
    message_content = request.data.get('message')
    if message_content:
        try:
            message = Message.objects.create(
                conversation=conversation,
                sender=request.user,
                message_type='text',
                content=message_content
            )
        except OperationalError as e:
            logger.exception(f"Database error creating support message for user {request.user.id}: {e}")
            return Response({
                'error': 'Failed to save message. The database may not support 4-byte UTF-8 characters (emojis). Please configure MySQL to use utf8mb4 charset/collation.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Mark as read by sender
        MessageRead.objects.create(message=message, user=request.user)
        # Update conversation timestamp
        conversation.save()

    return Response({
        'conversation_id': conversation.id,
        'message': 'Support conversation created' if not message_content else 'Message sent to support'
    }, status=status.HTTP_201_CREATED)