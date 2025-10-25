"""
Phone Detection Processor - Real-time mobile phone usage detection for connected vehicles
Only active in WebRTC Viewer mode for monitoring driver behavior
"""

import asyncio
import logging
import os
import time
import cv2
import numpy as np
from typing import Optional, Callable
from datetime import datetime
import threading

logger = logging.getLogger(__name__)

class PhoneDetectionProcessor:
    """
    Real-time phone detection processor for video streams
    Integrates with MediaRecorder for automatic recording during phone usage
    """
    
    # Configuration constants
    DEFAULT_FRAME_SAMPLING = 15  # Process every Nth frame (higher = less frequent processing)
    
    def __init__(self, media_recorder=None):
        """
        Initialize phone detection processor
        
        Args:
            media_recorder: MediaRecorder instance for MP4 recording
        """
        self.media_recorder = media_recorder
        self.yolo_model = None
        self.is_processing = False
        self.detection_enabled = False
        
        # Detection parameters
        self.confidence_threshold = 0.5
        self.consecutive_frames_required = 3
        self.recording_duration = 3.0       # Fixed recording duration for phone usage incidents
        self.cooldown_period = 10.0         # seconds
        
        # Detection state
        self.consecutive_detections = 0
        self.phone_detected = False
        self.last_detection_time = 0
        self.recording_active = False
        self.last_recording_end = 0
        
        # Frame processing - frame-based sampling for performance
        self.frame_count = 0
        self.process_every_n_frames = self.DEFAULT_FRAME_SAMPLING  # Configurable sampling rate
        self.frame_timestamps = []  # Track frame timing for interval calculation
        
        # Statistics
        self.stats = {
            'frames_processed': 0,
            'phone_detections': 0,
            'recordings_triggered': 0,
            'total_recording_time': 0.0,
            'last_detection': None
        }
        
        # Thread safety
        self.processing_lock = threading.Lock()
        
        logger.info("[PhoneDetectionProcessor] Initialized phone detection processor")
        
    def initialize_model(self):
        """Initialize YOLOv8 model for phone detection"""
        try:
            # Check if phone detection is enabled
            if os.getenv('ENABLE_PHONE_DETECTION', '').lower() != 'true':
                logger.info("[PhoneDetectionProcessor] Phone detection disabled (ENABLE_PHONE_DETECTION not set)")
                return False
                
            logger.info("[PhoneDetectionProcessor] Initializing YOLOv8 model...")
            
            # Import ultralytics (will be added to requirements)
            try:
                from ultralytics import YOLO
            except ImportError:
                logger.error("[PhoneDetectionProcessor] ultralytics not installed. Run: pip install ultralytics")
                return False
            
            # Load YOLOv8 nano model (lightweight)
            logger.info("[PhoneDetectionProcessor] Loading YOLOv8n model (this may take a moment on first run)...")
            self.yolo_model = YOLO('yolov8n.pt')
            logger.info("[PhoneDetectionProcessor] YOLOv8n model loaded successfully")
            

            
            self.detection_enabled = True
            logger.info("✅ [PhoneDetectionProcessor] YOLOv8 model initialized successfully")
            logger.info(f"[PhoneDetectionProcessor] Detection parameters:")
            logger.info(f"   Confidence threshold: {self.confidence_threshold}")
            logger.info(f"   Consecutive frames required: {self.consecutive_frames_required}")
            logger.info(f"   Recording duration: {self.recording_duration}s (fixed duration for phone usage)")
            logger.info(f"   Cooldown period: {self.cooldown_period}s")
            logger.info(f"[PhoneDetectionProcessor] Frame sampling configuration:")
            logger.info(f"   Processing every {self.process_every_n_frames} frames for performance")
            logger.info(f"   Expected sampling rate: ~{30/self.process_every_n_frames:.1f} FPS (assuming 30 FPS input)")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ [PhoneDetectionProcessor] Error initializing model: {e}")
            self.detection_enabled = False
            return False
            
    async def process_video_frame(self, frame_data: np.ndarray, client_id: str = "master"):
        """
        Process individual video frame for phone detection
        
        Args:
            frame_data: Video frame as numpy array (BGR format)
            client_id: Client identifier
        """
        if not self.detection_enabled or not self.yolo_model:
            return
            
        try:
            with self.processing_lock:
                current_time = time.time()
                self.frame_count += 1
                
                # Skip frames for performance (process every Nth frame)
                if self.frame_count % self.process_every_n_frames != 0:
                    return
                
                # Track processed frame timing
                self.frame_timestamps.append(current_time)
                self.stats['frames_processed'] += 1
                
                # Log sampling stats occasionally (every 100 processed frames)
                if len(self.frame_timestamps) >= 2 and self.stats['frames_processed'] % 100 == 0:
                    recent_timestamps = self.frame_timestamps[-10:]
                    if len(recent_timestamps) >= 2:
                        intervals = [recent_timestamps[i] - recent_timestamps[i-1] 
                                   for i in range(1, len(recent_timestamps))]
                        avg_interval = sum(intervals) / len(intervals)
                        sampling_fps = 1.0 / avg_interval if avg_interval > 0 else 0
                        
                        logger.debug(f"📊 [PhoneDetectionProcessor] Processed {self.stats['frames_processed']} frames, detection FPS: {sampling_fps:.1f}")
                
                # Keep only recent timestamps to avoid memory growth
                if len(self.frame_timestamps) > 20:
                    self.frame_timestamps = self.frame_timestamps[-10:]
                
                # Ensure frame is in correct format for YOLO
                if not isinstance(frame_data, np.ndarray):
                    logger.error(f"[PhoneDetectionProcessor] Invalid frame data type: {type(frame_data)}")
                    return
                
                if len(frame_data.shape) != 3 or frame_data.shape[2] != 3:
                    logger.error(f"[PhoneDetectionProcessor] Invalid frame shape: {frame_data.shape}, expected (H, W, 3)")
                    return
                

                
                # Ensure frame is in correct format for YOLO processing
                frame_data = np.ascontiguousarray(frame_data)
                
                # Ensure frame is in uint8 format (required by YOLO)
                if frame_data.dtype != np.uint8:
                    if frame_data.dtype == np.float32 or frame_data.dtype == np.float64:
                        # Convert from float [0,1] to uint8 [0,255]
                        if frame_data.max() <= 1.0:
                            frame_data = (frame_data * 255).astype(np.uint8)
                        else:
                            frame_data = np.clip(frame_data, 0, 255).astype(np.uint8)
                    else:
                        # Convert other types to uint8
                        frame_data = np.clip(frame_data, 0, 255).astype(np.uint8)
                
                # Ensure frame has correct memory layout
                if not frame_data.flags.c_contiguous:
                    frame_data = np.ascontiguousarray(frame_data)
                
                # Ensure frame is in standard OpenCV format (BGR)
                if frame_data.shape[2] == 3:
                    # Assume it's already in BGR format from WebRTC
                    pass
                elif frame_data.shape[2] == 4:
                    # Convert RGBA to BGR
                    frame_data = cv2.cvtColor(frame_data, cv2.COLOR_RGBA2BGR)
                else:
                    logger.error(f"[PhoneDetectionProcessor] Unsupported channel count: {frame_data.shape[2]}")
                    return
                
                # Process frame with YOLO
                try:
                    # Use PIL Image (most reliable method)
                    from PIL import Image
                    # Convert BGR to RGB for PIL
                    rgb_data = frame_data[:, :, ::-1]  # BGR to RGB
                    pil_image = Image.fromarray(rgb_data, 'RGB')
                    results = self.yolo_model(pil_image, verbose=False)
                        
                except Exception as processing_error:
                    logger.debug(f"[PhoneDetectionProcessor] Frame processing failed, skipping: {processing_error}")
                    return
                
                # Check for phone detection
                phone_detected_in_frame = False
                total_detections = 0
                
                for result in results:
                    if result.boxes is not None:
                        total_detections += len(result.boxes)
                        for box in result.boxes:
                            # Check if detected object is a cell phone (class 67 in COCO)
                            class_id = int(box.cls[0])
                            confidence = float(box.conf[0])
                            
                            if class_id == 67 and confidence >= self.confidence_threshold:  # cell phone
                                phone_detected_in_frame = True
                                logger.warning(f"📱 [PhoneDetectionProcessor] Phone detected! Confidence: {confidence:.2f}")
                                break
                
                # Update detection state
                await self._update_detection_state(phone_detected_in_frame, client_id)
                
        except Exception as e:
            logger.error(f"❌ [PhoneDetectionProcessor] Error processing frame: {e}")
            
    async def _update_detection_state(self, phone_detected_in_frame: bool, client_id: str):
        """
        Update detection state and trigger recording if needed
        
        Args:
            phone_detected_in_frame: Whether phone was detected in current frame
            client_id: Client identifier
        """
        try:
            current_time = time.time()
            
            if phone_detected_in_frame:
                self.consecutive_detections += 1
                self.last_detection_time = current_time
                
                # Trigger detection if we have enough consecutive frames
                if (self.consecutive_detections >= self.consecutive_frames_required and 
                    not self.phone_detected):
                    
                    self.phone_detected = True
                    self.stats['phone_detections'] += 1
                    self.stats['last_detection'] = datetime.now().isoformat()
                    
                    logger.warning(f"🚨 [PhoneDetectionProcessor] PHONE USAGE DETECTED! (confidence after {self.consecutive_detections} frames)")
                    
                    # Start recording if not in cooldown period
                    if current_time - self.last_recording_end > self.cooldown_period:
                        await self._start_recording(client_id)
                    else:
                        logger.info(f"⏳ [PhoneDetectionProcessor] Recording in cooldown period ({self.cooldown_period}s)")
                        
            else:
                # Reset consecutive detections if no phone detected
                if self.consecutive_detections > 0:
                    self.consecutive_detections = 0
                    
                # Check if we should stop detection (phone no longer visible)
                # Use half the recording duration as buffer time for stopping detection
                stop_detection_buffer = self.recording_duration / 2
                if (self.phone_detected and 
                    current_time - self.last_detection_time > stop_detection_buffer):
                    
                    self.phone_detected = False
                    logger.info(f"✅ [PhoneDetectionProcessor] Phone no longer detected - ending detection period")
                    
                    # Stop recording after buffer period
                    if self.recording_active:
                        await self._stop_recording(client_id)
                        
        except Exception as e:
            logger.error(f"❌ [PhoneDetectionProcessor] Error updating detection state: {e}")
            
    async def _start_recording(self, client_id: str):
        """
        Start MP4 recording using MediaRecorder
        
        Args:
            client_id: Client identifier
        """
        try:
            if not self.media_recorder or self.recording_active:
                return
                
            # Use fixed recording duration for phone usage incidents
            recording_duration = self.recording_duration
            
            logger.warning(f"🎬 [PhoneDetectionProcessor] Starting phone usage recording for {client_id}")
            logger.info(f"📹 [PhoneDetectionProcessor] Recording duration: {recording_duration}s")
            
            # Start recording via MediaRecorder
            self.media_recorder.start_recording(client_id, recording_duration)
            
            self.recording_active = True
            self.stats['recordings_triggered'] += 1
            self.stats['total_recording_time'] += recording_duration
            
            logger.info(f"✅ [PhoneDetectionProcessor] Recording started successfully")
            
        except Exception as e:
            logger.error(f"❌ [PhoneDetectionProcessor] Error starting recording: {e}")
            
    async def _stop_recording(self, client_id: str):
        """
        Stop MP4 recording
        
        Args:
            client_id: Client identifier
        """
        try:
            if not self.recording_active:
                return
                
            logger.info(f"⏹️ [PhoneDetectionProcessor] Stopping phone usage recording for {client_id}")
            
            # Stop recording via MediaRecorder
            if self.media_recorder:
                await self.media_recorder.stop_recording(client_id)
            
            self.recording_active = False
            self.last_recording_end = time.time()
            
            logger.info(f"✅ [PhoneDetectionProcessor] Recording stopped successfully")
            
        except Exception as e:
            logger.error(f"❌ [PhoneDetectionProcessor] Error stopping recording: {e}")
            
    async def handle_audio_track(self, audio_track, client_id: str = "master"):
        """
        Handle audio track for MediaRecorder integration
        
        Args:
            audio_track: WebRTC audio track
            client_id: Client identifier
        """
        try:
            if not self.detection_enabled or not self.media_recorder:
                return
                
            logger.info(f"🎵 [PhoneDetectionProcessor] Starting audio track processing for MediaRecorder: {client_id}")
            
            # Process audio frames for recording
            while self.is_processing:
                try:
                    # Get frame from audio track
                    frame = await audio_track.recv()
                    
                    # Feed frame to MediaRecorder if recording is active
                    if self.recording_active and self.media_recorder:
                        await self.media_recorder.add_audio_frame(client_id, frame)
                    
                except Exception as frame_error:
                    logger.debug(f"[PhoneDetectionProcessor] Audio frame processing error (normal during shutdown): {frame_error}")
                    break
                    
            logger.info(f"[PhoneDetectionProcessor] Audio track processing ended for {client_id}")
            
        except Exception as e:
            logger.error(f"❌ [PhoneDetectionProcessor] Error handling audio track: {e}")

    async def handle_video_track(self, video_track, client_id: str = "master"):
        """
        Handle entire video track stream for phone detection
        
        Args:
            video_track: WebRTC video track
            client_id: Client identifier
        """
        try:
            if not self.detection_enabled:
                logger.info("[PhoneDetectionProcessor] Phone detection disabled - using MediaBlackhole for video")
                from aiortc.contrib.media import MediaBlackhole
                MediaBlackhole().addTrack(video_track)
                return
                
            logger.info(f"📹 [PhoneDetectionProcessor] Starting video track processing for {client_id}")
            
            logger.info(f"📹 [PhoneDetectionProcessor] Starting video track processing for {client_id}")
            
            self.is_processing = True
            
            self.is_processing = True
            
            # Process video frames
            while self.is_processing:
                try:
                    # Get frame from video track
                    frame = await video_track.recv()
                    
                    # Feed original frame to MediaRecorder if recording is active
                    if self.recording_active and self.media_recorder:
                        await self.media_recorder.add_video_frame(client_id, frame)
                    
                    # Convert to numpy array for phone detection
                    try:
                        frame_array = frame.to_ndarray(format='bgr24')
                        
                        # Process frame for phone detection
                        await self.process_video_frame(frame_array, client_id)
                        
                    except Exception as conversion_error:
                        logger.debug(f"[PhoneDetectionProcessor] Frame conversion error: {conversion_error}")
                        # Continue processing other frames instead of breaking
                        continue
                    
                except Exception as frame_error:
                    if "Connection lost" in str(frame_error) or "cancelled" in str(frame_error).lower():
                        logger.info(f"[PhoneDetectionProcessor] Video track ended normally")
                    else:
                        logger.error(f"❌ [PhoneDetectionProcessor] Frame processing error: {frame_error}")
                        import traceback
                        logger.error(f"❌ [PhoneDetectionProcessor] Traceback: {traceback.format_exc()}")
                    break
                    
            logger.info(f"[PhoneDetectionProcessor] Video track processing ended for {client_id}")
            
        except Exception as e:
            logger.error(f"❌ [PhoneDetectionProcessor] Error handling video track: {e}")
            import traceback
            logger.error(f"❌ [PhoneDetectionProcessor] Traceback: {traceback.format_exc()}")
        finally:
            self.is_processing = False
            
    def stop_processing(self):
        """Stop video processing"""
        logger.info("[PhoneDetectionProcessor] Stopping phone detection processing...")
        self.is_processing = False
        
    def get_stats(self) -> dict:
        """Get phone detection statistics"""
        return {
            **self.stats,
            'detection_enabled': self.detection_enabled,
            'phone_currently_detected': self.phone_detected,
            'recording_active': self.recording_active,
            'consecutive_detections': self.consecutive_detections
        }
        
    def get_detection_status(self) -> dict:
        """Get current detection status"""
        return {
            'enabled': self.detection_enabled,
            'processing': self.is_processing,
            'phone_detected': self.phone_detected,
            'recording_active': self.recording_active,
            'frames_processed': self.stats['frames_processed'],
            'total_detections': self.stats['phone_detections']
        }