"""S2S Session Manager - Manages bidirectional streaming with Bedrock Nova Sonic."""

import asyncio
import json
import logging
import time

from aws_sdk_bedrock_runtime.client import BedrockRuntimeClient, InvokeModelWithBidirectionalStreamOperationInput
from aws_sdk_bedrock_runtime.models import InvokeModelWithBidirectionalStreamInputChunk, BidirectionalInputPayloadPart
from aws_sdk_bedrock_runtime.config import Config
from smithy_aws_core.identity.environment import EnvironmentCredentialsResolver

from . import s2s_events

logger = logging.getLogger(__name__)


class S2sSessionManager:
    """Manages bidirectional streaming with AWS Bedrock Nova Sonic."""

    def __init__(self, region: str, model_id: str = "amazon.nova-sonic-v1:0"):
        self.region = region
        self.model_id = model_id
        self.audio_input_queue = asyncio.Queue()
        self.output_queue = asyncio.Queue()
        self.stream = None
        self.is_active = False
        self.bedrock_client = None
        self.prompt_name = None
        self.audio_content_name = None

    async def initialize_stream(self):
        """Initialize the bidirectional stream with Bedrock."""
        if not self.bedrock_client:
            config = Config(
                endpoint_uri=f"https://bedrock-runtime.{self.region}.amazonaws.com",
                region=self.region,
                aws_credentials_identity_resolver=EnvironmentCredentialsResolver(),
            )
            self.bedrock_client = BedrockRuntimeClient(config=config)

        self.stream = await self.bedrock_client.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id=self.model_id)
        )
        self.is_active = True
        asyncio.create_task(self._process_responses())
        asyncio.create_task(self._process_audio_input())
        logger.info("[S2sSession] Stream initialized")

    async def send_raw_event(self, event_data: dict):
        """Send a raw event to the Bedrock stream."""
        if not self.stream or not self.is_active:
            return
        if "event" in event_data:
            etype = list(event_data["event"].keys())[0]
            if etype == "promptStart":
                self.prompt_name = event_data["event"]["promptStart"]["promptName"]
            elif etype == "contentStart" and event_data["event"]["contentStart"].get("type") == "AUDIO":
                self.audio_content_name = event_data["event"]["contentStart"]["contentName"]

        event_json = json.dumps(event_data)
        event = InvokeModelWithBidirectionalStreamInputChunk(
            value=BidirectionalInputPayloadPart(bytes_=event_json.encode("utf-8"))
        )
        await self.stream.input_stream.send(event)

    def add_audio_chunk(self, audio_data):
        """Queue an audio chunk for processing."""
        if not self.is_active:
            return
        self.audio_input_queue.put_nowait(audio_data)

    def is_session_ready(self):
        return self.prompt_name is not None and self.audio_content_name is not None

    async def _process_audio_input(self):
        while self.is_active:
            try:
                audio_bytes = await asyncio.wait_for(self.audio_input_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            audio_event = s2s_events.audio_input(
                self.prompt_name, self.audio_content_name,
                audio_bytes.decode("utf-8") if isinstance(audio_bytes, bytes) else audio_bytes,
            )
            await self.send_raw_event(audio_event)

    async def _process_responses(self):
        """Process incoming responses from Bedrock."""
        while self.is_active:
            try:
                output = await asyncio.wait_for(self.stream.await_output(), timeout=300.0)
                result = await output[1].receive()
                if result.value and result.value.bytes_:
                    response_data = result.value.bytes_.decode("utf-8")
                    json_data = json.loads(response_data)
                    json_data["timestamp"] = int(time.time() * 1000)
                    await self.output_queue.put(json_data)
            except asyncio.TimeoutError:
                continue
            except StopAsyncIteration:
                logger.info("[S2sSession] Stream ended")
                break
            except Exception as e:
                if "closed" in str(e).lower() or "cancel" in str(e).lower():
                    break
                logger.error(f"[S2sSession] Response error: {e}")
                continue

        self.is_active = False

    async def close(self):
        """Close the stream."""
        if not self.is_active:
            return
        self.is_active = False
        if self.stream:
            try:
                await self.stream.input_stream.close()
            except Exception as e:
                logger.error(f"[S2sSession] Close error: {e}")
