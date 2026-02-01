#!/usr/bin/env python3
"""
AgentCore Runtime HTTP Protocol Wrapper for Nova S2S WebRTC
Adapts WebRTC server to AgentCore Runtime HTTP protocol

Runtime mode:
- Initialize WebRTC Master on container startup (background service)
- /invocations receives params, triggers new session, returns immediately
- /ping checks active peer connection status
"""
import asyncio
import json
import logging
import os
import sys
from typing import Dict, Any, Optional
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

# Import WebRTC integration
from webrtc_s2s_integration import WebRTCS2SIntegration

# Configure logging
LOGLEVEL = os.environ.get("LOGLEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOGLEVEL, logging.INFO),
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Nova S2S WebRTC AgentCore Runtime",
    version="1.0.0",
    description="WebRTC Speech-to-Speech service for AgentCore Runtime"
)

# Request/Response models
class InvocationRequest(BaseModel):
    input: Dict[str, Any]

class InvocationResponse(BaseModel):
    output: Dict[str, Any]

# Global state: WebRTC integration instance (initialized on container startup)
webrtc_integration: Optional[WebRTCS2SIntegration] = None
initialization_lock = asyncio.Lock()
active_sessions: Dict[str, Dict[str, Any]] = {}  # session_id -> session_info
webrtc_task: Optional[asyncio.Task] = None  # WebRTC Master background task


async def ensure_webrtc_initialized():
    """Ensure WebRTC integration is initialized (lazy loading)"""
    global webrtc_integration
    
    if webrtc_integration is not None:
        return webrtc_integration
    
    async with initialization_lock:
        # Double-check
        if webrtc_integration is not None:
            return webrtc_integration
        
        logger.info("🚀 [AgentCore] Initializing WebRTC integration...")
        
        # Get config from environment variables
        region = os.environ.get("AWS_REGION", "ap-northeast-1")
        model_id = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-2-sonic-v1:0")
        
        # Create WebRTC integration instance
        webrtc_integration = WebRTCS2SIntegration(
            region=region,
            model_id=model_id,
            loopback_mode=False  # Production mode
        )
        
        logger.info(f"✅ [AgentCore] WebRTC integration initialized")
        logger.info(f"   Region: {region}")
        logger.info(f"   Model: {model_id}")
        
        return webrtc_integration


def get_active_peer_connections_count() -> int:
    """
    Get count of active peer connections
    Only counts connections actively transmitting media (connectionState == 'connected')
    """
    if webrtc_integration is None or webrtc_integration.webrtc_master is None:
        return 0
    
    master = webrtc_integration.webrtc_master
    active_count = 0
    
    for client_id, pc in master.peer_connections.items():
        # Check connection state: only 'connected' counts as active
        # 'new', 'connecting', 'disconnected', 'failed', 'closed' are not active
        if pc.connectionState == 'connected':
            active_count += 1
            logger.debug(f"🔗 [AgentCore] Active peer: {client_id} (state: {pc.connectionState})")
    
    return active_count


@app.on_event("startup")
async def startup_event():
    """
    Container startup initialization
    Note: WebRTC Master is initialized on first /invocations call (lazy loading)
    because channel_name is needed
    """
    logger.info("🌟 [AgentCore] AgentCore Runtime starting up...")
    logger.info(f"   Runtime Name: NovaSonic-S2S-KVSWebRTC")
    logger.info(f"   Log Level: {LOGLEVEL}")
    logger.info(f"   AWS Region: {os.environ.get('AWS_REGION', 'ap-northeast-1')}")
    logger.info("✅ [AgentCore] Startup complete - ready to accept invocations")


@app.on_event("shutdown")
async def shutdown_event():
    """Container shutdown cleanup"""
    global webrtc_integration
    
    logger.info("🛑 [AgentCore] AgentCore Runtime shutting down...")
    
    if webrtc_integration and webrtc_integration.webrtc_master:
        try:
            logger.info("🧹 [AgentCore] Cleaning up WebRTC connections...")
            await webrtc_integration.stop()
            logger.info("✅ [AgentCore] Cleanup complete")
        except Exception as e:
            logger.error(f"❌ [AgentCore] Error during cleanup: {e}")
    
    logger.info("👋 [AgentCore] Shutdown complete")


