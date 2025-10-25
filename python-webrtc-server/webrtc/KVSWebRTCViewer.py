"""
KVS WebRTC Viewer - WebRTC Viewer implementation for Kinesis Video Streams
Based on the reference kvsWebRTCClientViewer.py
"""

import asyncio
import boto3
import json
import logging
import websockets
from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
from aiortc.contrib.media import MediaPlayer, MediaRelay, MediaBlackhole
from aiortc.sdp import candidate_from_sdp
from base64 import b64decode, b64encode
from botocore.auth import SigV4QueryAuth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from botocore.session import Session
from typing import Dict, Optional, Callable
import time
from webrtc.AudioProcessor import AudioProcessor
from webrtc.AudioOutputTrack import AudioOutputTrack

logger = logging.getLogger(__name__)

class KVSWebRTCViewer:
    """
    WebRTC Viewer for Kinesis Video Streams
    Connects as a viewer to a WebRTC Master
    """
    
    def __init__(self, channel_name: str, region: str, credentials: Optional[Dict] = None):
        """
        Initialize WebRTC Viewer
        
        Args:
            channel_name: KVS signaling channel name
            region: AWS region
            credentials: AWS credentials (optional)
        """
        self.channel_name = channel_name
        self.region = region
        self.credentials = credentials
        self.client_id = "VIEWER"
        
        # AWS clients
        if self.credentials:
            self.kinesisvideo = boto3.client('kinesisvideo',
                                           region_name=self.region,
                                           aws_access_key_id=self.credentials['accessKeyId'],
                                           aws_secret_access_key=self.credentials['secretAccessKey'],
                                           aws_session_token=self.credentials['sessionToken'])
        else:
            self.kinesisvideo = boto3.client('kinesisvideo', region_name=self.region)
            
        # WebRTC components
        self.pc: Optional[RTCPeerConnection] = None
        self.websocket: Optional[websockets.WebSocketServerProtocol] = None
        self.data_channel = None
        
        # Endpoints and configuration
        self.endpoints = None
        self.endpoint_https = None
        self.endpoint_wss = None
        self.ice_servers = None
        
        # Audio processing
        self.audio_processor: Optional[AudioProcessor] = None
        self.audio_output_track: Optional[AudioOutputTrack] = None
        self.media_relay = MediaRelay()
        
        # Callbacks
        self.on_master_connected: Optional[Callable] = None
        self.on_master_disconnected: Optional[Callable] = None
        self.on_audio_received: Optional[Callable] = None
        self.on_video_received: Optional[Callable] = None  # New: separate video callback
        self.on_event_received: Optional[Callable] = None
        
        # State
        self.is_running = False
        self.is_connected = False
        self.answer_processed = False
        
        # Audio configuration
        self.prompt_name = None
        self.content_name = None
        
    async def initialize(self):
        """Initialize the WebRTC viewer"""
        try:
            logger.debug("🚀 [KVSWebRTCViewer] Initializing WebRTC viewer...")
            
            # Initialize audio processor
            logger.debug("🎵 [KVSWebRTCViewer] Initializing audio processor...")
            self.audio_processor = AudioProcessor()
            
            # Get signaling channel endpoints
            logger.debug("📡 [KVSWebRTCViewer] Getting signaling channel endpoints...")
            self._get_signaling_channel_endpoint()
            
            logger.info("✅ [KVSWebRTCViewer] WebRTC viewer initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ [KVSWebRTCViewer] Error initializing viewer: {e}")
            raise
            
    async def start(self):
        """Start the WebRTC viewer and connect to Master"""
        max_retries = 3
        retry_delay = 5.0
        
        for attempt in range(max_retries):
            try:
                if not self.endpoints:
                    raise ValueError("Viewer not initialized")
                    
                logger.info(f"🚀 [KVSWebRTCViewer] Starting WebRTC viewer (attempt {attempt + 1}/{max_retries})...")
                self.is_running = True
                
                # Start signaling client
                await self._signaling_client()
                
                # If we get here without exception, connection was successful
                break
                
            except Exception as e:
                logger.error(f"❌ [KVSWebRTCViewer] Error starting viewer (attempt {attempt + 1}): {e}")
                self.is_running = False
                
                if attempt < max_retries - 1:
                    logger.info(f"🔄 [KVSWebRTCViewer] Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error(f"❌ [KVSWebRTCViewer] Failed to start after {max_retries} attempts")
                    raise
            
    async def stop(self):
        """Stop the WebRTC viewer"""
        logger.info("[KVSWebRTCViewer] Stopping WebRTC viewer...")
        
        self.is_running = False
        self.is_connected = False
        self.answer_processed = False  # Reset for next connection
        
        # Close data channel first
        if self.data_channel:
            try:
                if hasattr(self.data_channel, 'readyState') and self.data_channel.readyState != 'closed':
                    self.data_channel.close()
                self.data_channel = None
            except Exception as e:
                logger.error(f"❌ [KVSWebRTCViewer] Error closing data channel: {e}")
        
        # Close peer connection
        if self.pc:
            try:
                if self.pc.connectionState not in ["closed", "failed"]:
                    await self.pc.close()
                self.pc = None
            except Exception as e:
                logger.error(f"❌ [KVSWebRTCViewer] Error closing peer connection: {e}")
            
        # Close websocket
        if self.websocket:
            try:
                if not self.websocket.closed:
                    await self.websocket.close()
                self.websocket = None
            except Exception as e:
                logger.error(f"❌ [KVSWebRTCViewer] Error closing websocket: {e}")
        
        # Stop audio processor
        if self.audio_processor:
            try:
                self.audio_processor.stop_processing()
            except Exception as e:
                logger.error(f"❌ [KVSWebRTCViewer] Error stopping audio processor: {e}")
            
        logger.info("[KVSWebRTCViewer] WebRTC viewer stopped")
        
    def set_audio_config(self, prompt_name: str, content_name: str):
        """
        Set audio configuration
        
        Args:
            prompt_name: Prompt name for S2S
            content_name: Content name for S2S
        """
        self.prompt_name = prompt_name
        self.content_name = content_name
            
    async def send_audio_to_master(self, base64_audio: str, sample_rate: int):
        """
        Send audio to Master via WebRTC media channel
        
        Args:
            base64_audio: Base64 encoded audio data
            sample_rate: Audio sample rate
        """
        try:
            if self.audio_output_track:
                self.audio_output_track.queue_audio(base64_audio, sample_rate)
                logger.debug(f"🎵➡️ [KVSWebRTCViewer] Sent audio to Master: {len(base64_audio)} chars at {sample_rate}Hz")
            else:
                logger.warning(f"⚠️ [KVSWebRTCViewer] No audio output track available to send audio to Master")
                
        except Exception as e:
            logger.error(f"❌ [KVSWebRTCViewer] Error sending audio to Master: {e}")
            
    async def send_event_to_master(self, event_data: dict):
        """
        Send event to Master via WebRTC data channel
        
        Args:
            event_data: Event data to send
        """
        try:
            if self.data_channel and self.data_channel.readyState == 'open':
                # Send via WebRTC data channel
                message = json.dumps(event_data)
                self.data_channel.send(message)
                logger.debug(f"📤 [KVSWebRTCViewer] Sent event to Master via data channel: {event_data.get('event', {}).keys()}")
            else:
                logger.warning(f"⚠️ [KVSWebRTCViewer] No data channel available to send event to Master")
                
        except Exception as e:
            logger.error(f"❌ [KVSWebRTCViewer] Error sending event to Master: {e}")
            
    def _get_signaling_channel_endpoint(self):
        """Get signaling channel endpoints"""
        if self.endpoints is None:
            # Get channel ARN first
            try:
                # Try to get channel by name
                response = self.kinesisvideo.describe_signaling_channel(ChannelName=self.channel_name)
                channel_arn = response['ChannelInfo']['ChannelARN']
            except Exception as e:
                logger.error(f"❌ [KVSWebRTCViewer] Error getting channel ARN: {e}")
                raise
                
            endpoints = self.kinesisvideo.get_signaling_channel_endpoint(
                ChannelARN=channel_arn,
                SingleMasterChannelEndpointConfiguration={'Protocols': ['HTTPS', 'WSS'], 'Role': 'VIEWER'}
            )
            self.endpoints = {
                'HTTPS': next(o['ResourceEndpoint'] for o in endpoints['ResourceEndpointList'] if o['Protocol'] == 'HTTPS'),
                'WSS': next(o['ResourceEndpoint'] for o in endpoints['ResourceEndpointList'] if o['Protocol'] == 'WSS')
            }
            self.endpoint_https = self.endpoints['HTTPS']
            self.endpoint_wss = self.endpoints['WSS']
            self.channel_arn = channel_arn
            
        return self.endpoints
        
    def _prepare_ice_servers(self):
        """Prepare ICE servers configuration"""
        if self.credentials:
            kinesis_video_signaling = boto3.client('kinesis-video-signaling',
                                                 endpoint_url=self.endpoint_https,
                                                 region_name=self.region,
                                                 aws_access_key_id=self.credentials['accessKeyId'],
                                                 aws_secret_access_key=self.credentials['secretAccessKey'],
                                                 aws_session_token=self.credentials['sessionToken'])
        else:
            kinesis_video_signaling = boto3.client('kinesis-video-signaling',
                                                 endpoint_url=self.endpoint_https,
                                                 region_name=self.region)
                                                 
        ice_server_config = kinesis_video_signaling.get_ice_server_config(
            ChannelARN=self.channel_arn,
            ClientId=self.client_id
        )

        ice_servers = [RTCIceServer(urls=f'stun:stun.kinesisvideo.{self.region}.amazonaws.com:443')]
        for ice_server in ice_server_config['IceServerList']:
            ice_servers.append(RTCIceServer(
                urls=ice_server['Uris'],
                username=ice_server['Username'],
                credential=ice_server['Password']
            ))
        self.ice_servers = ice_servers

        return self.ice_servers
        
    def _create_wss_url(self):
        """Create WebSocket signaling URL"""
        if self.credentials:
            auth_credentials = Credentials(
                access_key=self.credentials['accessKeyId'],
                secret_key=self.credentials['secretAccessKey'],
                token=self.credentials['sessionToken']
            )
        else:
            session = Session()
            auth_credentials = session.get_credentials()

        sig_v4 = SigV4QueryAuth(auth_credentials, 'kinesisvideo', self.region, 299)
        aws_request = AWSRequest(
            method='GET',
            url=self.endpoint_wss,
            params={'X-Amz-ChannelARN': self.channel_arn, 'X-Amz-ClientId': self.client_id},
        )
        sig_v4.add_auth(aws_request)
        prepared_request = aws_request.prepare()
        return prepared_request.url
        
    def _decode_msg(self, msg):
        """Decode WebSocket message"""
        try:
            data = json.loads(msg)
            payload = json.loads(b64decode(data['messagePayload'].encode('ascii')).decode('ascii'))
            return data['messageType'], payload, data.get('senderClientId')
        except json.decoder.JSONDecodeError:
            return '', {}, ''
            
    def _encode_msg(self, action, payload, client_id):
        """Encode WebSocket message"""
        return json.dumps({
            'action': action,
            'messagePayload': b64encode(json.dumps(payload).encode('ascii')).decode('ascii'),
            'recipientClientId': client_id,
        })
        
    async def _signaling_client(self):
        """Main signaling client loop"""
        try:
            # Create media tracks (audio only for now)
            audio_track = None
            video_track = None
            
            # Create WebSocket URL
            wss_url = self._create_wss_url()
            
            logger.info(f"🔗 [KVSWebRTCViewer] Connecting to signaling server...")
            
            # Add connection timeout
            connection_timeout = 30.0  # 30 seconds timeout
            
            # Connect with timeout
            websocket = await asyncio.wait_for(
                websockets.connect(wss_url), 
                timeout=connection_timeout
            )
            
            try:
                self.websocket = websocket
                logger.info('✅ [KVSWebRTCViewer] Signaling Server Connected!')
                
                # Handle SDP offer (send offer to Master)
                await self._handle_sdp_offer(audio_track, video_track, websocket)
                
                # Handle incoming messages
                await self._handle_messages(websocket)
                
            finally:
                # Ensure websocket is closed
                if websocket:
                    try:
                        await websocket.close()
                    except Exception:
                        pass  # Already closed or connection lost
                
        except Exception as e:
            logger.error(f"❌ [KVSWebRTCViewer] Signaling client error: {e}")
            import traceback
            logger.error(f"❌ [KVSWebRTCViewer] Traceback: {traceback.format_exc()}")
        finally:
            self.is_connected = False
            
            # Clean up peer connection
            if self.pc:
                try:
                    if self.pc.connectionState not in ["closed", "failed"]:
                        await self.pc.close()
                except Exception as cleanup_error:
                    logger.error(f"❌ [KVSWebRTCViewer] Error during peer connection cleanup: {cleanup_error}")
                finally:
                    self.pc = None
                
            # Notify disconnection
            if self.on_master_disconnected:
                try:
                    await self.on_master_disconnected()
                except Exception as callback_error:
                    logger.error(f"❌ [KVSWebRTCViewer] Error in disconnection callback: {callback_error}")
                
    async def _handle_sdp_offer(self, audio_track, video_track, websocket):
        """Create and send SDP offer to Master"""
        try:
            # Prepare ICE servers
            ice_servers = self._prepare_ice_servers()
            configuration = RTCConfiguration(iceServers=ice_servers)
            self.pc = RTCPeerConnection(configuration=configuration)

            @self.pc.on('connectionstatechange')
            async def on_connectionstatechange():
                logger.info(f'[KVSWebRTCViewer] connectionState: {self.pc.connectionState}')
                if self.pc.connectionState == "connected":
                    self.is_connected = True
                    if self.on_master_connected:
                        try:
                            await self.on_master_connected()
                        except Exception as e:
                            logger.error(f"❌ [KVSWebRTCViewer] Error in master connected callback: {e}")
                elif self.pc.connectionState in ["disconnected", "failed", "closed"]:
                    self.is_connected = False
                    if self.pc.connectionState == "failed":
                        logger.error(f"❌ [KVSWebRTCViewer] WebRTC connection failed")
                        # Stop processing to prevent further errors
                        self.is_running = False

            @self.pc.on('iceconnectionstatechange')
            async def on_iceconnectionstatechange():
                logger.info(f'[KVSWebRTCViewer] ICE connectionState: {self.pc.iceConnectionState}')

            @self.pc.on('icegatheringstatechange')
            async def on_icegatheringstatechange():
                logger.info(f'[KVSWebRTCViewer] ICE gatheringState: {self.pc.iceGatheringState}')

            @self.pc.on('signalingstatechange')
            async def on_signalingstatechange():
                logger.info(f'[KVSWebRTCViewer] signalingState: {self.pc.signalingState}')

            @self.pc.on('track')
            def on_track(track):
                logger.info(f"📥 [KVSWebRTCViewer] Received track from Master: {track.kind}")
                if track.kind == "audio":
                    logger.info(f"🎵 [KVSWebRTCViewer] Audio track received - forwarding to integration")
                    # Handle incoming audio from Master
                    if self.on_audio_received:
                        asyncio.create_task(self.on_audio_received(track))
                    else:
                        logger.warning(f"⚠️ [KVSWebRTCViewer] No audio received callback set!")
                elif track.kind == "video":
                    logger.info(f"📹 [KVSWebRTCViewer] Video track received - forwarding to integration")
                    # Handle incoming video from Master
                    if self.on_video_received:
                        asyncio.create_task(self.on_video_received(track))
                    else:
                        logger.info(f"📹 [KVSWebRTCViewer] No video received callback set - using MediaBlackhole")
                        # Use MediaBlackhole to consume video track if no callback
                        from aiortc.contrib.media import MediaBlackhole
                        MediaBlackhole().addTrack(track)
                else:
                    logger.info(f"❓ [KVSWebRTCViewer] Unknown track type: {track.kind}")

            @self.pc.on('datachannel')
            def on_datachannel(channel):
                logger.info(f"📨 [KVSWebRTCViewer] Data channel received from Master: {channel.label}")
                self.data_channel = channel
                
                @channel.on('open')
                def on_open():
                    logger.info(f"✅ [KVSWebRTCViewer] Data channel opened: {channel.label}")
                    
                @channel.on('message')
                def on_message(message):
                    try:
                        event_data = json.loads(message)
                        if self.on_event_received:
                            asyncio.create_task(self.on_event_received(event_data))
                    except Exception as e:
                        logger.error(f"❌ [KVSWebRTCViewer] Error processing data channel message: {e}")
                        
                @channel.on('close')
                def on_close():
                    logger.info(f"📨 [KVSWebRTCViewer] Data channel closed: {channel.label}")
                    self.data_channel = None

            @self.pc.on('icecandidate')
            async def on_icecandidate(event):
                if event.candidate and self.is_running and websocket and not websocket.closed:
                    try:
                        logger.debug(f"🧊 [KVSWebRTCViewer] Local ICE candidate: {event.candidate}")
                        await websocket.send(self._encode_msg('ICE_CANDIDATE', {
                            'candidate': event.candidate.candidate,
                            'sdpMid': event.candidate.sdpMid,
                            'sdpMLineIndex': event.candidate.sdpMLineIndex,
                        }, self.client_id))
                    except Exception as e:
                        logger.error(f"❌ [KVSWebRTCViewer] Error sending ICE candidate: {e}")

            # Add outgoing audio track (for sending audio to Master)
            logger.debug("🎵 [KVSWebRTCViewer] Creating audio output track...")
            self.audio_output_track = AudioOutputTrack(self.client_id)
            self.pc.addTrack(self.audio_output_track)
            
            # Add video transceiver to request video from Master
            logger.debug("📹 [KVSWebRTCViewer] Adding video transceiver to receive video from Master...")
            self.pc.addTransceiver("video", direction="recvonly")
            
            # Create data channel for sending events to Master
            logger.debug("📨 [KVSWebRTCViewer] Creating data channel...")
            self.data_channel = self.pc.createDataChannel('kvsDataChannel')
            
            @self.data_channel.on('open')
            def on_data_channel_open():
                logger.info(f"✅ [KVSWebRTCViewer] Data channel opened: {self.data_channel.label}")
                
            @self.data_channel.on('close')
            def on_data_channel_close():
                logger.info(f"📨 [KVSWebRTCViewer] Data channel closed: {self.data_channel.label}")
                
            @self.data_channel.on('message')
            def on_data_channel_message(message):
                try:
                    event_data = json.loads(message)
                    if self.on_event_received:
                        asyncio.create_task(self.on_event_received(event_data))
                except Exception as e:
                    logger.error(f"❌ [KVSWebRTCViewer] Error processing data channel message: {e}")

            # Create and send offer
            logger.debug(f"📤 [KVSWebRTCViewer] Creating SDP offer (current signaling state: {self.pc.signalingState})...")
            offer = await self.pc.createOffer()
            await self.pc.setLocalDescription(offer)
            logger.debug(f"📤 [KVSWebRTCViewer] Local description set (new signaling state: {self.pc.signalingState})")



            logger.info("📤 [KVSWebRTCViewer] Sending SDP offer to Master...")
            await websocket.send(self._encode_msg('SDP_OFFER', {
                'sdp': self.pc.localDescription.sdp, 
                'type': self.pc.localDescription.type
            }, self.client_id))
            
        except Exception as e:
            logger.error(f"❌ [KVSWebRTCViewer] Error handling SDP offer: {e}")
            raise
            
    async def _handle_ice_candidate(self, payload):
        """Handle incoming ICE candidate"""
        try:
            if not self.pc or self.pc.connectionState in ["closed", "failed"]:
                logger.warning(f"⚠️ [KVSWebRTCViewer] Ignoring ICE candidate - peer connection not available")
                return
                
            candidate = candidate_from_sdp(payload['candidate'])
            candidate.sdpMid = payload['sdpMid']
            candidate.sdpMLineIndex = payload['sdpMLineIndex']
            logger.debug(f"🧊 [KVSWebRTCViewer] Adding remote ICE candidate: {candidate}")
            await self.pc.addIceCandidate(candidate)
        except Exception as e:
            logger.error(f"❌ [KVSWebRTCViewer] Error adding ICE candidate: {e}")
            # Don't re-raise the exception to prevent connection failure
            
    async def _handle_messages(self, websocket):
        """Handle incoming WebSocket messages"""
        try:
            async for message in websocket:
                if not self.is_running:
                    break
                    
                try:
                    # Try to decode as signaling message first
                    msg_type, payload, sender_id = self._decode_msg(message)
                    
                    if msg_type == 'SDP_ANSWER':
                        if not self.pc or self.pc.connectionState in ["closed", "failed"]:
                            logger.warning(f"⚠️ [KVSWebRTCViewer] Ignoring SDP answer - peer connection not available")
                            continue
                            
                        # Check if we've already processed an answer
                        if self.answer_processed:
                            logger.warning(f"⚠️ [KVSWebRTCViewer] Ignoring duplicate SDP answer")
                            continue
                            
                        # Check signaling state before setting remote description
                        if self.pc.signalingState != "have-local-offer":
                            logger.warning(f"⚠️ [KVSWebRTCViewer] Ignoring SDP answer - wrong signaling state: {self.pc.signalingState}")
                            continue
                            
                        logger.info(f"📥 [KVSWebRTCViewer] Received SDP answer from Master (signaling state: {self.pc.signalingState})")
                        

                        
                        await self.pc.setRemoteDescription(RTCSessionDescription(
                            sdp=payload["sdp"], 
                            type=payload["type"]
                        ))
                        self.answer_processed = True
                        logger.info(f"✅ [KVSWebRTCViewer] SDP answer processed successfully (new signaling state: {self.pc.signalingState})")
                        
                    elif msg_type == 'ICE_CANDIDATE':
                        await self._handle_ice_candidate(payload)
                        
                    else:
                        logger.debug(f"🔍 [KVSWebRTCViewer] Unknown signaling message type: {msg_type}")
                        
                except json.JSONDecodeError:
                    # Try to decode as direct event message
                    try:
                        event_data = json.loads(message)
                        if self.on_event_received:
                            await self.on_event_received(event_data)
                    except json.JSONDecodeError:
                        logger.warning(f"⚠️ [KVSWebRTCViewer] Could not decode message: {message}")
                        
        except Exception as e:
            logger.error(f"❌ [KVSWebRTCViewer] Error handling messages: {e}")
            
    def get_audio_stats(self) -> dict:
        """Get audio processing statistics"""
        stats = {}
        
        if self.audio_processor:
            stats.update(self.audio_processor.get_stats())
            
        if self.audio_output_track:
            stats['output_track_stats'] = self.audio_output_track.get_stats()
            
        return stats