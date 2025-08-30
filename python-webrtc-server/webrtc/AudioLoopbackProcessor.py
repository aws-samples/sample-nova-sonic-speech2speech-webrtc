"""
AudioLoopbackProcessor - Simple audio loopback for testing WebRTC audio quality
Receives audio from React, saves original data, and sends it back unchanged
"""

import asyncio
import logging
import numpy as np
import os
import struct
import time
from typing import Optional
from aiortc import MediaStreamTrack
from aiortc.mediastreams import MediaStreamError
from collections import deque
import threading

logger = logging.getLogger(__name__)

class AudioLoopbackProcessor:
    """
    Simple audio loopback processor for testing
    - Receives WebRTC audio from React
    - Saves original audio data (no processing)
    - Sends the same audio back to React for playback
    """
    
    def __init__(self):
        # Processing state
        self.is_processing = False
        self.audio_tracks = {}
        self.processing_tasks = {}
        
        # Audio buffer for loopback playback
        self.loopback_buffer = deque(maxlen=1000)  # Store recent audio for playback
        self.buffer_lock = threading.Lock()
        
        # Collect all audio data for delayed playback
        self.collected_audio = {}  # client_id -> list of audio chunks
        self.audio_configs = {}    # client_id -> (sample_rate, data_type)
        self.playback_delay = 2.0  # Wait 2 seconds after audio stops before playback
        
        # Callbacks
        self.on_audio_output = None  # Callback to send audio back to React
        
        # Statistics
        self.stats = {
            'frames_received': 0,
            'frames_sent': 0,
            'bytes_processed': 0,
            'last_activity': None
        }
        
        # Original audio saving
        self.original_audio_counter = 0
        self.original_audio_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "loopback_audio")
        self._ensure_original_audio_dir()
        
    def set_audio_output_callback(self, callback):
        """Set callback for sending audio back to React"""
        self.on_audio_output = callback
        
    def start_processing(self):
        """Start loopback processing"""
        self.is_processing = True
        logger.info("[AudioLoopbackProcessor] Started audio loopback processing")
        
    def stop_processing(self):
        """Stop loopback processing"""
        self.is_processing = False
        
        # Cancel all processing tasks
        for client_id, task in self.processing_tasks.items():
            if not task.done():
                task.cancel()
                
        self.processing_tasks.clear()
        self.audio_tracks.clear()
        
        with self.buffer_lock:
            self.loopback_buffer.clear()
            
        logger.info("[AudioLoopbackProcessor] Stopped audio loopback processing")
        
    async def add_audio_track(self, client_id: str, track: MediaStreamTrack):
        """Add audio track for loopback processing"""
        try:
            if not self.is_processing:
                logger.warning(f"[AudioLoopbackProcessor] Not processing, ignoring track for {client_id}")
                return
                
            logger.info(f"[AudioLoopbackProcessor] Adding audio track for loopback: {client_id}")
            
            # Store track reference
            self.audio_tracks[client_id] = track
            
            # Start processing task for this track
            task = asyncio.create_task(self._process_audio_track(client_id, track))
            self.processing_tasks[client_id] = task
            
            logger.info(f"[AudioLoopbackProcessor] Started loopback processing for {client_id}")
            
        except Exception as e:
            logger.error(f"[AudioLoopbackProcessor] Error adding audio track for {client_id}: {e}")
            
    async def remove_audio_track(self, client_id: str):
        """Remove audio track and stop processing"""
        try:
            logger.info(f"[AudioLoopbackProcessor] Removing audio track for: {client_id}")
            
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
                
            logger.info(f"[AudioLoopbackProcessor] Removed audio track for {client_id}")
            
        except Exception as e:
            logger.error(f"[AudioLoopbackProcessor] Error removing audio track for {client_id}: {e}")
            
    async def _process_audio_track(self, client_id: str, track: MediaStreamTrack):
        """Process audio frames for loopback"""
        try:
            logger.info(f"[AudioLoopbackProcessor] Starting loopback processing for {client_id}")
            
            frame_count = 0
            
            while self.is_processing:
                try:
                    # Receive audio frame from WebRTC
                    frame = await track.recv()
                    
                    if not frame:
                        continue
                        
                    frame_count += 1
                    self.stats['frames_received'] += 1
                    self.stats['last_activity'] = time.time()
                    
                    # Log frame reception (every 50 frames)
                    if frame_count % 50 == 0:
                        frame_duration_ms = (frame.samples / frame.sample_rate) * 1000
                        logger.info(f"🎤 [AudioLoopbackProcessor] Received frame #{frame_count} from {client_id}: {frame.samples} samples, {frame.sample_rate}Hz, {frame_duration_ms:.1f}ms")
                    
                    # Convert frame to numpy array (NO PROCESSING)
                    audio_data = self._frame_to_numpy(frame)
                    
                    if audio_data is None:
                        continue
                    
                    # Save original audio data for analysis
                    self._save_original_audio(client_id, audio_data, frame.sample_rate)
                    
                    # Collect audio data for delayed playback
                    with self.buffer_lock:
                        if client_id not in self.collected_audio:
                            self.collected_audio[client_id] = []
                            self.audio_configs[client_id] = (frame.sample_rate, audio_data.dtype)
                        
                        self.collected_audio[client_id].append({
                            'audio_data': audio_data.copy(),
                            'timestamp': time.time()
                        })
                        
                        logger.debug(f"🔄 [AudioLoopbackProcessor] Collected audio chunk {len(self.collected_audio[client_id])} for {client_id}")
                    
                except MediaStreamError:
                    logger.info(f"[AudioLoopbackProcessor] Audio track ended for {client_id}")
                    break
                except asyncio.CancelledError:
                    logger.info(f"[AudioLoopbackProcessor] Audio processing cancelled for {client_id}")
                    break
                except Exception as e:
                    logger.error(f"[AudioLoopbackProcessor] Error processing frame for {client_id}: {e}")
                    continue
                    
            logger.info(f"[AudioLoopbackProcessor] Finished loopback processing for {client_id}, processed {frame_count} frames")
            
            # Start delayed playback of collected audio
            await self._start_delayed_playback(client_id)
            
        except Exception as e:
            logger.error(f"[AudioLoopbackProcessor] Fatal error in loopback processing for {client_id}: {e}")
            
    def _frame_to_numpy(self, frame) -> Optional[np.ndarray]:
        """Convert WebRTC audio frame to numpy array and convert to int16"""
        try:
            if hasattr(frame, 'to_ndarray'):
                # Get raw audio data (typically float32 in range -1.0 to 1.0)
                audio_array = frame.to_ndarray()
                
                # Handle different array shapes
                if audio_array.ndim == 2:
                    if audio_array.shape[0] == 1:
                        # Single channel in 2D format - flatten
                        audio_array = audio_array.flatten()
                    elif audio_array.shape[0] == 2:
                        # Stereo - take left channel only (simple approach)
                        audio_array = audio_array[0]
                    else:
                        # Multi-channel - take first channel
                        audio_array = audio_array[0]
                
                # Convert from float32 (-1.0 to 1.0) to int16 (-32768 to 32767)
                if audio_array.dtype == np.float32 or audio_array.dtype == np.float64:
                    # Clamp to valid range and convert to int16
                    audio_array = np.clip(audio_array, -1.0, 1.0)
                    audio_array = (audio_array * 32767).astype(np.int16)
                    logger.debug(f"[AudioLoopbackProcessor] Converted float audio to int16: {audio_array.dtype}")
                
                return audio_array
                
            else:
                logger.warning("[AudioLoopbackProcessor] Frame does not support to_ndarray conversion")
                return None
                
        except Exception as e:
            logger.error(f"[AudioLoopbackProcessor] Error converting frame to numpy: {e}")
            return None
            
    async def _send_loopback_audio(self, client_id: str, audio_data: np.ndarray, sample_rate: int):
        """Send audio back to React for loopback playback"""
        try:
            if not self.on_audio_output:
                logger.warning(f"[AudioLoopbackProcessor] No audio output callback set for {client_id}")
                return
            
            # Convert to the format expected by AudioOutputTrack
            # Keep original sample rate and data characteristics
            if audio_data.dtype != np.float32:
                # Convert to float32 but preserve the original range
                if audio_data.dtype == np.int16:
                    float32_data = audio_data.astype(np.float32) / 32767.0
                elif audio_data.dtype == np.int32:
                    float32_data = audio_data.astype(np.float32) / 2147483647.0
                else:
                    float32_data = audio_data.astype(np.float32)
            else:
                float32_data = audio_data.copy()
            
            # Send to AudioOutputTrack with original sample rate
            await self.on_audio_output(client_id, float32_data, sample_rate)
            
            self.stats['frames_sent'] += 1
            logger.debug(f"🔄 [AudioLoopbackProcessor] Sent audio chunk to {client_id}: {len(audio_data)} samples at {sample_rate}Hz")
            
        except Exception as e:
            logger.error(f"[AudioLoopbackProcessor] Error sending loopback audio for {client_id}: {e}")
    
    def _ensure_original_audio_dir(self):
        """Ensure original audio directory exists"""
        try:
            os.makedirs(self.original_audio_dir, exist_ok=True)
            logger.info(f"[AudioLoopbackProcessor] Loopback audio directory ready: {self.original_audio_dir}")
        except Exception as e:
            logger.error(f"[AudioLoopbackProcessor] Failed to create loopback audio directory: {e}")
    
    def _save_original_audio(self, client_id: str, audio_data: np.ndarray, sample_rate: int):
        """Save original raw audio from WebRTC as pure PCM (NO PROCESSING, NO HEADERS)"""
        try:
            self.original_audio_counter += 1
            
            # Create filename with timestamp and counter - use .pcm extension
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"loopback_{timestamp}_{self.original_audio_counter:04d}.pcm"
            filepath = os.path.join(self.original_audio_dir, filename)
            
            # Save raw audio data with NO conversion, NO headers
            # Keep the original data type and values exactly as received from WebRTC
            with open(filepath, 'wb') as f:
                f.write(audio_data.tobytes())
            
            # Log original audio stats
            rms = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2))
            max_val = np.max(np.abs(audio_data))
            
            logger.info(f"🎵 [AudioLoopbackProcessor] RAW PCM saved: {filename}")
            logger.info(f"📊 [AudioLoopbackProcessor] PURE ORIGINAL DATA:")
            logger.info(f"   RMS: {rms:.3f}, Max: {max_val:.3f}")
            logger.info(f"   Sample Rate: {sample_rate}Hz")
            logger.info(f"   Samples: {len(audio_data)}")
            logger.info(f"   Data Type: {audio_data.dtype}")
            logger.info(f"   File Size: {len(audio_data.tobytes())} bytes")
            
            # Also create a metadata file with playback information
            metadata_filename = f"loopback_{timestamp}_{self.original_audio_counter:04d}.txt"
            metadata_filepath = os.path.join(self.original_audio_dir, metadata_filename)
            
            with open(metadata_filepath, 'w') as f:
                f.write(f"Raw PCM Audio Metadata\n")
                f.write(f"======================\n")
                f.write(f"File: {filename}\n")
                f.write(f"Client ID: {client_id}\n")
                f.write(f"Timestamp: {timestamp}\n")
                f.write(f"Sample Rate: {sample_rate}Hz\n")
                f.write(f"Samples: {len(audio_data)}\n")
                f.write(f"Data Type: {audio_data.dtype}\n")
                f.write(f"Channels: 1 (mono)\n")
                f.write(f"Duration: {len(audio_data)/sample_rate:.3f}s\n")
                f.write(f"File Size: {len(audio_data.tobytes())} bytes\n")
                f.write(f"RMS: {rms:.3f}\n")
                f.write(f"Max: {max_val:.3f}\n")
                f.write(f"\n")
                f.write(f"To play with ffplay:\n")
                f.write(f"ffplay -f f32le -ar {sample_rate} -ac 1 {filename}\n")
                f.write(f"\n")
                f.write(f"To convert to WAV:\n")
                f.write(f"ffmpeg -f f32le -ar {sample_rate} -ac 1 -i {filename} output.wav\n")
            
        except Exception as e:
            logger.error(f"[AudioLoopbackProcessor] Error saving raw PCM audio: {e}")
            
    async def _start_delayed_playback(self, client_id: str):
        """Start delayed playback of collected audio"""
        try:
            with self.buffer_lock:
                if client_id not in self.collected_audio or not self.collected_audio[client_id]:
                    logger.info(f"🔄 [AudioLoopbackProcessor] No audio collected for playback: {client_id}")
                    return
                
                audio_chunks = self.collected_audio[client_id].copy()
                sample_rate, data_type = self.audio_configs.get(client_id, (48000, np.float32))
                
                # Clear collected data
                del self.collected_audio[client_id]
                del self.audio_configs[client_id]
            
            total_chunks = len(audio_chunks)
            total_duration = sum(len(chunk['audio_data']) for chunk in audio_chunks) / sample_rate
            
            logger.info(f"🔄 [AudioLoopbackProcessor] Starting delayed playback for {client_id}:")
            logger.info(f"   Collected chunks: {total_chunks}")
            logger.info(f"   Total duration: {total_duration:.2f}s")
            logger.info(f"   Sample rate: {sample_rate}Hz")
            logger.info(f"   Data type: {data_type}")
            logger.info(f"   Delay before playback: {self.playback_delay}s")
            
            # Wait before starting playback
            await asyncio.sleep(self.playback_delay)
            
            logger.info(f"🎵 [AudioLoopbackProcessor] Starting audio playback for {client_id}...")
            
            # Play back all collected audio chunks in order
            for i, chunk in enumerate(audio_chunks):
                audio_data = chunk['audio_data']
                
                # Send the exact same audio data back
                await self._send_loopback_audio(client_id, audio_data, sample_rate)
                
                # Small delay between chunks to maintain timing
                chunk_duration = len(audio_data) / sample_rate
                await asyncio.sleep(chunk_duration)
                
                if (i + 1) % 10 == 0:  # Log every 10 chunks
                    logger.info(f"🎵 [AudioLoopbackProcessor] Played chunk {i+1}/{total_chunks} for {client_id}")
            
            logger.info(f"✅ [AudioLoopbackProcessor] Completed audio playback for {client_id}")
            
        except Exception as e:
            logger.error(f"❌ [AudioLoopbackProcessor] Error in delayed playback for {client_id}: {e}")
    
    def get_stats(self):
        """Get processing statistics"""
        return {
            'frames_received': self.stats['frames_received'],
            'frames_sent': self.stats['frames_sent'],
            'bytes_processed': self.stats['bytes_processed'],
            'last_activity': self.stats['last_activity'],
            'buffer_size': len(self.loopback_buffer),
            'collected_clients': len(self.collected_audio)
        }