import asyncio
import json
import base64
import warnings
import uuid
import logging
from s2s_events import S2sEvent
import time
import os
from datetime import datetime
from aws_sdk_bedrock_runtime.client import BedrockRuntimeClient, InvokeModelWithBidirectionalStreamOperationInput
from aws_sdk_bedrock_runtime.models import InvokeModelWithBidirectionalStreamInputChunk, BidirectionalInputPayloadPart
from aws_sdk_bedrock_runtime.config import Config, HTTPAuthSchemeResolver, SigV4AuthScheme
from smithy_aws_core.identity.environment import EnvironmentCredentialsResolver
from integration import inline_agent, bedrock_knowledge_bases as kb

# Import webrtcvad with error handling
try:
    import webrtcvad
    WEBRTCVAD_AVAILABLE = True
except ImportError as e:
    logger.error(f"❌ WebRTCVAD not available: {e}")
    logger.error("📦 Install with: pip install webrtcvad>=2.0.10")
    logger.error("🔄 Falling back to RMS-based filtering")
    WEBRTCVAD_AVAILABLE = False

# Suppress warnings
warnings.filterwarnings("ignore")

# Get logger for this module
logger = logging.getLogger(__name__)

DEBUG = True

def debug_print(message):
    """Print only if debug mode is enabled"""
    if DEBUG:
        # Use logging to ensure it appears in log files
        import logging
        logger = logging.getLogger(__name__)
        logger.info(message)


