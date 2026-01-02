"""
WebRTC S2S Integration - Connects WebRTC audio processing with S2sSessionManager
Handles bidirectional audio processing and event routing between WebRTC and Nova Sonic
"""

import asyncio
import json
import logging
from typing import Dict, Optional
from s2s_session_manager import S2sSessionManager
from webrtc.KVSWebRTCMaster import KVSWebRTCMaster
from s2s_events import S2sEvent
import time

logger = logging.getLogger(__name__)

class WebRTCS2SIntegration:
    """
    Integration layer between WebRTC and S2S systems
    Manages session lifecycle, audio routing, and event handling
    """
    
    def __init__(self, region: str, model_id: str = 'amazon.nova-sonic-v1:0', 
                 mcp_client=None, mcp_iot_client=None, strands_agent=None, loopback_mode: bool = False):
        """
        Initialize WebRTC S2S integration
        
        Args:
            region: AWS region
            model_id: Bedrock model ID
            mcp_client: MCP client for location tool integration
            mcp_iot_client: MCP client for IoT Core tool integration
            strands_agent: Strands agent for external queries
            loopback_mode: If True, enables audio loopback testing (bypasses S2S)
        """
        self.region = region
        self.model_id = model_id
        self.mcp_client = mcp_client
        self.mcp_iot_client = mcp_iot_client
        self.strands_agent = strands_agent
        self.loopback_mode = loopback_mode
        
        # WebRTC master instance
        self.webrtc_master: Optional[KVSWebRTCMaster] = None
        
        # Session management
        self.client_sessions: Dict[str, S2sSessionManager] = {}
        self.session_tasks: Dict[str, asyncio.Task] = {}
        
        # Configuration
        self.default_prompt_name = "webrtc_prompt"
        self.default_content_name = "webrtc_content"
        self.audio_content_name = "audio_input"
        
        # Loopback processor (for testing)
        self.loopback_processor = None
        if self.loopback_mode:
            from webrtc.AudioLoopbackProcessor import AudioLoopbackProcessor
            self.loopback_processor = AudioLoopbackProcessor()
            logger.info("[WebRTCS2SIntegration] 🔄 LOOPBACK MODE ENABLED - Audio will be echoed back for testing")
        
        # State
        self.is_running = False
        
    async def initialize_webrtc_master(self, channel_name: str, credentials: Optional[Dict] = None):
        """
        Initialize WebRTC master
        
        Args:
            channel_name: KVS signaling channel name
            credentials: AWS credentials (optional)
        """
        try:
            logger.debug("🚀 [WebRTCS2SIntegration] Initializing WebRTC master...")
            logger.debug(f"📡 [WebRTCS2SIntegration] Channel: {channel_name}")
            logger.debug(f"🌍 [WebRTCS2SIntegration] Region: {self.region}")
            logger.debug(f"🤖 [WebRTCS2SIntegration] Model: {self.model_id}")
            
            # Create WebRTC master
            logger.debug("🔧 [WebRTCS2SIntegration] Creating KVSWebRTCMaster instance...")
            self.webrtc_master = KVSWebRTCMaster(
                channel_name=channel_name,
                region=self.region,
                credentials=credentials
            )
            
            # Set up WebRTC callbacks
            logger.debug("🔗 [WebRTCS2SIntegration] Setting up WebRTC callbacks...")
            self.webrtc_master.on_client_connected = self._handle_client_connected
            self.webrtc_master.on_client_disconnected = self._handle_client_disconnected
            
            if self.loopback_mode:
                # In loopback mode, use loopback processor instead of S2S
                self.webrtc_master.on_audio_received = self._handle_loopback_audio_received
                # Set reference for cleanup
                self.webrtc_master._loopback_processor = self.loopback_processor
                # Disable test audio playback in loopback mode
                self.webrtc_master._disable_test_audio = True
                logger.info("🔄 [WebRTCS2SIntegration] Using loopback audio handler")
            else:
                # Normal S2S mode
                self.webrtc_master.on_audio_received = self._handle_audio_received
                logger.info("🤖 [WebRTCS2SIntegration] Using S2S audio handler")
                
            self.webrtc_master.on_event_received = self._handle_event_received
            
            # Set audio configuration
            logger.debug("🎵 [WebRTCS2SIntegration] Setting audio configuration...")
            self.webrtc_master.set_audio_config(
                prompt_name=self.default_prompt_name,
                content_name=self.audio_content_name
            )
            
            # Initialize WebRTC master
            logger.debug("⚡ [WebRTCS2SIntegration] Initializing WebRTC master...")
            await self.webrtc_master.initialize()
            
            logger.info("✅ [WebRTCS2SIntegration] WebRTC master initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ [WebRTCS2SIntegration] Error initializing WebRTC master: {e}")
            raise
            
    async def start(self):
        """Start the WebRTC S2S integration"""
        try:
            if not self.webrtc_master:
                raise ValueError("WebRTC master not initialized")
                
            logger.info("🚀 [WebRTCS2SIntegration] Starting WebRTC S2S integration...")
            
            self.is_running = True
            
            # Start loopback processor if in loopback mode
            if self.loopback_mode and self.loopback_processor:
                logger.debug("🔄 [WebRTCS2SIntegration] Starting loopback processor...")
                self.loopback_processor.start_processing()
                # Set callback for sending audio back to clients
                self.loopback_processor.set_audio_output_callback(self._send_loopback_audio_to_client)
            
            # Start WebRTC master
            logger.debug("📡 [WebRTCS2SIntegration] Starting WebRTC master server...")
            await self.webrtc_master.start()
            
            logger.info("✅ [WebRTCS2SIntegration] WebRTC S2S integration started successfully")
            logger.info("👂 [WebRTCS2SIntegration] Waiting for WebRTC viewer connections...")
            
        except Exception as e:
            logger.error(f"❌ [WebRTCS2SIntegration] Error starting integration: {e}")
            self.is_running = False
            raise
            
    async def stop(self):
        """Stop the WebRTC S2S integration"""
        logger.info("[WebRTCS2SIntegration] Stopping WebRTC S2S integration...")
        
        self.is_running = False
        
        # Close all client sessions
        for client_id in list(self.client_sessions.keys()):
            await self._cleanup_client_session(client_id)
            
        # Stop WebRTC master
        if self.webrtc_master:
            await self.webrtc_master.stop()
            
        logger.info("[WebRTCS2SIntegration] WebRTC S2S integration stopped")
        
    async def _handle_client_connected(self, client_id: str):
        """
        Handle new client connection
        
        Args:
            client_id: Connected client identifier
        """
        try:
            logger.info(f"🎉 [WebRTCS2SIntegration] Client connected: {client_id}")
            
            if self.loopback_mode:
                # In loopback mode, skip S2S session creation
                logger.info(f"🔄 [WebRTCS2SIntegration] LOOPBACK MODE - Skipping S2S session creation for {client_id}")
                return
            
            # Create S2S session manager for this client
            logger.debug(f"🤖 [WebRTCS2SIntegration] Creating S2S session manager for {client_id}...")
            session_manager = S2sSessionManager(
                region=self.region,
                model_id=self.model_id,
                mcp_client=self.mcp_client,
                mcp_iot_client=self.mcp_iot_client,
                strands_agent=self.strands_agent
            )
            
            # Initialize the session
            logger.debug(f"⚡ [WebRTCS2SIntegration] Initializing S2S stream for {client_id}...")
            await session_manager.initialize_stream()
            
            # Store session manager
            logger.debug(f"💾 [WebRTCS2SIntegration] Storing session manager for {client_id}...")
            logger.debug(f"💾 [WebRTCS2SIntegration] Session manager initialization complete - Active: {session_manager.is_active}")
            
            self.client_sessions[client_id] = session_manager
            logger.debug(f"💾 [WebRTCS2SIntegration] Session manager stored in client_sessions for {client_id}")
            
            logger.debug(f"🔗 [WebRTCS2SIntegration] Associating session manager with WebRTC master for {client_id}...")
            self.webrtc_master.set_session_manager(client_id, session_manager)
            
            # Also set session manager in AudioProcessor for S2S state checking
            if self.webrtc_master.audio_processor:
                self.webrtc_master.audio_processor.set_session_manager(client_id, session_manager)
                logger.debug(f"🔗 [WebRTCS2SIntegration] Set session manager in AudioProcessor for {client_id}")
            
            logger.debug(f"✅ [WebRTCS2SIntegration] Session manager association complete for {client_id}")
            
            # Start session response processing task
            logger.debug(f"🔄 [WebRTCS2SIntegration] Starting response processing task for {client_id}...")
            task = asyncio.create_task(self._process_session_responses(client_id, session_manager))
            self.session_tasks[client_id] = task
            
            # Auto-initialize session with default values to avoid waiting for client events
            logger.debug(f"[WebRTCS2SIntegration] Auto-initializing S2S session for {client_id}...")
            await self._auto_initialize_session(client_id, session_manager)
            
            logger.info(f"[WebRTCS2SIntegration] Session manager ready for {client_id} - session auto-initialized, waiting for Nova Sonic responses...")
            
            # Check if we're getting any responses from Nova Sonic after a few seconds
            # asyncio.create_task(self._check_nova_responses(client_id, session_manager))
            
            # Add connection health check
            asyncio.create_task(self._monitor_client_health(client_id))
            
        except Exception as e:
            logger.error(f"❌ [WebRTCS2SIntegration] Error handling client connection {client_id}: {e}")
            
    async def _handle_client_disconnected(self, client_id: str):
        """
        Handle client disconnection
        
        Args:
            client_id: Disconnected client identifier
        """
        logger.info(f"👋 [WebRTCS2SIntegration] Client disconnected: {client_id}")
        await self._cleanup_client_session(client_id)
        
    async def _cleanup_client_session(self, client_id: str):
        """
        Clean up client session resources
        
        Args:
            client_id: Client identifier
        """
        try:
            # Cancel response processing task
            if client_id in self.session_tasks:
                task = self.session_tasks[client_id]
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                del self.session_tasks[client_id]
                
            # Close S2S session
            if client_id in self.client_sessions:
                session_manager = self.client_sessions[client_id]
                
                # Just close the session without sending end events
                # The session manager will handle proper cleanup
                await session_manager.close()
                del self.client_sessions[client_id]
                
            logger.debug(f"[WebRTCS2SIntegration] Cleaned up session for {client_id}")
            
        except Exception as e:
            logger.error(f"[WebRTCS2SIntegration] Error cleaning up session for {client_id}: {e}")
            
    async def _start_s2s_session(self, client_id: str, session_manager: S2sSessionManager):
        """(deprecated)
        Start S2S session with initial events
        
        Args:
            client_id: Client identifier
            session_manager: S2S session manager
        """
        try:
            # Send session start event
            session_start_event = S2sEvent.session_start()
            await session_manager.send_raw_event(session_start_event)
            
            # Send prompt start event
            prompt_start_event = S2sEvent.prompt_start(self.default_prompt_name)
            await session_manager.send_raw_event(prompt_start_event)
            
            # Send system prompt content
            system_content_name = "system_content"
            content_start_event = S2sEvent.content_start_text(self.default_prompt_name, system_content_name)
            await session_manager.send_raw_event(content_start_event)
            
            text_input_event = S2sEvent.text_input(self.default_prompt_name, system_content_name)
            await session_manager.send_raw_event(text_input_event)
            
            content_end_event = S2sEvent.content_end(self.default_prompt_name, system_content_name)
            await session_manager.send_raw_event(content_end_event)
            
            # Start audio content
            audio_start_event = S2sEvent.content_start_audio(self.default_prompt_name, self.audio_content_name)
            await session_manager.send_raw_event(audio_start_event)
            
            logger.info(f"[WebRTCS2SIntegration] S2S session started for {client_id}")
            
        except Exception as e:
            logger.error(f"[WebRTCS2SIntegration] Error starting S2S session for {client_id}: {e}")
            
    async def _process_session_responses(self, client_id: str, session_manager: S2sSessionManager):
        """
        Process responses from S2S session and forward to WebRTC client
        
        Args:
            client_id: Client identifier
            session_manager: S2S session manager
        """
        try:
            logger.debug(f"[WebRTCS2SIntegration] Starting response processing for {client_id}")
            
            while self.is_running and session_manager.is_active:
                try:
                    # Get response from session manager
                    response = await asyncio.wait_for(session_manager.output_queue.get(), timeout=1.0)
                    
                    # Process different types of responses
                    await self._handle_s2s_response(client_id, response)
                    
                except asyncio.TimeoutError:
                    # Continue processing - timeout is normal
                    continue
                except Exception as e:
                    logger.error(f"[WebRTCS2SIntegration] Error processing response for {client_id}: {e}")
                    break
                    
            logger.debug(f"[WebRTCS2SIntegration] Finished response processing for {client_id}")
            
        except Exception as e:
            logger.error(f"[WebRTCS2SIntegration] Fatal error in response processing for {client_id}: {e}")
            
    async def _handle_s2s_response(self, client_id: str, response: dict):
        """
        Handle S2S response and forward to WebRTC client
        
        Args:
            client_id: Client identifier
            response: S2S response data
        """
        try:
            logger.debug(f"🔍 [WebRTCS2SIntegration] _handle_s2s_response called for {client_id}")
            logger.debug(f"🔍 [WebRTCS2SIntegration] Response keys: {list(response.keys())}")
            
            if 'event' not in response:
                logger.warning(f"⚠️ [WebRTCS2SIntegration] No 'event' key in response for {client_id}")
                return
                
            event = response['event']
            event_type = list(event.keys())[0] if event else None
            logger.debug(f"🔍 [WebRTCS2SIntegration] Processing event type: {event_type} for {client_id}")
            
            if event_type == 'audioOutput':
                # Handle audio output
                audio_data = event['audioOutput']
                base64_audio = audio_data.get('content', '')
                
                if base64_audio:
                    logger.debug(f"🎵⬅️ [WebRTCS2SIntegration] Received audioOutput from Nova Sonic for {client_id}: {len(base64_audio)} chars")
                    logger.debug(f"📡 [WebRTCS2SIntegration] Routing audio to WebRTC media channel for {client_id}")
                    # Send audio to client via WebRTC media channel
                    await self.webrtc_master.send_audio_to_client(client_id, base64_audio, 24000)
                    
            # Forward ALL Nova events to client in the format React expects
            # React expects: {"event": {"textOutput": {...}}, "timestamp": ...}
            logger.debug(f"📤 [WebRTCS2SIntegration] ABOUT TO FORWARD {event_type} event to {client_id}")
            logger.debug(f"🔍 [WebRTCS2SIntegration] WebRTC master available: {self.webrtc_master is not None}")
            logger.debug(f"🔍 [WebRTCS2SIntegration] Original response structure: {list(response.keys())}")
            
            # Extract just the Nova event part for React client
            # React expects: {event: {textOutput: {...}}}
            # But response contains: {event: {textOutput: {...}}, timestamp: ...}
            nova_event_data = response.get('event', {})
            logger.debug(f"🔍 [WebRTCS2SIntegration] Extracted Nova event keys: {list(nova_event_data.keys())}")
            
            try:
                result = await self.webrtc_master.send_event_to_client(client_id, nova_event_data)
                logger.debug(f"✅ [WebRTCS2SIntegration] Successfully forwarded {event_type} event to {client_id}, result: {result}")
            except Exception as forward_error:
                logger.error(f"❌ [WebRTCS2SIntegration] Error forwarding {event_type} event to {client_id}: {forward_error}")
                import traceback
                logger.error(f"❌ [WebRTCS2SIntegration] Forward error traceback: {traceback.format_exc()}")
            
        except Exception as e:
            logger.error(f"❌ [WebRTCS2SIntegration] Error handling S2S response for {client_id}: {e}")
            import traceback
            logger.error(f"❌ [WebRTCS2SIntegration] Error traceback: {traceback.format_exc()}")
            
    async def _handle_audio_received(self, client_id: str, audio_data):
        """
        Handle audio received from WebRTC client
        
        Args:
            client_id: Client identifier
            audio_data: Either RemoteStreamTrack object or processed audio packet dict
        """
        try:
            # Check if this is a RemoteStreamTrack (raw audio track) or processed audio packet
            if hasattr(audio_data, 'kind') and audio_data.kind == 'audio':
                # This is a RemoteStreamTrack object - we need to process it
                logger.info(f"🎵 [WebRTCS2SIntegration] Raw audio track received from {client_id}: {type(audio_data)}")
                
                # Add the track to the audio processor for processing
                await self.webrtc_master.audio_processor.add_audio_track(client_id, audio_data)
                
                # Use MediaBlackhole to consume the track (required by aiortc)
                from aiortc.contrib.media import MediaBlackhole
                MediaBlackhole().addTrack(audio_data)
                
            elif isinstance(audio_data, dict) and 'size_bytes' in audio_data:
                # This is a processed audio packet
                logger.debug(f"🎵 [WebRTCS2SIntegration] Processed audio received from {client_id}: {audio_data['size_bytes']} bytes")
                
            else:
                logger.warning(f"⚠️ [WebRTCS2SIntegration] Unknown audio data type from {client_id}: {type(audio_data)}")
                
        except Exception as e:
            logger.error(f"❌ [WebRTCS2SIntegration] Error handling audio from {client_id}: {e}")
            logger.error(f"❌ [WebRTCS2SIntegration] Audio data type: {type(audio_data)}")
            logger.error(f"❌ [WebRTCS2SIntegration] Audio data: {audio_data}")
        
    async def _handle_event_received(self, client_id: str, event_data: dict):
        """
        Handle event received from WebRTC client
        
        Args:
            client_id: Client identifier
            event_data: Event data
        """
        try:
            logger.info(f"[WebRTCS2SIntegration] Event received from {client_id}: {event_data.get('type', 'unknown')}")
            
            event_type = event_data.get('type')
            
            if event_type == 'CONFIGURATION_UPDATE':
                # Handle configuration updates
                await self._handle_configuration_update(client_id, event_data)
                
            elif event_type == 'BARGE_IN':
                # Handle barge-in request
                await self._handle_barge_in(client_id)
                
            elif event_type == 'SESSION_CONTROL':
                # Handle session control commands
                await self._handle_session_control(client_id, event_data)
                
            else:
                logger.warning(f"[WebRTCS2SIntegration] Unknown event type from {client_id}: {event_type}")
                
        except Exception as e:
            logger.error(f"[WebRTCS2SIntegration] Error handling event from {client_id}: {e}")
            
    async def _handle_configuration_update(self, client_id: str, event_data: dict):
        """
        Handle configuration update from client
        
        Args:
            client_id: Client identifier
            event_data: Configuration update data
        """
        try:
            config = event_data.get('config', {})
            
            # Update voice ID, system prompt, etc.
            # This would require restarting the S2S session with new configuration
            logger.info(f"[WebRTCS2SIntegration] Configuration update for {client_id}: {config}")
            
            # Send acknowledgment
            ack_event = {
                'type': 'CONFIGURATION_ACK',
                'status': 'success',
                'timestamp': int(time.time() * 1000)
            }
            self.webrtc_master.send_event_to_client(client_id, ack_event)
            
        except Exception as e:
            logger.error(f"[WebRTCS2SIntegration] Error handling configuration update for {client_id}: {e}")
            
    async def _handle_barge_in(self, client_id: str):
        """
        Handle barge-in request from client
        
        Args:
            client_id: Client identifier
        """
        try:
            logger.info(f"[WebRTCS2SIntegration] 🛑 Barge-in requested for {client_id}")
            
            # Clear audio buffers in AudioProcessor
            if self.webrtc_master and self.webrtc_master.audio_processor:
                self.webrtc_master.audio_processor.clear_client_buffer(client_id)
                
            # Clear audio buffers in AudioOutputTrack
            if self.webrtc_master:
                for peer_connection in self.webrtc_master.peer_connections.values():
                    for sender in peer_connection.getSenders():
                        if hasattr(sender.track, 'clear_buffer') and hasattr(sender.track, 'client_id'):
                            if sender.track.client_id == client_id:
                                sender.track.clear_buffer()
                                logger.debug(f"🔄 [WebRTCS2SIntegration] Cleared audio buffer for {client_id}")
                                
        except Exception as e:
            logger.error(f"[WebRTCS2SIntegration] Error handling barge-in for {client_id}: {e}")
            
    async def _handle_session_control(self, client_id: str, event_data: dict):
        """
        Handle session control commands from client
        
        Args:
            client_id: Client identifier
            event_data: Session control data
        """
        try:
            command = event_data.get('command')
            
            if command == 'restart':
                # Restart S2S session
                await self._cleanup_client_session(client_id)
                await self._handle_client_connected(client_id)
                
            elif command == 'pause':
                # Pause audio processing
                if self.webrtc_master and self.webrtc_master.audio_processor:
                    await self.webrtc_master.audio_processor.remove_audio_track(client_id)
                    
            elif command == 'resume':
                # Resume audio processing would require re-adding the track
                pass
                
            logger.info(f"[WebRTCS2SIntegration] Session control for {client_id}: {command}")
            
        except Exception as e:
            logger.error(f"[WebRTCS2SIntegration] Error handling session control for {client_id}: {e}")
            
    async def _auto_initialize_session(self, client_id: str, session_manager: S2sSessionManager):
        """
        Auto-initialize S2S session with default events
        Without auto-initialization, the system would need to wait for the client (frontend) to send these initialization events.

        Args:
            client_id: Client identifier
            session_manager: S2S session manager
        """
        try:
            logger.info(f"[WebRTCS2SIntegration] Starting auto-initialization for {client_id}")
            
            # Use unique prompt name to avoid duplicates
            import uuid
            unique_prompt = f"webrtc_prompt_{uuid.uuid4().hex[:8]}"
            unique_audio_content = f"audio_input_{uuid.uuid4().hex[:8]}"
            
            logger.info(f"[WebRTCS2SIntegration] Using unique prompt: {unique_prompt}")
            
            # Send session start event
            session_start_event = S2sEvent.session_start()
            await session_manager.send_raw_event(session_start_event)
            logger.info(f"[WebRTCS2SIntegration] Sent sessionStart for {client_id}")
            
            # Wait for Nova Sonic to acknowledge
            await asyncio.sleep(0.2)
            
            # Send prompt start event with unique name
            prompt_start_event = S2sEvent.prompt_start(unique_prompt)
            await session_manager.send_raw_event(prompt_start_event)
            logger.info(f"[WebRTCS2SIntegration] Sent promptStart with unique name for {client_id}")
            
            # Wait for Nova Sonic to process
            await asyncio.sleep(0.2)
            
            # Send system prompt content
            system_content_name = f"system_content_{uuid.uuid4().hex[:8]}"
            content_start_event = S2sEvent.content_start_text(unique_prompt, system_content_name)
            await session_manager.send_raw_event(content_start_event)
            
            # Default system prompt
            system_prompt = "You are a helpful AI assistant. Respond naturally and conversationally to user questions."
            text_input_event = S2sEvent.text_input(unique_prompt, system_content_name, system_prompt)
            await session_manager.send_raw_event(text_input_event)
            
            content_end_event = S2sEvent.content_end(unique_prompt, system_content_name)
            await session_manager.send_raw_event(content_end_event)
            logger.info(f"[WebRTCS2SIntegration] Sent system prompt for {client_id}")
            
            # Wait for system prompt to be processed
            await asyncio.sleep(0.3)
            
            # Start audio content with unique name
            audio_start_event = S2sEvent.content_start_audio(unique_prompt, unique_audio_content)
            await session_manager.send_raw_event(audio_start_event)
            logger.info(f"[WebRTCS2SIntegration] Sent audio contentStart for {client_id}")
            
            # Update session manager with unique names
            session_manager.prompt_name = unique_prompt
            session_manager.audio_content_name = unique_audio_content
            
            # Update WebRTC master audio config with unique names
            self.webrtc_master.set_audio_config(unique_prompt, unique_audio_content)
            
            # Wait for Nova Sonic to process the initialization
            await asyncio.sleep(0.5)
            
            logger.info(f"[WebRTCS2SIntegration] Auto-initialization complete for {client_id} - Nova Sonic should be ready for audio")
            
        except Exception as e:
            logger.error(f"[WebRTCS2SIntegration] Error auto-initializing session for {client_id}: {e}")
            import traceback
            logger.error(f"[WebRTCS2SIntegration] Traceback: {traceback.format_exc()}")
    
    async def _monitor_client_health(self, client_id: str):
        """Monitor client connection health"""
        try:
            await asyncio.sleep(10)  # Wait 10 seconds after connection
            
            if client_id in self.client_sessions:
                session_manager = self.client_sessions[client_id]
                if not session_manager.is_active:
                    logger.warning(f"⚠️ [WebRTCS2SIntegration] Session manager inactive for {client_id}")
                    
                if not session_manager.is_session_ready():
                    logger.warning(f"⚠️ [WebRTCS2SIntegration] Session not ready for {client_id}: {session_manager.get_session_state()}")
                    
        except Exception as e:
            logger.error(f"❌ [WebRTCS2SIntegration] Error monitoring client health for {client_id}: {e}")
    
    async def _check_nova_responses(self, client_id: str, session_manager: S2sSessionManager):
        """Check if Nova Sonic is responding after initialization"""
        try:
            await asyncio.sleep(5.0)  # Wait 5 seconds after initialization
            
            if client_id in self.client_sessions:
                # Check if we've received any responses
                queue_size = session_manager.output_queue.qsize()
                logger.info(f"[WebRTCS2SIntegration] Nova Sonic response check for {client_id}: {queue_size} responses in queue")
                
                if queue_size == 0:
                    logger.warning(f"[WebRTCS2SIntegration] NO RESPONSES from Nova Sonic for {client_id} after 5 seconds")
                    logger.warning(f"[WebRTCS2SIntegration] Possible issues: 1) Model not available in region, 2) Invalid session setup, 3) Audio format issues")
                    
                    # Check session state
                    session_state = session_manager.get_session_state()
                    logger.info(f"🔍 [WebRTCS2SIntegration] Session state: {session_state}")
                    
                    # Check if stream is still active
                    logger.info(f"[WebRTCS2SIntegration] Stream active: {session_manager.is_active}")
                else:
                    logger.info(f"[WebRTCS2SIntegration] Nova Sonic is responding normally for {client_id}")
                    
        except Exception as e:
            logger.error(f"[WebRTCS2SIntegration] Error checking Nova responses for {client_id}: {e}")
    
    async def _handle_loopback_audio_received(self, client_id: str, track):
        """Handle audio received in loopback mode"""
        try:
            logger.info(f"🔄 [WebRTCS2SIntegration] Adding audio track for loopback: {client_id}")
            
            if self.loopback_processor:
                await self.loopback_processor.add_audio_track(client_id, track)
            else:
                logger.error(f"❌ [WebRTCS2SIntegration] Loopback processor not available for {client_id}")
                
        except Exception as e:
            logger.error(f"❌ [WebRTCS2SIntegration] Error handling loopback audio for {client_id}: {e}")
    
    async def _send_loopback_audio_to_client(self, client_id: str, audio_data, sample_rate: int):
        """Send loopback audio back to client"""
        try:
            if self.webrtc_master:
                # Send audio through AudioOutputTrack
                await self.webrtc_master.send_raw_audio_to_client(client_id, audio_data, sample_rate)
                logger.debug(f"🔄 [WebRTCS2SIntegration] Sent loopback audio to {client_id}: {len(audio_data)} samples at {sample_rate}Hz")
            else:
                logger.error(f"❌ [WebRTCS2SIntegration] WebRTC master not available for loopback to {client_id}")
                
        except Exception as e:
            logger.error(f"❌ [WebRTCS2SIntegration] Error sending loopback audio to {client_id}: {e}")
    
    def get_integration_status(self) -> dict:
        """
        Get integration status and statistics
        
        Returns:
            Dictionary with integration status
        """
        status = {
            'is_running': self.is_running,
            'loopback_mode': self.loopback_mode,
            'active_sessions': len(self.client_sessions),
            'connected_clients': len(self.webrtc_master.get_connected_clients()) if self.webrtc_master else 0,
            'audio_stats': self.webrtc_master.get_audio_stats() if self.webrtc_master else {},
            'region': self.region,
            'model_id': self.model_id
        }
        
        # Add loopback stats if in loopback mode
        if self.loopback_mode and self.loopback_processor:
            status['loopback_stats'] = self.loopback_processor.get_stats()
            
        return status