"""
MediaRecorder - Records WebRTC audio and video streams to MP4 files
Handles both audio and video tracks from React client for testing purposes
"""

import asyncio
import logging
import os
import threading
import time
from datetime import datetime
from typing import Dict, Optional, List
import numpy as np
import cv2
from av import VideoFrame, AudioFrame
import subprocess


logger = logging.getLogger(__name__)

class MediaRecorder:
    """
    Records WebRTC media streams to MP4 files for testing
    """
    
    def __init__(self):
        self.is_active = False
        self.buffer_lock = threading.Lock()
        
        # Recording state
        self.active_recordings: Dict[str, dict] = {}  # client_id -> recording_info
        
        # Media buffers
        self.audio_buffers: Dict[str, List] = {}  # client_id -> audio frames
        self.video_buffers: Dict[str, List] = {}  # client_id -> video frames
        
        # Recording configuration
        self.output_dir = None
        self.recording_counter = 0
        
        # Stats
        self.stats = {
            'recordings_started': 0,
            'recordings_completed': 0,
            'audio_frames_received': 0,
            'video_frames_received': 0,
            'total_duration_recorded': 0.0
        }
        
        # Create output directory
        self._ensure_output_dir()
        
        logger.debug("[MediaRecorder] Initialized media recorder for WebRTC streams")
        
    def _ensure_output_dir(self):
        """Create output directory for media files"""
        try:
            # Use the same logs directory structure as webrtc_server.py
            # MediaRecorder.py is in webrtc/ subdirectory, so we need to go up two levels to match webrtc_server.py
            logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "logs")
            self.output_dir = os.path.join(logs_dir, "media_test")
            
            # Ensure both logs and media_test directories exist
            os.makedirs(self.output_dir, exist_ok=True)
            
            logger.debug(f"[MediaRecorder] Created/verified output directory: {self.output_dir}")
            logger.debug(f"[MediaRecorder] Absolute path: {os.path.abspath(self.output_dir)}")
            logger.debug(f"[MediaRecorder] This matches webrtc_server.py logs directory structure")
                
        except Exception as e:
            logger.error(f"[MediaRecorder] Failed to create output directory: {e}")
            # Fallback to a temp directory in the current working directory
            try:
                self.output_dir = os.path.join(os.getcwd(), "temp_media_test")
                os.makedirs(self.output_dir, exist_ok=True)
                logger.warning(f"[MediaRecorder] Using fallback directory: {self.output_dir}")
            except Exception as fallback_error:
                logger.error(f"[MediaRecorder] Fallback directory creation failed: {fallback_error}")
                self.output_dir = None
            
    def start_recording(self, client_id: str, duration_seconds: float = 10.0):
        """
        Start recording media streams for a client
        
        Args:
            client_id: Client identifier
            duration_seconds: Recording duration in seconds
        """
        try:
            with self.buffer_lock:
                if client_id in self.active_recordings:
                    logger.warning(f"[MediaRecorder] Recording already active for {client_id}")
                    return
                
                self.recording_counter += 1
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                
                recording_info = {
                    'client_id': client_id,
                    'start_time': time.time(),
                    'duration': duration_seconds,
                    'timestamp': timestamp,
                    'counter': self.recording_counter,
                    'audio_frames': 0,
                    'video_frames': 0,
                    'output_file': os.path.join(self.output_dir, f"webrtc_test_{timestamp}_{self.recording_counter:04d}.mp4")
                }
                
                self.active_recordings[client_id] = recording_info
                self.audio_buffers[client_id] = []
                self.video_buffers[client_id] = []
                
                logger.debug(f"🎬 [MediaRecorder] Started recording for {client_id}:")
                logger.debug(f"   Duration: {duration_seconds}s")
                logger.debug(f"   Output: {recording_info['output_file']}")
                
                # Schedule automatic stop
                asyncio.create_task(self._auto_stop_recording(client_id, duration_seconds))
                
                self.stats['recordings_started'] += 1
                
        except Exception as e:
            logger.error(f"[MediaRecorder] Error starting recording for {client_id}: {e}")
            
    async def _auto_stop_recording(self, client_id: str, duration: float):
        """Automatically stop recording after specified duration"""
        try:
            await asyncio.sleep(duration)
            await self.stop_recording(client_id)
        except Exception as e:
            logger.error(f"[MediaRecorder] Error in auto-stop for {client_id}: {e}")
            
    async def stop_recording(self, client_id: str):
        """
        Stop recording and save media file
        
        Args:
            client_id: Client identifier
        """
        try:
            with self.buffer_lock:
                if client_id not in self.active_recordings:
                    logger.warning(f"[MediaRecorder] No active recording for {client_id}")
                    return
                
                recording_info = self.active_recordings[client_id]
                audio_frames = self.audio_buffers.get(client_id, [])
                video_frames = self.video_buffers.get(client_id, [])
                
                # Remove from active recordings
                del self.active_recordings[client_id]
                if client_id in self.audio_buffers:
                    del self.audio_buffers[client_id]
                if client_id in self.video_buffers:
                    del self.video_buffers[client_id]
                
            # Save media file
            await self._save_media_file(recording_info, audio_frames, video_frames)
            
            actual_duration = time.time() - recording_info['start_time']
            self.stats['recordings_completed'] += 1
            self.stats['total_duration_recorded'] += actual_duration
            
            logger.info(f"✅ [MediaRecorder] Completed recording for {client_id}: {actual_duration:.2f}s")
            
        except Exception as e:
            logger.error(f"[MediaRecorder] Error stopping recording for {client_id}: {e}")
            
    async def add_audio_frame(self, client_id: str, frame):
        """
        Add audio frame to recording buffer
        
        Args:
            client_id: Client identifier
            frame: WebRTC audio frame
        """
        try:
            with self.buffer_lock:
                if client_id not in self.active_recordings:
                    return  # Not recording for this client
                
                # Debug: Log frame properties and Nova Sonic compatibility (only first frame)
                if len(self.audio_buffers[client_id]) == 0:  # Log only first frame
                    logger.debug(f"🔍 [MediaRecorder] Audio frame debug for {client_id}:")
                    logger.debug(f"   Sample rate: {frame.sample_rate}Hz")
                    logger.debug(f"   Samples: {frame.samples}")
                    if hasattr(frame, 'format'):
                        logger.debug(f"   Format: {frame.format}")
                    if hasattr(frame, 'layout'):
                        logger.debug(f"   Layout: {frame.layout}")
                    
                    # Nova Sonic compatibility check
                    nova_compatible = (
                        frame.sample_rate == 16000 and
                        str(frame.format).lower() in ['s16', 's16le', '<av.audioformat s16>'] and
                        str(frame.layout).lower() in ['mono', '<av.audiolayout \'mono\'>']
                    )
                    logger.debug(f"   🤖 Nova Sonic compatible: {nova_compatible}")
                    if not nova_compatible:
                        logger.warning(f"   ⚠️  Expected: 16kHz, s16, mono")
                
                # Convert frame to numpy array
                audio_data = self._frame_to_numpy(frame)
                if audio_data is None:
                    return
                
                # Debug: Log converted data properties (only first frame)
                if len(self.audio_buffers[client_id]) == 0:  # Log only first frame
                    logger.debug(f"   Converted shape: {audio_data.shape}")
                    logger.debug(f"   Converted dtype: {audio_data.dtype}")
                    logger.debug(f"   Converted samples: {len(audio_data)}")
                    logger.debug(f"   RMS: {np.sqrt(np.mean(audio_data.astype(np.float32) ** 2)):.2f}")
                
                # Store frame data
                frame_info = {
                    'timestamp': time.time(),
                    'sample_rate': frame.sample_rate,
                    'samples': frame.samples,
                    'data': audio_data,
                    'frame_number': len(self.audio_buffers[client_id])
                }
                
                self.audio_buffers[client_id].append(frame_info)
                self.active_recordings[client_id]['audio_frames'] += 1
                self.stats['audio_frames_received'] += 1
                
                if len(self.audio_buffers[client_id]) % 50 == 0:  # Log every 50 frames
                    logger.debug(f"🎤 [MediaRecorder] Audio frame #{len(self.audio_buffers[client_id])} from {client_id}")
                
        except Exception as e:
            logger.error(f"[MediaRecorder] Error adding audio frame for {client_id}: {e}")
            
    async def add_video_frame(self, client_id: str, frame):
        """
        Add video frame to recording buffer
        
        Args:
            client_id: Client identifier
            frame: WebRTC video frame
        """
        try:
            with self.buffer_lock:
                if client_id not in self.active_recordings:
                    return  # Not recording for this client
                
                # Debug: Log first video frame only
                if len(self.video_buffers[client_id]) == 0:
                    logger.debug(f"🔍 [MediaRecorder] Video frame debug for {client_id}:")
                    logger.debug(f"   Width: {frame.width}, Height: {frame.height}")
                    if hasattr(frame, 'format'):
                        logger.debug(f"   Format: {frame.format}")
                    if hasattr(frame, 'time_base'):
                        logger.debug(f"   Time base: {frame.time_base}")
                    if hasattr(frame, 'pts'):
                        logger.debug(f"   PTS: {frame.pts}")
                
                # Convert frame to numpy array
                video_data = self._video_frame_to_numpy(frame)
                if video_data is None:
                    return
                
                # Store frame data with more timing info
                frame_info = {
                    'timestamp': time.time(),
                    'width': frame.width,
                    'height': frame.height,
                    'format': frame.format.name if hasattr(frame.format, 'name') else str(frame.format),
                    'data': video_data,
                    'frame_number': len(self.video_buffers[client_id]),
                    'pts': getattr(frame, 'pts', None),
                    'time_base': getattr(frame, 'time_base', None)
                }
                
                self.video_buffers[client_id].append(frame_info)
                self.active_recordings[client_id]['video_frames'] += 1
                self.stats['video_frames_received'] += 1
                
                if len(self.video_buffers[client_id]) % 30 == 0:  # Log every 30 frames
                    logger.debug(f"📹 [MediaRecorder] Video frame #{len(self.video_buffers[client_id])} from {client_id}")
                
        except Exception as e:
            logger.error(f"[MediaRecorder] Error adding video frame for {client_id}: {e}")
            
    def _frame_to_numpy(self, frame) -> Optional[np.ndarray]:
        """Convert WebRTC audio frame to numpy array"""
        try:
            if hasattr(frame, 'to_ndarray'):
                audio_array = frame.to_ndarray()
                
                logger.debug(f"[MediaRecorder] Raw audio array shape: {audio_array.shape}, dtype: {audio_array.dtype}")
                
                # CRITICAL FIX: Handle stereo data correctly
                expected_samples = frame.samples  # This should be 960 for stereo
                
                if audio_array.ndim == 2:
                    logger.debug(f"[MediaRecorder] 2D array detected: {audio_array.shape}")
                    # Special case: (1, 1920) with 960 expected samples = interleaved stereo in single row
                    if audio_array.shape[0] == 1 and audio_array.shape[1] == expected_samples * 2:
                        logger.debug(f"[MediaRecorder] Detected interleaved stereo in 2D array: (1, {audio_array.shape[1]}) -> {expected_samples} samples")
                        # Flatten and then de-interleave
                        audio_array = audio_array.flatten()
                        audio_array = audio_array[::2]  # Take every other sample (left channel)
                        logger.debug(f"[MediaRecorder] After de-interleaving: {len(audio_array)} samples")
                    # Check if it's channels x samples or samples x channels
                    elif audio_array.shape[0] < audio_array.shape[1]:
                        # Likely channels x samples (e.g., 2 x 480)
                        if audio_array.shape[0] == 1:
                            # Mono: 1 x samples
                            audio_array = audio_array.flatten()
                        elif audio_array.shape[0] == 2:
                            # Stereo: 2 x samples - take left channel
                            logger.debug(f"[MediaRecorder] Taking left channel from 2D stereo array")
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
                            logger.debug(f"[MediaRecorder] Taking left channel from samples x channels array")
                            audio_array = audio_array[:, 0]
                        else:
                            # Multi-channel: take first channel
                            audio_array = audio_array[:, 0]
                elif audio_array.ndim == 1:
                    logger.debug(f"[MediaRecorder] 1D array detected: length={len(audio_array)}, expected_samples={expected_samples}")
                    # Check if it's interleaved stereo (L,R,L,R,...)
                    if len(audio_array) == expected_samples * 2:
                        logger.debug(f"[MediaRecorder] Detected interleaved stereo! De-interleaving {len(audio_array)} samples to {expected_samples}")
                        # De-interleave: take every other sample (left channel)
                        audio_array = audio_array[::2]
                        logger.debug(f"[MediaRecorder] After de-interleaving: {len(audio_array)} samples")
                    elif len(audio_array) == expected_samples:
                        logger.debug(f"[MediaRecorder] Already correct mono length: {len(audio_array)} samples")
                    else:
                        logger.warning(f"[MediaRecorder] Unexpected array length: {len(audio_array)}, expected {expected_samples} or {expected_samples * 2}")
                
                logger.debug(f"[MediaRecorder] Processed audio array shape: {audio_array.shape}")
                
                # Convert to int16 for proper audio levels
                if audio_array.dtype == np.float32 or audio_array.dtype == np.float64:
                    audio_array = np.clip(audio_array, -1.0, 1.0)
                    audio_array = (audio_array * 32767).astype(np.int16)
                
                return audio_array
            else:
                logger.warning("[MediaRecorder] Audio frame does not support to_ndarray conversion")
                return None
                
        except Exception as e:
            logger.error(f"[MediaRecorder] Error converting audio frame to numpy: {e}")
            return None
            
    def _video_frame_to_numpy(self, frame) -> Optional[np.ndarray]:
        """Convert WebRTC video frame to numpy array"""
        try:
            if hasattr(frame, 'to_ndarray'):
                # Get video data as numpy array
                video_array = frame.to_ndarray(format='bgr24')  # OpenCV format
                return video_array
            else:
                logger.warning("[MediaRecorder] Video frame does not support to_ndarray conversion")
                return None
                
        except Exception as e:
            logger.error(f"[MediaRecorder] Error converting video frame to numpy: {e}")
            return None
            
    async def _save_media_file(self, recording_info: dict, audio_frames: List, video_frames: List):
        """
        Save recorded media to MP4 file using FFmpeg
        
        Args:
            recording_info: Recording metadata
            audio_frames: List of audio frame data
            video_frames: List of video frame data
        """
        try:
            output_file = recording_info['output_file']
            client_id = recording_info['client_id']
            
            logger.debug(f"💾 [MediaRecorder] Saving media file for {client_id}:")
            logger.debug(f"   Audio frames: {len(audio_frames)}")
            logger.debug(f"   Video frames: {len(video_frames)}")
            logger.debug(f"   Output: {output_file}")
            
            # Create temporary files for audio and video
            temp_audio = output_file.replace('.mp4', '_temp_audio.wav')
            temp_video = output_file.replace('.mp4', '_temp_video.mp4')
            
            # Save audio if available
            audio_saved = False
            if audio_frames:
                audio_saved = await self._save_audio_wav(audio_frames, temp_audio)
            
            # Save video if available
            video_saved = False
            if video_frames:
                video_saved = await self._save_video_mp4(video_frames, temp_video)
            
            # Combine audio and video using FFmpeg with sync options
            if audio_saved and video_saved:
                # Both audio and video - use shortest stream to avoid sync issues
                cmd = [
                    'ffmpeg', '-y',
                    '-i', temp_video,
                    '-i', temp_audio,
                    '-c:v', 'copy',
                    '-c:a', 'aac',
                    '-strict', 'experimental',
                    '-shortest',  # Use shortest stream duration
                    '-avoid_negative_ts', 'make_zero',  # Fix timestamp issues
                    output_file
                ]
            elif video_saved:
                # Video only
                cmd = ['ffmpeg', '-y', '-i', temp_video, '-c:v', 'copy', output_file]
            elif audio_saved:
                # Audio only
                cmd = ['ffmpeg', '-y', '-i', temp_audio, '-c:a', 'aac', output_file]
            else:
                logger.warning(f"[MediaRecorder] No media data to save for {client_id}")
                return
            
            # Run FFmpeg
            logger.debug(f"🔧 [MediaRecorder] Running FFmpeg: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                logger.info(f"✅ [MediaRecorder] Successfully created MP4: {output_file}")
                
                # Create metadata file
                await self._save_metadata(recording_info, audio_frames, video_frames, output_file)
                
                # Clean up temporary files
                for temp_file in [temp_audio, temp_video]:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                        
            else:
                logger.error(f"❌ [MediaRecorder] FFmpeg failed: {result.stderr}")
                
        except Exception as e:
            logger.error(f"[MediaRecorder] Error saving media file: {e}")
            
    async def _save_audio_wav(self, audio_frames: List, output_file: str) -> bool:
        """Save audio frames to WAV file"""
        try:
            if not audio_frames:
                return False
            
            # Ensure output directory exists
            output_dir = os.path.dirname(output_file)
            if not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)
                logger.debug(f"[MediaRecorder] Created directory for audio file: {output_dir}")
            
            # Combine all audio data
            all_audio_data = []
            sample_rate = audio_frames[0]['sample_rate']
            
            for frame in audio_frames:
                all_audio_data.append(frame['data'])
            
            combined_audio = np.concatenate(all_audio_data)
            
            # Save as WAV using scipy
            from scipy.io import wavfile
            wavfile.write(output_file, sample_rate, combined_audio)
            
            logger.debug(f"🎵 [MediaRecorder] Saved audio WAV: {output_file} ({len(combined_audio)} samples at {sample_rate}Hz)")
            return True
            
        except Exception as e:
            logger.error(f"[MediaRecorder] Error saving audio WAV: {e}")
            logger.error(f"[MediaRecorder] Output file path: {output_file}")
            logger.error(f"[MediaRecorder] Output directory exists: {os.path.exists(os.path.dirname(output_file))}")
            return False
            
    async def _save_video_mp4(self, video_frames: List, output_file: str) -> bool:
        """Save video frames to MP4 file using OpenCV"""
        try:
            if not video_frames:
                return False
            
            # Get video properties from first frame
            first_frame = video_frames[0]
            width = first_frame['width']
            height = first_frame['height']
            
            # Calculate actual FPS based on timestamps
            if len(video_frames) > 1:
                first_timestamp = video_frames[0]['timestamp']
                last_timestamp = video_frames[-1]['timestamp']
                duration = last_timestamp - first_timestamp
                calculated_fps = len(video_frames) / duration if duration > 0 else 30
                
                # Use reasonable FPS bounds
                fps = max(10, min(60, calculated_fps))
                logger.debug(f"📹 [MediaRecorder] Calculated FPS: {calculated_fps:.2f}, using: {fps:.2f}")
            else:
                fps = 30  # Fallback
                logger.debug(f"📹 [MediaRecorder] Using fallback FPS: {fps}")
            
            # Create video writer
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(output_file, fourcc, fps, (width, height))
            
            for frame_info in video_frames:
                frame_data = frame_info['data']
                out.write(frame_data)
            
            out.release()
            
            expected_duration = len(video_frames) / fps
            logger.debug(f"📹 [MediaRecorder] Saved video MP4: {output_file}")
            logger.debug(f"   Frames: {len(video_frames)}, FPS: {fps:.2f}, Expected duration: {expected_duration:.2f}s")
            return True
            
        except Exception as e:
            logger.error(f"[MediaRecorder] Error saving video MP4: {e}")
            return False
            
    async def _save_metadata(self, recording_info: dict, audio_frames: List, video_frames: List, output_file: str):
        """Save recording metadata"""
        try:
            metadata_file = output_file.replace('.mp4', '_metadata.txt')
            
            with open(metadata_file, 'w') as f:
                f.write(f"WebRTC Media Recording Metadata\n")
                f.write(f"================================\n")
                f.write(f"Client ID: {recording_info['client_id']}\n")
                f.write(f"Timestamp: {recording_info['timestamp']}\n")
                f.write(f"Recording Duration: {recording_info['duration']}s\n")
                f.write(f"Output File: {os.path.basename(output_file)}\n")
                f.write(f"\n")
                f.write(f"Audio Information:\n")
                f.write(f"  Frames: {len(audio_frames)}\n")
                if audio_frames:
                    f.write(f"  Sample Rate: {audio_frames[0]['sample_rate']}Hz\n")
                    total_samples = sum(len(frame['data']) for frame in audio_frames)
                    f.write(f"  Total Samples: {total_samples}\n")
                    f.write(f"  Duration: {total_samples / audio_frames[0]['sample_rate']:.2f}s\n")
                f.write(f"\n")
                f.write(f"Video Information:\n")
                f.write(f"  Frames: {len(video_frames)}\n")
                if video_frames:
                    f.write(f"  Resolution: {video_frames[0]['width']}x{video_frames[0]['height']}\n")
                    f.write(f"  Format: {video_frames[0]['format']}\n")
                    f.write(f"  Duration: {len(video_frames) / 30:.2f}s (assuming 30fps)\n")
                f.write(f"\n")
                f.write(f"To play the file:\n")
                f.write(f"ffplay {os.path.basename(output_file)}\n")
                f.write(f"\n")
                f.write(f"To analyze with ffprobe:\n")
                f.write(f"ffprobe -v quiet -print_format json -show_format -show_streams {os.path.basename(output_file)}\n")
            
            logger.debug(f"📄 [MediaRecorder] Saved metadata: {metadata_file}")
            
        except Exception as e:
            logger.error(f"[MediaRecorder] Error saving metadata: {e}")
            
    def get_stats(self) -> dict:
        """Get recording statistics"""
        return {
            **self.stats,
            'active_recordings': len(self.active_recordings),
            'output_directory': self.output_dir
        }
        
    def cleanup_client(self, client_id: str):
        """Clean up resources for a client"""
        try:
            with self.buffer_lock:
                if client_id in self.active_recordings:
                    logger.debug(f"[MediaRecorder] Cleaning up active recording for {client_id}")
                    del self.active_recordings[client_id]
                
                if client_id in self.audio_buffers:
                    del self.audio_buffers[client_id]
                    
                if client_id in self.video_buffers:
                    del self.video_buffers[client_id]
                    
        except Exception as e:
            logger.error(f"[MediaRecorder] Error cleaning up client {client_id}: {e}")