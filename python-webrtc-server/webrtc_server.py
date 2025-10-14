#!/usr/bin/env python3
"""
WebRTC Server - Main entry point for Nova S2S WebRTC Master/Viewer
Starts the KVS WebRTC server with S2S integration

Logging Levels:
- INFO: Basic operational messages
- DEBUG: Detailed application debugging (filters third-party noise)
- TRACE: Everything including third-party library internals (botocore, smithy, etc.)

Usage:
  export LOGLEVEL=DEBUG    # Recommended for debugging
  export LOGLEVEL=TRACE    # Only when you need AWS SDK internals
"""

import asyncio
import logging
import os
import sys
import argparse
from datetime import datetime
from webrtc_s2s_integration import WebRTCS2SIntegration
from integration.mcp_client import McpLocationClient
from integration.mcp_iot_client import McpIoTCoreClient
from integration.strands_agent import StrandsAgent

# Configure logging with file export and custom TRACE level
LOGLEVEL = os.environ.get("LOGLEVEL", "INFO").upper()

# Add custom TRACE level (lower than DEBUG)
TRACE_LEVEL = 5
logging.addLevelName(TRACE_LEVEL, "TRACE")

def trace(self, message, *args, **kwargs):
    if self.isEnabledFor(TRACE_LEVEL):
        self._log(TRACE_LEVEL, message, args, **kwargs)

logging.Logger.trace = trace

# Create shared logs directory
logs_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
if not os.path.exists(logs_dir):
    os.makedirs(logs_dir)

LOG_FILE = os.environ.get("LOG_FILE", os.path.join(logs_dir, "webrtc_server.log"))

# Convert LOGLEVEL string to numeric level
numeric_level = getattr(logging, LOGLEVEL, logging.INFO)
if LOGLEVEL == "TRACE":
    numeric_level = TRACE_LEVEL

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
console_handler.setLevel(numeric_level)
console_handler.setFormatter(formatter)

# Create file handler with explicit path
file_handler = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8')
file_handler.setLevel(numeric_level)
file_handler.setFormatter(formatter)

# Add handlers to root logger
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)
root_logger.setLevel(numeric_level)

# Force all loggers to use root logger handlers
logging.basicConfig(level=numeric_level, handlers=[console_handler, file_handler], force=True)

# Set third-party library log levels based on our log level
# Only show noisy third-party logs at TRACE level
third_party_level = TRACE_LEVEL if numeric_level <= TRACE_LEVEL else logging.WARNING

# AWS/Boto3 libraries
logging.getLogger('botocore').setLevel(third_party_level)
logging.getLogger('botocore.hooks').setLevel(third_party_level)
logging.getLogger('botocore.loaders').setLevel(third_party_level)
logging.getLogger('botocore.configprovider').setLevel(third_party_level)
logging.getLogger('botocore.endpoint').setLevel(third_party_level)
logging.getLogger('botocore.auth').setLevel(third_party_level)
logging.getLogger('urllib3').setLevel(third_party_level)
logging.getLogger('urllib3.connectionpool').setLevel(third_party_level)

# AWS SDK libraries
logging.getLogger('aws_sdk_bedrock_runtime').setLevel(third_party_level)
logging.getLogger('aws_sdk_bedrock_runtime.client').setLevel(third_party_level)
logging.getLogger('smithy_aws_event_stream').setLevel(third_party_level)
logging.getLogger('smithy_aws_event_stream.aio').setLevel(third_party_level)

# WebRTC libraries
aioice_logger = logging.getLogger('aioice')
aioice_logger.setLevel(third_party_level)
aioice_logger.propagate = True

aiortc_logger = logging.getLogger('aiortc')
aiortc_logger.setLevel(third_party_level)
aiortc_logger.propagate = True

websockets_logger = logging.getLogger('websockets')
websockets_logger.setLevel(third_party_level)
websockets_logger.propagate = True

# Also set the ice submodule specifically
aioice_ice_logger = logging.getLogger('aioice.ice')
aioice_ice_logger.setLevel(third_party_level)
aioice_ice_logger.propagate = True

logger = logging.getLogger(__name__)

# Log the logging configuration
logger.debug(f"🗂️ [WebRTCServer] Logging configured - Level: {LOGLEVEL} ({numeric_level}), File: {LOG_FILE}")
logger.debug(f"🗂️ [WebRTCServer] Log file location: {os.path.abspath(LOG_FILE)}")
logger.debug(f"🗂️ [WebRTCServer] Third-party libraries level: {third_party_level} ({'TRACE' if third_party_level == TRACE_LEVEL else logging.getLevelName(third_party_level)})")

# Verify third-party library log levels
logger.debug(f"🔧 [WebRTCServer] botocore log level: {logging.getLogger('botocore').level}")
logger.debug(f"🔧 [WebRTCServer] aws_sdk_bedrock_runtime log level: {logging.getLogger('aws_sdk_bedrock_runtime').level}")
logger.debug(f"🔧 [WebRTCServer] smithy_aws_event_stream log level: {logging.getLogger('smithy_aws_event_stream').level}")
logger.debug(f"🔧 [WebRTCServer] aioice log level: {logging.getLogger('aioice').level}")
logger.debug(f"🔧 [WebRTCServer] aiortc log level: {logging.getLogger('aiortc').level}")
logger.debug(f"🔧 [WebRTCServer] websockets log level: {logging.getLogger('websockets').level}")