@app.post("/invocations")
async def invoke_agent(request: Request):
    """
    AgentCore Runtime main invocation endpoint
    
    Accepts arbitrary JSON request body with flexible handling
    """
    try:
        # Read raw request body
        body = await request.body()
        logger.info(f"📥 [AgentCore] Received invocation request")
        logger.debug(f"   Raw body: {body[:200]}")  # Log first 200 bytes only
        
        # Try to parse JSON
        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            logger.error(f"❌ [AgentCore] Invalid JSON: {e}")
            raise HTTPException(status_code=400, detail="Invalid JSON in request body")
        
        logger.debug(f"   Parsed data: {data}")
        
        # Flexible parameter extraction - supports multiple formats
        # Format 1: {"input": {"channel_name": "..."}}
        # Format 2: {"channel_name": "..."}
        if "input" in data and isinstance(data["input"], dict):
            params = data["input"]
        else:
            params = data
        
        # Extract input parameters
        prompt = params.get("prompt", "")
        channel_name = params.get("channel_name")
        session_id = params.get("session_id", f"session-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}")
        log_level = params.get("log_level", "INFO")
        
        logger.info(f"   Channel: {channel_name}")
        logger.info(f"   Session: {session_id}")
        
        # Validate required parameters
        if not channel_name:
            raise HTTPException(
                status_code=400,
                detail="Missing required parameter: 'channel_name'"
            )
        
        # Update log level (if specified)
        if log_level.upper() in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            logging.getLogger().setLevel(getattr(logging, log_level.upper()))
            logger.info(f"🔧 [AgentCore] Log level updated to: {log_level}")
        
        # Ensure WebRTC integration is initialized
        integration = await ensure_webrtc_initialized()
        
        # Check if need to initialize or switch channel
        current_channel = None
        if integration.webrtc_master:
            current_channel = integration.webrtc_master.channel_name
        
        if current_channel != channel_name:
            logger.info(f"🔄 [AgentCore] Initializing WebRTC Master for channel: {channel_name}")
            
            # If master exists, stop it first
            if integration.webrtc_master:
                logger.info(f"🛑 [AgentCore] Stopping previous channel: {current_channel}")
                await integration.stop()
            
            # Initialize new WebRTC Master
            # Note: AWS credentials auto-obtained from IAM Role (no explicit passing needed)
            await integration.initialize_webrtc_master(
                channel_name=channel_name,
                credentials=None  # AgentCore Runtime auto-injects IAM Role credentials
            )
            
            # Start WebRTC Master (background task, non-blocking)
            logger.info(f"▶️  [AgentCore] Starting WebRTC Master...")
            global webrtc_task
            
            # Create wrapper function to run start() and keep event loop active
            async def run_webrtc_master():
                try:
                    await integration.start()
                except Exception as e:
                    logger.error(f"❌ [AgentCore] WebRTC Master error: {e}", exc_info=True)
            
            # Create task in current event loop
            webrtc_task = asyncio.create_task(run_webrtc_master())
            
            # Wait briefly to ensure WebSocket connection is established
            await asyncio.sleep(1.0)
            logger.info(f"✅ [AgentCore] WebRTC Master started for channel: {channel_name}")
        else:
            logger.info(f"♻️  [AgentCore] Reusing existing channel: {channel_name}")
        
        # Record session info
        session_info = {
            "session_id": session_id,
            "channel_name": channel_name,
            "prompt": prompt,
            "created_at": datetime.utcnow().isoformat(),
            "status": "active"
        }
        active_sessions[session_id] = session_info
        
        # Build response (return immediately, async processing)
        result = {
            "session_id": session_id,
            "channel_name": channel_name,
            "status": "session_started",
            "message": f"WebRTC session started on channel '{channel_name}'",
            "timestamp": datetime.utcnow().isoformat(),
            "service": "NovaSonic-S2S-KVSWebRTC",
            "active_peers": get_active_peer_connections_count()
        }
        
        if prompt:
            result["prompt_received"] = prompt
        
        logger.info(f"✅ [AgentCore] Session started: {session_id}")
        logger.info(f"   Channel: {channel_name}")
        logger.info(f"   Active peers: {result['active_peers']}")
        
        # Return JSON response (without Pydantic model)
        return JSONResponse(content={"output": result})
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [AgentCore] Invocation failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Agent processing failed: {str(e)}"
        )


@app.get("/ping")
async def ping():
    """
    AgentCore Runtime health check endpoint
    
    Returns status:
    - HealthyBusy: Has active peer connections (transmitting media)
    - Healthy: No active peer connections (idle or waiting for connections)
    
    Note: Only connectionState == 'connected' counts as active
    Waiting on signaling channel alone doesn't count as active
    """
    try:
        # Check active peer connections
        active_peers = get_active_peer_connections_count()
        
        # Determine health status
        if active_peers > 0:
            status = "HealthyBusy"
            message = f"Service is healthy and busy with {active_peers} active peer connection(s)"
        else:
            status = "Healthy"
            message = "Service is healthy and ready"
        
        health_status = {
            "status": status,
            "timestamp": datetime.utcnow().isoformat(),
            "service": "NovaSonic-S2S-KVSWebRTC",
            "version": "1.0.0",
            "active_peers": active_peers,
            "message": message
        }
        
        # Add detailed info (DEBUG mode)
        if LOGLEVEL == "DEBUG" and webrtc_integration and webrtc_integration.webrtc_master:
            master = webrtc_integration.webrtc_master
            health_status["debug_info"] = {
                "channel_name": master.channel_name if master else None,
                "total_peer_connections": len(master.peer_connections) if master else 0,
                "peer_states": {
                    client_id: pc.connectionState 
                    for client_id, pc in master.peer_connections.items()
                } if master else {}
            }
        
        logger.debug(f"💓 [AgentCore] Health check: {status} (active_peers={active_peers})")
        
        return health_status
        
    except Exception as e:
        logger.error(f"❌ [AgentCore] Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "Unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )


@app.get("/")
async def root():
    """Root path info"""
    return {
        "service": "Nova S2S WebRTC AgentCore Runtime",
        "runtime_name": "NovaSonic-S2S-KVSWebRTC",
        "version": "1.0.0",
        "endpoints": {
            "invocations": "POST /invocations - Start WebRTC session",
            "health": "GET /ping - Health check with peer connection status"
        },
        "status": "ready"
    }


if __name__ == "__main__":
    # AgentCore Runtime requires listening on port 8080
    logger.info("🚀 Starting Nova S2S WebRTC AgentCore Runtime on port 8080...")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080,
        log_level=LOGLEVEL.lower()
    )
