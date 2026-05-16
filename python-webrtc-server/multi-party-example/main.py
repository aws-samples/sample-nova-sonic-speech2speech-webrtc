"""
Multi-Party Conversation Server - Example Entry Point.

Two participants join via KVS WebRTC signaling and converse with each other
and a shared Nova Sonic AI agent.

Leverages:
- ../webrtc/KVSWebRTCMaster for WebRTC connection management
- ../multi-party/ for S2S session, events, and conversation modules
"""

import asyncio
import json
import logging
import os
import sys
import uuid
import base64

import numpy as np
from dotenv import load_dotenv

# Add parent directory to path for sibling imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from webrtc.KVSWebRTCMaster import KVSWebRTCMaster
from multi_party import s2s_events
from multi_party.s2s_session import S2sSessionManager
from multi_party.conversation import SpeakerTracker, AudioMixer

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

logging.basicConfig(level=os.getenv("LOGLEVEL", "INFO").upper(), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
for lib in ["botocore", "urllib3", "aioice", "websockets", "smithy_aws_event_stream", "smithy_core"]:
    logging.getLogger(lib).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

REGION = os.getenv("AWS_REGION", "us-east-1")
BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-east-1")
CHANNEL_NAME = os.getenv("KVS_CHANNEL_NAME", "nova-s2s-multi-party-channel")
MODEL_ID = os.getenv("MODEL_ID", "amazon.nova-sonic-v1:0")
MAX_PARTICIPANTS = int(os.getenv("MAX_PARTICIPANTS", "2"))
AGENT_NAME = os.getenv("AGENT_NAME", "Nova")


class NoOpSessionManager:
    """Dummy session manager that absorbs client-sent S2S events without error.
    In multi-party mode, the shared session is managed server-side."""
    is_active = True
    prompt_name = "shared"
    audio_content_name = "shared"

    def is_session_ready(self):
        return True

    async def send_raw_event(self, event_data: dict):
        pass  # Swallow all client-sent events

    def add_audio_chunk(self, *args, **kwargs):
        pass

    async def close(self):
        pass


class MultiPartyServer:
    """Bridges multiple WebRTC participants with a shared Nova Sonic session using KVSWebRTCMaster."""

    def __init__(self):
        credentials = None
        if os.getenv("AWS_ACCESS_KEY_ID"):
            credentials = {
                'accessKeyId': os.getenv("AWS_ACCESS_KEY_ID"),
                'secretAccessKey': os.getenv("AWS_SECRET_ACCESS_KEY"),
                'sessionToken': os.getenv("AWS_SESSION_TOKEN"),
            }

        self.webrtc_master = KVSWebRTCMaster(
            channel_name=CHANNEL_NAME,
            region=REGION,
            credentials=credentials,
        )

        self.session: S2sSessionManager | None = None
        self.speaker_tracker = SpeakerTracker()
        self.audio_mixer = AudioMixer()
        self.participants: set[str] = set()
        self.is_running = False

    @property
    def participant_count(self):
        return len(self.participants)

    async def initialize(self):
        """Set up KVSWebRTCMaster. S2S session is deferred until first participant joins."""
        self.audio_mixer.set_output_callback(self._on_mixed_audio)

        self.webrtc_master.on_client_connected = self._on_client_connected
        self.webrtc_master.on_client_disconnected = self._on_client_disconnected
        self.webrtc_master.on_audio_received = self._on_audio_received
        self.webrtc_master._disable_test_audio = True

        await self.webrtc_master.initialize()

        # Use STUN only (no TURN to avoid Forbidden IP errors)
        from aiortc import RTCIceServer
        self.webrtc_master.ice_servers = [
            RTCIceServer(urls=f'stun:stun.kinesisvideo.{REGION}.amazonaws.com:443')
        ]

        logger.info(f"[Server] Initialized channel={CHANNEL_NAME}, agent={AGENT_NAME}")
        logger.info(f"[Server] S2S session will start when first participant joins")

    async def _start_s2s_session(self):
        """Initialize the shared S2S session (called on first participant join)."""
        if self.session and self.session.is_active:
            return  # Already running

        logger.info("[Server] Starting shared S2S session...")
        self.session = S2sSessionManager(region=BEDROCK_REGION, model_id=MODEL_ID)
        await self.session.initialize_stream()

        prompt_name = f"prompt_{uuid.uuid4().hex[:8]}"
        audio_content = f"audio_{uuid.uuid4().hex[:8]}"

        await self.session.send_raw_event(s2s_events.session_start())
        await self.session.send_raw_event(s2s_events.prompt_start(prompt_name))

        sys_content = f"sys_{uuid.uuid4().hex[:8]}"
        await self.session.send_raw_event(s2s_events.content_start_text(prompt_name, sys_content))
        await self.session.send_raw_event(s2s_events.text_input(prompt_name, sys_content,
            content=self._build_system_prompt()))
        await self.session.send_raw_event(s2s_events.content_end(prompt_name, sys_content))

        await self.session.send_raw_event(s2s_events.content_start_audio(prompt_name, audio_content))

        # Start audio mixer now that session is ready
        self.audio_mixer.start()

        logger.info("[Server] S2S session started successfully")

    def _build_system_prompt(self) -> str:
        return (
            f"You are {AGENT_NAME}, a helpful AI assistant in a multi-party conversation with two human participants. "
            f"Rules:\n"
            f"1. When someone addresses you directly (e.g., 'Hey {AGENT_NAME}'), respond helpfully.\n"
            f"2. When someone says 'ask them about X' or 'tell them about X', address the other participant.\n"
            f"3. When participants are clearly talking to each other, stay quiet.\n"
            f"4. Keep responses concise (1-3 sentences) unless asked for detail.\n"
        )

    def _on_mixed_audio(self, b64_audio: str):
        if self.session and self.session.is_active:
            self.session.add_audio_chunk(b64_audio)
            logger.debug(f"[Server] Mixed audio sent to S2S: {len(b64_audio)} chars")

    async def _on_client_connected(self, client_id: str):
        if self.participant_count >= MAX_PARTICIPANTS and client_id not in self.participants:
            logger.warning(f"[Server] Rejecting {client_id} - full ({self.participant_count}/{MAX_PARTICIPANTS})")
            return

        # Start S2S session on first participant join (avoids timeout)
        if not self.session or not self.session.is_active:
            await self._start_s2s_session()

        self.participants.add(client_id)
        self.speaker_tracker.register(client_id, name=client_id)
        self.audio_mixer.register(client_id)

        # Register a no-op session manager so EventBridge doesn't error on
        # client-sent S2S setup events (sessionStart, promptStart, etc.).
        self.webrtc_master.set_session_manager(client_id, NoOpSessionManager())

        logger.info(f"[Server] Participant joined: {client_id} ({self.participant_count}/{MAX_PARTICIPANTS})")

    def _on_client_disconnected(self, client_id: str):
        self.participants.discard(client_id)
        self.speaker_tracker.unregister(client_id)
        self.audio_mixer.unregister(client_id)
        logger.info(f"[Server] Participant left: {client_id} ({self.participant_count}/{MAX_PARTICIPANTS})")

    async def _on_audio_received(self, client_id: str, track):
        """Process incoming audio from a participant's WebRTC track."""
        # Wait for both the shared S2S session to be ready AND the participant to be registered
        for _ in range(100):
            if (self.session and self.session.is_session_ready() and
                    client_id in self.participants):
                break
            await asyncio.sleep(0.1)

        if not self.session or not self.session.is_session_ready():
            logger.error(f"[Audio] Session not ready for {client_id}")
            return

        if client_id not in self.participants:
            logger.error(f"[Audio] Participant {client_id} not registered, skipping audio")
            return

        frame_count = 0
        try:
            while client_id in self.participants and self.session.is_active:
                frame = await track.recv()
                frame_count += 1

                audio = self._decode_frame(frame)
                rms = np.sqrt(np.mean(audio.astype(np.float64) ** 2))
                self.speaker_tracker.update(client_id, rms)

                # Send audio directly to S2S (bypass mixer for reliability)
                if rms > 20 or frame_count % 5 == 0:
                    b64 = base64.b64encode(audio.tobytes()).decode("utf-8")
                    if self.session and self.session.is_active:
                        self.session.add_audio_chunk(b64)

                # Relay to other participants (disabled for same-machine testing to avoid echo)
                # Uncomment for actual multi-device usage:
                # if rms > 30 or frame_count % 10 == 0:
                #     self._relay_to_others(client_id, audio)

        except Exception as e:
            if "closed" not in str(e).lower():
                logger.error(f"[Audio] Error for {client_id}: {e}")

        logger.info(f"[Audio] Ended for {client_id}, frames: {frame_count}")

    def _decode_frame(self, frame) -> np.ndarray:
        """Decode an audio frame to 16kHz mono int16 (matching server-multiparty logic)."""
        audio = frame.to_ndarray()

        # Handle 2D arrays (channels x samples or interleaved)
        if audio.ndim == 2:
            if audio.shape[0] == 1 and audio.shape[1] == frame.samples * 2:
                # Interleaved stereo in single row
                audio = audio[0][::2]
            elif audio.shape[0] == 2:
                # Stereo: take first channel
                audio = audio[0]
            else:
                audio = audio[0]
        elif audio.ndim == 1 and len(audio) == frame.samples * 2:
            # Interleaved stereo
            audio = audio[::2]

        # Convert to int16 first
        if frame.format.name in ('flt', 'fltp'):
            audio = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        elif frame.format.name in ('s32', 's32p'):
            audio = (audio / 65536).astype(np.int16)
        else:
            audio = audio.astype(np.int16)

        # Resample to 16kHz
        if frame.sample_rate != 16000:
            ratio = 16000 / frame.sample_rate
            indices = (np.arange(0, len(audio) * ratio) / ratio).astype(int)
            indices = indices[indices < len(audio)]
            audio = audio[indices]

        return audio

    def _relay_to_others(self, sender_id: str, audio_16k: np.ndarray):
        """Relay 16kHz audio to other participants as 24kHz."""
        n_out = int(len(audio_16k) * 1.5)
        idx = (np.arange(n_out) * len(audio_16k) / n_out).astype(int)
        idx = np.clip(idx, 0, len(audio_16k) - 1)
        samples_24k = audio_16k[idx]
        b64 = base64.b64encode(samples_24k.tobytes()).decode("utf-8")

        for pid in self.participants:
            if pid != sender_id and pid in self.webrtc_master.audio_output_tracks:
                self.webrtc_master.audio_output_tracks[pid].queue_audio(b64)

    async def _broadcast_responses(self):
        """Broadcast Nova Sonic responses to all participants."""
        seen_text = {}  # contentName -> last content, to deduplicate
        while self.is_running:
            if not self.session or not self.session.is_active:
                await asyncio.sleep(0.5)
                continue
            try:
                response = await asyncio.wait_for(self.session.output_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except Exception:
                break

            if "event" not in response:
                continue

            event = response["event"]
            event_type = list(event.keys())[0]

            # Deduplicate textOutput events (Nova sometimes sends same content twice)
            if event_type == "textOutput":
                text_data = event["textOutput"]
                content_name = text_data.get("contentName", "")
                content = text_data.get("content", "")
                role = text_data.get("role", "")
                key = f"{role}:{content_name}"
                if key in seen_text and seen_text[key] == content:
                    continue  # Skip duplicate
                seen_text[key] = content

            for client_id in list(self.participants):
                if event_type == "audioOutput":
                    b64 = event["audioOutput"].get("content", "")
                    if b64 and client_id in self.webrtc_master.audio_output_tracks:
                        self.webrtc_master.audio_output_tracks[client_id].queue_audio(b64)

                if event_type in ("textOutput", "contentStart", "contentEnd"):
                    msg = dict(response)
                    if event_type == "textOutput":
                        text_data = event["textOutput"]
                        if text_data.get("role") == "USER":
                            speaker = self.speaker_tracker.active_speaker
                            msg["speaker"] = speaker
                            msg["isSelf"] = speaker == client_id
                    await self.webrtc_master.send_event_to_client(client_id, msg)

        logger.info("[Server] Response broadcasting ended")

    async def start(self):
        self.is_running = True
        asyncio.create_task(self._broadcast_responses())
        logger.info(f"[Server] Starting: channel={CHANNEL_NAME}, region={REGION}, bedrock={BEDROCK_REGION}, model={MODEL_ID}, max={MAX_PARTICIPANTS}")
        await self.webrtc_master.start()

    async def stop(self):
        self.is_running = False
        self.audio_mixer.stop()
        if self.session and self.session.is_active:
            try:
                if self.session.prompt_name and self.session.audio_content_name:
                    await self.session.send_raw_event(s2s_events.content_end(self.session.prompt_name, self.session.audio_content_name))
                    await self.session.send_raw_event(s2s_events.prompt_end(self.session.prompt_name))
                    await self.session.send_raw_event(s2s_events.session_end())
            except Exception:
                pass
            await self.session.close()
        await self.webrtc_master.stop()


async def main():
    server = MultiPartyServer()
    await server.initialize()
    try:
        await server.start()
    except KeyboardInterrupt:
        logger.info("[Server] Shutting down...")
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