# Log level usage information
if LOGLEVEL == "DEBUG":
    logger.info("💡 [WebRTCServer] Using DEBUG level - third-party library logs are filtered")
    logger.info("💡 [WebRTCServer] For full third-party logs, use: export LOGLEVEL=TRACE")
elif LOGLEVEL == "TRACE":
    logger.info("🔍 [WebRTCServer] Using TRACE level - showing ALL logs including third-party libraries")

# Test file logging
try:
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"# LOG FILE TEST - {datetime.now().isoformat()} - File logging is working\n")
    logger.debug(f"✅ [WebRTCServer] File logging test successful")
except Exception as e:
    logger.error(f"❌ [WebRTCServer] File logging test failed: {e}")
    print(f"CRITICAL: Cannot write to log file {LOG_FILE}: {e}")

# global variable to control each agent
MCP_CLIENT = None
MCP_IOT_CLIENT = None
STRANDS_AGENT = None

async def main():
    """Main entry point for WebRTC server"""
    parser = argparse.ArgumentParser(description='Nova S2S WebRTC Server')
    parser.add_argument('--region', default=os.environ.get('AWS_REGION', 'ap-northeast-1'),
                       help='AWS region (default: ap-northeast-1)')
    parser.add_argument('--channel-name', default=os.environ.get('KVS_CHANNEL_NAME', 'nova-s2s-webrtc-test'),
                       help='KVS channel name (default: nova-s2s-webrtc-test)')
    parser.add_argument('--model-id', default='amazon.nova-sonic-v1:0',
                       help='Bedrock model ID (default: amazon.nova-sonic-v1:0)')
    parser.add_argument('--webrtc-role', default='Master', choices=['Master', 'Viewer'],
                       help='WebRTC role: Master or Viewer (default: Master)')
    parser.add_argument('--agent', type=str, help='Agent intergation "mcp" or "strands".') # argument to choose agent, value = "mcp" | "strands"
    
    args = parser.parse_args()
    
    logger.info(f"Starting Nova S2S WebRTC Server")
    logger.debug(f"Region: {args.region}")
    logger.debug(f"Channel: {args.channel_name}")
    logger.debug(f"Model: {args.model_id}")
    logger.debug(f"WebRTC Role: {args.webrtc_role}")
    
    try:
        # Init MCP client
        if args.agent == "mcp":
            print("MCP enabled")
            try:
                global MCP_CLIENT, MCP_IOT_CLIENT
                
                # Initialize location MCP client
                MCP_CLIENT = McpLocationClient()
                await MCP_CLIENT.connect_to_server()
                logger.info("✅ [WebRTCServer] Location MCP client connected")
                
                # Initialize IoT Core MCP client
                MCP_IOT_CLIENT = McpIoTCoreClient()
                await MCP_IOT_CLIENT.connect_to_server()
                logger.info("✅ [WebRTCServer] IoT Core MCP client connected")
                
            except Exception as ex:
                logger.error(f"❌ [WebRTCServer] Failed to start MCP clients: {ex}")
                print("Failed to start MCP clients",ex)
        # Init Strands Agent
        elif args.agent == "strands":
            print("Strands agent enabled")
            try:
                global STRANDS_AGENT
                STRANDS_AGENT = StrandsAgent()
            except Exception as ex:
                print("Failed to start Strands agent",ex)
        else:
            MCP_CLIENT = MCP_IOT_CLIENT = STRANDS_AGENT = None


        # Initialize WebRTC S2S integration based on role
        if args.webrtc_role == 'Viewer':
            from webrtc_s2s_viewer_integration import WebRTCS2SViewerIntegration
            integration = WebRTCS2SViewerIntegration(
                region=args.region,
                model_id=args.model_id,
                mcp_client=MCP_CLIENT,
                mcp_iot_client=MCP_IOT_CLIENT,
                strands_agent=STRANDS_AGENT
            )
            logger.info("🤖 [WebRTCServer] VIEWER MODE - Audio will be processed by Nova Sonic, connecting as Viewer")
            
            # Initialize and start the WebRTC viewer
            await integration.initialize_webrtc_viewer(args.channel_name)
            await integration.start()
        else:
            # Master mode (existing implementation)
            integration = WebRTCS2SIntegration(
                region=args.region,
                model_id=args.model_id,
                mcp_client=MCP_CLIENT,
                mcp_iot_client=MCP_IOT_CLIENT,
                strands_agent=STRANDS_AGENT
            )
            logger.info("🤖 [WebRTCServer] MASTER MODE - Audio will be processed by Nova Sonic")
            
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
            if MCP_CLIENT:
                await MCP_CLIENT.cleanup()
            if MCP_IOT_CLIENT:
                await MCP_IOT_CLIENT.cleanup()
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