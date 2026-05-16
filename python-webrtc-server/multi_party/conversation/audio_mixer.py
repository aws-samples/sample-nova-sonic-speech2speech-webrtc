"""Audio mixing for multi-party conversations."""

import asyncio
import logging
import base64

import numpy as np

logger = logging.getLogger(__name__)


class AudioMixer:
    """Mixes audio from multiple participants into a single stream for S2S."""

    SAMPLE_RATE = 16000
    FRAME_DURATION_MS = 20
    SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_DURATION_MS // 1000  # 320

    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = {}
        self._running = False
        self._task: asyncio.Task | None = None
        self._on_mixed_audio = None

    def set_output_callback(self, callback):
        self._on_mixed_audio = callback

    def register(self, client_id: str):
        self._queues[client_id] = asyncio.Queue(maxsize=100)

    def unregister(self, client_id: str):
        self._queues.pop(client_id, None)

    def feed(self, client_id: str, audio_int16: np.ndarray):
        if client_id not in self._queues:
            return
        try:
            self._queues[client_id].put_nowait(audio_int16)
        except asyncio.QueueFull:
            pass

    def start(self):
        self._running = True
        self._task = asyncio.create_task(self._mix_loop())

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def _mix_loop(self):
        interval = self.FRAME_DURATION_MS / 1000.0
        while self._running:
            await asyncio.sleep(interval)
            if not self._queues or not self._on_mixed_audio:
                continue

            mixed = np.zeros(self.SAMPLES_PER_FRAME, dtype=np.int32)
            has_audio = False

            for q in list(self._queues.values()):
                if q.empty():
                    continue
                try:
                    chunk = q.get_nowait()
                    n = min(len(chunk), self.SAMPLES_PER_FRAME)
                    mixed[:n] += chunk[:n].astype(np.int32)
                    has_audio = True
                except asyncio.QueueEmpty:
                    continue

            if not has_audio:
                continue

            mixed = np.clip(mixed, -32768, 32767).astype(np.int16)
            rms = np.sqrt(np.mean(mixed.astype(np.float64) ** 2))
            if rms < 30:
                continue

            b64 = base64.b64encode(mixed.tobytes()).decode("utf-8")
            self._on_mixed_audio(b64)
