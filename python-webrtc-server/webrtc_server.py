#!/usr/bin/env python3
"""
WebRTC Server - Main entry point for Nova S2S WebRTC Master
Starts the KVS WebRTC Master server with S2S integration
"""

import asyncio
import logging
import os
import sys
import argparse
from datetime import datetime
from webrtc_s2s_integration import WebRTCS2SIntegration

# Configure logging with file export
LOGLEVEL = os.environ.get("LOGLEVEL", "INFO").upper()

# Create shared logs directory
logs_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
if not os.path.exists(logs_dir):
    os.makedirs(logs_dir)

LOG_FILE = os.environ.get("LOG_FILE", os.path.join(logs_dir, "webrtc_server.log"))

# Force clear any existing handlers and configure logging explicitly
root_logger = logging.getLogger()

# Remove all existing handlers
for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)

# Also clear handlers from any child loggers that might interfere
for name in logging.Logger.manager.loggerDict:
    child_logger = logging.getLogger(name)
    for handler in child_logger.handlers[:]:
        child_logger.removeHandler(handler)

# Create formatters
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Create console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(LOGLEVEL)
console_handler.setFormatter(formatter)

# Create file handler with explicit path
file_handler = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8')
file_handler.setLevel(LOGLEVEL)
file_handler.setFormatter(formatter)

# Add handlers to root logger
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)
root_logger.setLevel(LOGLEVEL)

# Force all loggers to use root logger handlers
logging.basicConfig(level=LOGLEVEL, handlers=[console_handler, file_handler], force=True)

# Set third-party library log levels to reduce noise (must be done after basicConfig)
aioice_logger = logging.getLogger('aioice')
aioice_logger.setLevel(logging.WARNING)
aioice_logger.propagate = True

aiortc_logger = logging.getLogger('aiortc')
aiortc_logger.setLevel(logging.WARNING)
aiortc_logger.propagate = True

websockets_logger = logging.getLogger('websockets')
websockets_logger.setLevel(logging.WARNING)
websockets_logger.propagate = True

# Also set the ice submodule specifically
aioice_ice_logger = logging.getLogger('aioice.ice')
aioice_ice_logger.setLevel(logging.WARNING)
aioice_ice_logger.propagate = True

logger = logging.getLogger(__name__)

# Log the logging configuration
logger.debug(f"🗂️ [WebRTCServer] Logging configured - Level: {LOGLEVEL}, File: {LOG_FILE}")
logger.debug(f"🗂️ [WebRTCServer] Log file location: {os.path.abspath(LOG_FILE)}")
logger.debug(f"🗂️ [WebRTCServer] File handler active: {file_handler}")
logger.debug(f"🗂️ [WebRTCServer] Console handler active: {console_handler}")

# Verify third-party library log levels
logger.debug(f"🔧 [WebRTCServer] aioice log level: {logging.getLogger('aioice').level}")
logger.debug(f"🔧 [WebRTCServer] aioice.ice log level: {logging.getLogger('aioice.ice').level}")
logger.debug(f"🔧 [WebRTCServer] aiortc log level: {logging.getLogger('aiortc').level}")
logger.debug(f"🔧 [WebRTCServer] websockets log level: {logging.getLogger('websockets').level}")

# Test file logging
try:
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"# LOG FILE TEST - {datetime.now().isoformat()} - File logging is working\n")
    logger.debug(f"✅ [WebRTCServer] File logging test successful")
except Exception as e:
    logger.error(f"❌ [WebRTCServer] File logging test failed: {e}")
    print(f"CRITICAL: Cannot write to log file {LOG_FILE}: {e}")

async def main():
    """Main entry point for WebRTC server"""
    parser = argparse.ArgumentParser(description='Nova S2S WebRTC Server')
    parser.add_argument('--region', default=os.environ.get('AWS_REGION', 'ap-northeast-1'),
                       help='AWS region (default: ap-northeast-1)')
    parser.add_argument('--channel-name', default=os.environ.get('KVS_CHANNEL_NAME', 'nova-s2s-webrtc-test'),
                       help='KVS channel name (default: nova-s2s-webrtc-test)')
    parser.add_argument('--model-id', default='amazon.nova-sonic-v1:0',
                       help='Bedrock model ID (default: amazon.nova-sonic-v1:0)')
    
    args = parser.parse_args()
    
    logger.info(f"Starting Nova S2S WebRTC Server")
    logger.debug(f"Region: {args.region}")
    logger.debug(f"Channel: {args.channel_name}")
    logger.debug(f"Model: {args.model_id}")
    
    try:
        # Initialize WebRTC S2S integration
        integration = WebRTCS2SIntegration(
            region=args.region,
            model_id=args.model_id
        )
        
        logger.info("🤖 [WebRTCServer] S2S MODE - Audio will be processed by Nova Sonic")
        
        # Initialize and start the WebRTC master server
        await integration.initialize_webrtc_master(args.channel_name)
        await integration.start()
        
        logger.info(f"WebRTC server started successfully on channel: {args.channel_name}")
        logger.debug(f"Waiting for WebRTC viewer connections...")
        
        # Keep the server running
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
            
    except Exception as e:
        logger.error(f"Failed to start WebRTC server: {e}")
        sys.exit(1)
    finally:
        # Cleanup
        try:
            await integration.stop()
            logger.info("WebRTC server stopped")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        sys.exit(1)