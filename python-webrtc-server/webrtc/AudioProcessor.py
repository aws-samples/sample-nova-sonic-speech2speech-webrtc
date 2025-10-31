"""
AudioProcessor - Handles WebRTC audio reception and format conversion for Nova S2S
Implements WebRTC audio reception, format conversion, and integration with S2sSessionManager
"""

import asyncio
import base64
import logging
import numpy as np
import os
import struct
from typing import Callable, Optional, Dict, Any
from aiortc import MediaStreamTrack
from aiortc.mediastreams import MediaStreamError
import time
import threading
from collections import deque
from scipy import signal

logger = logging.getLogger(__name__)

class AudioProcessor:
    """
    Handles WebRTC audio reception and format conversion for Nova Sonic integration
    Converts WebRTC audio formats to Nova Sonic's expected 16kHz PCM format
    """
    
    def __init__(self):
        # Audio configuration
        self.target_sample_rate = 16000  # Nova Sonic expects 16kHz
        self.target_channels = 1         # Mono audio
        self.target_sample_width = 2     # 16-bit samples
        
        # Processing state
        self.is_processing = False
        self.audio_tracks: Dict[str, MediaStreamTrack] = {}
        self.processing_tasks: Dict[str, asyncio.Task] = {}
        
        # Audio buffers for each client
        self.audio_buffers: Dict[str, deque] = {}
        self.buffer_lock = threading.Lock()
        
        # Callbacks
        self.on_audio_data: Optional[Callable] = None
        self.on_error: Optional[Callable] = None
        
        # S2S session state tracking
        self.session_managers: Dict[str, object] = {}  # client_id -> S2sSessionManager
        
        # Statistics
        self.stats = {
            'frames_processed': 0,
            'bytes_processed': 0,
            'conversion_errors': 0,
            'last_activity': None,
            'ignored_frames_before_s2s': 0  # Track ignored frames
        }
        
        # Session-level audio configuration cache to reduce logging
        self.session_audio_config: Dict[str, dict] = {}
        
        # Track what we've already logged per client to reduce repetitive messages
        self.logged_info: Dict[str, set] = {}  # client_id -> set of logged message types
        
        # Audio file saving control (disabled by default, enable with AUDIO_DEBUG_SAVE=true)
        self.audio_debug_save_enabled = os.getenv('AUDIO_DEBUG_SAVE', 'false').lower() == 'true'
        
        if self.audio_debug_save_enabled:
            # Original audio saving for analysis
            self.original_audio_counter = 0
            self.original_audio_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "original_audio")
            self._ensure_original_audio_dir()
            
            # Audio merging for complete file generation
            self.merged_audio_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "merged_audio")
            self._ensure_merged_audio_dir()
            self.original_audio_buffer = []  # Buffer for original audio chunks
            self.processed_audio_buffer = []  # Buffer for processed audio chunks
            self.merge_interval = 200  # Merge every N chunks (increased for longer files)
            self.last_merge_time = time.time()
            self.merge_timeout = 60  # Merge every 60 seconds (increased for longer files)
            self.current_session_id = None  # Track current session for file naming
            
            logger.debug("[AudioProcessor] Audio debug saving ENABLED via AUDIO_DEBUG_SAVE environment variable")
        else:
            logger.debug("[AudioProcessor] Audio debug saving DISABLED (set AUDIO_DEBUG_SAVE=true to enable)")
        
    def set_audio_callback(self, callback: Callable[[str, dict], None]):
        """
        Set callback for processed audio data
        
        Args:
            callback: Function that takes (client_id, audio_packet)
        """
        self.on_audio_data = callback
        
    def set_error_callback(self, callback: Callable[[str, Exception], None]):
        """
        Set callback for error handling
        
        Args:
            callback: Function that takes (client_id, error)
        """
        self.on_error = callback
        
    def set_session_manager(self, client_id: str, session_manager):
        """
        Set S2S session manager for a client to track session state
        
        Args:
            client_id: Client identifier
            session_manager: S2sSessionManager instance
        """
        self.session_managers[client_id] = session_manager
        # Set current session ID for file naming
        self.current_session_id = client_id
        logger.debug(f"[AudioProcessor] Set session manager for {client_id}")
        
    def has_received_session_start(self, client_id: str) -> bool:
        """
        Check if S2S session has started for a client
        
        Args:
            client_id: Client identifier
            
        Returns:
            True if session has started and is ready for audio processing
        """
        if client_id not in self.session_managers:
            return False
            
        session_manager = self.session_managers[client_id]
        
        # Check if session manager is active and has received session setup
        if not hasattr(session_manager, 'is_active') or not session_manager.is_active:
            return False
            
        # Check if session is ready (has prompt_name and audio_content_name)
        if hasattr(session_manager, 'is_session_ready'):
            return session_manager.is_session_ready()
            
        # Fallback: check if basic session parameters are set
        return (hasattr(session_manager, 'prompt_name') and 
                hasattr(session_manager, 'audio_content_name') and
                session_manager.prompt_name is not None and 
                session_manager.audio_content_name is not None)
        
    def start_processing(self):
        """Start audio processing"""
        self.is_processing = True
        logger.debug("[AudioProcessor] Started audio processing")
        
    def stop_processing(self):
        """Stop audio processing"""
        self.is_processing = False
        
        # Force merge any remaining buffered audio before stopping (only if debug saving enabled)
        if self.audio_debug_save_enabled:
            try:
                self.force_merge_audio()
            except Exception as e:
                logger.error(f"[AudioProcessor] Error during final audio merge: {e}")
        
        # Cancel all processing tasks
        for client_id, task in self.processing_tasks.items():
            if not task.done():
                task.cancel()
                
        self.processing_tasks.clear()
        self.audio_tracks.clear()
        
        with self.buffer_lock:
            self.audio_buffers.clear()
        
        # Clear all session configurations
        self.session_audio_config.clear()
        
        # Clear all session manager references
        self.session_managers.clear()
            
        logger.debug("[AudioProcessor] Stopped audio processing")
        
    async def add_audio_track(self, client_id: str, track: MediaStreamTrack):
        """
        Add audio track for processing
        
        Args:
            client_id: Unique identifier for the client
            track: WebRTC audio track to process
        """
        try:
            if not self.is_processing:
                logger.debug(f"[AudioProcessor] Not processing, ignoring track for {client_id}")
                return
                
            logger.info(f"🎵 [AudioProcessor] Starting audio processing for {client_id}")
            
            # Store track reference
            self.audio_tracks[client_id] = track
            
            # Initialize audio buffer for this client
            with self.buffer_lock:
                self.audio_buffers[client_id] = deque(maxlen=1000)  # Limit buffer size
            
            # Initialize logged info for this client
            if client_id not in self.logged_info:
                self.logged_info[client_id] = set()
                
            # Start processing task for this track
            task = asyncio.create_task(self._process_audio_track(client_id, track))
            self.processing_tasks[client_id] = task
            
            logger.debug(f"[AudioProcessor] Started processing audio track for {client_id}")
            
        except Exception as e:
            logger.error(f"[AudioProcessor] Error adding audio track for {client_id}: {e}")
            if self.on_error:
                self.on_error(client_id, e)
                
    async def remove_audio_track(self, client_id: str):
        """
        Remove audio track and stop processing
        
        Args:
            client_id: Client identifier
        """
        try:
            logger.debug(f"[AudioProcessor] Removing audio track for client: {client_id}")
            
            # Cancel processing task
            if client_id in self.processing_tasks:
                task = self.processing_tasks[client_id]
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                del self.processing_tasks[client_id]
                
            # Remove track reference
            if client_id in self.audio_tracks:
                del self.audio_tracks[client_id]
                
            # Clear audio buffer
            with self.buffer_lock:
                if client_id in self.audio_buffers:
                    del self.audio_buffers[client_id]
            
            # Clear session audio configuration
            if client_id in self.session_audio_config:
                del self.session_audio_config[client_id]
                logger.debug(f"[AudioProcessor] Cleared session audio config for {client_id}")
                
            # Clear session manager reference
            if client_id in self.session_managers:
                del self.session_managers[client_id]
                logger.debug(f"[AudioProcessor] Cleared session manager reference for {client_id}")
            
            # Clear logged info to allow fresh logging for new connections
            if client_id in self.logged_info:
                del self.logged_info[client_id]
                logger.debug(f"[AudioProcessor] Cleared logged info for {client_id}")
            
            # Force merge any remaining buffered audio when client disconnects (only if debug saving enabled)
            if self.audio_debug_save_enabled:
                try:
                    if hasattr(self, 'original_audio_buffer') and hasattr(self, 'processed_audio_buffer'):
                        if self.original_audio_buffer or self.processed_audio_buffer:
                            logger.debug(f"[AudioProcessor] Client {client_id} disconnected, merging remaining audio...")
                            self.force_merge_audio()
                except Exception as e:
                    logger.error(f"[AudioProcessor] Error merging audio on client disconnect: {e}")
                    
            logger.debug(f"[AudioProcessor] Removed audio track for {client_id}")
            
        except Exception as e:
            logger.error(f"[AudioProcessor] Error removing audio track for {client_id}: {e}")
            
    async def _process_audio_track(self, client_id: str, track: MediaStreamTrack):
        """
        Process audio frames from WebRTC track
        
        Args:
            client_id: Client identifier
            track: Audio track to process
        """
        try:
            logger.debug(f"[AudioProcessor] Starting audio processing for {client_id}")
            
            frame_count = 0
            chunk_size = 4096  # Process audio in chunks
            audio_chunk_buffer = []
            
            while self.is_processing:
                try:
                    # Receive audio frame from WebRTC
                    frame = await track.recv()
                    
                    if not frame:
                        continue
                        
                    frame_count += 1
                    self.stats['frames_processed'] += 1
                    self.stats['last_activity'] = time.time()
                    
                    # Check if S2S session has started before processing audio
                    if not self.has_received_session_start(client_id):
                        # Ignore audio data before S2S session starts
                        self.stats['ignored_frames_before_s2s'] += 1
                        
                        # Log periodically to avoid spam
                        if frame_count % 50 == 0:
                            logger.debug(f"🚫 [AudioProcessor] Ignoring audio frame #{frame_count} from {client_id} - S2S session not started yet")
                        continue
                    
                    # Log audio frame reception (every 50 frames to avoid spam)
                    if frame_count % 50 == 0:
                        frame_duration_ms = (frame.samples / frame.sample_rate) * 1000
                        logger.debug(f"🎤 [AudioProcessor] Received WebRTC frame #{frame_count} from {client_id}: {frame.samples} samples, {frame.sample_rate}Hz, {frame_duration_ms:.1f}ms duration")
                    
                    # Convert frame to numpy array
                    audio_data = self._frame_to_numpy(frame, client_id)
                    
                    if audio_data is None:
                        continue
                    
                    # DEBUG: Log actual array size vs expected
                    expected_samples = int(frame.samples)
                    actual_samples = len(audio_data)
                    if actual_samples != expected_samples:
                        logger.warning(f"🔍 [AudioProcessor] SAMPLE MISMATCH for {client_id}: Expected {expected_samples}, Got {actual_samples} samples")
                    else:
                        # Only log sample count on first few frames to avoid spam
                        if client_id not in self.logged_info:
                            self.logged_info[client_id] = set()
                        if 'sample_count' not in self.logged_info[client_id]:
                            logger.debug(f"✅ [AudioProcessor] Sample count correct for {client_id}: {actual_samples} samples")
                            self.logged_info[client_id].add('sample_count')
                    
                    # SAVE ORIGINAL RAW AUDIO for VLC analysis (only if debug saving enabled)
                    if self.audio_debug_save_enabled:
                        self._save_original_audio(client_id, audio_data, frame.sample_rate)
                        
                        # Add to buffer for merging into complete WAV file (copy to avoid reference issues)
                        self._add_to_audio_buffer(audio_data.copy(), frame.sample_rate, is_original=True)
                        
                    # Add to chunk buffer
                    audio_chunk_buffer.append(audio_data)
                    
                    # Process when we have enough data or periodically
                    total_samples = sum(len(chunk) for chunk in audio_chunk_buffer)
                    if total_samples >= chunk_size or frame_count % 10 == 0:
                        
                        if audio_chunk_buffer:
                            # Concatenate chunks
                            combined_audio = np.concatenate(audio_chunk_buffer)
                            audio_chunk_buffer = []
                            
                            # Convert to Nova Sonic format and send (with original sample rate)
                            await self._process_audio_chunk(client_id, combined_audio, frame.sample_rate)
                            
                except MediaStreamError:
                    logger.debug(f"[AudioProcessor] Audio track ended for {client_id}")
                    break
                except asyncio.CancelledError:
                    logger.debug(f"[AudioProcessor] Audio processing cancelled for {client_id}")
                    break
                except Exception as e:
                    logger.error(f"[AudioProcessor] Error processing frame for {client_id}: {e}")
                    self.stats['conversion_errors'] += 1
                    
                    if self.on_error:
                        self.on_error(client_id, e)
                        
                    # Continue processing despite errors
                    continue
                    
            logger.debug(f"[AudioProcessor] Finished processing audio for {client_id}, processed {frame_count} frames")
            
            # Log statistics about ignored frames
            ignored_count = self.stats.get('ignored_frames_before_s2s', 0)
            if ignored_count > 0:
                logger.debug(f"📊 [AudioProcessor] Session stats for {client_id}: {ignored_count} frames ignored before S2S session start")
            
        except Exception as e:
            logger.error(f"[AudioProcessor] Fatal error in audio processing for {client_id}: {e}")
            if self.on_error:
                self.on_error(client_id, e)
                
    def _frame_to_numpy(self, frame, client_id: str) -> Optional[np.ndarray]:
        """
        Convert WebRTC audio frame to numpy array
        
        Args:
            frame: WebRTC audio frame
            client_id: Client identifier for session-level configuration caching
            
        Returns:
            Numpy array of audio samples or None if conversion fails
        """
        try:
            # Convert frame to numpy array
            # WebRTC frames are typically in planar format
            if hasattr(frame, 'to_ndarray'):
                # aiortc AudioFrame
                audio_array = frame.to_ndarray()
                
                # TRACE: Log original array shape and size
                logger.trace(f"🔍 [AudioProcessor] Raw frame.to_ndarray() shape: {audio_array.shape}, size: {audio_array.size}")
                
                # Check if we have session configuration cached for this client
                session_config = self.session_audio_config.get(client_id)
                is_first_analysis = session_config is None
                
                # MEDIARECORDER-INSPIRED: Use the proven stereo detection logic from MediaRecorder.py
                # This logic has been verified to work correctly in test mode
                expected_samples = frame.samples  # WebRTC reported sample count
                
                if audio_array.ndim == 2:
                    if is_first_analysis:
                        logger.debug(f"🔍 [AudioProcessor] 2D array detected: {audio_array.shape}")
                    
                    # Special case: (1, 1920) with 960 expected samples = interleaved stereo in single row
                    if audio_array.shape[0] == 1 and audio_array.shape[1] == expected_samples * 2:
                        if is_first_analysis:
                            logger.debug(f"🔍 [AudioProcessor] Detected interleaved stereo in 2D array: (1, {audio_array.shape[1]}) -> {expected_samples} samples")
                        # Flatten and then de-interleave
                        audio_array = audio_array.flatten()
                        audio_array = audio_array[::2]  # Take every other sample (left channel)
                        if is_first_analysis:
                            logger.debug(f"🔍 [AudioProcessor] After de-interleaving: {len(audio_array)} samples")
                    # Check if it's channels x samples or samples x channels
                    elif audio_array.shape[0] < audio_array.shape[1]:
                        # Likely channels x samples (e.g., 2 x 480)
                        if audio_array.shape[0] == 1:
                            # Mono: 1 x samples
                            audio_array = audio_array.flatten()
                        elif audio_array.shape[0] == 2:
                            # Stereo: 2 x samples - take left channel
                            if is_first_analysis:
                                logger.debug(f"🔍 [AudioProcessor] Taking left channel from 2D stereo array")
                            audio_array = audio_array[0]
                        else:
                            # Multi-channel: take first channel
                            audio_array = audio_array[0]
                    else:
                        # Likely samples x channels (e.g., 480 x 2)
                        if audio_array.shape[1] == 1:
                            # Mono: samples x 1
                            audio_array = audio_array.flatten()
                        elif audio_array.shape[1] == 2:
                            # Stereo: samples x 2 - take left channel
                            if is_first_analysis:
                                logger.debug(f"🔍 [AudioProcessor] Taking left channel from samples x channels array")
                            audio_array = audio_array[:, 0]
                        else:
                            # Multi-channel: take first channel
                            audio_array = audio_array[:, 0]
                            
                elif audio_array.ndim == 1:
                    if is_first_analysis:
                        logger.debug(f"🔍 [AudioProcessor] 1D array detected: length={len(audio_array)}, expected_samples={expected_samples}")
                    
                    # Check if it's interleaved stereo (L,R,L,R,...)
                    if len(audio_array) == expected_samples * 2:
                        if is_first_analysis:
                            logger.debug(f"🔍 [AudioProcessor] Detected interleaved stereo! De-interleaving {len(audio_array)} samples to {expected_samples}")
                        # De-interleave: take every other sample (left channel)
                        audio_array = audio_array[::2]
                        if is_first_analysis:
                            logger.debug(f"🔍 [AudioProcessor] After de-interleaving: {len(audio_array)} samples")
                    elif len(audio_array) == expected_samples:
                        if is_first_analysis:
                            logger.debug(f"🔍 [AudioProcessor] Already correct mono length: {len(audio_array)} samples")
                    else:
                        if is_first_analysis:
                            logger.warning(f"🔍 [AudioProcessor] Unexpected array length: {len(audio_array)}, expected {expected_samples} or {expected_samples * 2}")
                else:
                    logger.warning(f"[AudioProcessor] Unexpected audio array shape: {audio_array.shape}")
                    return None
                
                # CRITICAL FIX: Simplified audio format handling to prevent slow audio
                # The previous logic was incorrectly assuming certain data lengths meant stereo
                # and was discarding samples, making audio play at wrong speed
                
                # Log audio array info for debugging
                if is_first_analysis:
                    logger.debug(f"🔍 [AudioProcessor] Audio array for {client_id}: {len(audio_array)} samples")
                    logger.debug(f"   Data type: {audio_array.dtype}")
                    logger.debug(f"   Shape: {audio_array.shape}")
                    logger.debug(f"   Sample range: {np.min(audio_array):.3f} to {np.max(audio_array):.3f}")
                
                # Cache the configuration for this session (simplified)
                if client_id not in self.session_audio_config:
                    self.session_audio_config[client_id] = {
                        'original_shape': audio_array.shape,
                        'analysis_completed': True
                    }
                    logger.debug(f"📝 [AudioProcessor] Cached audio config for {client_id}")
                    
                # Convert to float32 and check the data type/range
                if audio_array.dtype == np.int16:
                    # Convert int16 to float32 normalized to [-1.0, 1.0]
                    float32_array = audio_array.astype(np.float32) / 32767.0
                    logger.trace(f"🔧 [AudioProcessor] Converted int16 to normalized float32")
                elif audio_array.dtype == np.int32:
                    # Convert int32 to float32 normalized to [-1.0, 1.0]
                    float32_array = audio_array.astype(np.float32) / 2147483647.0
                    logger.trace(f"🔧 [AudioProcessor] Converted int32 to normalized float32")
                else:
                    # Assume it's already float32, but check the range
                    float32_array = audio_array.astype(np.float32)
                    max_val = np.max(np.abs(float32_array))
                    if max_val > 10.0:
                        # Looks like unnormalized integer data in float format
                        if max_val <= 32767:
                            float32_array = float32_array / 32767.0
                            logger.trace(f"🔧 [AudioProcessor] Normalized float32 data (was int16-like): max {max_val} -> {np.max(np.abs(float32_array)):.3f}")
                        elif max_val <= 2147483647:
                            float32_array = float32_array / 2147483647.0
                            logger.trace(f"🔧 [AudioProcessor] Normalized float32 data (was int32-like): max {max_val} -> {np.max(np.abs(float32_array)):.3f}")
                
                # Log WebRTC audio levels after normalization
                rms = np.sqrt(np.mean(float32_array ** 2))
                max_val = np.max(np.abs(float32_array))
                logger.trace(f"[AudioProcessor] WebRTC audio levels: RMS={rms:.3f}, Max={max_val:.3f}")
                
                return float32_array
                
            else:
                logger.warning("[AudioProcessor] Frame does not support to_ndarray conversion")
                return None
                
        except Exception as e:
            logger.error(f"[AudioProcessor] Error converting frame to numpy: {e}")
            return None
            
    async def _process_audio_chunk(self, client_id: str, audio_data: np.ndarray, original_sample_rate: int = 48000):
        """
        Process audio chunk and convert to Nova Sonic format
        
        Args:
            client_id: Client identifier
            audio_data: Audio data as numpy array (float32, normalized)
            original_sample_rate: Original sample rate of the audio data
        """
        try:
            if len(audio_data) == 0:
                return
            
            # Check if this is a test client
            is_test_client = 'test' in client_id.lower()
            
            # Debug: Check input audio levels BEFORE processing
            input_rms = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2))
            input_max = np.max(np.abs(audio_data))
            input_clipping = np.sum(np.abs(audio_data) >= 0.99) / len(audio_data) * 100
            
            # Only log audio analysis occasionally to avoid spam
            if client_id not in self.logged_info:
                self.logged_info[client_id] = set()
            
            # Log audio analysis only for first few frames or when there are issues
            should_log_audio = (
                'audio_analysis' not in self.logged_info[client_id] or
                input_clipping > 5.0 or  # Log if significant clipping
                input_rms < 0.001  # Log if very quiet (potential issue)
            )
            
            if should_log_audio:
                if is_test_client:
                    logger.debug(f"🧪 [AudioProcessor] TEST MODE - Processing audio for {client_id}: RMS={input_rms:.3f}, Max={input_max:.3f}, Clipping={input_clipping:.1f}%")
                else:
                    logger.debug(f"🔍 [AudioProcessor] INPUT AUDIO for {client_id}: RMS={input_rms:.3f}, Max={input_max:.3f}, Clipping={input_clipping:.1f}%")
                self.logged_info[client_id].add('audio_analysis')
                
            # Resample to Nova Sonic's required 16kHz if needed
            if original_sample_rate != self.target_sample_rate:
                # PRECISION RESAMPLING: Calculate exact target length to preserve timing
                # MediaRecorder.py doesn't resample, but when we must resample for Nova Sonic,
                # we need to be extremely precise to avoid the timing issues
                input_duration = len(audio_data) / original_sample_rate
                precise_target_length = int(input_duration * self.target_sample_rate)
                
                # Also calculate the simple ratio for comparison
                resample_ratio = self.target_sample_rate / original_sample_rate
                original_length = len(audio_data)
                simple_target_length = int(original_length * resample_ratio)
                
                # Only log resampling setup once per client to avoid spam
                resampling_key = f"resampling_{original_sample_rate}_{self.target_sample_rate}"
                if resampling_key not in self.logged_info[client_id]:
                    logger.info(f"🔍 [AudioProcessor] RESAMPLING SETUP for {client_id}: {original_sample_rate}Hz → {self.target_sample_rate}Hz")
                    self.logged_info[client_id].add(resampling_key)
                # Only log detailed resampling info once per client
                if resampling_key not in self.logged_info[client_id]:
                    logger.debug(f"   Input duration: {input_duration:.6f}s, length: {original_length} samples")
                    logger.debug(f"   Target length: {precise_target_length} samples")
                
                # Use the precise target length
                target_length = precise_target_length
                
                if target_length > 0:
                    # MEDIARECORDER-INSPIRED PRECISION RESAMPLING
                    # MediaRecorder.py works by preserving exact timing - we apply the same principle
                    
                    # Only log resampling method once per client
                    if resampling_key not in self.logged_info[client_id]:
                        logger.debug(f"🔄 [AudioProcessor] Using scipy.signal.resample for precision resampling")
                    
                    try:
                        # Use scipy.signal.resample with precise target length
                        resampled_data = signal.resample(audio_data, target_length)
                        
                        # Verify timing precision
                        output_duration = len(resampled_data) / self.target_sample_rate
                        duration_error = abs(output_duration - input_duration) / input_duration * 100
                        
                        if len(resampled_data) == target_length and duration_error < 0.1:
                            audio_data = resampled_data
                            
                            # Only log success details once per client
                            if resampling_key not in self.logged_info[client_id]:
                                logger.debug(f"✅ [AudioProcessor] Resampling successful - Duration error: {duration_error:.3f}%")
                        else:
                            logger.warning(f"⚠️ [AudioProcessor] Precision resampling quality check failed")
                            logger.warning(f"   Expected length: {target_length}, got: {len(resampled_data)}")
                            logger.warning(f"   Duration error: {duration_error:.3f}%")
                            raise ValueError("Precision resampling quality check failed")
                            
                    except Exception as e:
                        # Fallback to careful linear interpolation
                        logger.warning(f"⚠️ [AudioProcessor] Precision resampling failed for {client_id}: {e}")
                        logger.warning(f"   Using careful linear interpolation fallback")
                        
                        # Use precise target length for fallback too
                        old_indices = np.linspace(0, original_length - 1, original_length)
                        new_indices = np.linspace(0, original_length - 1, target_length)
                        audio_data = np.interp(new_indices, old_indices, audio_data)
                        
                        fallback_duration = len(audio_data) / self.target_sample_rate
                        logger.warning(f"🔄 [AudioProcessor] FALLBACK resampling: {original_length} -> {len(audio_data)} samples")
                        logger.warning(f"   Duration: {input_duration:.6f}s -> {fallback_duration:.6f}s")
                else:
                    logger.warning(f"[AudioProcessor] Invalid target length for resampling: {target_length}")
                    return
                    
                # PRECISION VERIFICATION: Ensure timing is preserved exactly
                actual_samples = len(audio_data)
                actual_duration = actual_samples / self.target_sample_rate
                duration_error = abs(actual_duration - input_duration) / input_duration * 100
                
                logger.trace(f"🔍 [AudioProcessor] PRECISION VERIFICATION for {client_id}:")
                logger.trace(f"   Input duration: {input_duration:.6f}s")
                logger.trace(f"   Output duration: {actual_duration:.6f}s")
                logger.trace(f"   Duration error: {duration_error:.3f}%")
                logger.trace(f"   Actual samples: {actual_samples}")
                
                if duration_error > 0.1:  # More strict than before
                    logger.error(f"❌ [AudioProcessor] TIMING PRECISION FAILED!")
                    logger.error(f"   Duration error {duration_error:.3f}% exceeds 0.1% threshold")
                    logger.error(f"   This may cause audio to sound slow or fast!")
                else:
                    logger.trace(f"✅ [AudioProcessor] Timing precision verification passed")
            else:
                # No resampling needed
                logger.trace(f"🔍 [AudioProcessor] No resampling needed for {client_id}: already {original_sample_rate}Hz")
                
            # Convert float32 to int16 (PCM 16-bit)
            # First, normalize the audio data to proper float32 range [-1.0, 1.0]
            max_abs_value = np.max(np.abs(audio_data))
            if max_abs_value > 1.0:
                # Audio is overdriven - normalize it first
                normalization_factor = 1.0 / max_abs_value
                audio_data = audio_data * normalization_factor
                logger.debug(f"🔧 [AudioProcessor] Normalized overdriven audio: max {max_abs_value:.3f} -> 1.0 (factor: {normalization_factor:.3f})")
            
            # Apply additional server-side gain reduction for safety
            server_gain_reduction = 0.8  # Conservative reduction after normalization
            audio_data = audio_data * server_gain_reduction
            
            logger.trace(f"🔧 [AudioProcessor] Applied server-side gain reduction: {server_gain_reduction}x")
            
            # Debug: Check audio levels AFTER gain reduction (only log occasionally)
            output_rms = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2))
            output_max = np.max(np.abs(audio_data))
            output_clipping = np.sum(np.abs(audio_data) >= 0.99) / len(audio_data) * 100
            
            # Clamp values to [-1, 1] range and convert to 16-bit integers
            audio_data = np.clip(audio_data, -1.0, 1.0)
            int16_data = (audio_data * 32767).astype(np.int16)
            
            # Debug: Check final 16-bit levels (only log occasionally or when there are issues)
            final_rms = np.sqrt(np.mean(int16_data.astype(np.float32) ** 2))
            final_max = np.max(np.abs(int16_data))
            final_clipping = np.sum(np.abs(int16_data) >= 32767) / len(int16_data) * 100
            
            # Only log gain/final analysis when there are issues or for first few frames
            should_log_gain = (
                'gain_analysis' not in self.logged_info[client_id] or
                output_clipping > 5.0 or final_clipping > 5.0 or
                output_rms < 0.001 or final_rms < 100
            )
            
            if should_log_gain:
                logger.trace(f"🔍 [AudioProcessor] AFTER GAIN for {client_id}: RMS={output_rms:.3f}, Max={output_max:.3f}, Clipping={output_clipping:.1f}%")
                logger.trace(f"🔍 [AudioProcessor] FINAL 16-BIT for {client_id}: RMS={final_rms:.0f}, Max={final_max:.0f}, Clipping={final_clipping:.1f}%")
                self.logged_info[client_id].add('gain_analysis')
            
            # Add processed audio to buffer for merging (after resampling, before converting to bytes)
            # CRITICAL: Verify that audio_data has been resampled to target_sample_rate
            # Log the actual sample count to verify resampling worked
            expected_samples_for_target_rate = int(len(audio_data))  # This should be the resampled count
            
            # Buffer processed audio for debugging (only if debug saving enabled)
            if self.audio_debug_save_enabled:
                logger.trace(f"🔍 [AudioProcessor] Buffering processed audio: {len(audio_data)} samples at {self.target_sample_rate}Hz")
                self._add_to_audio_buffer(audio_data.copy(), self.target_sample_rate, is_original=False)
            
            # Convert to bytes
            audio_bytes = int16_data.tobytes()
            
            # Convert to base64 for transmission (matching S2S format)
            base64_audio = base64.b64encode(audio_bytes).decode('utf-8')
            
            # Update statistics
            self.stats['bytes_processed'] += len(audio_bytes)
            
            # Handle test vs production mode
            if is_test_client:
                # Test mode: Save audio to file and log
                test_file_path = self._save_test_audio_chunk(client_id, int16_data, self.target_sample_rate)
                logger.debug(f"🧪 [AudioProcessor] TEST MODE - Audio saved to: {test_file_path}")
                logger.debug(f"🧪 [AudioProcessor] TEST AUDIO STATS - Samples: {len(int16_data)}, Duration: {len(int16_data)/self.target_sample_rate:.2f}s")
                
                # Don't send to Nova Sonic for test clients
                return
            
            # Production mode: Send to callback if available
            if self.on_audio_data:
                # Create audio data packet with metadata
                audio_packet = {
                    'audioData': base64_audio,
                    'sampleRate': self.target_sample_rate,
                    'channels': self.target_channels,
                    'format': 'pcm16',
                    'timestamp': int(time.time() * 1000),
                    'client_id': client_id,
                    'size_bytes': len(audio_bytes)
                }
                
                # Call the callback with processed audio
                # The callback should handle routing to S2sSessionManager
                await self._invoke_audio_callback(client_id, audio_packet)
                
        except Exception as e:
            logger.error(f"[AudioProcessor] Error processing audio chunk for {client_id}: {e}")
            self.stats['conversion_errors'] += 1
            
    async def _invoke_audio_callback(self, client_id: str, audio_packet: dict):
        """
        Invoke audio callback safely
        
        Args:
            client_id: Client identifier
            audio_packet: Processed audio data packet
        """
        try:
            if self.on_audio_data:
                # Only log audio sending occasionally to avoid spam
                if 'audio_sending' not in self.logged_info.get(client_id, set()):
                    logger.debug(f"📤 [AudioProcessor] Sending processed audio to callback for {client_id}: {audio_packet['size_bytes']} bytes, {audio_packet['sampleRate']}Hz")
                    if client_id not in self.logged_info:
                        self.logged_info[client_id] = set()
                    self.logged_info[client_id].add('audio_sending')
                
                # Check if callback is async
                if asyncio.iscoroutinefunction(self.on_audio_data):
                    await self.on_audio_data(client_id, audio_packet)
                else:
                    self.on_audio_data(client_id, audio_packet)
                    
        except Exception as e:
            logger.error(f"[AudioProcessor] Error in audio callback for {client_id}: {e}")
    
    def _ensure_original_audio_dir(self):
        """Ensure original audio directory exists (only if debug saving enabled)"""
        if not self.audio_debug_save_enabled:
            return
        try:
            os.makedirs(self.original_audio_dir, exist_ok=True)
            logger.debug(f"[AudioProcessor] Original audio directory ready: {self.original_audio_dir}")
        except Exception as e:
            logger.error(f"[AudioProcessor] Failed to create original audio directory: {e}")
            
    def _ensure_merged_audio_dir(self):
        """Ensure merged audio directory exists (only if debug saving enabled)"""
        if not self.audio_debug_save_enabled:
            return
        try:
            os.makedirs(self.merged_audio_dir, exist_ok=True)
            logger.debug(f"[AudioProcessor] Merged audio directory ready: {self.merged_audio_dir}")
        except Exception as e:
            logger.error(f"[AudioProcessor] Failed to create merged audio directory: {e}")
    
    def _save_original_audio(self, client_id: str, audio_data: np.ndarray, sample_rate: int):
        """Save original raw audio from WebRTC for VLC analysis (only if debug saving enabled)"""
        if not self.audio_debug_save_enabled:
            return
        try:
            self.original_audio_counter += 1
            
            # Create filename with timestamp and counter
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"original_{timestamp}_{self.original_audio_counter:04d}.wav"
            filepath = os.path.join(self.original_audio_dir, filename)
            
            # Convert float32 audio to 16-bit PCM
            if audio_data.dtype == np.float32:
                # Clamp to [-1, 1] and convert to 16-bit
                audio_data_clamped = np.clip(audio_data, -1.0, 1.0)
                int16_data = (audio_data_clamped * 32767).astype(np.int16)
            else:
                int16_data = audio_data.astype(np.int16)
            
            # Create WAV file header
            import struct
            channels = 1
            bits_per_sample = 16
            byte_rate = sample_rate * channels * bits_per_sample // 8
            block_align = channels * bits_per_sample // 8
            data_size = len(int16_data) * 2  # 2 bytes per sample
            
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
                f.write(int16_data.tobytes())
            
            # Log original audio stats
            rms = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2))
            max_val = np.max(np.abs(audio_data))
            clipping_samples = np.sum(np.abs(audio_data) >= 0.99) if audio_data.dtype == np.float32 else np.sum(np.abs(audio_data) >= 32767)
            clipping_percent = (clipping_samples / len(audio_data)) * 100
            
            # Debug WAV file metadata
            logger.debug(f"🎵 [AudioProcessor] ORIGINAL AUDIO saved: {filename}")
            logger.debug(f"📊 [AudioProcessor] ORIGINAL STATS: RMS={rms:.3f}, Max={max_val:.3f}, Clipping={clipping_percent:.1f}%, Rate={sample_rate}Hz")
            logger.debug(f"🔧 [AudioProcessor] WAV HEADER: {len(int16_data)} samples, {data_size} bytes, {sample_rate}Hz, {channels}ch, {bits_per_sample}bit")
            logger.debug(f"🔍 [AudioProcessor] INT16 RANGE: Min={np.min(int16_data)}, Max={np.max(int16_data)}, First5={int16_data[:5].tolist()}")
            
        except Exception as e:
            logger.error(f"[AudioProcessor] Error saving original audio: {e}")
            
    def _save_test_audio_chunk(self, client_id: str, audio_data: np.ndarray, sample_rate: int) -> str:
        """Save test audio chunk to file"""
        try:
            # Create test audio directory
            test_audio_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "test_audio")
            os.makedirs(test_audio_dir, exist_ok=True)
            
            # Create filename with client ID and timestamp
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # Include milliseconds
            safe_client_id = client_id.replace('-', '_')
            filename = f"test_{safe_client_id}_{timestamp}.wav"
            filepath = os.path.join(test_audio_dir, filename)
            
            # Ensure audio_data is int16
            if audio_data.dtype != np.int16:
                int16_data = audio_data.astype(np.int16)
            else:
                int16_data = audio_data
            
            # CRITICAL FIX: Use the target sample rate (16kHz) for WAV header
            # The audio data has already been resampled to 16kHz, so the WAV file
            # header must match this rate, not the original WebRTC rate (48kHz)
            wav_sample_rate = self.target_sample_rate  # Always 16kHz for processed audio
            
            # Create WAV file header
            import struct
            channels = 1
            bits_per_sample = 16
            byte_rate = wav_sample_rate * channels * bits_per_sample // 8
            block_align = channels * bits_per_sample // 8
            data_size = len(int16_data) * 2  # 2 bytes per sample
            
            # WAV header
            wav_header = struct.pack('<4sI4s4sIHHIIHH4sI',
                b'RIFF',
                36 + data_size,  # File size - 8
                b'WAVE',
                b'fmt ',
                16,  # PCM format chunk size
                1,   # PCM format
                channels,
                wav_sample_rate,  # Use correct sample rate (16kHz)
                byte_rate,
                block_align,
                bits_per_sample,
                b'data',
                data_size
            )
            
            # Write WAV file
            with open(filepath, 'wb') as f:
                f.write(wav_header)
                f.write(int16_data.tobytes())
            
            # Debug: Log WAV file details
            rms = np.sqrt(np.mean(int16_data.astype(np.float32) ** 2))
            max_val = np.max(np.abs(int16_data))
            min_val = np.min(int16_data)
            unique_values = len(np.unique(int16_data))
            
            logger.debug(f"🧪 [AudioProcessor] WAV FILE SAVED: {filename}")
            logger.debug(f"🧪 [AudioProcessor] WAV STATS: RMS={rms:.0f}, Max={max_val}, Min={min_val}, Unique values={unique_values}")
            logger.debug(f"🧪 [AudioProcessor] WAV HEADER: {wav_sample_rate}Hz, {channels}ch, {bits_per_sample}bit, {data_size} bytes")
            logger.debug(f"🧪 [AudioProcessor] FIRST 10 SAMPLES: {int16_data[:10].tolist()}")
            
            return filepath
            
        except Exception as e:
            logger.error(f"[AudioProcessor] Error saving test audio: {e}")
            return ""
            
    def create_nova_sonic_audio(self, base64_audio_data: str, sample_rate: int = 24000) -> bytes:
        """
        Convert Nova Sonic audio response to WebRTC format
        
        Args:
            base64_audio_data: Base64 encoded audio from Nova Sonic
            sample_rate: Sample rate of the audio (default 24kHz for Nova Sonic output)
            
        Returns:
            Audio bytes suitable for WebRTC transmission
        """
        try:
            # Decode base64 audio
            audio_bytes = base64.b64decode(base64_audio_data)
            
            # Convert bytes to int16 array
            int16_array = np.frombuffer(audio_bytes, dtype=np.int16)
            
            # Convert to float32 for WebRTC
            float32_array = int16_array.astype(np.float32) / 32767.0
            
            # Ensure mono channel
            if len(float32_array.shape) > 1:
                float32_array = np.mean(float32_array, axis=1)
                
            return float32_array.tobytes()
            
        except Exception as e:
            logger.error(f"[AudioProcessor] Error converting Nova Sonic audio: {e}")
            return b''
            
    def get_processing_stats(self) -> dict:
        """
        Get audio processing statistics
        
        Returns:
            Dictionary with processing statistics
        """
        return {
            **self.stats,
            'active_tracks': len(self.audio_tracks),
            'active_buffers': len(self.audio_buffers),
            'is_processing': self.is_processing
        }
        
    def get_client_buffer_size(self, client_id: str) -> int:
        """
        Get audio buffer size for specific client
        
        Args:
            client_id: Client identifier
            
        Returns:
            Buffer size or 0 if client not found
        """
        with self.buffer_lock:
            if client_id in self.audio_buffers:
                return len(self.audio_buffers[client_id])
            return 0
            
    def clear_client_buffer(self, client_id: str):
        """
        Clear audio buffer for specific client
        
        Args:
            client_id: Client identifier
        """
        with self.buffer_lock:
            if client_id in self.audio_buffers:
                self.audio_buffers[client_id].clear()
                logger.debug(f"[AudioProcessor] Cleared audio buffer for {client_id}")
                
    def is_client_active(self, client_id: str) -> bool:
        """
        Check if client is actively sending audio
        
        Args:
            client_id: Client identifier
            
        Returns:
            True if client has active audio track
        """
        return (client_id in self.audio_tracks and 
                client_id in self.processing_tasks and 
                not self.processing_tasks[client_id].done())
                
    def _add_to_audio_buffer(self, audio_data: np.ndarray, sample_rate: int, is_original: bool = True):
        """
        Add audio data to buffer for later merging (only if debug saving enabled)
        
        Args:
            audio_data: Audio data as numpy array
            sample_rate: Sample rate of the audio
            is_original: True for original audio, False for processed audio
        """
        if not self.audio_debug_save_enabled:
            return
        try:
            buffer_type = "Original" if is_original else "Processed"
            
            # Log buffer addition (every 5th chunk to get more debugging info)
            if is_original:
                chunk_count = len(self.original_audio_buffer)
                self.original_audio_buffer.append((audio_data.copy(), sample_rate))
            else:
                chunk_count = len(self.processed_audio_buffer)
                self.processed_audio_buffer.append((audio_data.copy(), sample_rate))
                
            if chunk_count % 5 == 0:
                duration = len(audio_data) / sample_rate
                logger.debug(f"🔄 [AudioProcessor] Added {buffer_type} audio chunk #{chunk_count + 1}: {len(audio_data)} samples, {sample_rate}Hz, {duration:.3f}s")
                
                # Additional debugging for first few chunks
                if chunk_count < 3:
                    logger.debug(f"   🔍 Audio data range: {np.min(audio_data):.3f} to {np.max(audio_data):.3f}")
                    logger.debug(f"   🔍 Expected for {buffer_type}: {'48kHz' if is_original else '16kHz'}")
                
            # Check if we should merge based on buffer size or time
            current_time = time.time()
            should_merge = (
                len(self.original_audio_buffer) >= self.merge_interval or
                len(self.processed_audio_buffer) >= self.merge_interval or
                (current_time - self.last_merge_time) >= self.merge_timeout
            )
            
            if should_merge:
                logger.debug(f"🎵 [AudioProcessor] Triggering merge: Original={len(self.original_audio_buffer)}, Processed={len(self.processed_audio_buffer)}, Time since last={current_time - self.last_merge_time:.1f}s")
                self._merge_buffered_audio()
                
        except Exception as e:
            logger.error(f"[AudioProcessor] Error adding to audio buffer: {e}")
            
    def _merge_buffered_audio(self):
        """Merge buffered audio chunks into complete WAV files"""
        try:
            current_time = time.time()
            timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(current_time))
            
            # Create session-specific filename prefix
            session_prefix = ""
            if self.current_session_id:
                # Clean session ID for filename
                clean_session_id = self.current_session_id.replace('-', '_').replace(':', '_')[:20]
                session_prefix = f"{clean_session_id}_"
            
            # Merge original audio if buffer has data
            if self.original_audio_buffer:
                filename = f"merged_original_{session_prefix}{timestamp}.wav"
                self._merge_audio_chunks(
                    self.original_audio_buffer,
                    os.path.join(self.merged_audio_dir, filename),
                    "Original WebRTC Audio (48kHz)"
                )
                self.original_audio_buffer.clear()
                
            # Merge processed audio if buffer has data
            if self.processed_audio_buffer:
                filename = f"merged_processed_{session_prefix}{timestamp}.wav"
                self._merge_audio_chunks(
                    self.processed_audio_buffer,
                    os.path.join(self.merged_audio_dir, filename),
                    "Processed Audio (16kHz)"
                )
                self.processed_audio_buffer.clear()
                
            self.last_merge_time = current_time
            
        except Exception as e:
            logger.error(f"[AudioProcessor] Error merging buffered audio: {e}")
            
    def _merge_audio_chunks(self, audio_chunks: list, output_file: str, description: str):
        """
        Merge audio chunks into a single WAV file
        
        Args:
            audio_chunks: List of (audio_data, sample_rate) tuples
            output_file: Output WAV file path
            description: Description for logging
        """
        try:
            if not audio_chunks:
                return
                
            logger.debug(f"🎵 [AudioProcessor] Merging {len(audio_chunks)} chunks for {description}")
            
            # CRITICAL FIX: Don't assume sample rates, use the actual sample rate from the first chunk
            # The previous logic was making incorrect assumptions about sample rates
            first_audio, first_sample_rate = audio_chunks[0]
            target_sample_rate = first_sample_rate
            
            logger.debug(f"🔍 [AudioProcessor] Using actual sample rate from first chunk: {target_sample_rate}Hz")
            
            # Verify all chunks have the same sample rate
            sample_rate_consistent = True
            for i, (audio_data, chunk_sample_rate) in enumerate(audio_chunks):
                if chunk_sample_rate != target_sample_rate:
                    sample_rate_consistent = False
                    logger.warning(f"⚠️ [AudioProcessor] Sample rate inconsistency in chunk {i}: {chunk_sample_rate}Hz vs {target_sample_rate}Hz")
                    
            if sample_rate_consistent:
                logger.debug(f"✅ [AudioProcessor] All chunks have consistent sample rate: {target_sample_rate}Hz")
            else:
                logger.warning(f"⚠️ [AudioProcessor] Sample rate inconsistencies detected - will resample")
            
            logger.debug(f"🎼 [AudioProcessor] Target sample rate for {description}: {target_sample_rate}Hz")
            
            # Concatenate all audio data with proper resampling
            merged_audio = []
            total_duration = 0
            
            for i, (audio_data, chunk_sample_rate) in enumerate(audio_chunks):
                # Log sample rate for first few chunks to debug
                if i < 3:
                    logger.debug(f"🔍 [AudioProcessor] Chunk {i}: {len(audio_data)} samples at {chunk_sample_rate}Hz")
                
                # Resample if needed using high-quality scipy resampling
                if chunk_sample_rate != target_sample_rate:
                    logger.warning(f"[AudioProcessor] Resampling chunk {i}: {chunk_sample_rate}Hz -> {target_sample_rate}Hz")
                    ratio = target_sample_rate / chunk_sample_rate
                    new_length = int(len(audio_data) * ratio)
                    if new_length > 0:
                        try:
                            # Use scipy.signal.resample for consistent high-quality resampling
                            audio_data = signal.resample(audio_data, new_length)
                            logger.debug(f"✅ [AudioProcessor] Scipy resampling in merge: {len(audio_data)} -> {new_length} samples")
                        except Exception as e:
                            # Fallback to linear interpolation
                            logger.warning(f"⚠️ [AudioProcessor] Scipy resampling failed in merge: {e}, using interpolation")
                            old_indices = np.linspace(0, len(audio_data) - 1, len(audio_data))
                            new_indices = np.linspace(0, len(audio_data) - 1, new_length)
                            audio_data = np.interp(new_indices, old_indices, audio_data)
                        logger.debug(f"🔄 [AudioProcessor] Resampled: {len(audio_chunks[i][0])} -> {len(audio_data)} samples")
                
                merged_audio.append(audio_data)
                total_duration += len(audio_data) / target_sample_rate
                
            # Concatenate all chunks
            final_audio = np.concatenate(merged_audio)
            
            # Write to WAV file with correct sample rate
            self._write_wav_file(output_file, final_audio, target_sample_rate)
            
            logger.debug(f"✅ [AudioProcessor] {description} merged successfully!")
            logger.debug(f"   📄 File: {os.path.basename(output_file)}")
            logger.debug(f"   📊 Chunks: {len(audio_chunks)}, Duration: {total_duration:.2f}s")
            logger.debug(f"   🎼 Sample Rate: {target_sample_rate}Hz, Samples: {len(final_audio)}")
            logger.debug(f"   🔍 Audio Range: Min={np.min(final_audio):.3f}, Max={np.max(final_audio):.3f}")
            
        except Exception as e:
            logger.error(f"[AudioProcessor] Error merging audio chunks: {e}")
            
    def _write_wav_file(self, filepath: str, audio_data: np.ndarray, sample_rate: int):
        """
        Write audio data to WAV file
        
        Args:
            filepath: Output file path
            audio_data: Audio data as numpy array (float32, normalized)
            sample_rate: Sample rate
        """
        try:
            import wave
            
            # Ensure the directory exists before writing
            output_dir = os.path.dirname(filepath)
            if not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)
                logger.debug(f"📁 [AudioProcessor] Created directory: {output_dir}")
            
            logger.debug(f"🎼 [AudioProcessor] Writing WAV file: {os.path.basename(filepath)}")
            logger.debug(f"   📊 Input: {len(audio_data)} samples, {sample_rate}Hz")
            logger.debug(f"   🔍 Data range: {np.min(audio_data):.3f} to {np.max(audio_data):.3f}")
            
            # Ensure audio data is in valid range [-1.0, 1.0]
            if np.max(np.abs(audio_data)) > 1.0:
                logger.warning(f"⚠️ [AudioProcessor] Audio data out of range, normalizing...")
                max_val = np.max(np.abs(audio_data))
                audio_data = audio_data / max_val
                logger.debug(f"   🔧 Normalized by factor: {max_val:.3f}")
            
            # Clip to ensure no overflow
            audio_data = np.clip(audio_data, -1.0, 1.0)
            
            # Convert to 16-bit integer
            audio_int16 = (audio_data * 32767).astype(np.int16)
            
            logger.debug(f"   🔢 16-bit range: {np.min(audio_int16)} to {np.max(audio_int16)}")
            
            with wave.open(filepath, 'wb') as wav_file:
                wav_file.setnchannels(1)  # Mono
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(audio_int16.tobytes())
                
            # Verify file was written
            file_size = os.path.getsize(filepath)
            duration = len(audio_int16) / sample_rate
            logger.debug(f"✅ [AudioProcessor] WAV file written successfully!")
            logger.debug(f"   📄 File: {os.path.basename(filepath)} ({file_size} bytes)")
            logger.debug(f"   ⏱️ Duration: {duration:.2f}s")
            logger.debug(f"   🎼 Format: {sample_rate}Hz, 16-bit, Mono")
                
        except Exception as e:
            logger.error(f"[AudioProcessor] Error writing WAV file {filepath}: {e}")
            import traceback
            logger.error(f"[AudioProcessor] Traceback: {traceback.format_exc()}")
            
    def force_merge_audio(self):
        """Force merge any buffered audio data (only if debug saving enabled)"""
        if not self.audio_debug_save_enabled:
            return
        try:
            if hasattr(self, 'original_audio_buffer') and hasattr(self, 'processed_audio_buffer'):
                if self.original_audio_buffer or self.processed_audio_buffer:
                    logger.debug(f"[AudioProcessor] Force merging buffered audio... (Original: {len(self.original_audio_buffer)} chunks, Processed: {len(self.processed_audio_buffer)} chunks)")
                    self._merge_buffered_audio()
                else:
                    logger.debug("[AudioProcessor] No buffered audio to merge")
        except Exception as e:
            logger.error(f"[AudioProcessor] Error in force merge: {e}")
            
    def get_merge_status(self) -> dict:
        """Get current audio merge buffer status"""
        if not self.audio_debug_save_enabled:
            return {
                'audio_debug_save_enabled': False,
                'message': 'Audio debug saving disabled (set AUDIO_DEBUG_SAVE=true to enable)'
            }
        
        return {
            'audio_debug_save_enabled': True,
            'original_chunks': len(self.original_audio_buffer) if hasattr(self, 'original_audio_buffer') else 0,
            'processed_chunks': len(self.processed_audio_buffer) if hasattr(self, 'processed_audio_buffer') else 0,
            'merge_interval': self.merge_interval if hasattr(self, 'merge_interval') else 0,
            'last_merge_time': self.last_merge_time if hasattr(self, 'last_merge_time') else 0,
            'time_since_last_merge': time.time() - (self.last_merge_time if hasattr(self, 'last_merge_time') else time.time()),
            'merge_timeout': self.merge_timeout if hasattr(self, 'merge_timeout') else 0,
            'current_session_id': self.current_session_id if hasattr(self, 'current_session_id') else None
        }