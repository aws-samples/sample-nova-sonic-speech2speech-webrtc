"""
EventBridge - Handles S2S event messaging via WebRTC data channels
Implements data channel message reception, parsing, event routing to S2sSessionManager,
and response transmission back to clients via data channels
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Dict, Optional, Callable, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class EventMessage:
    """Represents an event message with metadata"""
    id: str
    type: str
    timestamp: int
    client_id: str
    event: dict
    require_ack: bool = False
    retry_count: int = 0

class EventBridge:
    """
    Handles S2S event messaging via WebRTC data channels
    Manages message reception, parsing, routing, and response transmission with enhanced reliability
    """
    
    def __init__(self):
        self.data_channels: Dict[str, Any] = {}
        self.session_managers: Dict[str, Any] = {}
        self.message_queue: Dict[str, list] = {}
        self.pending_acks: Dict[str, EventMessage] = {}
        self.chunk_buffers: Dict[str, Dict] = {}
        
        # Configuration
        self.max_message_size = 65536  # 64KB WebRTC data channel limit
        self.chunk_size = 60000  # 60KB chunks to be safe
        self.ack_timeout = 5.0  # 5 seconds
        self.max_retries = 3
        self.retry_delay = 1.0  # 1 second
        
        # Enhanced reliability features
        self.sequence_numbers: Dict[str, int] = {}  # Per-client sequence numbers
        self.expected_sequence_numbers: Dict[str, int] = {}  # Expected sequence per client
        self.out_of_order_buffers: Dict[str, Dict[int, dict]] = {}  # Per-client out-of-order buffers
        self.delivered_messages: Dict[str, set] = {}  # Per-client delivered message IDs
        self.message_retry_map: Dict[str, dict] = {}  # Message retry tracking
        self.connection_monitors: Dict[str, dict] = {}  # Per-client connection monitoring
        
        # Event callbacks
        self.on_event_received: Optional[Callable] = None
        self.on_client_connected: Optional[Callable] = None
        self.on_client_disconnected: Optional[Callable] = None
        self.on_error: Optional[Callable] = None
        self.on_test_audio_requested: Optional[Callable] = None
        
        # Enhanced statistics
        self.stats = {
            'messages_sent': 0,
            'messages_received': 0,
            'events_processed': 0,
            'errors': 0,
            'chunks_sent': 0,
            'chunks_received': 0,
            'messages_retried': 0,
            'messages_dropped': 0,
            'out_of_order_messages': 0,
            'duplicate_messages': 0,
            'ack_timeouts': 0,
            'connection_losses': 0
        }
        
        # Start background tasks
        self._start_background_tasks()
        
        logger.debug("[EventBridge] Initialized with enhanced reliability")
        
    def set_event_callback(self, callback: Callable[[str, dict], None]):
        """Set callback for received events"""
        self.on_event_received = callback
        
    def set_error_callback(self, callback: Callable[[str, Exception], None]):
        """Set callback for errors"""
        self.on_error = callback
        
    def set_test_audio_callback(self, callback: Callable[[str], None]):
        """Set callback for test audio playback requests"""
        self.on_test_audio_requested = callback
        
    def add_data_channel(self, client_id: str, channel: Any):
        """
        Add data channel for a client
        
        Args:
            client_id: Unique client identifier
            channel: WebRTC data channel object
        """
        logger.debug(f"📨 [EventBridge] Adding data channel for client: {client_id}")
        self.data_channels[client_id] = channel
        self.message_queue[client_id] = []
        
        # Initialize reliability tracking for this client
        self.sequence_numbers[client_id] = 0
        self.expected_sequence_numbers[client_id] = 1  # Client starts from 1
        self.out_of_order_buffers[client_id] = {}
        self.delivered_messages[client_id] = set()
        self.connection_monitors[client_id] = {
            'last_activity': time.time(),
            'heartbeat_task': None,
            'is_healthy': True
        }
        
        # Set up data channel event handlers
        @channel.on('message')
        def on_message(message):
            logger.debug(f"📨 [EventBridge] Raw data channel message from {client_id}: {len(message)} bytes")
            logger.debug(f"🔍 [EventBridge] Raw message content: {message[:500]}...")  # Log first 500 chars
            self.connection_monitors[client_id]['last_activity'] = time.time()
            asyncio.create_task(self._handle_data_channel_message(client_id, message))
            
        @channel.on('open')
        def on_open():
            logger.debug(f"🎉 [EventBridge] Data channel OPENED for {client_id} - ready to receive messages!")
            self.connection_monitors[client_id]['is_healthy'] = True
            # Heartbeat monitoring disabled - relying on WebRTC native connection state
            # self._start_heartbeat_monitoring(client_id)
            asyncio.create_task(self._process_message_queue(client_id))
            
        @channel.on('close')
        def on_close():
            logger.info(f"[EventBridge] Data channel closed for {client_id}")
            self.stats['connection_losses'] += 1
            self._handle_client_disconnection(client_id)
            
        @channel.on('error')
        def on_error(error):
            logger.error(f"[EventBridge] Data channel error for {client_id}: {error}")
            self.stats['errors'] += 1
            self.connection_monitors[client_id]['is_healthy'] = False
            
            if self.on_error:
                self.on_error(client_id, error)
                
        logger.debug(f"[EventBridge] Added data channel for client: {client_id}")
        
    def remove_data_channel(self, client_id: str):
        """Remove data channel for a client"""
        self._cleanup_client(client_id)
        logger.debug(f"[EventBridge] Removed data channel for client: {client_id}")
        
    def set_session_manager(self, client_id: str, session_manager: Any):
        """
        Associate S2sSessionManager with client
        
        Args:
            client_id: Client identifier
            session_manager: S2sSessionManager instance
        """
        logger.debug(f"🔗 [EventBridge] ASSOCIATING SESSION MANAGER - Client: {client_id}")
        logger.debug(f"🔗 [EventBridge] Session manager type: {type(session_manager).__name__}")
        logger.debug(f"🔗 [EventBridge] Session manager active: {getattr(session_manager, 'is_active', 'unknown')}")
        logger.debug(f"🔗 [EventBridge] Current session managers before association: {list(self.session_managers.keys())}")
        
        self.session_managers[client_id] = session_manager
        
        logger.debug(f"✅ [EventBridge] SESSION MANAGER ASSOCIATED - Client: {client_id}")
        logger.debug(f"✅ [EventBridge] Total session managers after association: {len(self.session_managers)}")
        logger.debug(f"✅ [EventBridge] All session managers: {list(self.session_managers.keys())}")
        
        # Verify the association worked
        if client_id in self.session_managers:
            logger.debug(f"✅ [EventBridge] VERIFICATION SUCCESS - Session manager found for {client_id}")
        else:
            logger.error(f"❌ [EventBridge] VERIFICATION FAILED - Session manager NOT found for {client_id} after association!")
        
    def get_session_manager(self, client_id: str) -> Optional[Any]:
        """Get session manager for client"""
        return self.session_managers.get(client_id)
        
    async def _handle_data_channel_message(self, client_id: str, message: str):
        """
        Handle incoming data channel message with enhanced reliability
        
        Args:
            client_id: Client identifier
            message: Raw message string
        """
        try:
            self.stats['messages_received'] += 1
            
            # Parse JSON message
            message_data = json.loads(message)
            logger.debug(f"📨 [EventBridge] Received message from {client_id}: type={message_data.get('type', 'unknown')}, keys={list(message_data.keys())}")
            
            # Debug: Log full message for S2S events and unknown types
            message_type = message_data.get('type', 'unknown')
            if message_type == 'S2S_EVENT':
                logger.debug(f"🎉 [EventBridge] S2S_EVENT RECEIVED! Details: {json.dumps(message_data, indent=2)}")
            elif message_type not in ['HEARTBEAT', 'ACK']:
                logger.debug(f"🔍 [EventBridge] Non-standard message: {json.dumps(message_data, indent=2)}")
            else:
                logger.debug(f"📨 [EventBridge] Standard message: {message_type}")
            
            # Handle different message types
            message_type = message_data.get('type')
            
            if message_type == 'HEARTBEAT':
                # Heartbeat handling disabled - relying on WebRTC native connection state
                logger.debug(f"[EventBridge] Ignoring heartbeat from {client_id} (heartbeat disabled)")
            elif message_type == 'ACK':
                await self._handle_acknowledgment(message_data)
            elif message_type == 'CHUNK':
                await self._handle_chunk(client_id, message_data)
            elif message_type == 'S2S_EVENT':
                await self._handle_s2s_event(client_id, message_data)
            elif 'event' in message_data:
                # Handle raw S2S events (direct from React client)
                logger.debug(f"🎉 [EventBridge] RAW S2S EVENT DETECTED! Processing directly...")
                await self._handle_raw_s2s_event(client_id, message_data)
            else:
                logger.warning(f"[EventBridge] Unknown message type: {message_type}")
                logger.warning(f"[EventBridge] Full message data: {json.dumps(message_data, indent=2)}")
                
        except json.JSONDecodeError as e:
            logger.error(f"[EventBridge] Error parsing message from {client_id}: {e}")
            self.stats['errors'] += 1
        except Exception as e:
            logger.error(f"[EventBridge] Error handling message from {client_id}: {e}")
            self.stats['errors'] += 1
            if self.on_error:
                self.on_error(client_id, e)
                
    async def _handle_acknowledgment(self, ack_data: dict):
        """Handle acknowledgment message"""
        message_id = ack_data.get('messageId')
        if message_id and message_id in self.pending_acks:
            del self.pending_acks[message_id]
            logger.debug(f"[EventBridge] Received acknowledgment for message: {message_id}")
            
    async def _handle_chunk(self, client_id: str, chunk_data: dict):
        """
        Handle chunk message for large message reassembly
        
        Args:
            client_id: Client identifier
            chunk_data: Chunk message data
        """
        try:
            self.stats['chunks_received'] += 1
            
            chunk_id = chunk_data.get('chunkId')
            chunk_index = chunk_data.get('chunkIndex')
            total_chunks = chunk_data.get('totalChunks')
            data = chunk_data.get('data')
            is_last = chunk_data.get('isLast', False)
            
            if not chunk_id or chunk_index is None or not total_chunks or not data:
                logger.error(f"[EventBridge] Invalid chunk data from {client_id}")
                return
                
            # Initialize chunk buffer if needed
            if chunk_id not in self.chunk_buffers:
                self.chunk_buffers[chunk_id] = {
                    'chunks': [None] * total_chunks,
                    'received_count': 0,
                    'client_id': client_id
                }
                
            buffer = self.chunk_buffers[chunk_id]
            buffer['chunks'][chunk_index] = data
            buffer['received_count'] += 1
            
            logger.debug(f"[EventBridge] Received chunk {chunk_index + 1}/{total_chunks} for message {chunk_id}")
            
            # Check if all chunks received
            if buffer['received_count'] == total_chunks:
                try:
                    # Reassemble message
                    reassembled = ''.join(buffer['chunks'])
                    original_message = json.loads(reassembled)
                    
                    logger.debug(f"[EventBridge] Reassembled large message from {client_id}")
                    
                    # Clean up buffer
                    del self.chunk_buffers[chunk_id]
                    
                    # Process the reassembled message
                    await self._handle_data_channel_message(client_id, json.dumps(original_message))
                    
                except Exception as e:
                    logger.error(f"[EventBridge] Error reassembling chunks for {chunk_id}: {e}")
                    if chunk_id in self.chunk_buffers:
                        del self.chunk_buffers[chunk_id]
                        
        except Exception as e:
            logger.error(f"[EventBridge] Error handling chunk from {client_id}: {e}")
            
    async def _handle_s2s_event(self, client_id: str, message_data: dict):
        """
        Handle S2S event message
        
        Args:
            client_id: Client identifier
            message_data: S2S event message data
        """
        try:
            self.stats['events_processed'] += 1
            
            # Enhanced logging for S2S event reception
            event_id = message_data.get('id', 'no-id')
            timestamp = message_data.get('timestamp', int(time.time() * 1000))
            logger.debug(f"🎉 [EventBridge] S2S EVENT RECEIVED! Client: {client_id}, ID: {event_id}, Timestamp: {timestamp}")
            
            # Send acknowledgment if required
            if message_data.get('requireAck'):
                await self._send_acknowledgment(client_id, message_data.get('id'))
                
            # Extract S2S event
            s2s_event = message_data.get('event')
            if not s2s_event:
                logger.warning(f"❌ [EventBridge] No event data in message from {client_id}")
                return
                
            event_type = self._get_event_type(s2s_event)
            logger.debug(f"📨 [EventBridge] Processing S2S event from {client_id}: {event_type} (ID: {event_id})")
            
            # Log event details for key events
            if event_type in ['sessionStart', 'promptStart', 'contentStart']:
                logger.debug(f"🔍 [EventBridge] Key event details - Type: {event_type}, Client: {client_id}, Data: {json.dumps(s2s_event, indent=2)}")
            
            # Route event to session manager
            await self._route_event_to_session_manager(client_id, s2s_event, message_data)
            
            # Call general event callback
            if self.on_event_received:
                self.on_event_received(client_id, s2s_event)
                
            logger.debug(f"✅ [EventBridge] Successfully processed S2S event {event_type} from {client_id} (ID: {event_id})")
                
        except Exception as e:
            logger.error(f"❌ [EventBridge] Error handling S2S event from {client_id}: {e}")
            logger.error(f"❌ [EventBridge] Exception details: {type(e).__name__}: {str(e)}")
            import traceback
            logger.error(f"❌ [EventBridge] Traceback: {traceback.format_exc()}")
            self.stats['errors'] += 1
            
    async def _handle_raw_s2s_event(self, client_id: str, message_data: dict):
        """
        Handle raw S2S event message (direct from React client)
        
        Args:
            client_id: Client identifier
            message_data: Raw S2S event data with 'event' field
        """
        try:
            self.stats['events_processed'] += 1
            
            # Extract S2S event
            s2s_event = message_data.get('event')
            if not s2s_event:
                logger.warning(f"❌ [EventBridge] No event data in raw message from {client_id}")
                return
                
            event_type = list(s2s_event.keys())[0] if s2s_event else 'unknown'
            logger.debug(f"🎉 [EventBridge] RAW S2S EVENT RECEIVED! Client: {client_id}, Type: {event_type}")
            
            # Check if this is a test client (client ID contains 'test')
            is_test_client = 'test' in client_id.lower()
            
            if is_test_client:
                logger.debug(f"🧪 [EventBridge] TEST MODE - Logging event without Nova Sonic processing")
                logger.debug(f"📋 [EventBridge] TEST EVENT DETAILS:")
                logger.debug(f"   - Client: {client_id}")
                logger.debug(f"   - Event Type: {event_type}")
                logger.debug(f"   - Event Data: {json.dumps(s2s_event, indent=2)}")
                
                # Send test acknowledgment back to client
                await self._send_test_acknowledgment(client_id, event_type)
                
                # Trigger test audio playback for specific events
                if event_type == 'contentEnd':
                    logger.debug(f"🧪 [EventBridge] Triggering test audio playback for {client_id}")
                    await self._trigger_test_audio_playback(client_id)
                
            else:
                # Normal processing - route to session manager
                logger.debug(f"📨 [EventBridge] PRODUCTION MODE - Routing to session manager")
                await self._route_event_to_session_manager(client_id, message_data, message_data)
            
            # Call general event callback
            if self.on_event_received:
                self.on_event_received(client_id, s2s_event)
                
            logger.debug(f"✅ [EventBridge] Successfully processed raw S2S event {event_type} from {client_id}")
                
        except Exception as e:
            logger.error(f"❌ [EventBridge] Error handling raw S2S event from {client_id}: {e}")
            logger.error(f"❌ [EventBridge] Exception details: {type(e).__name__}: {str(e)}")
            import traceback
            logger.error(f"❌ [EventBridge] Traceback: {traceback.format_exc()}")
            self.stats['errors'] += 1
            
    async def _send_test_acknowledgment(self, client_id: str, event_type: str):
        """Send test acknowledgment back to client"""
        try:
            if client_id not in self.data_channels:
                return
                
            ack_message = {
                'type': 'TEST_ACK',
                'eventType': event_type,
                'status': 'received',
                'timestamp': int(time.time() * 1000),
                'message': f'Test event {event_type} received and logged successfully'
            }
            
            channel = self.data_channels[client_id]
            if hasattr(channel, 'send'):
                channel.send(json.dumps(ack_message))
                logger.debug(f"📤 [EventBridge] Sent test acknowledgment to {client_id} for {event_type}")
            
        except Exception as e:
            logger.error(f"❌ [EventBridge] Error sending test acknowledgment: {e}")
            
    async def _trigger_test_audio_playback(self, client_id: str):
        """Trigger test audio playback for test client"""
        try:
            logger.debug(f"🧪 [EventBridge] Starting test audio playback for {client_id}")
            
            # Get the WebRTC master instance to access audio output track
            # This requires access to the parent WebRTC system
            # We'll need to add a callback mechanism for this
            
            # For now, send a message to indicate test audio should start
            test_audio_message = {
                'type': 'TEST_AUDIO_START',
                'message': 'Test audio playback starting',
                'timestamp': int(time.time() * 1000)
            }
            
            if client_id in self.data_channels:
                channel = self.data_channels[client_id]
                if hasattr(channel, 'send'):
                    channel.send(json.dumps(test_audio_message))
                    logger.debug(f"🧪 [EventBridge] Sent test audio start notification to {client_id}")
            
            # Trigger test audio playback via callback
            if self.on_test_audio_requested:
                self.on_test_audio_requested(client_id)
            
        except Exception as e:
            logger.error(f"❌ [EventBridge] Error triggering test audio playback: {e}")
            
    async def _route_event_to_session_manager(self, client_id: str, s2s_event: dict, message_data: dict):
        """
        Route S2S event to appropriate session manager
        
        Args:
            client_id: Client identifier
            s2s_event: S2S event data (wrapper with correlationId, timestamp, etc.)
            message_data: Full message data
        """
        event_id = message_data.get('id', 'no-id')
        
        # Extract the actual Nova Sonic event from the wrapper
        # s2s_event structure: {"event": {"sessionStart": {...}}, "correlationId": "...", "timestamp": ...}
        nova_sonic_event = s2s_event.get('event', {})
        if not nova_sonic_event:
            logger.error(f"❌ [EventBridge] No Nova Sonic event found in S2S event wrapper for {client_id} (ID: {event_id})")
            logger.error(f"❌ [EventBridge] S2S event structure: {list(s2s_event.keys())}")
            return
            
        # Get the actual event type from the Nova Sonic event
        event_type = list(nova_sonic_event.keys())[0] if nova_sonic_event else 'unknown'
        
        logger.debug(f"🔍 [EventBridge] ROUTING ATTEMPT - Event: {event_type}, Client: {client_id}, ID: {event_id}")
        logger.debug(f"🔍 [EventBridge] Available session managers: {list(self.session_managers.keys())}")
        logger.debug(f"🔍 [EventBridge] Total session managers: {len(self.session_managers)}")
        
        session_manager = self.session_managers.get(client_id)
        if not session_manager:
            logger.error(f"❌ [EventBridge] ROUTING FAILED - No session manager found for {client_id}!")
            logger.error(f"❌ [EventBridge] Available session managers: {list(self.session_managers.keys())}")
            logger.error(f"❌ [EventBridge] Event {event_type} (ID: {event_id}) will be LOST!")
            
            # Log session manager association status
            logger.error(f"❌ [EventBridge] Session manager association status:")
            for sm_client_id, sm in self.session_managers.items():
                logger.error(f"   - Client {sm_client_id}: {type(sm).__name__} (active: {getattr(sm, 'is_active', 'unknown')})")
            
            return
            
        try:
            logger.debug(f"📨 [EventBridge] ROUTING SUCCESS - Found session manager for {client_id}")
            logger.debug(f"📨 [EventBridge] Session manager type: {type(session_manager).__name__}")
            logger.debug(f"📨 [EventBridge] Session manager active: {getattr(session_manager, 'is_active', 'unknown')}")
            
            # Create the properly formatted event for the session manager
            # Session manager expects: {"event": {"sessionStart": {...}}}
            formatted_event = {"event": nova_sonic_event}
            
            logger.debug(f"🎯 [EventBridge] Calling session_manager.send_raw_event() for {event_type} event (Client: {client_id}, ID: {event_id})")
            logger.debug(f"🔍 [EventBridge] Formatted event structure: {list(formatted_event.keys())} -> {list(formatted_event['event'].keys())}")
            
            await session_manager.send_raw_event(formatted_event)
            logger.debug(f"✅ [EventBridge] ROUTING COMPLETE - Successfully sent {event_type} event to session manager for {client_id} (ID: {event_id})")
            
        except Exception as e:
            logger.error(f"❌ [EventBridge] ROUTING ERROR - Failed to send event to session manager for {client_id}")
            logger.error(f"❌ [EventBridge] Event: {event_type} (ID: {event_id})")
            logger.error(f"❌ [EventBridge] Exception: {type(e).__name__}: {str(e)}")
            import traceback
            logger.error(f"❌ [EventBridge] Traceback: {traceback.format_exc()}")
            
            # Send error response back to client
            error_response = {
                'type': 'ERROR',
                'message': f'Error processing event: {str(e)}',
                'originalEventId': message_data.get('id'),
                'timestamp': int(time.time() * 1000)
            }
            await self.send_event(client_id, error_response)
            
    def _get_event_type(self, s2s_event: dict) -> str:
        """
        Extract event type from S2S event
        
        Args:
            s2s_event: S2S event data
            
        Returns:
            Event type string
        """
        if not s2s_event or 'event' not in s2s_event:
            return 'unknown'
            
        event_keys = list(s2s_event['event'].keys())
        return event_keys[0] if event_keys else 'unknown'
        
    async def send_event(self, client_id: str, event_data: dict, require_ack: bool = False):
        """
        Send event to specific client via data channel
        
        Args:
            client_id: Target client identifier
            event_data: Event data to send
            require_ack: Whether to require acknowledgment
        """
        logger.debug(f"📤 [EventBridge] send_event called for {client_id}")
        logger.debug(f"🔍 [EventBridge] Available data channels: {list(self.data_channels.keys())}")
        logger.debug(f"🔍 [EventBridge] Event data keys: {list(event_data.keys())}")
        
        if client_id not in self.data_channels:
            logger.warning(f"❌ [EventBridge] No data channel found for {client_id}")
            logger.warning(f"❌ [EventBridge] Available channels: {list(self.data_channels.keys())}")
            return False
            
        channel = self.data_channels[client_id]
        logger.debug(f"🔍 [EventBridge] Found data channel for {client_id}")
        
        # Check if channel is ready
        channel_ready = hasattr(channel, 'readyState') and channel.readyState == 'open'
        logger.debug(f"🔍 [EventBridge] Channel ready state: {getattr(channel, 'readyState', 'no-readyState')} (ready: {channel_ready})")
        
        if not channel_ready:
            # Queue message for later
            message = {
                'id': self._generate_message_id(),
                'type': 'S2S_RESPONSE',
                'timestamp': int(time.time() * 1000),
                'requireAck': require_ack,
                'event': event_data
            }
            self.message_queue[client_id].append(message)
            logger.warning(f"⚠️ [EventBridge] Queued message for {client_id} (channel not ready)")
            return True
            
        try:
            message = {
                'id': self._generate_message_id(),
                'type': 'S2S_RESPONSE',
                'timestamp': int(time.time() * 1000),
                'requireAck': require_ack,
                'event': event_data
            }
            
            logger.debug(f"📤 [EventBridge] Sending message to {client_id}: type={message['type']}, id={message['id']}")
            await self._send_message(client_id, message, require_ack)
            logger.debug(f"✅ [EventBridge] Successfully sent message to {client_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ [EventBridge] Error sending event to {client_id}: {e}")
            import traceback
            logger.error(f"❌ [EventBridge] Error traceback: {traceback.format_exc()}")
            self.stats['errors'] += 1
            return False
            
    async def _send_message(self, client_id: str, message: dict, require_ack: bool = False):
        """
        Send message via data channel with chunking support
        
        Args:
            client_id: Target client identifier
            message: Message to send
            require_ack: Whether to require acknowledgment
        """
        try:
            serialized = json.dumps(message)
            
            # Check if message needs chunking
            if len(serialized) > self.max_message_size:
                await self._send_large_message(client_id, message, require_ack)
            else:
                await self._send_single_message(client_id, serialized, message.get('id'), require_ack)
                
        except Exception as e:
            logger.error(f"[EventBridge] Error sending message to {client_id}: {e}")
            raise
            
    async def _send_single_message(self, client_id: str, serialized: str, message_id: str, require_ack: bool):
        """Send single message via data channel"""
        channel = self.data_channels[client_id]
        channel.send(serialized)
        
        self.stats['messages_sent'] += 1
        logger.debug(f"[EventBridge] Sent message to {client_id}")
        
        # Handle acknowledgment if required
        if require_ack and message_id:
            # Set up timeout for acknowledgment
            asyncio.create_task(self._handle_ack_timeout(message_id))
            
    async def _send_large_message(self, client_id: str, message: dict, require_ack: bool):
        """
        Send large message by chunking
        
        Args:
            client_id: Target client identifier
            message: Large message to send
            require_ack: Whether to require acknowledgment
        """
        try:
            serialized = json.dumps(message)
            total_chunks = (len(serialized) + self.chunk_size - 1) // self.chunk_size
            chunk_id = self._generate_message_id()
            
            logger.info(f"[EventBridge] Sending large message to {client_id} in {total_chunks} chunks")
            
            # Send chunks
            for i in range(total_chunks):
                start = i * self.chunk_size
                end = min(start + self.chunk_size, len(serialized))
                chunk_data = serialized[start:end]
                
                chunk_message = {
                    'id': self._generate_message_id(),
                    'type': 'CHUNK',
                    'chunkId': chunk_id,
                    'chunkIndex': i,
                    'totalChunks': total_chunks,
                    'isLast': i == total_chunks - 1,
                    'data': chunk_data,
                    'requireAck': require_ack and i == total_chunks - 1
                }
                
                await self._send_single_message(
                    client_id, 
                    json.dumps(chunk_message), 
                    chunk_message['id'], 
                    chunk_message['requireAck']
                )
                
                self.stats['chunks_sent'] += 1
                
        except Exception as e:
            logger.error(f"[EventBridge] Error sending large message to {client_id}: {e}")
            raise
            
    async def _send_acknowledgment(self, client_id: str, message_id: str):
        """Send acknowledgment for received message"""
        try:
            ack_message = {
                'id': self._generate_message_id(),
                'type': 'ACK',
                'messageId': message_id,
                'timestamp': int(time.time() * 1000)
            }
            
            channel = self.data_channels[client_id]
            channel.send(json.dumps(ack_message))
            
            logger.debug(f"[EventBridge] Sent acknowledgment to {client_id} for message {message_id}")
            
        except Exception as e:
            logger.error(f"[EventBridge] Error sending acknowledgment to {client_id}: {e}")
            
    async def _handle_ack_timeout(self, message_id: str):
        """Handle acknowledgment timeout"""
        await asyncio.sleep(self.ack_timeout)
        
        if message_id in self.pending_acks:
            logger.warning(f"[EventBridge] Acknowledgment timeout for message: {message_id}")
            del self.pending_acks[message_id]
            
    async def _process_message_queue(self, client_id: str):
        """Process queued messages when data channel becomes ready"""
        if client_id not in self.message_queue:
            return
            
        queue = self.message_queue[client_id]
        logger.info(f"[EventBridge] Processing {len(queue)} queued messages for {client_id}")
        
        while queue:
            message = queue.pop(0)
            try:
                await self._send_message(client_id, message, message.get('requireAck', False))
            except Exception as e:
                logger.error(f"[EventBridge] Error processing queued message for {client_id}: {e}")
                
    def _cleanup_client(self, client_id: str):
        """Clean up client resources"""
        if client_id in self.data_channels:
            del self.data_channels[client_id]
            
        if client_id in self.session_managers:
            del self.session_managers[client_id]
            
        if client_id in self.message_queue:
            del self.message_queue[client_id]
            
        # Clean up reliability tracking
        if client_id in self.sequence_numbers:
            del self.sequence_numbers[client_id]
            
        if client_id in self.expected_sequence_numbers:
            del self.expected_sequence_numbers[client_id]
            
        if client_id in self.out_of_order_buffers:
            del self.out_of_order_buffers[client_id]
            
        if client_id in self.delivered_messages:
            del self.delivered_messages[client_id]
            
        if client_id in self.connection_monitors:
            del self.connection_monitors[client_id]
            
        # Clean up any pending chunks for this client
        to_remove = []
        for chunk_id, buffer in self.chunk_buffers.items():
            if buffer.get('client_id') == client_id:
                to_remove.append(chunk_id)
                
        for chunk_id in to_remove:
            del self.chunk_buffers[chunk_id]
            
        # Clean up retry map entries for this client
        to_remove_retries = []
        for message_id, retry_info in self.message_retry_map.items():
            if retry_info.get('client_id') == client_id:
                to_remove_retries.append(message_id)
                
        for message_id in to_remove_retries:
            del self.message_retry_map[message_id]
            
        logger.info(f"[EventBridge] Cleaned up resources for client: {client_id}")
        
    def _generate_message_id(self) -> str:
        """Generate unique message ID"""
        return f"msg_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        
    def broadcast_event(self, event_data: dict, exclude_client: str = None, require_ack: bool = False):
        """
        Broadcast event to all connected clients
        
        Args:
            event_data: Event data to broadcast
            exclude_client: Client ID to exclude from broadcast
            require_ack: Whether to require acknowledgment
        """
        for client_id in self.data_channels:
            if exclude_client and client_id == exclude_client:
                continue
            asyncio.create_task(self.send_event(client_id, event_data, require_ack))
            
    def get_connected_clients(self) -> list:
        """Get list of connected client IDs"""
        return list(self.data_channels.keys())
        
    def is_client_connected(self, client_id: str) -> bool:
        """Check if client is connected"""
        if client_id not in self.data_channels:
            return False
            
        channel = self.data_channels[client_id]
        return hasattr(channel, 'readyState') and channel.readyState == 'open'
        
    def get_statistics(self) -> dict:
        """Get event bridge statistics"""
        return {
            **self.stats,
            'connected_clients': len(self.data_channels),
            'active_sessions': len(self.session_managers),
            'queued_messages': sum(len(queue) for queue in self.message_queue.values()),
            'pending_acks': len(self.pending_acks),
            'active_chunk_buffers': len(self.chunk_buffers)
        }
        
    def get_client_status(self, client_id: str) -> dict:
        """
        Get status for specific client
        
        Args:
            client_id: Client identifier
            
        Returns:
            Dictionary with client status information
        """
        return {
            'is_connected': self.is_client_connected(client_id),
            'has_session_manager': client_id in self.session_managers,
            'queued_messages': len(self.message_queue.get(client_id, [])),
            'channel_state': getattr(self.data_channels.get(client_id), 'readyState', 'not_found')
        }
        
    async def _handle_s2s_event_with_ordering(self, client_id: str, message_data: dict):
        """
        Handle S2S event with ordered delivery guarantees
        
        Args:
            client_id: Client identifier
            message_data: S2S event message data
        """
        # Check for duplicate messages
        message_id = message_data.get('id')
        if message_id and message_id in self.delivered_messages[client_id]:
            logger.debug(f"[EventBridge] Duplicate message detected from {client_id}, ignoring: {message_id}")
            self.stats['duplicate_messages'] += 1
            
            # Still send ACK if required
            if message_data.get('requireAck'):
                await self._send_acknowledgment(client_id, message_id)
            return
            
        # Handle ordered delivery
        sequence_number = message_data.get('sequenceNumber')
        if sequence_number is not None:
            if not await self._handle_ordered_message(client_id, message_data, sequence_number):
                return  # Message was buffered for later processing
                
        # Mark message as delivered
        if message_id:
            self.delivered_messages[client_id].add(message_id)
            
            # Limit the size of delivered messages set
            if len(self.delivered_messages[client_id]) > 1000:
                oldest_messages = list(self.delivered_messages[client_id])[:500]
                for old_id in oldest_messages:
                    self.delivered_messages[client_id].discard(old_id)
                    
        # Process the S2S event
        await self._handle_s2s_event(client_id, message_data)
        
    async def _handle_ordered_message(self, client_id: str, message_data: dict, sequence_number: int) -> bool:
        """
        Handle ordered message delivery
        
        Args:
            client_id: Client identifier
            message_data: Message data
            sequence_number: Message sequence number
            
        Returns:
            True if message should be processed now, False if buffered
        """
        expected_seq = self.expected_sequence_numbers[client_id]
        
        if sequence_number == expected_seq:
            # Message is in order, process it
            self.expected_sequence_numbers[client_id] += 1
            
            # Check if we can process any buffered out-of-order messages
            await self._process_buffered_messages(client_id)
            
            return True  # Process this message
            
        elif sequence_number > expected_seq:
            # Message is out of order, buffer it
            logger.debug(f"[EventBridge] Out-of-order message buffered for {client_id}: expected {expected_seq}, got {sequence_number}")
            self.out_of_order_buffers[client_id][sequence_number] = message_data
            self.stats['out_of_order_messages'] += 1
            
            # Send ACK if required (even for buffered messages)
            if message_data.get('requireAck'):
                await self._send_acknowledgment(client_id, message_data.get('id'))
                
            return False  # Don't process this message yet
            
        else:
            # Message is older than expected (duplicate or very late)
            logger.debug(f"[EventBridge] Old message ignored for {client_id}: expected {expected_seq}, got {sequence_number}")
            self.stats['duplicate_messages'] += 1
            
            # Send ACK if required
            if message_data.get('requireAck'):
                await self._send_acknowledgment(client_id, message_data.get('id'))
                
            return False  # Don't process this message
            
    async def _process_buffered_messages(self, client_id: str):
        """
        Process buffered out-of-order messages for a client
        
        Args:
            client_id: Client identifier
        """
        buffer = self.out_of_order_buffers[client_id]
        expected_seq = self.expected_sequence_numbers[client_id]
        
        while expected_seq in buffer:
            message_data = buffer.pop(expected_seq)
            
            logger.debug(f"[EventBridge] Processing buffered message for {client_id} with sequence {expected_seq}")
            
            # Mark as delivered and process
            message_id = message_data.get('id')
            if message_id:
                self.delivered_messages[client_id].add(message_id)
                
            await self._handle_s2s_event(client_id, message_data)
            
            expected_seq += 1
            self.expected_sequence_numbers[client_id] = expected_seq
            
    async def _handle_heartbeat(self, client_id: str, message_data: dict):
        """
        Handle heartbeat message
        
        Args:
            client_id: Client identifier
            message_data: Heartbeat message data
        """
        logger.debug(f"[EventBridge] Received heartbeat from {client_id}")
        
        # Send heartbeat response
        response = {
            'id': self._generate_message_id(),
            'type': 'HEARTBEAT',
            'timestamp': int(time.time() * 1000),
            'responseToId': message_data.get('id')
        }
        
        try:
            channel = self.data_channels[client_id]
            channel.send(json.dumps(response))
            logger.debug(f"[EventBridge] Sent heartbeat response to {client_id}")
        except Exception as e:
            logger.error(f"[EventBridge] Error sending heartbeat response to {client_id}: {e}")
            
    def _start_heartbeat_monitoring(self, client_id: str):
        """
        Start heartbeat monitoring for a client
        
        Args:
            client_id: Client identifier
        """
        async def monitor_heartbeat():
            while client_id in self.data_channels:
                try:
                    await asyncio.sleep(30)  # Check every 30 seconds
                    
                    if client_id not in self.connection_monitors:
                        break
                        
                    monitor = self.connection_monitors[client_id]
                    time_since_activity = time.time() - monitor['last_activity']
                    
                    if time_since_activity > 120:  # 120 seconds timeout (2x heartbeat interval)
                        logger.warning(f"[EventBridge] Heartbeat timeout for {client_id} (no activity for {time_since_activity:.1f}s)")
                        monitor['is_healthy'] = False
                        
                        if self.on_error:
                            self.on_error(client_id, Exception("Heartbeat timeout"))
                            
                        break
                        
                except Exception as e:
                    logger.error(f"[EventBridge] Error in heartbeat monitoring for {client_id}: {e}")
                    break
                    
        # Start the monitoring task
        task = asyncio.create_task(monitor_heartbeat())
        self.connection_monitors[client_id]['heartbeat_task'] = task
        
    def _handle_client_disconnection(self, client_id: str):
        """
        Handle client disconnection with reliability cleanup
        
        Args:
            client_id: Client identifier
        """
        logger.info(f"[EventBridge] Handling disconnection for {client_id}")
        
        # Cancel heartbeat monitoring
        if client_id in self.connection_monitors:
            task = self.connection_monitors[client_id].get('heartbeat_task')
            if task and not task.done():
                task.cancel()
                
        # Move pending messages to retry queue if applicable
        if client_id in self.message_queue:
            queued_count = len(self.message_queue[client_id])
            if queued_count > 0:
                logger.info(f"[EventBridge] {queued_count} messages were queued for disconnected client {client_id}")
                
        self._cleanup_client(client_id)
        
    def _start_background_tasks(self):
        """Start background maintenance tasks"""
        async def retry_failed_messages():
            while True:
                try:
                    await asyncio.sleep(10)  # Check every 10 seconds
                    await self._retry_failed_messages()
                except Exception as e:
                    logger.error(f"[EventBridge] Error in retry task: {e}")
                    
        asyncio.create_task(retry_failed_messages())
        
    async def _retry_failed_messages(self):
        """Retry failed messages that are eligible for retry"""
        current_time = time.time()
        
        for message_id, retry_info in list(self.message_retry_map.items()):
            time_since_attempt = current_time - retry_info.get('last_attempt', 0)
            retry_count = retry_info.get('retry_count', 0)
            
            should_retry = (
                time_since_attempt > self.retry_delay * (2 ** retry_count) and
                retry_count < self.max_retries
            )
            
            if should_retry:
                client_id = retry_info.get('client_id')
                message = retry_info.get('message')
                require_ack = retry_info.get('require_ack', False)
                
                if client_id and message and self.is_client_connected(client_id):
                    try:
                        logger.info(f"[EventBridge] Retrying failed message: {message_id}")
                        await self._send_message(client_id, message, require_ack)
                        
                        # Update retry info
                        retry_info['retry_count'] += 1
                        retry_info['last_attempt'] = current_time
                        self.stats['messages_retried'] += 1
                        
                    except Exception as e:
                        logger.error(f"[EventBridge] Error retrying message {message_id}: {e}")
                        
            elif retry_count >= self.max_retries:
                logger.error(f"[EventBridge] Message exceeded max retries, dropping: {message_id}")
                del self.message_retry_map[message_id]
                self.stats['messages_dropped'] += 1
                
    async def send_event_with_retry(self, client_id: str, event_data: dict, require_ack: bool = False):
        """
        Send event with retry mechanism
        
        Args:
            client_id: Target client identifier
            event_data: Event data to send
            require_ack: Whether to require acknowledgment
        """
        message = {
            'id': self._generate_message_id(),
            'type': 'S2S_RESPONSE',
            'timestamp': int(time.time() * 1000),
            'sequenceNumber': self._get_next_sequence_number(client_id),
            'requireAck': require_ack,
            'event': event_data
        }
        
        try:
            await self._send_message_with_retry(client_id, message, require_ack)
            return True
        except Exception as e:
            logger.error(f"[EventBridge] Failed to send event to {client_id} after retries: {e}")
            return False
            
    async def _send_message_with_retry(self, client_id: str, message: dict, require_ack: bool = False):
        """
        Send message with retry mechanism
        
        Args:
            client_id: Target client identifier
            message: Message to send
            require_ack: Whether to require acknowledgment
        """
        message_id = message.get('id')
        retry_count = 0
        
        while retry_count <= self.max_retries:
            try:
                await self._send_message(client_id, message, require_ack)
                
                # Remove from retry map if successful
                if message_id in self.message_retry_map:
                    del self.message_retry_map[message_id]
                    
                return
                
            except Exception as e:
                retry_count += 1
                self.stats['messages_retried'] += 1
                
                if retry_count > self.max_retries:
                    self.stats['messages_dropped'] += 1
                    if message_id in self.message_retry_map:
                        del self.message_retry_map[message_id]
                    raise Exception(f"Message failed after {self.max_retries} retries: {e}")
                    
                logger.warning(f"[EventBridge] Message send failed (attempt {retry_count}/{self.max_retries}) for {client_id}: {e}")
                
                # Store retry information
                self.message_retry_map[message_id] = {
                    'client_id': client_id,
                    'message': message,
                    'require_ack': require_ack,
                    'retry_count': retry_count,
                    'last_attempt': time.time()
                }
                
                # Wait before retry with exponential backoff
                delay = self.retry_delay * (2 ** (retry_count - 1))
                await asyncio.sleep(delay)
                
                # Check if client is still connected
                if not self.is_client_connected(client_id):
                    raise Exception("Client disconnected during retry")
                    
    def _get_next_sequence_number(self, client_id: str) -> int:
        """
        Get next sequence number for a client
        
        Args:
            client_id: Client identifier
            
        Returns:
            Next sequence number
        """
        if client_id not in self.sequence_numbers:
            self.sequence_numbers[client_id] = 0
            
        self.sequence_numbers[client_id] += 1
        return self.sequence_numbers[client_id]
        
    def get_reliability_status(self, client_id: str) -> dict:
        """
        Get reliability status for a client
        
        Args:
            client_id: Client identifier
            
        Returns:
            Dictionary with reliability status
        """
        if client_id not in self.connection_monitors:
            return {'error': 'Client not found'}
            
        monitor = self.connection_monitors[client_id]
        total_messages = self.stats['messages_sent'] + self.stats['messages_received']
        
        return {
            'is_healthy': monitor['is_healthy'],
            'time_since_last_activity': time.time() - monitor['last_activity'],
            'sequence_number': self.sequence_numbers.get(client_id, 0),
            'expected_sequence': self.expected_sequence_numbers.get(client_id, 0),
            'out_of_order_buffer_size': len(self.out_of_order_buffers.get(client_id, {})),
            'delivered_messages_count': len(self.delivered_messages.get(client_id, set())),
            'reliability_score': f"{((total_messages - self.stats['messages_dropped']) / max(total_messages, 1) * 100):.2f}%" if total_messages > 0 else 'N/A',
            'ordering_efficiency': f"{((self.stats['messages_received'] - self.stats['out_of_order_messages']) / max(self.stats['messages_received'], 1) * 100):.2f}%" if self.stats['messages_received'] > 0 else '100%',
            'duplicate_rate': f"{(self.stats['duplicate_messages'] / max(self.stats['messages_received'], 1) * 100):.2f}%" if self.stats['messages_received'] > 0 else '0%'
        }

    async def cleanup(self):
        """Clean up all resources"""
        logger.info("[EventBridge] Cleaning up all resources...")
        
        # Cancel all heartbeat monitoring tasks
        for client_id, monitor in self.connection_monitors.items():
            task = monitor.get('heartbeat_task')
            if task and not task.done():
                task.cancel()
        
        # Clean up all clients
        for client_id in list(self.data_channels.keys()):
            self._cleanup_client(client_id)
            
        # Clear remaining data
        self.pending_acks.clear()
        self.chunk_buffers.clear()
        self.sequence_numbers.clear()
        self.expected_sequence_numbers.clear()
        self.out_of_order_buffers.clear()
        self.delivered_messages.clear()
        self.message_retry_map.clear()
        self.connection_monitors.clear()
        
        logger.info("[EventBridge] Cleanup complete")