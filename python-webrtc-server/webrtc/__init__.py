"""
WebRTC module for Nova S2S
Provides WebRTC Master functionality for real-time audio streaming and event messaging
"""

from .KVSWebRTCMaster import KVSWebRTCMaster
from .KVSWebRTCViewer import KVSWebRTCViewer
from .AudioProcessor import AudioProcessor
from .EventBridge import EventBridge

__all__ = [
    'KVSWebRTCMaster',
    'KVSWebRTCViewer',
    'AudioProcessor',
    'EventBridge'
]