class S2sSessionManager:
    """Manages bidirectional streaming with AWS Bedrock using asyncio"""
    
    def __init__(self, region, model_id='amazon.nova-sonic-v1:0', mcp_client=None, mcp_iot_client=None, strands_agent=None):
        """Initialize the stream manager."""
        self.model_id = model_id
        self.region = region
        
        # Audio and output queues
        self.audio_input_queue = asyncio.Queue()
        self.output_queue = asyncio.Queue()
        
        self.response_task = None
        self.stream = None
        self._is_active = False
        self.bedrock_client = None
        
        # Session information
        self.prompt_name = None  # Will be set from frontend
        self.content_name = None  # Will be set from frontend
        self.audio_content_name = None  # Will be set from frontend
        self.toolUseContent = ""
        self.toolUseId = ""
        self.toolName = ""
        self.mcp_loc_client = mcp_client
        self.mcp_iot_client = mcp_iot_client
        self.strands_agent = strands_agent
        
        # Session readiness tracking
        self.session_acknowledged = False  # Track if Nova Sonic has acknowledged session setup
        self.first_response_received = False  # Track if we've received any response from Nova Sonic
        
        # Audio data saving control (disabled by default, enable with AUDIO_DEBUG_SAVE=true)
        self.audio_debug_save_enabled = os.getenv('AUDIO_DEBUG_SAVE', 'false').lower() == 'true'
        
        # Voice Activity Detection (VAD) configuration
        self.vad_enabled = os.getenv('WEBRTCVAD_ENABLED', 'true').lower() == 'true'
        
        if self.vad_enabled and WEBRTCVAD_AVAILABLE:
            # WebRTCVAD configuration
            self.vad = webrtcvad.Vad()
            self.vad_aggressiveness = int(os.getenv('VAD_AGGRESSIVENESS', '2'))  # 0-3, 2 = moderate
            self.vad.set_mode(self.vad_aggressiveness)
            logger.info(f"[S2sSessionManager] ✅ WebRTCVAD enabled - Aggressiveness level: {self.vad_aggressiveness} (set VAD_AGGRESSIVENESS 0-3 to change)")
            
            # VAD frame configuration for 16kHz audio
            self.vad_frame_duration_ms = 30  # 30ms frames (WebRTCVAD supports 10ms, 20ms, 30ms)
            self.vad_frame_size = int(16000 * self.vad_frame_duration_ms / 1000)  # 480 samples for 16kHz, 30ms
            logger.info(f"[S2sSessionManager] VAD frame configuration - Duration: {self.vad_frame_duration_ms}ms, Size: {self.vad_frame_size} samples")
            self.use_vad = True
        else:
            # VAD disabled or not available - send all audio to Nova
            if not self.vad_enabled:
                logger.info(f"[S2sSessionManager] 🔇 WebRTCVAD disabled via WEBRTCVAD_ENABLED=false - sending all audio to Nova Sonic")
            else:
                logger.info(f"[S2sSessionManager] ⚠️ WebRTCVAD not available - sending all audio to Nova Sonic")
            self.use_vad = False
        
        # Always initialize audio chunk counter for logging purposes
        self.audio_chunk_counter = 0
        
        if self.audio_debug_save_enabled:
            self.audio_save_dir = os.path.join(os.path.dirname(__file__), "..", "logs", "audio_data")
            self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._ensure_audio_dir()
            logger.debug("[S2sSessionManager] Audio debug saving ENABLED via AUDIO_DEBUG_SAVE environment variable")
        else:
            logger.debug("[S2sSessionManager] Audio debug saving DISABLED (set AUDIO_DEBUG_SAVE=true to enable)")
    
    @property
    def is_active(self):
        return self._is_active
    
    @is_active.setter
    def is_active(self, value):
        if self._is_active != value:
            logger.debug(f"🔄 [S2sSessionManager] State change: is_active {self._is_active} -> {value}")
        self._is_active = value

    def is_session_ready(self):
        """Check if session is ready for audio processing."""
        return self.prompt_name is not None and self.audio_content_name is not None
    
    def get_session_state(self):
        """Get current session state for debugging."""
        return {
            'is_active': self.is_active,
            'prompt_name': self.prompt_name,
            'audio_content_name': self.audio_content_name,
            'is_session_ready': self.is_session_ready()
        }
    
    def _ensure_audio_dir(self):
        """Ensure audio data directory exists (only if debug saving enabled)."""
        if not self.audio_debug_save_enabled:
            return
        try:
            os.makedirs(self.audio_save_dir, exist_ok=True)
            logger.debug(f"📁 [S2sSessionManager] Audio data will be saved to: {self.audio_save_dir}")
        except Exception as e:
            logger.error(f"❌ [S2sSessionManager] Failed to create audio directory: {e}")
    
    def _save_audio_chunk(self, audio_data, prompt_name, content_name):
        """Save audio chunk to file for analysis (only if debug saving enabled)."""
        # Always increment counter for logging purposes
        self.audio_chunk_counter += 1
        
        if not self.audio_debug_save_enabled:
            return None
        try:
            filename = f"audio_{self.session_id}_{self.audio_chunk_counter:04d}.wav"
            filepath = os.path.join(self.audio_save_dir, filename)
            
            # Decode base64 audio data
            audio_bytes = base64.b64decode(audio_data if isinstance(audio_data, str) else audio_data.decode('utf-8'))
            
            # Create a simple WAV file header for 16kHz, 16-bit, mono PCM
            import struct
            sample_rate = 16000
            bits_per_sample = 16
            channels = 1
            byte_rate = sample_rate * channels * bits_per_sample // 8
            block_align = channels * bits_per_sample // 8
            data_size = len(audio_bytes)
            
            # WAV header
            wav_header = struct.pack('<4sI4s4sIHHIIHH4sI',
                b'RIFF',
                36 + data_size,  # File size - 8
                b'WAVE',
                b'fmt ',
                16,  # PCM format chunk size
                1,   # PCM format
                channels,
                sample_rate,
                byte_rate,
                block_align,
                bits_per_sample,
                b'data',
                data_size
            )
            
            # Write WAV file
            with open(filepath, 'wb') as f:
                f.write(wav_header)
                f.write(audio_bytes)
            
            logger.debug(f"💾 [S2sSessionManager] Saved audio chunk: {filename} ({len(audio_bytes)} bytes)")
            return filepath
            
        except Exception as e:
            logger.error(f"❌ [S2sSessionManager] Failed to save audio chunk: {e}")
            return None

    def _initialize_client(self):
        """Initialize the Bedrock client."""
        config = Config(
            endpoint_uri=f"https://bedrock-runtime.{self.region}.amazonaws.com",
            region=self.region,
            aws_credentials_identity_resolver=EnvironmentCredentialsResolver()
        )
        self.bedrock_client = BedrockRuntimeClient(config=config)

    async def initialize_stream(self):
        """Initialize the bidirectional stream with Bedrock."""
        logger.info(f"🚀 [S2sSessionManager] Starting stream initialization...")
        debug_print(f"🚀 [S2sSessionManager] DEBUG: Starting stream initialization...")
        
        try:
            if not self.bedrock_client:
                logger.debug(f"🔧 [S2sSessionManager] Initializing Bedrock client...")
                self._initialize_client()
                logger.debug(f"✅ [S2sSessionManager] Bedrock client initialized")
        except Exception as ex:
            self.is_active = False
            logger.error(f"❌ [S2sSessionManager] Failed to initialize Bedrock client: {str(ex)}")
            import traceback
            logger.error(f"❌ [S2sSessionManager] Bedrock client error traceback: {traceback.format_exc()}")
            raise

        try:
            logger.debug(f"🔗 [S2sSessionManager] Creating bidirectional stream with model: {self.model_id}")
            # Initialize the stream
            self.stream = await self.bedrock_client.invoke_model_with_bidirectional_stream(
                InvokeModelWithBidirectionalStreamOperationInput(model_id=self.model_id)
            )
            self.is_active = True
            logger.info(f"✅ [S2sSessionManager] Bidirectional stream created successfully")
            
            # Start listening for responses
            logger.debug(f"🔄 [S2sSessionManager] Starting response processing task...")
            self.response_task = asyncio.create_task(self._process_responses())

            # Start processing audio input
            logger.debug(f"🎵 [S2sSessionManager] Starting audio input processing task...")
            asyncio.create_task(self._process_audio_input())
            
            # Wait a bit to ensure everything is set up
            await asyncio.sleep(0.1)
            
            logger.info(f"✅ [S2sSessionManager] Stream initialized successfully - is_active: {self.is_active}")
            return self
        except Exception as e:
            self.is_active = False
            logger.error(f"❌ [S2sSessionManager] Failed to initialize stream: {str(e)}")
            logger.error(f"❌ [S2sSessionManager] Exception type: {type(e).__name__}")
            import traceback
            logger.error(f"❌ [S2sSessionManager] Stream initialization error traceback: {traceback.format_exc()}")
            raise
    
    async def send_raw_event(self, event_data):
        try:
            """Send a raw event to the Bedrock stream."""
            # Add logging to see if events are reaching the session manager
            # Removed verbose event debugging
            
            if not self.stream or not self.is_active:
                logger.error(f"❌ [S2sSessionManager] Stream not initialized or closed - stream: {self.stream}, active: {self.is_active}")
                return
            
            # Extract and store prompt/content names from events (needed for audio processing)
            if "event" in event_data:
                event_type = list(event_data["event"].keys())[0]
                # Store prompt name from promptStart event
                if event_type == 'promptStart':
                    self.prompt_name = event_data['event']['promptStart']['promptName']
                    logger.debug(f"📝 [S2sSessionManager] Set prompt_name: {self.prompt_name}")
                
                # Store audio content name from contentStart event
                elif event_type == 'contentStart':
                    content_type = event_data['event']['contentStart'].get('type')
                    if content_type == 'AUDIO':
                        self.audio_content_name = event_data['event']['contentStart']['contentName']
                        logger.debug(f"🎵 [S2sSessionManager] Set audio_content_name: {self.audio_content_name}")
            else:
                logger.error(f"❌ [S2sSessionManager] No 'event' key in event_data: {list(event_data.keys()) if isinstance(event_data, dict) else 'not dict'}")
            
            event_json = json.dumps(event_data)
            # Audio data now flows through WebRTC media channel, not as audioInput events
            if "audioInput" not in event_data["event"]:
                logger.debug(event_json)
            event = InvokeModelWithBidirectionalStreamInputChunk(
                value=BidirectionalInputPayloadPart(bytes_=event_json.encode('utf-8'))
            )
            await self.stream.input_stream.send(event)

            # Close session
            if "sessionEnd" in event_data["event"]:
                self.close()
            
        except Exception as e:
            error_msg = f"❌ [S2sSessionManager] Error in send_raw_event: {str(e)}"
            debug_print(error_msg)
            logger.error(error_msg)
            if DEBUG:
                import traceback
                logger.debug(traceback.format_exc())
            # Check if this error should make the session inactive
            if "stream" in str(e).lower() or "connection" in str(e).lower():
                debug_print("🔚 [S2sSessionManager] Stream/connection error detected - setting is_active = False")
                self.is_active = False
    
    async def _process_audio_input(self):
        """Process audio input from the queue and send to Bedrock."""
        while self.is_active:
            try:
                # Get audio data from the queue
                data = await self.audio_input_queue.get()
                
                # Extract data from the queue item
                prompt_name = data.get('prompt_name')
                content_name = data.get('content_name')
                audio_bytes = data.get('audio_bytes')
                
                if not audio_bytes or not prompt_name or not content_name:
                    debug_print("Missing required audio data properties")
                    continue

                # Wait for session initialization
                session_ready = await self._wait_for_session_initialization(timeout=30.0)
                if not session_ready:
                    logger.warning(f"⚠️ [SESSION] Timeout waiting for Nova Sonic - using fallback values")
                
                # Small delay to ensure Nova Sonic is ready
                await asyncio.sleep(0.1)
                
                # Use session values if available, otherwise use the provided values
                final_prompt_name = self.prompt_name if self.prompt_name else prompt_name
                final_content_name = self.audio_content_name if self.audio_content_name else content_name
                
                # Create the audio input event
                audio_event = S2sEvent.audio_input(final_prompt_name, final_content_name, audio_bytes.decode('utf-8') if isinstance(audio_bytes, bytes) else audio_bytes)
                
                # Save audio data to file for analysis (only if debug saving enabled, but always increment counter)
                saved_file = self._save_audio_chunk(audio_bytes, final_prompt_name, final_content_name)
                
                # Analyze audio quality and perform Voice Activity Detection
                try:
                    import base64
                    import numpy as np
                    audio_data = base64.b64decode(audio_bytes if isinstance(audio_bytes, str) else audio_bytes.decode('utf-8'))
                    audio_samples = np.frombuffer(audio_data, dtype=np.int16)
                    rms = np.sqrt(np.mean(audio_samples.astype(np.float32) ** 2))
                    
                    # Log audio info with clipping detection
                    clipping_samples = np.sum(np.abs(audio_samples) >= 32767)
                    clipping_percent = (clipping_samples / len(audio_samples)) * 100
                    
                    # Only log audio chunks periodically or when there are issues
                    if self.audio_chunk_counter % 10 == 0:  # Every 10 chunks instead of every chunk
                        logger.debug(f"🎵➡️ [AUDIO] Chunk #{self.audio_chunk_counter}: {len(audio_samples)} samples, RMS={rms:.0f}, Clipping={clipping_percent:.1f}%")
                    
                    # Voice Activity Detection (if enabled)
                    if self.use_vad:
                        # WebRTCVAD - process audio in VAD-compatible frames
                        has_speech = False
                        speech_frames = 0
                        total_frames = 0
                        
                        for i in range(0, len(audio_samples), self.vad_frame_size):
                            frame = audio_samples[i:i+self.vad_frame_size]
                            if len(frame) == self.vad_frame_size:  # Only process complete frames
                                total_frames += 1
                                frame_bytes = frame.tobytes()
                                if self.vad.is_speech(frame_bytes, 16000):
                                    speech_frames += 1
                                    has_speech = True
                        
                        # Calculate speech percentage for logging
                        speech_percentage = (speech_frames / total_frames * 100) if total_frames > 0 else 0
                        
                        if not has_speech:
                            logger.debug(f"🔇 [VAD] No speech detected ({speech_frames}/{total_frames} frames, {speech_percentage:.1f}%) - skipping transmission to Nova Sonic")
                            continue  # Skip sending this audio chunk to Nova Sonic
                        else:
                            logger.debug(f"🎤 [VAD] Speech detected ({speech_frames}/{total_frames} frames, {speech_percentage:.1f}%) - sending audio chunk to Nova Sonic")
                    else:
                        # VAD disabled - send all audio to Nova Sonic
                        logger.debug(f"🎵 [NO-FILTER] Sending all audio to Nova Sonic (VAD disabled)")
                        
                    # Audio quality monitoring (for clipping detection)
                    if clipping_percent > 10:
                        logger.error(f"🔥 [AUDIO] SEVERE CLIPPING detected ({clipping_percent:.1f}%) - audio will be distorted!")
                    elif clipping_percent > 1:
                        logger.warning(f"⚠️ [AUDIO] Clipping detected ({clipping_percent:.1f}%) - reducing microphone gain recommended")
                    
                except Exception as e:
                    logger.debug(f"🎵➡️ [AUDIO] Chunk #{self.audio_chunk_counter}: Audio analysis failed - {e}")
                    # On analysis failure, fall back to sending the audio (fail-safe behavior)
                    logger.debug(f"🔄 [AUDIO] Falling back to sending audio due to analysis failure")
                
                # Send the event (only if it passed quality control)
                await self.send_raw_event(audio_event)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ [AUDIO] Processing error: {str(e)}")
                # Continue processing despite errors
    
    async def _wait_for_session_initialization(self, timeout=30.0):
        """Wait for session to be properly initialized with prompt_name and audio_content_name.
        
        Args:
            timeout: Maximum time to wait in seconds
            
        Returns:
            bool: True if session is ready, False if timeout occurred
        """
        start_time = time.time()
        check_interval = 0.1  # Check every 100ms
        
        while (time.time() - start_time) < timeout:
            if not self.is_active:
                return False
                
            # Check if we have the required session values
            session_params_ready = self.prompt_name is not None and self.audio_content_name is not None
            
            # More lenient check - don't require first response for audio processing
            if session_params_ready:
                elapsed = time.time() - start_time
                logger.debug(f"✅ [SESSION] Session params ready after {elapsed:.1f}s")
                return True
            
            await asyncio.sleep(check_interval)
        
        # Timeout occurred - use fallback values
        logger.warning(f"⏰ [SESSION] Timeout after {timeout}s - will use fallback values")
        return False

    def add_audio_chunk(self, prompt_name, content_name, audio_data):
        """Add an audio chunk to the queue."""
        self.audio_input_queue.put_nowait({
            'prompt_name': prompt_name,
            'content_name': content_name,
            'audio_bytes': audio_data
        })
    
    async def _process_responses(self):
        """Process incoming responses from Bedrock."""
        debug_print("🎧 [S2sSessionManager] Starting _process_responses loop")
        logger.debug("🎧 [S2sSessionManager] Starting _process_responses loop")
        
        while self.is_active:
            try:            
                output = await self.stream.await_output()
                result = await output[1].receive()
                
                if result.value and result.value.bytes_:
                    response_data = result.value.bytes_.decode('utf-8')
                    
                    json_data = json.loads(response_data)
                    json_data["timestamp"] = int(time.time() * 1000)  # Milliseconds since epoch
                    
                    # Debug log for events
                    if 'event' in json_data:
                        event_keys = list(json_data['event'].keys())
                        logger.debug(f"🎭 [NOVA] Received event: {event_keys}")
                        
                        # Special info log for completion events (keep these visible)
                        if 'completionEnd' in event_keys or 'completionStart' in event_keys:
                            logger.info(f"🎭 [NOVA] ⭐ COMPLETION EVENT: {event_keys}")
                            logger.debug(f"🎭 [NOVA] ⭐ Full event data: {json_data}")
                    
                    event_name = None
                    if 'event' in json_data:
                        event_name = list(json_data["event"].keys())[0]
                        
                        # Mark first response received
                        if not self.first_response_received:
                            self.first_response_received = True
                            logger.info(f"✅ [NOVA] First response: {event_name}")
                        
                        # Log important responses only
                        if event_name == "audioOutput":
                            audio_content = json_data['event']['audioOutput'].get('content', '')
                            logger.debug(f"🎵⬅️ [NOVA] AudioOutput received: {len(audio_content)} chars")
                        elif event_name == "textOutput":
                            text_content = json_data['event']['textOutput'].get('content', '')
                            logger.info(f"📝⬅️ [NOVA] TextOutput: '{text_content[:100]}{'...' if len(text_content) > 100 else ''}'")
                        elif event_name == "contentStart":
                            content_type = json_data['event']['contentStart'].get('type', 'UNKNOWN')
                            content_name = json_data['event']['contentStart'].get('contentName', 'unnamed')
                            logger.info(f"🚀 [NOVA] ContentStart received: type={content_type}, name={content_name}")
                        elif event_name == "contentEnd":
                            content_type = json_data['event']['contentEnd'].get('type', 'UNKNOWN')
                            content_name = json_data['event']['contentEnd'].get('contentName', 'unnamed')
                            logger.info(f"🏁 [NOVA] ContentEnd received: type={content_type}, name={content_name}")
                        elif event_name == "completionStart":
                            logger.info(f"🎬 [NOVA] CompletionStart received")
                        elif event_name == "completionEnd":
                            logger.info(f"🎭 [NOVA] CompletionEnd received")
                        elif event_name == "usageEvent":
                            # Only log speech detection
                            usage_details = json_data['event']['usageEvent'].get('details', {})
                            delta = usage_details.get('delta', {})
                            input_tokens = delta.get('input', {})
                            speech_tokens = input_tokens.get('speechTokens', 0)
                            text_tokens = input_tokens.get('textTokens', 0)
                            
                            if speech_tokens > 0:
                                logger.info(f"🎤 [NOVA] Speech detected: {speech_tokens} speech tokens")
                                
                                # Guidance for good speech detection without response
                                if speech_tokens > 100:
                                    logger.info(f"💡 [NOVA] Good speech detected! Try complete sentences with clear pauses.")
                        # Skip logging other event types to reduce noise
                        
                        # Handle tool use detection
                        if event_name == 'toolUse':
                            self.toolUseContent = json_data['event']['toolUse']
                            self.toolName = json_data['event']['toolUse']['toolName']
                            self.toolUseId = json_data['event']['toolUse']['toolUseId']
                            debug_print(f"Tool use detected: {self.toolName}, ID: {self.toolUseId}, "+ json.dumps(json_data['event']))

                        # Process tool use when content ends
                        elif event_name == 'contentEnd' and json_data['event'][event_name].get('type') == 'TOOL':
                            prompt_name = json_data['event']['contentEnd'].get("promptName")
                            debug_print("Processing tool use and sending result")
                            toolResult = await self.processToolUse(self.toolName, self.toolUseContent)
                                
                            # Send tool start event
                            toolContent = str(uuid.uuid4())
                            tool_start_event = S2sEvent.content_start_tool(prompt_name, toolContent, self.toolUseId)
                            await self.send_raw_event(tool_start_event)
                            
                            # Send tool result event
                            if isinstance(toolResult, dict):
                                content_json_string = json.dumps(toolResult)
                            else:
                                content_json_string = toolResult

                            tool_result_event = S2sEvent.text_input_tool(prompt_name, toolContent, content_json_string)
                            logger.debug(f"🔧 [NOVA] Tool result: {tool_result_event}")
                            await self.send_raw_event(tool_result_event)

                            # Send tool content end event
                            tool_content_end_event = S2sEvent.content_end(prompt_name, toolContent)
                            await self.send_raw_event(tool_content_end_event)
                    
                    # Put the response in the output queue for forwarding to the frontend
                    await self.output_queue.put(json_data)


            except json.JSONDecodeError as ex:
                logger.error(f"❌ [NOVA] JSON decode error: {str(ex)}")
                await self.output_queue.put({"raw_data": response_data})
            except StopAsyncIteration:
                logger.info(f"🔚 [NOVA] Stream ended")
                break
            except Exception as e:
                if "ValidationException" in str(e):
                    logger.error(f"❌ [NOVA] Validation error: {str(e)}")
                else:
                    logger.error(f"❌ [NOVA] Unexpected error: {str(e)}")
                break

        self.is_active = False
        self.close()

    async def processToolUse(self, toolName, toolUseContent):
        """Return the tool result"""
        logger.debug(f"🔧 [NOVA] Tool Use Content: {toolUseContent}")

        toolName = toolName.lower()
        content, result = None, None
        try:
            if toolUseContent.get("content"):
                # Parse the JSON string in the content field
                query_json = json.loads(toolUseContent.get("content"))
                content = toolUseContent.get("content")  # Pass the JSON string directly to the agent
                logger.debug(f"🔧 [NOVA] Extracted query: {content}")
            
            # Simple toolUse to get system time in UTC
            if toolName == "getdatetool":
                from datetime import datetime, timezone
                result = datetime.now(timezone.utc).strftime('%A, %Y-%m-%d %H-%M-%S')

            # Bedrock Knowledge Bases (RAG)
            if toolName == "getkbtool":
                result = kb.retrieve_kb(content)

            # Bedrock Knowledge Bases (RAG)
            if toolName == "getkbtool_smarthome":
                result = kb.retrieve_kb(content)

            # MCP integration - location search                        
            if toolName == "getlocationtool":
                if self.mcp_loc_client:
                    result = await self.mcp_loc_client.call_tool(content)
            
            # MCP integration - IoT Core MQTT publishing
            if toolName == "publish_mqtt":
                logger.info(f"🔧 [NOVA] Processing publish_mqtt tool")
                logger.debug(f"🔧 [NOVA] MCP IoT client available: {self.mcp_iot_client is not None}")
                logger.debug(f"🔧 [NOVA] Tool content: {content}")
                
                if self.mcp_iot_client:
                    try:
                        logger.info(f"🔧 [NOVA] Calling MCP IoT client...")
                        result = await self.mcp_iot_client.call_tool(content)
                        logger.info(f"🔧 [NOVA] MCP IoT client result: {result}")
                    except Exception as e:
                        logger.error(f"❌ [NOVA] MCP IoT client error: {e}")
                        result = f"Error publishing MQTT message: {str(e)}"
                else:
                    logger.error(f"❌ [NOVA] MCP IoT client not available")
                    result = "IoT Core MCP client not initialized"
            
            # Strands Agent integration - weather questions
            if toolName == "externalagent":
                if self.strands_agent:
                    result = self.strands_agent.query(content)

            # Bedrock Agents integration - Bookings
            if toolName == "getbookingdetails":
                try:
                    # Pass the tool use content (JSON string) directly to the agent
                    result = await inline_agent.invoke_agent(content)
                    # Try to parse and format if needed
                    try:
                        booking_json = json.loads(result)
                        if "bookings" in booking_json:
                            result = await inline_agent.invoke_agent(
                                f"Format this booking information for the user: {result}"
                            )
                    except Exception:
                        pass  # Not JSON, just return as is
                    
                except json.JSONDecodeError as e:
                    logger.error(f"🔧 [NOVA] JSON decode error: {str(e)}")
                    return {"result": f"Invalid JSON format for booking details: {str(e)}"}
                except Exception as e:
                    logger.error(f"🔧 [NOVA] Error processing booking details: {str(e)}")
                    return {"result": f"Error processing booking details: {str(e)}"}

            if not result:
                result = "no result found"

            return {"result": result}
        except Exception as ex:
            logger.error(f"🔧 [NOVA] Tool processing error: {ex}")
            return {"result": "An error occurred while attempting to retrieve information related to the toolUse event."}
    
    async def close(self):
        """Close the stream properly."""
        debug_print("🔚 [S2sSessionManager] close() method called")
        if not self.is_active:
            debug_print("🔚 [S2sSessionManager] Already inactive, skipping close")
            return
            
        # Wait a bit for any final events (like completionEnd) before closing
        debug_print("🔚 [S2sSessionManager] Waiting for final events before closing...")
        await asyncio.sleep(1.5)  # Wait 1.5 seconds for final events
            
        debug_print("🔚 [S2sSessionManager] Setting is_active = False in close()")
        self.is_active = False
        
        if self.stream:
            debug_print("🔚 [S2sSessionManager] Closing Bedrock stream")
            try:
                await self.stream.input_stream.close()
                debug_print("✅ [S2sSessionManager] Bedrock stream closed successfully")
            except Exception as e:
                error_msg = f"❌ [S2sSessionManager] Error closing Bedrock stream: {str(e)}"
                debug_print(error_msg)
                logger.error(error_msg)
        
        if self.response_task and not self.response_task.done():
            debug_print("🔚 [S2sSessionManager] Cancelling response task")
            self.response_task.cancel()
            try:
                await self.response_task
                debug_print("✅ [S2sSessionManager] Response task cancelled successfully")
            except asyncio.CancelledError:
                debug_print("✅ [S2sSessionManager] Response task cancellation confirmed")
            except Exception as e:
                error_msg = f"❌ [S2sSessionManager] Error cancelling response task: {str(e)}"
                debug_print(error_msg)
                logger.error(error_msg)
        
        debug_print("✅ [S2sSessionManager] Session manager closed completely")
        