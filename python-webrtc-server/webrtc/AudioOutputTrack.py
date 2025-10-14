"""
AudioOutputTrack - Custom WebRTC audio track for sending Nova Sonic responses
Generates audio frames from Nova Sonic base64 audio data for WebRTC transmission
"""

import asyncio
import logging
import time
import base64
import numpy as np
import fractions
from typing import Optional, Dict, Any
from aiortc import MediaStreamTrack
from aiortc.mediastreams import AudioFrame
from collections import deque
import threading

logger = logging.getLogger(__name__)

class AudioOutputTrack(MediaStreamTrack):
    """
    Custom audio track for sending Nova Sonic audio responses via WebRTC media channel
    Converts base64 Nova Sonic audio to WebRTC AudioFrames
    """
    
    kind = "audio"
    
    def __init__(self, client_id: str):
        super().__init__()
        self.client_id = client_id
        
        # Audio configuration (Nova Sonic output format)
        self.sample_rate = 24000  # Nova Sonic outputs 24kHz
        self.channels = 1         # Mono
        self.samples_per_frame = 480  # 20ms frames at 24kHz
        
        # Audio buffer and playback state
        self.audio_buffer = deque()
        self.buffer_lock = threading.Lock()
        self.is_playing = False
        self.start_time = None
        self.frames_sent = 0
        
        # Statistics
        self.stats = {
            'frames_generated': 0,
            'audio_chunks_queued': 0,
            'buffer_underruns': 0,
            'last_activity': time.time()
        }
        
        logger.debug(f"[AudioOutputTrack] Created for client {client_id}: {self.sample_rate}Hz, {self.channels} channel(s)")
    
    async def recv(self) -> AudioFrame:
        """
        Generate next audio frame for WebRTC transmission
        
        Returns:
            AudioFrame: Audio frame with samples from Nova Sonic or silence
        """
        try:
            # Calculate timing for consistent frame rate
            if self.start_time is None:
                self.start_time = time.time()
            
            # Calculate expected timestamp for this frame
            frame_duration = self.samples_per_frame / self.sample_rate  # 20ms
            expected_time = self.start_time + (self.frames_sent * frame_duration)
            current_time = time.time()
            
            # Sleep if we're ahead of schedule
            if current_time < expected_time:
                await asyncio.sleep(expected_time - current_time)
            
            # Get audio samples
            samples = self._get_next_samples()
            
            # Create AudioFrame
            frame = AudioFrame(
                format="s16",  # 16-bit signed integers
                layout="mono",
                samples=self.samples_per_frame
            )
            
            # Convert samples to the format expected by AudioFrame
            if samples is not None:
                # Convert float32 samples to int16
                int16_samples = (samples * 32767).astype(np.int16)
                frame.planes[0].update(int16_samples.tobytes())
            else:
                # Generate silence
                silence = np.zeros(self.samples_per_frame, dtype=np.int16)
                frame.planes[0].update(silence.tobytes())
            
            # Set frame properties
            frame.sample_rate = self.sample_rate
            frame.time_base = fractions.Fraction(1, self.sample_rate)
            frame.pts = self.frames_sent * self.samples_per_frame
            
            self.frames_sent += 1
            self.stats['frames_generated'] += 1
            self.stats['last_activity'] = time.time()
            
            # Log frame generation (every 100 frames to avoid spam)
            if self.frames_sent % 100 == 0:
                with self.buffer_lock:
                    buffer_chunks = len(self.audio_buffer)
                logger.debug(f"🎵📡 [AudioOutputTrack] Generated WebRTC frame #{self.frames_sent} for {self.client_id}: {self.samples_per_frame} samples, buffer: {buffer_chunks} chunks")
            
            return frame
            
        except Exception as e:
            logger.error(f"[AudioOutputTrack] Error generating frame for {self.client_id}: {e}")
            # Return silence frame on error
            frame = AudioFrame(
                format="s16",
                layout="mono", 
                samples=self.samples_per_frame
            )
            silence = np.zeros(self.samples_per_frame, dtype=np.int16)
            frame.planes[0].update(silence.tobytes())
            frame.sample_rate = self.sample_rate
            frame.time_base = fractions.Fraction(1, self.sample_rate)
            frame.pts = self.frames_sent * self.samples_per_frame
            self.frames_sent += 1
            return frame
    
    def _get_next_samples(self) -> Optional[np.ndarray]:
        """
        Get next audio samples from buffer
        
        Returns:
            numpy array of float32 samples or None for silence
        """
        with self.buffer_lock:
            buffer_chunks = len(self.audio_buffer)
            
            if buffer_chunks > 0:
                # Get samples from buffer
                samples = self.audio_buffer.popleft()
                samples_available = len(samples)
                
                # Debug logging for buffer management
                if self.frames_sent % 50 == 0:  # Log every 50 frames (1 second)
                    logger.debug(f"🎵🔍 [AudioOutputTrack] Buffer status for {self.client_id}:")
                    logger.debug(f"   - Chunks available: {buffer_chunks}")
                    logger.debug(f"   - Current chunk: {samples_available} samples")
                    logger.debug(f"   - Frame needs: {self.samples_per_frame} samples")
                
                # Ensure we have exactly the right number of samples
                if samples_available >= self.samples_per_frame:
                    # Take exactly what we need
                    frame_samples = samples[:self.samples_per_frame]
                    
                    # Put remaining samples back if any
                    if samples_available > self.samples_per_frame:
                        remaining = samples[self.samples_per_frame:]
                        self.audio_buffer.appendleft(remaining)
                        
                        if self.frames_sent % 50 == 0:
                            logger.debug(f"   - Returned {len(remaining)} samples to buffer")
                    
                    return frame_samples
                else:
                    # Not enough samples, pad with zeros
                    padded = np.zeros(self.samples_per_frame, dtype=np.float32)
                    padded[:samples_available] = samples
                    
                    if self.frames_sent % 50 == 0:
                        logger.debug(f"   - ⚠️ Padded frame: {samples_available}/{self.samples_per_frame} samples")
                    
                    return padded
            else:
                # No audio data available
                self.stats['buffer_underruns'] += 1
                
                if self.stats['buffer_underruns'] % 50 == 1:  # Log every 50 underruns
                    logger.debug(f"⚠️ [AudioOutputTrack] Buffer underrun #{self.stats['buffer_underruns']} for {self.client_id} - playing silence")
                
                return None
    
    def queue_audio(self, base64_audio_data: str, sample_rate: int = 24000):
        """
        Queue Nova Sonic audio data for playback
        
        Args:
            base64_audio_data: Base64 encoded PCM audio from Nova Sonic
            sample_rate: Sample rate of the audio data
        """
        try:
            # Decode base64 audio
            audio_bytes = base64.b64decode(base64_audio_data)
            
            # Convert bytes to numpy array (assuming 16-bit PCM)
            audio_samples = np.frombuffer(audio_bytes, dtype=np.int16)
            
            # Convert to float32 normalized to [-1, 1]
            float_samples = audio_samples.astype(np.float32) / 32767.0
            
            # Calculate duration for debugging
            duration_ms = (len(float_samples) / sample_rate) * 1000
            
            # Resample if needed (Nova Sonic should already be 24kHz)
            if sample_rate != self.sample_rate:
                logger.warning(f"[AudioOutputTrack] Sample rate mismatch: expected {self.sample_rate}Hz, got {sample_rate}Hz")
                # Simple resampling (for production, use proper resampling)
                resample_ratio = self.sample_rate / sample_rate
                new_length = int(len(float_samples) * resample_ratio)
                if new_length > 0:
                    old_indices = np.linspace(0, len(float_samples) - 1, len(float_samples))
                    new_indices = np.linspace(0, len(float_samples) - 1, new_length)
                    float_samples = np.interp(new_indices, old_indices, float_samples)
            
            # Add to buffer
            with self.buffer_lock:
                buffer_size_before = len(self.audio_buffer)
                self.audio_buffer.append(float_samples)
                self.stats['audio_chunks_queued'] += 1
                buffer_size_after = len(self.audio_buffer)
                
                # Calculate total buffered duration
                total_samples = sum(len(chunk) for chunk in self.audio_buffer)
                total_duration_ms = (total_samples / self.sample_rate) * 1000
            
            logger.debug(f"🔊 [AudioOutputTrack] Queued Nova Sonic audio for {self.client_id}:")
            logger.debug(f"   - Chunk: {len(float_samples)} samples ({duration_ms:.1f}ms)")
            logger.debug(f"   - Buffer: {buffer_size_before} -> {buffer_size_after} chunks")
            logger.debug(f"   - Total buffered: {total_duration_ms:.1f}ms ({total_samples} samples)")
            
        except Exception as e:
            logger.error(f"[AudioOutputTrack] Error queuing audio for {self.client_id}: {e}")
    
    def queue_raw_audio(self, audio_data: np.ndarray, sample_rate: int):
        """
        Queue raw audio data for playback (for loopback mode)
        
        Args:
            audio_data: Raw audio data as numpy array (float32 normalized to [-1, 1])
            sample_rate: Sample rate of the audio data
        """
        try:
            # Ensure audio is float32
            if audio_data.dtype != np.float32:
                if audio_data.dtype == np.int16:
                    float_samples = audio_data.astype(np.float32) / 32767.0
                elif audio_data.dtype == np.int32:
                    float_samples = audio_data.astype(np.float32) / 2147483647.0
                else:
                    float_samples = audio_data.astype(np.float32)
            else:
                float_samples = audio_data.copy()
            
            # Resample if needed
            if sample_rate != self.sample_rate:
                logger.debug(f"[AudioOutputTrack] Resampling: {sample_rate}Hz -> {self.sample_rate}Hz")
                resample_ratio = self.sample_rate / sample_rate
                new_length = int(len(float_samples) * resample_ratio)
                if new_length > 0:
                    old_indices = np.linspace(0, len(float_samples) - 1, len(float_samples))
                    new_indices = np.linspace(0, len(float_samples) - 1, new_length)
                    float_samples = np.interp(new_indices, old_indices, float_samples)
            
            # Add to buffer
            with self.buffer_lock:
                self.audio_buffer.append(float_samples)
                self.stats['audio_chunks_queued'] += 1
            
            # Removed verbose debug logging for raw audio queuing
            
        except Exception as e:
            logger.error(f"[AudioOutputTrack] Error queuing raw audio for {self.client_id}: {e}")
            
    def queue_test_audio(self, test_audio_path: str):
        """
        Queue test audio file for playback during testing
        
        Args:
            test_audio_path: Path to test audio file (WAV or PCM)
        """
        try:
            import os
            import wave
            
            if not os.path.exists(test_audio_path):
                logger.error(f"[AudioOutputTrack] Test audio file not found: {test_audio_path}")
                return
                
            logger.debug(f"🧪 [AudioOutputTrack] Loading test audio for {self.client_id}: {test_audio_path}")
            
            if test_audio_path.endswith('.wav'):
                # Load WAV file
                with wave.open(test_audio_path, 'rb') as wav_file:
                    frames = wav_file.getnframes()
                    sample_rate = wav_file.getframerate()
                    channels = wav_file.getnchannels()
                    sample_width = wav_file.getsampwidth()
                    
                    logger.debug(f"🧪 [AudioOutputTrack] WAV file info: {frames} frames, {sample_rate}Hz, {channels}ch, {sample_width*8}bit")
                    
                    # Read audio data
                    audio_bytes = wav_file.readframes(frames)
                    
                    # Convert to numpy array based on sample width
                    if sample_width == 2:  # 16-bit
                        audio_samples = np.frombuffer(audio_bytes, dtype=np.int16)
                    elif sample_width == 4:  # 32-bit
                        audio_samples = np.frombuffer(audio_bytes, dtype=np.int32)
                        audio_samples = (audio_samples / 2147483647.0 * 32767).astype(np.int16)
                    else:
                        logger.error(f"[AudioOutputTrack] Unsupported sample width: {sample_width}")
                        return
                    
                    # Handle stereo to mono conversion
                    if channels == 2:
                        audio_samples = audio_samples.reshape(-1, 2)
                        audio_samples = np.mean(audio_samples, axis=1).astype(np.int16)
                        logger.debug(f"🧪 [AudioOutputTrack] Converted stereo to mono")
                    
            elif test_audio_path.endswith('.pcm'):
                # Load raw PCM file (assume 16-bit, 24kHz, mono)
                with open(test_audio_path, 'rb') as pcm_file:
                    audio_bytes = pcm_file.read()
                    audio_samples = np.frombuffer(audio_bytes, dtype=np.int16)
                    sample_rate = 24000  # Assume 24kHz for PCM
                    
                    logger.debug(f"🧪 [AudioOutputTrack] PCM file info: {len(audio_samples)} samples, assumed {sample_rate}Hz")
            else:
                logger.error(f"[AudioOutputTrack] Unsupported test audio format: {test_audio_path}")
                return
            
            # Convert to float32 normalized to [-1, 1]
            float_samples = audio_samples.astype(np.float32) / 32767.0
            
            # Resample if needed
            if sample_rate != self.sample_rate:
                logger.debug(f"🧪 [AudioOutputTrack] Resampling test audio: {sample_rate}Hz -> {self.sample_rate}Hz")
                resample_ratio = self.sample_rate / sample_rate
                new_length = int(len(float_samples) * resample_ratio)
                if new_length > 0:
                    old_indices = np.linspace(0, len(float_samples) - 1, len(float_samples))
                    new_indices = np.linspace(0, len(float_samples) - 1, new_length)
                    float_samples = np.interp(new_indices, old_indices, float_samples)
            
            # Add to buffer
            with self.buffer_lock:
                self.audio_buffer.append(float_samples)
                self.stats['audio_chunks_queued'] += 1
            
            duration_seconds = len(float_samples) / self.sample_rate
            logger.debug(f"🧪 [AudioOutputTrack] Queued test audio for {self.client_id}: {len(float_samples)} samples, {duration_seconds:.2f}s duration")
            
        except Exception as e:
            logger.error(f"[AudioOutputTrack] Error loading test audio for {self.client_id}: {e}")
            import traceback
            logger.error(f"[AudioOutputTrack] Traceback: {traceback.format_exc()}")
    
    def clear_buffer(self):
        """Clear audio buffer (for barge-in scenarios)"""
        with self.buffer_lock:
            self.audio_buffer.clear()
        logger.debug(f"[AudioOutputTrack] Cleared audio buffer for {self.client_id}")
    

    
    def get_stats(self) -> Dict[str, Any]:
        """Get track statistics"""
        with self.buffer_lock:
            buffer_size = len(self.audio_buffer)
            total_samples = sum(len(chunk) for chunk in self.audio_buffer)
        
        return {
            **self.stats,
            'client_id': self.client_id,
            'buffer_chunks': buffer_size,
            'buffer_samples': total_samples,
            'buffer_duration_ms': (total_samples / self.sample_rate) * 1000 if total_samples > 0 else 0,
            'frames_sent': self.frames_sent,
            'is_active': buffer_size > 0
        }
    
    def stop(self):
        """Stop the audio track"""
        self.clear_buffer()
        logger.debug(f"[AudioOutputTrack] Stopped for client {self.client_id}")