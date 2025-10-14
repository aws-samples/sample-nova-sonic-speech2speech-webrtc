import asyncio
import json
import os
import logging
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

class McpIoTCoreClient:
    """MCP client for AWS IoT Core MQTT publishing operations."""
    
    def __init__(self):
        """Initialize the IoT Core MCP client."""
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.stdio: Optional[Any] = None
        self.write: Optional[Any] = None
        logger.info("🔌 [IoTCore] MCP IoT Core client initialized")

    async def connect_to_server(self):
        """Connect to the IoT Core MCP server."""
        logger.info("🔗 [IoTCore] Connecting to IoT Core MCP server...")
        
        try:
            # Read AWS credentials from environment variables
            aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
            aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
            aws_session_token = os.getenv("AWS_SESSION_TOKEN")  # Optional
            iot_endpoint = os.getenv("IOT_ENDPOINT")
            
            if not aws_access_key or not aws_secret_key:
                raise ValueError("AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set in environment variables")
            
            logger.debug(f"🔑 [IoTCore] AWS credentials loaded from environment")
            if iot_endpoint:
                logger.debug(f"🌐 [IoTCore] IoT endpoint: {iot_endpoint}")
            
            # Get configurable MCP server paths
            mcp_server_base_path = os.getenv(
                "IOT_MCP_SERVER_PATH", 
                "/Users/zihangh/PycharmProjects/iot/mcpServer_iotCore/AmazonIoTCore_MCP"
            )
            
            # Configurable Python virtual environment path
            python_venv_path = os.getenv(
                "IOT_MCP_PYTHON_PATH",
                f"{mcp_server_base_path}/venv/bin/python"
            )
            
            server_script_path = os.getenv(
                "IOT_MCP_SERVER_SCRIPT",
                f"{mcp_server_base_path}/server.py"
            )
            
            logger.debug(f"🐍 [IoTCore] Python path: {python_venv_path}")
            logger.debug(f"📜 [IoTCore] Server script: {server_script_path}")
            
            # Build environment variables for MCP server
            env = {
                "AWS_ACCESS_KEY_ID": aws_access_key,
                "AWS_SECRET_ACCESS_KEY": aws_secret_key,
            }
            
            if aws_session_token:
                env["AWS_SESSION_TOKEN"] = aws_session_token
                logger.debug("🎫 [IoTCore] AWS session token included")
                
            if iot_endpoint:
                env["IOT_ENDPOINT"] = iot_endpoint
                
            # Add logging level for MCP server
            env["FASTMCP_LOG_LEVEL"] = os.getenv("FASTMCP_LOG_LEVEL", "ERROR")
                
            server_params = StdioServerParameters(
                command=python_venv_path,
                args=[server_script_path],
                env=env
            )
            
            logger.info("🚀 [IoTCore] Starting MCP server connection...")
            
            # Connect to the server (MCP server handles retry logic)
            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            self.stdio, self.write = stdio_transport
            self.session = await self.exit_stack.enter_async_context(
                ClientSession(self.stdio, self.write)
            )

            # Initialize the connection
            await self.session.initialize()
            
            logger.info("✅ [IoTCore] Successfully connected to IoT Core MCP server")
            
            # Log available tools
            try:
                tools = await self.get_mcp_tools()
                tool_names = [tool["function"]["name"] for tool in tools]
                logger.info(f"🛠️ [IoTCore] Available tools: {', '.join(tool_names)}")
            except Exception as e:
                logger.warning(f"⚠️ [IoTCore] Could not list tools: {e}")
                
        except Exception as e:
            logger.error(f"❌ [IoTCore] Failed to connect to MCP server: {e}")
            raise

    async def get_mcp_tools(self) -> List[Dict[str, Any]]:
        """Get list of available MCP tools."""
        logger.debug("📋 [IoTCore] Retrieving available MCP tools...")
        
        try:
            tools_result = await self.session.list_tools()
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    },
                }
                for tool in tools_result.tools
            ]
            
            logger.debug(f"📋 [IoTCore] Retrieved {len(tools)} tools")
            return tools
            
        except Exception as e:
            logger.error(f"❌ [IoTCore] Failed to get MCP tools: {e}")
            raise

    async def call_tool(self, input):
        """Call the publish_mqtt tool with the provided parameters."""
        logger.info("📤 [IoTCore] Calling publish_mqtt tool...")
        
        try:
            if isinstance(input, str):
                input = json.loads(input)
            
            tool_name = input.get("tool", "publish_mqtt")
            logger.debug(f"🔧 [IoTCore] Tool name: {tool_name}")
            
            # Extract parameters for publish_mqtt tool
            params = {}
            
            # Required parameters
            if "topic" in input:
                params["topic"] = input["topic"]
                logger.debug(f"📍 [IoTCore] Topic: {params['topic']}")
            if "payload" in input:
                params["payload"] = input["payload"]
                logger.debug(f"📦 [IoTCore] Payload length: {len(str(params['payload']))} characters")
            
            # Optional parameters
            optional_params = [
                "endpoint", "cert_path", "key_path", "username", "password",
                "custom_authorizer", "client_id", "qos", "retain"
            ]
            
            for param in optional_params:
                if param in input:
                    params[param] = input[param]
                    if param in ["username", "password"]:
                        logger.debug(f"🔐 [IoTCore] {param}: [REDACTED]")
                    else:
                        logger.debug(f"⚙️ [IoTCore] {param}: {params[param]}")

            logger.info(f"🚀 [IoTCore] Publishing MQTT message to topic: {params.get('topic', 'unknown')}")
            
            # Call the MCP tool
            response = await self.session.call_tool(tool_name, params)
            
            # Process response
            result = []
            for c in response.content:
                result.append(c.text)
            
            logger.info(f"✅ [IoTCore] MQTT message published successfully")
            logger.debug(f"📋 [IoTCore] Response: {result}")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ [IoTCore] Failed to publish MQTT message: {e}")
            logger.error(f"🔍 [IoTCore] Input parameters: {input}")
            raise

    async def cleanup(self):
        """Clean up resources."""
        logger.info("🧹 [IoTCore] Cleaning up MCP IoT Core client...")
        
        try:
            await self.exit_stack.aclose()
            logger.info("✅ [IoTCore] MCP IoT Core client cleanup completed")
        except Exception as e:
            logger.error(f"❌ [IoTCore] Error during cleanup: {e}")