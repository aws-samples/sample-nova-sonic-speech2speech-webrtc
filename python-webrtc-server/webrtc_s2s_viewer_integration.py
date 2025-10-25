"""
WebRTC S2S Viewer Integration - Connects WebRTC Viewer with S2S processing
Handles bidirectional audio processing and event routing as a WebRTC Viewer
"""

import asyncio
import json
import logging
import os
from typing import Dict, Optional
from s2s_session_manager import S2sSessionManager
from webrtc.KVSWebRTCViewer import KVSWebRTCViewer
from s2s_events import S2sEvent
import time

logger = logging.getLogger(__name__)

class WebRTCS2SViewerIntegration:
    """
    Integration layer between WebRTC Viewer and S2S systems
    Manages session lifecycle, audio routing, and event handling in Viewer mode
    """
    
    def __init__(self, region: str, model_id: str = 'amazon.nova-sonic-v1:0', 
                 mcp_client=None, mcp_iot_client=None, strands_agent=None):
        """
        Initialize WebRTC S2S Viewer integration
        
        Args:
            region: AWS region
            model_id: Bedrock model ID
            mcp_client: MCP client for location tool integration
            mcp_iot_client: MCP client for IoT Core tool integration
            strands_agent: Strands agent for external queries
        """
        self.region = region
        self.model_id = model_id
        self.mcp_client = mcp_client
        self.mcp_iot_client = mcp_iot_client
        self.strands_agent = strands_agent
        
        # WebRTC viewer instance
        self.webrtc_viewer: Optional[KVSWebRTCViewer] = None
        
        # Session management
        self.session_manager: Optional[S2sSessionManager] = None
        self.session_task: Optional[asyncio.Task] = None
        
        # Phone detection (video processing)
        self.phone_detector = None
        self._pending_video_track = None  # Store video track if received before phone detection is ready
        
        # Configuration - use defaults from S2sEvent
        self.default_prompt_name = "viewer_prompt"
        self.default_content_name = "viewer_content"
        self.audio_content_name = "audio_input"
        
        # State
        self.is_running = False
        self.master_connected = False
        
    async def initialize_webrtc_viewer(self, channel_name: str, credentials: Optional[Dict] = None):
        """
        Initialize WebRTC viewer
        
        Args:
            channel_name: KVS signaling channel name
            credentials: AWS credentials (optional)
        """
        try:
            logger.debug("🚀 [WebRTCS2SViewerIntegration] Initializing WebRTC viewer...")
            logger.debug(f"📡 [WebRTCS2SViewerIntegration] Channel: {channel_name}")
            logger.debug(f"🌍 [WebRTCS2SViewerIntegration] Region: {self.region}")
            logger.debug(f"🤖 [WebRTCS2SViewerIntegration] Model: {self.model_id}")
            
            # Create WebRTC viewer
            logger.debug("🔧 [WebRTCS2SViewerIntegration] Creating KVSWebRTCViewer instance...")
            self.webrtc_viewer = KVSWebRTCViewer(
                channel_name=channel_name,
                region=self.region,
                credentials=credentials
            )
            
            # Set up WebRTC callbacks
            logger.debug("🔗 [WebRTCS2SViewerIntegration] Setting up WebRTC callbacks...")
            self.webrtc_viewer.on_master_connected = self._handle_master_connected
            self.webrtc_viewer.on_master_disconnected = self._handle_master_disconnected
            self.webrtc_viewer.on_audio_received = self._handle_audio_received
            self.webrtc_viewer.on_video_received = self._handle_video_received  # New: video callback
            self.webrtc_viewer.on_event_received = self._handle_event_received
            
            # Set audio configuration
            logger.debug("🎵 [WebRTCS2SViewerIntegration] Setting audio configuration...")
            self.webrtc_viewer.set_audio_config(
                prompt_name=self.default_prompt_name,
                content_name=self.audio_content_name
            )
            
            # Initialize WebRTC viewer
            logger.debug("⚡ [WebRTCS2SViewerIntegration] Initializing WebRTC viewer...")
            await self.webrtc_viewer.initialize()
            
            logger.info("✅ [WebRTCS2SViewerIntegration] WebRTC viewer initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ [WebRTCS2SViewerIntegration] Error initializing WebRTC viewer: {e}")
            raise
            
    async def start(self):
        """Start the WebRTC S2S Viewer integration"""
        try:
            if not self.webrtc_viewer:
                raise ValueError("WebRTC viewer not initialized")
                
            logger.info("🚀 [WebRTCS2SViewerIntegration] Starting WebRTC S2S Viewer integration...")
            
            self.is_running = True
            
            # Start WebRTC viewer
            logger.debug("📡 [WebRTCS2SViewerIntegration] Starting WebRTC viewer...")
            await self.webrtc_viewer.start()
            
            logger.info("✅ [WebRTCS2SViewerIntegration] WebRTC S2S Viewer integration started successfully")
            logger.info("👂 [WebRTCS2SViewerIntegration] Connecting to WebRTC Master...")
            
        except Exception as e:
            logger.error(f"❌ [WebRTCS2SViewerIntegration] Error starting integration: {e}")
            self.is_running = False
            raise
            
    async def stop(self):
        """Stop the WebRTC S2S Viewer integration"""
        logger.info("[WebRTCS2SViewerIntegration] Stopping WebRTC S2S Viewer integration...")
        
        self.is_running = False
        
        # Close session
        await self._cleanup_session()
            
        # Stop WebRTC viewer
        if self.webrtc_viewer:
            await self.webrtc_viewer.stop()
            
        logger.info("[WebRTCS2SViewerIntegration] WebRTC S2S Viewer integration stopped")
        
    async def _handle_master_connected(self):
        """
        Handle connection to WebRTC Master
        """
        try:
            logger.info(f"🎉 [WebRTCS2SViewerIntegration] Connected to WebRTC Master")
            self.master_connected = True
            
            # Create S2S session manager
            logger.debug(f"🤖 [WebRTCS2SViewerIntegration] Creating S2S session manager...")
            self.session_manager = S2sSessionManager(
                region=self.region,
                model_id=self.model_id,
                mcp_client=self.mcp_client,
                mcp_iot_client=self.mcp_iot_client,
                strands_agent=self.strands_agent
            )
            
            # Initialize the session
            logger.debug(f"⚡ [WebRTCS2SViewerIntegration] Initializing S2S stream...")
            await self.session_manager.initialize_stream()
            
            # Set prompt and content names in session manager (needed for AudioProcessor)
            self.session_manager.prompt_name = self.default_prompt_name
            self.session_manager.audio_content_name = self.audio_content_name
            logger.debug(f"🔧 [WebRTCS2SViewerIntegration] Set session manager prompt names: {self.default_prompt_name}, {self.audio_content_name}")
            
            # Set session manager in viewer for audio processing
            if self.webrtc_viewer.audio_processor:
                self.webrtc_viewer.audio_processor.set_session_manager("master", self.session_manager)
                # CRITICAL: Set audio callback to connect processing chain
                self.webrtc_viewer.audio_processor.set_audio_callback(self._handle_processed_audio)
                # Start audio processing BEFORE adding any tracks
                self.webrtc_viewer.audio_processor.start_processing()
                logger.info(f"🔗 [WebRTCS2SViewerIntegration] AudioProcessor started and ready to receive tracks")
                
                # Check if we already have an audio track that was ignored
                if hasattr(self, '_pending_audio_track'):
                    logger.info(f"🔄 [WebRTCS2SViewerIntegration] Re-adding previously ignored audio track")
                    await self.webrtc_viewer.audio_processor.add_audio_track("master", self._pending_audio_track)
                    delattr(self, '_pending_audio_track')
                    logger.info(f"✅ [WebRTCS2SViewerIntegration] Previously ignored audio track re-added successfully")
                
                logger.debug(f"🔗 [WebRTCS2SViewerIntegration] Set session manager, audio callback, and started AudioProcessor")
            
            # Start S2S session with default configuration
            await self._start_s2s_session()
            
            # Start session response processing task
            logger.debug(f"🔄 [WebRTCS2SViewerIntegration] Starting response processing task...")
            self.session_task = asyncio.create_task(self._process_session_responses())
            
            # Start local event generation task (for generating text events locally)
            # Note: Disabled to avoid interfering with audio processing
            logger.info(f"🔄 [WebRTCS2SViewerIntegration] Local event generation disabled - waiting for audio input from Master")
            # asyncio.create_task(self._generate_local_events())  # Disabled - Nova responds to audio, not text
            
            logger.info(f"✅ [WebRTCS2SViewerIntegration] S2S session ready - using default configuration")
            
            # Initialize phone detection if enabled
            await self._initialize_phone_detection()
            
        except Exception as e:
            logger.error(f"❌ [WebRTCS2SViewerIntegration] Error handling master connection: {e}")
            
    async def _handle_master_disconnected(self):
        """
        Handle disconnection from WebRTC Master
        """
        logger.info(f"👋 [WebRTCS2SViewerIntegration] Disconnected from WebRTC Master")
        self.master_connected = False
        await self._cleanup_session()
        
    async def _cleanup_session(self):
        """
        Clean up session resources
        """
        try:
            # Stop phone detection
            if self.phone_detector:
                try:
                    self.phone_detector.stop_processing()
                    self.phone_detector = None
                    logger.debug(f"[WebRTCS2SViewerIntegration] Phone detection stopped")
                except Exception as e:
                    logger.error(f"[WebRTCS2SViewerIntegration] Error stopping phone detection: {e}")
            
            # Cancel response processing task
            if self.session_task and not self.session_task.done():
                self.session_task.cancel()
                try:
                    await self.session_task
                except asyncio.CancelledError:
                    pass
                self.session_task = None
                
            # Close S2S session
            if self.session_manager:
                # Send session end event
                try:
                    session_end_event = S2sEvent.session_end()
                    await self.session_manager.send_raw_event(session_end_event)
                    
                    # Wait a bit for Nova Sonic to send completionEnd event
                    logger.debug(f"[WebRTCS2SViewerIntegration] Waiting for final events from Nova Sonic")
                    await asyncio.sleep(2.0)  # Wait 2 seconds for completionEnd
                    
                except Exception as e:
                    logger.warning(f"[WebRTCS2SViewerIntegration] Error sending session end: {e}")
                    
                # Close session
                await self.session_manager.close()
                self.session_manager = None
                
            logger.debug(f"[WebRTCS2SViewerIntegration] Cleaned up session")
            
        except Exception as e:
            logger.error(f"[WebRTCS2SViewerIntegration] Error cleaning up session: {e}")
            
    async def _start_s2s_session(self):
        """
        Start S2S session with default configuration from S2sEvent
        """
        try:
            # Send session start event
            session_start_event = S2sEvent.session_start(S2sEvent.DEFAULT_INFER_CONFIG)
            await self.session_manager.send_raw_event(session_start_event)
            
            # Send prompt start event with default tool config
            prompt_start_event = S2sEvent.prompt_start(
                self.default_prompt_name,
                S2sEvent.DEFAULT_AUDIO_OUTPUT_CONFIG,
                S2sEvent.DEFAULT_TOOL_CONFIG
            )
            await self.session_manager.send_raw_event(prompt_start_event)
            
            # Send system prompt content
            system_content_name = "system_content"
            content_start_event = S2sEvent.content_start_text(self.default_prompt_name, system_content_name)
            await self.session_manager.send_raw_event(content_start_event)
            
            text_input_event = S2sEvent.text_input(
                self.default_prompt_name, 
                system_content_name, 
                S2sEvent.DEFAULT_SYSTEM_PROMPT
            )
            await self.session_manager.send_raw_event(text_input_event)
            
            content_end_event = S2sEvent.content_end(self.default_prompt_name, system_content_name)
            await self.session_manager.send_raw_event(content_end_event)
            
            # Start audio content
            audio_start_event = S2sEvent.content_start_audio(
                self.default_prompt_name, 
                self.audio_content_name,
                S2sEvent.DEFAULT_AUDIO_INPUT_CONFIG
            )
            await self.session_manager.send_raw_event(audio_start_event)
            
            logger.info(f"[WebRTCS2SViewerIntegration] S2S session started with default configuration")
            
        except Exception as e:
            logger.error(f"[WebRTCS2SViewerIntegration] Error starting S2S session: {e}")
            
    async def _process_session_responses(self):
        """
        Process responses from S2S session and forward to WebRTC Master
        """
        try:
            logger.info(f"[WebRTCS2SViewerIntegration] Starting response processing")
            response_count = 0
            
            while self.is_running and self.session_manager and self.session_manager.is_active:
                try:
                    # Get response from session manager
                    response = await asyncio.wait_for(self.session_manager.output_queue.get(), timeout=1.0)
                    response_count += 1
                    
                    logger.debug(f"[WebRTCS2SViewerIntegration] 📥 Received response #{response_count} from Nova Sonic")
                    logger.debug(f"[WebRTCS2SViewerIntegration] Response keys: {list(response.keys())}")
                    
                    # Process different types of responses
                    await self._handle_s2s_response(response)
                    
                except asyncio.TimeoutError:
                    # Continue processing - timeout is normal
                    continue
                except Exception as e:
                    logger.error(f"[WebRTCS2SViewerIntegration] Error processing response: {e}")
                    break
                    
            logger.info(f"[WebRTCS2SViewerIntegration] Finished response processing - total responses: {response_count}")
            
        except Exception as e:
            logger.error(f"[WebRTCS2SViewerIntegration] Fatal error in response processing: {e}")
            
    async def _handle_s2s_response(self, response: dict):
        """
        Handle S2S response and forward to WebRTC Master
        
        Args:
            response: S2S response data
        """
        try:
            logger.debug(f"🔍 [WebRTCS2SViewerIntegration] _handle_s2s_response called")
            logger.debug(f"🔍 [WebRTCS2SViewerIntegration] Response keys: {list(response.keys())}")
            
            if 'event' not in response:
                logger.warning(f"⚠️ [WebRTCS2SViewerIntegration] No 'event' key in response")
                return
                
            event = response['event']
            event_type = list(event.keys())[0] if event else None
            logger.debug(f"🔍 [WebRTCS2SViewerIntegration] Processing event type: {event_type}")
            
            if event_type == 'audioOutput':
                # Handle audio output - send to WebRTC media channel
                audio_data = event['audioOutput']
                base64_audio = audio_data.get('content', '')
                
                if base64_audio:
                    logger.debug(f"🎵⬅️ [WebRTCS2SViewerIntegration] 🎉 RECEIVED AUDIO OUTPUT from Nova Sonic: {len(base64_audio)} chars")
                    logger.debug(f"📡 [WebRTCS2SViewerIntegration] Routing audio to WebRTC media channel")
                    # Send audio to master via WebRTC media channel
                    await self.webrtc_viewer.send_audio_to_master(base64_audio, 24000)
                    logger.debug(f"✅ [WebRTCS2SViewerIntegration] Audio successfully queued to AudioOutputTrack")
                else:
                    logger.warning(f"⚠️ [WebRTCS2SViewerIntegration] Received audioOutput event but no content")
                    
            # Send Nova text output events to Master via data channel in original format
            # Keep the original Nova event format
            if event_type in ['textOutput', 'toolUse', 'completionStart', 'completionEnd']:
                logger.debug(f"📤 [WebRTCS2SViewerIntegration] Sending {event_type} event to Master via data channel")
                logger.debug(f"🔍 [WebRTCS2SViewerIntegration] Original response structure: {list(response.keys())}")
                
                try:
                    # Send the original Nova event format to Master
                    await self.webrtc_viewer.send_event_to_master(response)
                    logger.debug(f"✅ [WebRTCS2SViewerIntegration] Successfully sent {event_type} event to Master")
                except Exception as forward_error:
                    logger.error(f"❌ [WebRTCS2SViewerIntegration] Error sending {event_type} event to Master: {forward_error}")
            
            # Also log other event types for debugging
            elif event_type:
                logger.debug(f"🔍 [WebRTCS2SViewerIntegration] Received {event_type} event from Nova Sonic")
            else:
                logger.warning(f"⚠️ [WebRTCS2SViewerIntegration] Received response with no event type: {response}")
            
        except Exception as e:
            logger.error(f"❌ [WebRTCS2SViewerIntegration] Error handling S2S response: {e}")
            import traceback
            logger.error(f"❌ [WebRTCS2SViewerIntegration] Error traceback: {traceback.format_exc()}")
            
    async def _handle_audio_received(self, audio_data):
        """
        Handle audio received from WebRTC Master
        
        Args:
            audio_data: Either RemoteStreamTrack object or processed audio packet dict
        """
        try:
            # Check if this is a RemoteStreamTrack (raw audio track) or processed audio packet
            if hasattr(audio_data, 'kind') and audio_data.kind == 'audio':
                # This is a RemoteStreamTrack object - we need to process it
                logger.info(f"🎵 [WebRTCS2SViewerIntegration] Raw audio track received from Master: {type(audio_data)}")
                
                if not self.webrtc_viewer.audio_processor:
                    logger.error(f"❌ [WebRTCS2SViewerIntegration] No audio processor available!")
                    return
                
                # Check if AudioProcessor is ready (processing started)
                if not self.webrtc_viewer.audio_processor.is_processing:
                    logger.warning(f"⚠️ [WebRTCS2SViewerIntegration] AudioProcessor not ready yet, storing track for later")
                    self._pending_audio_track = audio_data
                    # Still use MediaBlackhole to consume the track
                    from aiortc.contrib.media import MediaBlackhole
                    MediaBlackhole().addTrack(audio_data)
                    return
                    
                # Add the track to the audio processor for processing
                logger.info(f"🎵 [WebRTCS2SViewerIntegration] Adding audio track to processor...")
                await self.webrtc_viewer.audio_processor.add_audio_track("master", audio_data)
                
                # Also add audio track to phone detection processor for MediaRecorder
                if hasattr(self, 'phone_detector') and self.phone_detector:
                    logger.info(f"🎵 [WebRTCS2SViewerIntegration] Adding audio track to phone detection processor for recording...")
                    asyncio.create_task(self.phone_detector.handle_audio_track(audio_data, "master"))
                
                # Use MediaBlackhole to consume the track (required by aiortc)
                from aiortc.contrib.media import MediaBlackhole
                MediaBlackhole().addTrack(audio_data)
                
                logger.info(f"✅ [WebRTCS2SViewerIntegration] Audio track added to processor successfully")
                logger.info(f"🔊 [WebRTCS2SViewerIntegration] AudioProcessor should now start receiving audio frames from Master")
                logger.info(f"💡 [WebRTCS2SViewerIntegration] NOTE: Nova Sonic will only respond when someone speaks on the Master side")
                
            elif isinstance(audio_data, dict) and 'size_bytes' in audio_data:
                # This is a processed audio packet
                logger.debug(f"🎵 [WebRTCS2SViewerIntegration] Processed audio received from Master: {audio_data['size_bytes']} bytes")
                
            else:
                logger.warning(f"⚠️ [WebRTCS2SViewerIntegration] Unknown audio data type from Master: {type(audio_data)}")
                
        except Exception as e:
            logger.error(f"❌ [WebRTCS2SViewerIntegration] Error handling audio from Master: {e}")
            logger.error(f"❌ [WebRTCS2SViewerIntegration] Audio data type: {type(audio_data)}")
        
    async def _handle_processed_audio(self, client_id: str, audio_packet: dict):
        """
        Handle processed audio from AudioProcessor and send to S2S session manager
        Following the same pattern as Master mode
        
        Args:
            client_id: Client identifier (should be "master")
            audio_packet: Processed audio data packet
        """
        try:
            if not self.session_manager or not self.session_manager.is_active:
                logger.warning(f"⚠️ [WebRTCS2SViewerIntegration] No active session manager for audio from {client_id}")
                return
                
            logger.debug(f"🎵➡️ [WebRTCS2SViewerIntegration] Received processed audio from {client_id}: {audio_packet.get('size_bytes', 0)} bytes")
            
            # Extract audio data (same as Master implementation)
            base64_audio = audio_packet.get('audioData', '')  # Note: Master uses 'audioData', not 'base64_audio'
            
            if base64_audio:
                logger.debug(f"📨 [WebRTCS2SViewerIntegration] Processing audio for S2S: prompt='{self.default_prompt_name}', content='{self.audio_content_name}', data_size={len(base64_audio)} chars")
                
                # Send audio to S2sSessionManager using the same method as Master
                self.session_manager.add_audio_chunk(
                    prompt_name=self.default_prompt_name,
                    content_name=self.audio_content_name,
                    audio_data=base64_audio
                )
                
                logger.debug(f"✅ [WebRTCS2SViewerIntegration] Audio sent to Nova Sonic successfully via add_audio_chunk")
            else:
                logger.warning(f"⚠️ [WebRTCS2SViewerIntegration] No audioData in packet: {list(audio_packet.keys())}")
                
        except Exception as e:
            logger.error(f"❌ [WebRTCS2SViewerIntegration] Error handling processed audio: {e}")
            import traceback
            logger.error(f"❌ [WebRTCS2SViewerIntegration] Traceback: {traceback.format_exc()}")
    
    async def _handle_event_received(self, event_data: dict):
        """
        Handle event received from WebRTC Master
        
        Args:
            event_data: Event data
        """
        try:
            logger.info(f"[WebRTCS2SViewerIntegration] Event received from Master: {event_data.get('type', 'unknown')}")
            
            # In Viewer mode, we generate events locally using defaults
            # So we can ignore most events from Master, but log them for debugging
            event_type = event_data.get('type')
            logger.debug(f"[WebRTCS2SViewerIntegration] Ignoring event from Master (using local defaults): {event_type}")
                
        except Exception as e:
            logger.error(f"[WebRTCS2SViewerIntegration] Error handling event from Master: {e}")
    
    async def _generate_local_events(self):
        """
        Generate local text events instead of receiving them from data channel
        This simulates user interactions that would normally come from React client
        """
        try:
            # Wait a bit for the session to be fully established
            await asyncio.sleep(3.0)
            
            if not self.is_running or not self.session_manager or not self.session_manager.is_active:
                return
                
            logger.info("[WebRTCS2SViewerIntegration] 🎯 Generating local text event example")
            
            # Example: Send a greeting text input to Nova Sonic
            # This simulates what would normally come from the React client
            example_text = "Hello, I'm testing the Viewer mode. Can you hear me?"
            
            # Create text content
            text_content_name = "local_text_input"
            
            # Start text content as USER (not SYSTEM to avoid duplicate)
            content_start_event = {
                "event": {
                    "contentStart": {
                        "promptName": self.default_prompt_name,
                        "contentName": text_content_name,
                        "type": "TEXT",
                        "interactive": True,
                        "role": "USER",  # Use USER role instead of SYSTEM
                        "textInputConfiguration": {
                            "mediaType": "text/plain"
                        }
                    }
                }
            }
            await self.session_manager.send_raw_event(content_start_event)
            
            # Send text input (create custom event to avoid using system prompt parameter)
            text_input_event = {
                "event": {
                    "textInput": {
                        "promptName": self.default_prompt_name,
                        "contentName": text_content_name,
                        "content": example_text,
                    }
                }
            }
            await self.session_manager.send_raw_event(text_input_event)
            
            # End text content
            content_end_event = S2sEvent.content_end(self.default_prompt_name, text_content_name)
            await self.session_manager.send_raw_event(content_end_event)
            
            logger.info(f"[WebRTCS2SViewerIntegration] ✅ Sent local text event: '{example_text}'")
            
        except Exception as e:
            logger.error(f"[WebRTCS2SViewerIntegration] Error generating local events: {e}")
    
    async def _initialize_phone_detection(self):
        """
        Initialize phone detection processor (Viewer mode only)
        """
        try:
            # Check if phone detection is enabled
            if os.getenv('ENABLE_PHONE_DETECTION', '').lower() != 'true':
                logger.info("[WebRTCS2SViewerIntegration] Phone detection disabled")
                return
                
            logger.info("[WebRTCS2SViewerIntegration] Initializing phone detection...")
            
            # Import phone detection processor
            import sys
            # Go up two levels from python-webrtc-server to project root, then to examples
            project_root = os.path.dirname(os.path.dirname(__file__))
            examples_path = os.path.join(project_root, 'examples', 'connected-vehicle')
            if examples_path not in sys.path:
                sys.path.append(examples_path)
                
            from phone_detection_processor import PhoneDetectionProcessor
            
            # Create MediaRecorder instance for phone detection recordings
            from webrtc.MediaRecorder import MediaRecorder
            media_recorder = MediaRecorder()
            
            # Initialize phone detector
            self.phone_detector = PhoneDetectionProcessor(media_recorder)
            
            # Initialize the YOLO model
            if self.phone_detector.initialize_model():
                logger.info("✅ [WebRTCS2SViewerIntegration] Phone detection initialized successfully")
                
                # Check if we have a pending video track to process
                if self._pending_video_track:
                    logger.info("🔄 [WebRTCS2SViewerIntegration] Processing previously received video track")
                    await self.phone_detector.handle_video_track(self._pending_video_track, "master")
                    self._pending_video_track = None
                    logger.info("✅ [WebRTCS2SViewerIntegration] Pending video track processed successfully")
            else:
                logger.warning("⚠️ [WebRTCS2SViewerIntegration] Phone detection initialization failed")
                self.phone_detector = None
                
        except Exception as e:
            logger.error(f"❌ [WebRTCS2SViewerIntegration] Error initializing phone detection: {e}")
            self.phone_detector = None
    
    async def _handle_video_received(self, video_track):
        """
        Handle video received from WebRTC Master (separate from audio)
        
        Args:
            video_track: WebRTC video track from Master
        """
        try:
            logger.info(f"📹 [WebRTCS2SViewerIntegration] Video track received from Master: {type(video_track)}")
            
            if self.phone_detector and self.phone_detector.detection_enabled:
                logger.info(f"📱 [WebRTCS2SViewerIntegration] Starting phone detection on video track")
                # Process video track for phone detection
                await self.phone_detector.handle_video_track(video_track, "master")
            else:
                logger.warning(f"⚠️ [WebRTCS2SViewerIntegration] Phone detection not ready yet, storing video track for later")
                # Store video track for later processing when phone detection is ready
                self._pending_video_track = video_track
                # Use MediaBlackhole temporarily to consume the track
                from aiortc.contrib.media import MediaBlackhole
                MediaBlackhole().addTrack(video_track)
                # Use MediaBlackhole to consume video track if no phone detection
                from aiortc.contrib.media import MediaBlackhole
                MediaBlackhole().addTrack(video_track)
                
        except Exception as e:
            logger.error(f"❌ [WebRTCS2SViewerIntegration] Error handling video from Master: {e}")
            # Fallback: use MediaBlackhole to prevent track issues
            try:
                from aiortc.contrib.media import MediaBlackhole
                MediaBlackhole().addTrack(video_track)
            except Exception as fallback_error:
                logger.error(f"❌ [WebRTCS2SViewerIntegration] Fallback MediaBlackhole failed: {fallback_error}")
    
    def get_integration_status(self) -> dict:
        """
        Get integration status and statistics
        
        Returns:
            Dictionary with integration status
        """
        status = {
            'is_running': self.is_running,
            'master_connected': self.master_connected,
            'session_active': self.session_manager.is_active if self.session_manager else False,
            'audio_stats': self.webrtc_viewer.get_audio_stats() if self.webrtc_viewer else {},
            'phone_detection_stats': self.phone_detector.get_stats() if self.phone_detector else {},
            'region': self.region,
            'model_id': self.model_id
        }
            
        return status