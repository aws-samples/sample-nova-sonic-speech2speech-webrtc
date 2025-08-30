"""
KVSWebRTCMaster - WebRTC Master implementation for Nova S2S
Handles KVS WebRTC master functionality, signaling channel management, and peer connection handling
"""

import asyncio
import json
import logging
import boto3
import websockets
import numpy as np
from typing import Dict, Optional, Callable
from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaBlackhole
from aiortc.sdp import candidate_from_sdp
from .AudioOutputTrack import AudioOutputTrack
from base64 import b64decode, b64encode
from botocore.auth import SigV4QueryAuth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from botocore.session import Session
import time
import uuid
from .AudioProcessor import AudioProcessor
from .EventBridge import EventBridge
from .PerformanceMonitor import PerformanceMonitor
from .MediaRecorder import MediaRecorder

logger = logging.getLogger(__name__)

class KVSWebRTCMaster:
    """KVS WebRTC Master implementation for Nova S2S"""
    
    def __init__(self, channel_name: str, region: str, credentials: Optional[Dict] = None):
        self.channel_name = channel_name
        self.region = region
        self.credentials = credentials
        
        # WebRTC components
        self.channel_arn = None
        self.endpoints = None
        self.ice_servers = None
        self.peer_connections: Dict[str, RTCPeerConnection] = {}
        self.websocket = None
        
        # Audio and event handling
        self.audio_processor = AudioProcessor()
        self.event_bridge = EventBridge()
        
        # 🔧 CRITICAL FIX: Set audio callback to connect processing chain
        self.audio_processor.set_audio_callback(self._handle_processed_audio)
        self.audio_processor.set_error_callback(self._handle_audio_error)
        
        # Media recording for testing
        self.media_recorder = MediaRecorder()
        
        # Performance monitoring
        self.performance_monitor = PerformanceMonitor()
        
        # Session management
        self.session_managers: Dict[str, any] = {}
        self.audio_output_tracks: Dict[str, AudioOutputTrack] = {}
        self.is_running = False
        
        # Callbacks
        self.on_client_connected = None
        self.on_client_disconnected = None
        self.on_audio_received = None
        self.on_event_received = None
        
        # Audio processing configuration
        self.audio_prompt_name = "default_prompt"
        self.audio_content_name = "audio_input"
        
        # Initialize AWS clients
        self._initialize_aws_clients()
        
    def _initialize_aws_clients(self):
        """Initialize AWS clients"""
        if self.credentials:
            self.kinesisvideo = boto3.client(
                'kinesisvideo',
                region_name=self.region,
                aws_access_key_id=self.credentials['accessKeyId'],
                aws_secret_access_key=self.credentials['secretAccessKey'],
                aws_session_token=self.credentials.get('sessionToken')
            )
        else:
            self.kinesisvideo = boto3.client('kinesisvideo', region_name=self.region)
            
    async def initialize(self):
        """Initialize the WebRTC master"""
        try:
            logger.info("🚀 [KVSWebRTCMaster] Initializing WebRTC master...")
            logger.debug(f"📡 [KVSWebRTCMaster] Channel: {self.channel_name}")
            logger.debug(f"🌍 [KVSWebRTCMaster] Region: {self.region}")
            
            # Get channel ARN
            logger.debug("🔍 [KVSWebRTCMaster] Getting channel ARN...")
            await self._get_channel_arn()
            
            # Get signaling endpoints
            logger.debug("🌐 [KVSWebRTCMaster] Getting signaling endpoints...")
            await self._get_signaling_endpoints()
            
            # Prepare ICE servers
            logger.debug("🧊 [KVSWebRTCMaster] Preparing ICE servers...")
            await self._prepare_ice_servers()
            
            # Set up event callbacks
            logger.debug("🔗 [KVSWebRTCMaster] Setting up event callbacks...")
            self.audio_processor.set_audio_callback(self._handle_processed_audio)
            self.audio_processor.set_error_callback(self._handle_audio_error)
            self.event_bridge.set_event_callback(self._handle_event_data)
            self.event_bridge.set_error_callback(self._handle_event_error)
            # Only set test audio callback if not in loopback mode
            if not hasattr(self, '_disable_test_audio') or not self._disable_test_audio:
                self.event_bridge.set_test_audio_callback(self._handle_test_audio_request)
                logger.debug("🧪 [KVSWebRTCMaster] Test audio callback enabled")
            else:
                logger.debug("🔄 [KVSWebRTCMaster] Test audio callback DISABLED (loopback mode)")
            
            # Set up performance monitoring
            logger.debug("📊 [KVSWebRTCMaster] Setting up performance monitoring...")
            self.performance_monitor.set_components(
                kvs_master=self,
                audio_processor=self.audio_processor,
                event_bridge=self.event_bridge
            )
            
            logger.info("✅ [KVSWebRTCMaster] WebRTC master initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ [KVSWebRTCMaster] Error initializing: {e}")
            raise
            
    async def _get_channel_arn(self):
        """Get signaling channel ARN"""
        try:
            logger.debug(f"🔍 [KVSWebRTCMaster] Describing signaling channel: {self.channel_name}")
            response = self.kinesisvideo.describe_signaling_channel(
                ChannelName=self.channel_name
            )
            self.channel_arn = response['ChannelInfo']['ChannelARN']
            logger.debug(f"✅ [KVSWebRTCMaster] Channel ARN obtained: {self.channel_arn}")
            
        except Exception as e:
            logger.error(f"❌ [KVSWebRTCMaster] Error getting channel ARN: {e}")
            raise
            
    async def _get_signaling_endpoints(self):
        """Get signaling channel endpoints"""
        try:
            logger.debug("🌐 [KVSWebRTCMaster] Getting signaling channel endpoints...")
            response = self.kinesisvideo.get_signaling_channel_endpoint(
                ChannelARN=self.channel_arn,
                SingleMasterChannelEndpointConfiguration={
                    'Protocols': ['HTTPS', 'WSS'],
                    'Role': 'MASTER'
                }
            )
            
            self.endpoints = {}
            for endpoint in response['ResourceEndpointList']:
                self.endpoints[endpoint['Protocol']] = endpoint['ResourceEndpoint']
                logger.debug(f"📍 [KVSWebRTCMaster] {endpoint['Protocol']} endpoint: {endpoint['ResourceEndpoint']}")
                
            logger.debug(f"✅ [KVSWebRTCMaster] All endpoints obtained: {list(self.endpoints.keys())}")
            
        except Exception as e:
            logger.error(f"❌ [KVSWebRTCMaster] Error getting endpoints: {e}")
            raise
            
    async def _prepare_ice_servers(self):
        """Prepare ICE servers configuration"""
        try:
            logger.debug("🧊 [KVSWebRTCMaster] Preparing ICE servers configuration...")
            
            # Create signaling client for ICE server config
            logger.debug("🔧 [KVSWebRTCMaster] Creating signaling client for ICE config...")
            if self.credentials:
                signaling_client = boto3.client(
                    'kinesis-video-signaling',
                    endpoint_url=self.endpoints['HTTPS'],
                    region_name=self.region,
                    aws_access_key_id=self.credentials['accessKeyId'],
                    aws_secret_access_key=self.credentials['secretAccessKey'],
                    aws_session_token=self.credentials.get('sessionToken')
                )
            else:
                signaling_client = boto3.client(
                    'kinesis-video-signaling',
                    endpoint_url=self.endpoints['HTTPS'],
                    region_name=self.region
                )
                
            logger.debug("📡 [KVSWebRTCMaster] Getting ICE server configuration...")
            response = signaling_client.get_ice_server_config(
                ChannelARN=self.channel_arn,
                ClientId='MASTER'
            )
            
            # Build ICE servers list
            logger.debug("🏗️ [KVSWebRTCMaster] Building ICE servers list...")
            self.ice_servers = [
                RTCIceServer(urls=f'stun:stun.kinesisvideo.{self.region}.amazonaws.com:443')
            ]
            logger.debug(f"🎯 [KVSWebRTCMaster] Added STUN server: stun.kinesisvideo.{self.region}.amazonaws.com:443")
            
            for i, ice_server in enumerate(response['IceServerList']):
                self.ice_servers.append(RTCIceServer(
                    urls=ice_server['Uris'],
                    username=ice_server['Username'],
                    credential=ice_server['Password']
                ))
                logger.debug(f"🎯 [KVSWebRTCMaster] Added ICE server {i+1}: {ice_server['Uris']}")
                
            logger.debug(f"✅ [KVSWebRTCMaster] ICE servers configured: {len(self.ice_servers)} servers total")
            
        except Exception as e:
            logger.error(f"❌ [KVSWebRTCMaster] Error preparing ICE servers: {e}")
            raise
            
    def _create_wss_url(self):
        """Create WebSocket Secure URL for signaling"""
        try:
            if self.credentials:
                auth_credentials = Credentials(
                    access_key=self.credentials['accessKeyId'],
                    secret_key=self.credentials['secretAccessKey'],
                    token=self.credentials.get('sessionToken')
                )
            else:
                session = Session()
                auth_credentials = session.get_credentials()
                
            sig_v4 = SigV4QueryAuth(auth_credentials, 'kinesisvideo', self.region, 299)
            aws_request = AWSRequest(
                method='GET',
                url=self.endpoints['WSS'],
                params={
                    'X-Amz-ChannelARN': self.channel_arn,
                    'X-Amz-ClientId': 'MASTER'
                }
            )
            sig_v4.add_auth(aws_request)
            prepared_request = aws_request.prepare()
            
            return prepared_request.url
            
        except Exception as e:
            logger.error(f"[KVSWebRTCMaster] Error creating WSS URL: {e}")
            raise
            
    def _decode_message(self, message: str):
        """Decode signaling message"""
        try:
            logger.debug(f"🔍 [KVSWebRTCMaster] Decoding message: {message[:100]}...")
            data = json.loads(message)
            logger.debug(f"📋 [KVSWebRTCMaster] Message data keys: {list(data.keys())}")
            
            if 'messagePayload' in data:
                payload = json.loads(b64decode(data['messagePayload'].encode('ascii')).decode('ascii'))
                return data['messageType'], payload, data.get('senderClientId')
            else:
                logger.warning(f"⚠️ [KVSWebRTCMaster] Message missing messagePayload: {data}")
                return '', {}, ''
                
        except json.JSONDecodeError as e:
            logger.error(f"❌ [KVSWebRTCMaster] JSON decode error: {e}")
            logger.error(f"📄 [KVSWebRTCMaster] Raw message: {message}")
            return '', {}, ''
        except Exception as e:
            logger.error(f"❌ [KVSWebRTCMaster] Message decode error: {e}")
            logger.error(f"📄 [KVSWebRTCMaster] Raw message: {message}")
            return '', {}, ''
            
    def _encode_message(self, message_type: str, payload: any, client_id: str):
        """Encode signaling message (following KVS WebRTC protocol format)"""
        # Use payload.__dict__ exactly like official implementation for RTCSessionDescription
        if hasattr(payload, '__dict__'):
            # This handles RTCSessionDescription objects correctly
            payload_data = payload.__dict__
        else:
            payload_data = payload
            
        # Use exact format from official AWS Python implementation
        return json.dumps({
            'action': message_type,  # Official Python implementation uses 'action'
            'messagePayload': b64encode(json.dumps(payload_data).encode('ascii')).decode('ascii'),
            'recipientClientId': client_id,
        })
        
    async def _handle_sdp_offer(self, payload: dict, client_id: str):
        """Handle SDP offer from viewer (following official AWS Python pattern)"""
        try:
            logger.info(f"📥 [KVSWebRTCMaster] Handling SDP offer from {client_id}")
            logger.debug(f"📋 [KVSWebRTCMaster] SDP offer details - Type: {payload.get('type')}, SDP length: {len(payload.get('sdp', ''))}")
            
            # 1. Prepare ICE servers and create peer connection (EXACT official pattern)
            logger.debug(f"🔗 [KVSWebRTCMaster] Creating peer connection for {client_id}...")
            configuration = RTCConfiguration(iceServers=self.ice_servers)
            pc = RTCPeerConnection(configuration=configuration)
            self.peer_connections[client_id] = pc
            logger.debug(f"✅ [KVSWebRTCMaster] Peer connection created for {client_id}")
            
            # 2. Create data channel (EXACT official pattern)
            logger.debug(f"📨 [KVSWebRTCMaster] Creating data channel for {client_id}...")
            data_channel = pc.createDataChannel('kvsDataChannel')  # Use same name as official
            self.event_bridge.add_data_channel(client_id, data_channel)
            
            # 3. Set up peer connection event handlers BEFORE setting remote description (official pattern)
            logger.debug(f"🎛️ [KVSWebRTCMaster] Setting up peer connection handlers for {client_id}...")
            self._setup_peer_connection_handlers(pc, client_id)
            
            # 4. Add tracks BEFORE setting remote description (CRITICAL official pattern)
            logger.debug(f"🎵 [KVSWebRTCMaster] Adding audio output track for {client_id}...")
            
            # Create and add audio output track for Nova Sonic responses
            audio_output_track = AudioOutputTrack(client_id)
            self.audio_output_tracks[client_id] = audio_output_track
            pc.addTrack(audio_output_track)
            
            logger.debug(f"✅ [KVSWebRTCMaster] Added audio output track for {client_id}")
            
            # 5. Set remote description (EXACT official pattern)
            logger.debug(f"🔧 [KVSWebRTCMaster] Setting remote description for {client_id}...")
            await pc.setRemoteDescription(RTCSessionDescription(
                sdp=payload['sdp'],
                type=payload['type']
            ))
            logger.debug(f"✅ [KVSWebRTCMaster] Remote description set for {client_id}")
            
            # 6. Create and set local description (EXACT official pattern)
            logger.debug(f"📝 [KVSWebRTCMaster] Creating SDP answer for {client_id}...")
            await pc.setLocalDescription(await pc.createAnswer())  # Direct createAnswer() like official
            logger.debug(f"✅ [KVSWebRTCMaster] Local description set for {client_id}")
            
            # 7. Send SDP answer (EXACT official pattern)
            logger.debug(f"📤 [KVSWebRTCMaster] Sending SDP answer to {client_id}...")
            logger.debug(f"📋 [KVSWebRTCMaster] SDP answer details - Type: {pc.localDescription.type}, SDP length: {len(pc.localDescription.sdp)}")
            
            # Debug the RTCSessionDescription object structure
            logger.debug(f"🔍 [KVSWebRTCMaster] RTCSessionDescription __dict__: {pc.localDescription.__dict__}")
            logger.debug(f"🔍 [KVSWebRTCMaster] RTCSessionDescription attributes: type={pc.localDescription.type}, sdp_length={len(pc.localDescription.sdp)}")
            
            answer_message = self._encode_message('SDP_ANSWER', pc.localDescription, client_id)
            await self.websocket.send(answer_message)
            
            logger.debug(f"✅ [KVSWebRTCMaster] SDP answer sent successfully to {client_id}")
            
            # 8. Associate session manager AFTER successful SDP exchange
            if client_id in self.session_managers:
                logger.debug(f"🔗 [KVSWebRTCMaster] Associating session manager for {client_id}")
                self.event_bridge.set_session_manager(client_id, self.session_managers[client_id])
            
            # 9. Notify client connected
            if self.on_client_connected:
                logger.debug(f"🎉 [KVSWebRTCMaster] Notifying client connected: {client_id}")
                await self.on_client_connected(client_id)
                
        except Exception as e:
            logger.error(f"❌ [KVSWebRTCMaster] Error handling SDP offer from {client_id}: {e}")
            # Clean up on error
            if client_id in self.peer_connections:
                try:
                    self.peer_connections[client_id].close()
                    del self.peer_connections[client_id]
                except:
                    pass
            
    def _setup_peer_connection_handlers(self, pc: RTCPeerConnection, client_id: str):
        """Set up peer connection event handlers"""
        
        @pc.on('connectionstatechange')
        async def on_connectionstatechange():
            state = pc.connectionState
            logger.debug(f"🔄 [KVSWebRTCMaster] {client_id} connection state changed: {state}")
            
            if state == 'connected':
                logger.info(f"🎉 [KVSWebRTCMaster] Client {client_id} peer connection CONNECTED successfully!")
            elif state in ['disconnected', 'failed', 'closed']:
                logger.warning(f"⚠️ [KVSWebRTCMaster] Client {client_id} peer connection {state.upper()}")
                await self._handle_client_disconnection(client_id)
                
        @pc.on('iceconnectionstatechange')
        async def on_iceconnectionstatechange():
            ice_state = pc.iceConnectionState
            logger.debug(f"🧊 [KVSWebRTCMaster] {client_id} ICE connection state: {ice_state}")
            
            if ice_state == 'connected':
                logger.info(f"✅ [KVSWebRTCMaster] {client_id} ICE connection established!")
            elif ice_state == 'failed':
                logger.error(f"❌ [KVSWebRTCMaster] {client_id} ICE connection FAILED!")
            
        @pc.on('track')
        def on_track(track):
            logger.info(f"🎥🎤 [KVSWebRTCMaster] Received {track.kind} track from {client_id}")
            
            if track.kind == 'audio':
                # Start media recording for test clients
                if client_id.startswith('test-viewer-'):
                    logger.info(f"🎬 [KVSWebRTCMaster] Starting media recording for test client {client_id}")
                    self.media_recorder.start_recording(client_id, duration_seconds=10.0)
                    asyncio.create_task(self._handle_media_recording_track(client_id, track, 'audio'))
                else:
                    # Check if there's a custom audio handler (for S2S mode)
                    if self.on_audio_received:
                        logger.info(f"🔄 [KVSWebRTCMaster] Using custom audio handler for {client_id}")
                        asyncio.create_task(self.on_audio_received(client_id, track))
                        # Note: Custom handler is responsible for consuming the track
                    else:
                        # Default: Add audio track to processor for real-time processing
                        logger.info(f"🤖 [KVSWebRTCMaster] Using default audio processor for {client_id}")
                        asyncio.create_task(self.audio_processor.add_audio_track(client_id, track))
                        
                        # Use MediaBlackhole to consume the track (required by aiortc)
                        MediaBlackhole().addTrack(track)
                
            elif track.kind == 'video':
                # Handle video track for test clients
                if client_id.startswith('test-viewer-'):
                    logger.info(f"📹 [KVSWebRTCMaster] Recording video track for test client {client_id}")
                    asyncio.create_task(self._handle_media_recording_track(client_id, track, 'video'))
                else:
                    logger.info(f"📹 [KVSWebRTCMaster] Video track received from {client_id} (not recording)")
                    # Use MediaBlackhole to consume the track (required by aiortc)
                    MediaBlackhole().addTrack(track)
                
        @pc.on('datachannel')
        def on_datachannel(channel):
            logger.debug(f"[KVSWebRTCMaster] Data channel received from {client_id}: {channel.label}")
            self.event_bridge.add_data_channel(client_id, channel)
            
            # Associate session manager with client if available
            if client_id in self.session_managers:
                self.event_bridge.set_session_manager(client_id, self.session_managers[client_id])
            
    async def _handle_ice_candidate(self, payload: dict, client_id: str):
        """Handle ICE candidate from viewer"""
        try:
            if client_id in self.peer_connections:
                candidate = candidate_from_sdp(payload['candidate'])
                candidate.sdpMid = payload['sdpMid']
                candidate.sdpMLineIndex = payload['sdpMLineIndex']
                await self.peer_connections[client_id].addIceCandidate(candidate)
                logger.debug(f"[KVSWebRTCMaster] Added ICE candidate for {client_id}")
                
        except Exception as e:
            logger.error(f"[KVSWebRTCMaster] Error handling ICE candidate: {e}")
            
    async def _handle_client_disconnection(self, client_id: str):
        """Handle client disconnection"""
        logger.info(f"[KVSWebRTCMaster] Handling disconnection for {client_id}")
        
        # Remove audio track from processor (or custom handler)
        if hasattr(self, '_loopback_processor') and self._loopback_processor:
            # Loopback mode cleanup
            await self._loopback_processor.remove_audio_track(client_id)
        else:
            # Default processor cleanup
            await self.audio_processor.remove_audio_track(client_id)
        
        # Clean up peer connection
        if client_id in self.peer_connections:
            pc = self.peer_connections[client_id]
            await pc.close()
            del self.peer_connections[client_id]
            
        # Clean up session manager
        if client_id in self.session_managers:
            session_manager = self.session_managers[client_id]
            await session_manager.close()
            del self.session_managers[client_id]
            
        # Clean up audio output track
        if client_id in self.audio_output_tracks:
            audio_track = self.audio_output_tracks[client_id]
            audio_track.stop()
            del self.audio_output_tracks[client_id]
            
        # Clean up media recording for test clients
        if client_id.startswith('test-viewer-'):
            logger.info(f"🎬 [KVSWebRTCMaster] Stopping media recording for test client {client_id}")
            await self.media_recorder.stop_recording(client_id)
            self.media_recorder.cleanup_client(client_id)
        
        # Remove data channel from event bridge
        self.event_bridge.remove_data_channel(client_id)
            
        # Notify disconnection
        if self.on_client_disconnected:
            self.on_client_disconnected(client_id)
            
    async def _handle_processed_audio(self, client_id: str, audio_packet: dict):
        """
        Handle processed audio data from AudioProcessor
        
        Args:
            client_id: Client identifier
            audio_packet: Processed audio data packet with metadata
        """
        try:
            logger.debug(f"🎵 [KVSWebRTCMaster] Received processed audio from {client_id}: {audio_packet['size_bytes']} bytes")
            
            # Get session manager for this client
            session_manager = self.session_managers.get(client_id)
            if not session_manager:
                logger.warning(f"[KVSWebRTCMaster] No session manager found for {client_id}")
                return
                
            # Extract audio data
            base64_audio = audio_packet['audioData']
            
            # Get prompt and content names from session manager (set by client events)
            session_prompt = getattr(session_manager, 'prompt_name', None)
            session_content = getattr(session_manager, 'audio_content_name', None)
            
            # Debug: Show what we got from session manager
            logger.debug(f"🔍 [KVSWebRTCMaster] Session manager values for {client_id}: prompt_name='{session_prompt}', audio_content_name='{session_content}'")
            
            # Check if session is properly initialized
            if session_prompt is None and session_content is None:
                logger.warning(f"⚠️ [KVSWebRTCMaster] Session not initialized for {client_id} - audio may be processed before session setup events")
            
            # Use fallback values if session manager values are None
            prompt_name = session_prompt if session_prompt is not None else self.audio_prompt_name
            content_name = session_content if session_content is not None else self.audio_content_name
            
            # Log if we're using fallback values (indicates session setup issue)
            if session_prompt is None or session_content is None:
                logger.warning(f"⚠️ [KVSWebRTCMaster] Using fallback names for {client_id}: prompt='{prompt_name}', content='{content_name}' (session manager values are None)")
            
            logger.debug(f"📨 [KVSWebRTCMaster] Processing audio for S2S: prompt='{prompt_name}', content='{content_name}', data_size={len(base64_audio)} chars")
            
            # Send audio to S2sSessionManager
            session_manager.add_audio_chunk(
                prompt_name=prompt_name,
                content_name=content_name,
                audio_data=base64_audio
            )
            
            # Notify callback if set
            if self.on_audio_received:
                self.on_audio_received(client_id, audio_packet)
                
        except Exception as e:
            logger.error(f"[KVSWebRTCMaster] Error handling processed audio for {client_id}: {e}")
            
    def _handle_audio_error(self, client_id: str, error: Exception):
        """
        Handle audio processing errors
        
        Args:
            client_id: Client identifier
            error: Audio processing error
        """
        logger.error(f"[KVSWebRTCMaster] Audio processing error for {client_id}: {error}")
        
        # Optionally notify client of error via data channel
        error_event = {
            'type': 'AUDIO_ERROR',
            'message': str(error),
            'timestamp': int(time.time() * 1000)
        }
        self.event_bridge.send_event(client_id, error_event)
            
    def _handle_event_data(self, client_id: str, event_data: dict):
        """Handle received event data"""
        if self.on_event_received:
            self.on_event_received(client_id, event_data)
            
    def _handle_event_error(self, client_id: str, error: Exception):
        """Handle event processing errors"""
        logger.error(f"[KVSWebRTCMaster] Event processing error for {client_id}: {error}")
        
        # Optionally notify client of error via data channel
        error_event = {
            'type': 'EVENT_ERROR',
            'message': str(error),
            'timestamp': int(time.time() * 1000)
        }
        asyncio.create_task(self.event_bridge.send_event(client_id, error_event))
        
    def _handle_test_audio_request(self, client_id: str):
        """Handle test audio playback request"""
        try:
            logger.info(f"🧪 [KVSWebRTCMaster] Test audio playback requested for {client_id}")
            
            # Get audio output track for this client
            if client_id in self.audio_output_tracks:
                audio_track = self.audio_output_tracks[client_id]
                
                # Load and queue test audio
                import os
                test_audio_dir = os.path.join(os.path.dirname(__file__), "..", "server_test_audio")
                test_audio_file = os.path.join(test_audio_dir, "test_scale.wav")
                
                if os.path.exists(test_audio_file):
                    logger.debug(f"🧪 [KVSWebRTCMaster] Loading test audio file: {test_audio_file}")
                    audio_track.queue_test_audio(test_audio_file)
                    logger.debug(f"🧪 [KVSWebRTCMaster] Test audio queued for playback to {client_id}")
                else:
                    logger.error(f"🧪 [KVSWebRTCMaster] Test audio file not found: {test_audio_file}")
                    
                    # Try PCM file as fallback
                    test_pcm_file = os.path.join(test_audio_dir, "test_scale.pcm")
                    if os.path.exists(test_pcm_file):
                        logger.debug(f"🧪 [KVSWebRTCMaster] Loading fallback PCM file: {test_pcm_file}")
                        audio_track.queue_test_audio(test_pcm_file)
                        logger.debug(f"🧪 [KVSWebRTCMaster] Test PCM audio queued for playback to {client_id}")
                    else:
                        logger.error(f"🧪 [KVSWebRTCMaster] No test audio files found in {test_audio_dir}")
            else:
                logger.error(f"🧪 [KVSWebRTCMaster] No audio output track found for {client_id}")
                
        except Exception as e:
            logger.error(f"🧪 [KVSWebRTCMaster] Error handling test audio request for {client_id}: {e}")
            import traceback
            logger.error(f"🧪 [KVSWebRTCMaster] Traceback: {traceback.format_exc()}")
            
    async def start(self):
        """Start the WebRTC master"""
        try:
            self.is_running = True
            logger.info("🚀 [KVSWebRTCMaster] Starting WebRTC master...")
            
            # Start audio processing
            logger.info("🎵 [KVSWebRTCMaster] Starting audio processing...")
            self.audio_processor.start_processing()
            
            # Start performance monitoring
            logger.info("📊 [KVSWebRTCMaster] Starting performance monitoring...")
            await self.performance_monitor.start_monitoring(interval=1.0)
            
            # Connect to signaling channel
            logger.info("📡 [KVSWebRTCMaster] Connecting to signaling channel...")
            await self._connect_signaling()
            
        except Exception as e:
            logger.error(f"❌ [KVSWebRTCMaster] Error starting: {e}")
            self.is_running = False
            raise
            
    async def _connect_signaling(self):
        """Connect to signaling channel and handle messages"""
        wss_url = self._create_wss_url()
        logger.debug(f"🔗 [KVSWebRTCMaster] Connecting to WebSocket: {wss_url[:50]}...")
        
        while self.is_running:
            try:
                logger.info("🔌 [KVSWebRTCMaster] Establishing WebSocket connection...")
                async with websockets.connect(wss_url) as websocket:
                    self.websocket = websocket
                    logger.info("✅ [KVSWebRTCMaster] Connected to signaling channel successfully!")
                    logger.info("👂 [KVSWebRTCMaster] Listening for signaling messages...")
                    
                    async for message in websocket:
                        if not self.is_running:
                            logger.info("🛑 [KVSWebRTCMaster] Stopping message processing...")
                            break
                            
                        # Skip empty messages
                        if not message or not message.strip():
                            logger.debug("📭 [KVSWebRTCMaster] Skipping empty message")
                            continue
                            
                        logger.debug(f"📨 [KVSWebRTCMaster] Received signaling message: {len(message)} bytes")
                        msg_type, payload, client_id = self._decode_message(message)
                        
                        # Skip messages that couldn't be decoded
                        if not msg_type:
                            logger.debug("📭 [KVSWebRTCMaster] Skipping message with no type")
                            continue
                            
                        logger.debug(f"📥 [KVSWebRTCMaster] Decoded message - Type: {msg_type}, Client: {client_id}")
                        
                        if msg_type == 'SDP_OFFER':
                            logger.info(f"📤 [KVSWebRTCMaster] Processing SDP offer from {client_id}...")
                            await self._handle_sdp_offer(payload, client_id)
                        elif msg_type == 'ICE_CANDIDATE':
                            logger.debug(f"🧊 [KVSWebRTCMaster] Processing ICE candidate from {client_id}...")
                            await self._handle_ice_candidate(payload, client_id)
                        else:
                            logger.warning(f"❓ [KVSWebRTCMaster] Unknown message type: {msg_type}")
                            
            except websockets.ConnectionClosed:
                if self.is_running:
                    logger.warning("⚠️ [KVSWebRTCMaster] Signaling connection closed, reconnecting...")
                    wss_url = self._create_wss_url()
                    await asyncio.sleep(1)  # Brief delay before reconnecting
                else:
                    logger.info("✅ [KVSWebRTCMaster] Signaling connection closed as expected")
                    break
            except Exception as e:
                logger.error(f"❌ [KVSWebRTCMaster] Signaling error: {e}")
                if self.is_running:
                    logger.info("🔄 [KVSWebRTCMaster] Retrying connection in 5 seconds...")
                    await asyncio.sleep(5)  # Longer delay on error
                    
    async def stop(self):
        """Stop the WebRTC master"""
        logger.info("[KVSWebRTCMaster] Stopping WebRTC master...")
        
        self.is_running = False
        
        # Stop audio processing
        self.audio_processor.stop_processing()
        
        # Close all peer connections
        for client_id in list(self.peer_connections.keys()):
            await self._handle_client_disconnection(client_id)
            
        # Close websocket
        if self.websocket:
            await self.websocket.close()
            
        logger.info("[KVSWebRTCMaster] WebRTC master stopped")
        
    def force_audio_merge(self):
        """Force merge any buffered audio data"""
        try:
            merge_status = self.audio_processor.get_merge_status()
            logger.info(f"[KVSWebRTCMaster] Current audio merge status: {merge_status}")
            
            if merge_status['original_chunks'] > 0 or merge_status['processed_chunks'] > 0:
                logger.info("[KVSWebRTCMaster] Forcing audio merge...")
                self.audio_processor.force_merge_audio()
                return True
            else:
                logger.info("[KVSWebRTCMaster] No audio data to merge")
                return False
        except Exception as e:
            logger.error(f"[KVSWebRTCMaster] Error forcing audio merge: {e}")
            return False
            
    def get_audio_merge_status(self) -> dict:
        """Get current audio merge buffer status"""
        try:
            return self.audio_processor.get_merge_status()
        except Exception as e:
            logger.error(f"[KVSWebRTCMaster] Error getting merge status: {e}")
            return {}
        
    async def setup_session_manager_integration(self, client_id: str, session_manager):
        """
        Set up integration between session manager and event bridge
        
        Args:
            client_id: Client identifier
            session_manager: S2sSessionManager instance
        """
        # Set session manager
        self.set_session_manager(client_id, session_manager)
        
        # Start task to forward session manager responses to client
        asyncio.create_task(self._forward_session_responses(client_id, session_manager))
        
        logger.info(f"[KVSWebRTCMaster] Set up session manager integration for {client_id}")
        
    async def _forward_session_responses(self, client_id: str, session_manager):
        """
        Forward S2S session manager responses to client via data channel
        
        Args:
            client_id: Client identifier
            session_manager: S2sSessionManager instance
        """
        try:
            while self.is_running and self.is_client_connected(client_id):
                try:
                    # Get response from session manager output queue
                    response = await asyncio.wait_for(session_manager.output_queue.get(), timeout=1.0)
                    
                    # Forward response to client via event bridge
                    await self.event_bridge.send_event(client_id, response)
                    
                    logger.debug(f"[KVSWebRTCMaster] Forwarded S2S response to {client_id}")
                    
                except asyncio.TimeoutError:
                    # Continue checking for responses
                    continue
                except Exception as e:
                    logger.error(f"[KVSWebRTCMaster] Error forwarding response to {client_id}: {e}")
                    break
                    
        except Exception as e:
            logger.error(f"[KVSWebRTCMaster] Error in response forwarding task for {client_id}: {e}")
        finally:
            logger.info(f"[KVSWebRTCMaster] Stopped forwarding responses for {client_id}")
        
    async def send_event_to_client(self, client_id: str, event_data: dict, require_ack: bool = False):
        """Send event to specific client"""
        return await self.event_bridge.send_event(client_id, event_data, require_ack)
        
    def broadcast_event(self, event_data: dict, exclude_client: str = None, require_ack: bool = False):
        """Broadcast event to all clients"""
        self.event_bridge.broadcast_event(event_data, exclude_client, require_ack)
        
    def get_connected_clients(self):
        """Get list of connected client IDs"""
        return list(self.peer_connections.keys())
        
    def is_client_connected(self, client_id: str):
        """Check if client is connected"""
        return (client_id in self.peer_connections and 
                self.peer_connections[client_id].connectionState == 'connected')
        
    def set_session_manager(self, client_id: str, session_manager):
        """Associate session manager with client"""
        logger.info(f"🔗 [KVSWebRTCMaster] SETTING SESSION MANAGER - Client: {client_id}")
        logger.info(f"🔗 [KVSWebRTCMaster] Session manager type: {type(session_manager).__name__}")
        logger.info(f"🔗 [KVSWebRTCMaster] Session manager active: {getattr(session_manager, 'is_active', 'unknown')}")
        logger.info(f"🔗 [KVSWebRTCMaster] Current session managers: {list(self.session_managers.keys())}")
        
        # Store in KVSWebRTCMaster
        self.session_managers[client_id] = session_manager
        logger.info(f"✅ [KVSWebRTCMaster] Session manager stored in KVSWebRTCMaster for {client_id}")
        
        # Also set in event bridge for direct event routing
        logger.info(f"🔗 [KVSWebRTCMaster] Setting session manager in EventBridge for {client_id}...")
        self.event_bridge.set_session_manager(client_id, session_manager)
        logger.info(f"✅ [KVSWebRTCMaster] Session manager association complete for {client_id}")
        
        # Verify both associations worked
        kvs_has_manager = client_id in self.session_managers
        bridge_has_manager = client_id in self.event_bridge.session_managers
        logger.info(f"🔍 [KVSWebRTCMaster] Association verification - KVS: {kvs_has_manager}, EventBridge: {bridge_has_manager}")
        
        if kvs_has_manager and bridge_has_manager:
            logger.info(f"✅ [KVSWebRTCMaster] SESSION MANAGER ASSOCIATION SUCCESS for {client_id}")
        else:
            logger.error(f"❌ [KVSWebRTCMaster] SESSION MANAGER ASSOCIATION FAILED for {client_id}!")
        
    def get_session_manager(self, client_id: str):
        """Get session manager for client"""
        return self.session_managers.get(client_id)
        
    async def send_audio_to_client(self, client_id: str, base64_audio_data: str, sample_rate: int = 24000):
        """
        Send Nova Sonic audio response to client via WebRTC media channel
        
        Args:
            client_id: Target client identifier
            base64_audio_data: Base64 encoded audio from Nova Sonic
            sample_rate: Audio sample rate
        """
        try:
            # Get audio output track for this client
            audio_track = self.audio_output_tracks.get(client_id)
            if not audio_track:
                logger.warning(f"[KVSWebRTCMaster] No audio output track found for {client_id}")
                return
            
            # Queue audio data in the output track
            audio_track.queue_audio(base64_audio_data, sample_rate)
            
            logger.debug(f"🔊 [KVSWebRTCMaster] Queued audio for {client_id} via media channel: {len(base64_audio_data)} chars, {sample_rate}Hz")
            
        except Exception as e:
            logger.error(f"[KVSWebRTCMaster] Error sending audio to {client_id}: {e}")
    
    async def send_raw_audio_to_client(self, client_id: str, audio_data: np.ndarray, sample_rate: int):
        """
        Send raw audio data to client (for loopback mode)
        
        Args:
            client_id: Target client identifier
            audio_data: Raw audio data as numpy array (float32)
            sample_rate: Sample rate in Hz
        """
        try:
            # Get audio output track for this client
            audio_track = self.audio_output_tracks.get(client_id)
            if not audio_track:
                logger.warning(f"[KVSWebRTCMaster] No audio output track found for {client_id}")
                return
            
            # Use the new direct method - no base64 encoding needed!
            audio_track.queue_raw_audio(audio_data, sample_rate)
            
            logger.debug(f"🔄 [KVSWebRTCMaster] Sent raw audio to {client_id}: {len(audio_data)} samples, {sample_rate}Hz")
            
        except Exception as e:
            logger.error(f"[KVSWebRTCMaster] Error sending raw audio to {client_id}: {e}")
            
    def set_audio_config(self, prompt_name: str, content_name: str):
        """
        Set audio configuration for S2S integration
        
        Args:
            prompt_name: Prompt name for S2S events
            content_name: Content name for S2S events
        """
        self.audio_prompt_name = prompt_name
        self.audio_content_name = content_name
        logger.info(f"[KVSWebRTCMaster] Set audio config: prompt={prompt_name}, content={content_name}")
        
    def get_audio_stats(self) -> dict:
        """
        Get audio processing statistics
        
        Returns:
            Dictionary with audio processing statistics
        """
        return self.audio_processor.get_processing_stats()
        
    def get_client_audio_status(self, client_id: str) -> dict:
        """
        Get audio status for specific client
        
        Args:
            client_id: Client identifier
            
        Returns:
            Dictionary with client audio status
        """
        return {
            'is_active': self.audio_processor.is_client_active(client_id),
            'buffer_size': self.audio_processor.get_client_buffer_size(client_id),
            'is_connected': self.is_client_connected(client_id)
        }
        
    def get_event_bridge_stats(self) -> dict:
        """
        Get event bridge statistics
        
        Returns:
            Dictionary with event bridge statistics
        """
        return self.event_bridge.get_statistics()
        
    def get_client_event_status(self, client_id: str) -> dict:
        """
        Get event status for specific client
        
        Args:
            client_id: Client identifier
            
        Returns:
            Dictionary with client event status
        """
        return self.event_bridge.get_client_status(client_id)
        
    async def _handle_media_recording_track(self, client_id: str, track, track_type: str):
        """
        Handle media track for recording
        
        Args:
            client_id: Client identifier
            track: WebRTC media track
            track_type: 'audio' or 'video'
        """
        try:
            logger.info(f"🎬 [KVSWebRTCMaster] Starting {track_type} recording for {client_id}")
            
            # Create a task to continuously read frames from the track
            async def record_frames():
                try:
                    while True:
                        frame = await track.recv()
                        if track_type == 'audio':
                            await self.media_recorder.add_audio_frame(client_id, frame)
                        elif track_type == 'video':
                            await self.media_recorder.add_video_frame(client_id, frame)
                except Exception as e:
                    logger.info(f"🎬 [KVSWebRTCMaster] {track_type} recording ended for {client_id}: {e}")
            
            # Start the recording task
            asyncio.create_task(record_frames())
            logger.info(f"✅ [KVSWebRTCMaster] {track_type} recording task started for {client_id}")
                    
        except Exception as e:
            logger.error(f"❌ [KVSWebRTCMaster] Error in {track_type} recording for {client_id}: {e}")
            
    def get_media_recording_stats(self) -> dict:
        """
        Get media recording statistics
        
        Returns:
            Dictionary with media recording statistics
        """
        return self.media_recorder.get_stats()

    async def cleanup_all_resources(self):
        """Clean up all WebRTC and event resources"""
        logger.info("[KVSWebRTCMaster] Cleaning up all resources...")
        
        # Stop the master
        await self.stop()
        
        # Clean up event bridge
        await self.event_bridge.cleanup()
        
        logger.info("[KVSWebRTCMaster] All resources cleaned up")