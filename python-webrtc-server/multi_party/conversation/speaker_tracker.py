"""Speaker tracking based on audio energy analysis."""

import time
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SpeakerState:
    client_id: str
    name: str = ""
    energy: float = 0.0
    is_speaking: bool = False
    last_spoke_at: float = 0.0


class SpeakerTracker:
    """Tracks which participant is currently speaking based on audio energy."""

    SPEECH_START_THRESHOLD = 100.0
    SPEECH_END_THRESHOLD = 50.0
    SILENCE_DURATION = 0.5

    def __init__(self):
        self._speakers: dict[str, SpeakerState] = {}
        self._active_speaker: str | None = None
        self._last_silence_start: dict[str, float] = {}

    def register(self, client_id: str, name: str = ""):
        self._speakers[client_id] = SpeakerState(client_id=client_id, name=name or client_id)
        self._last_silence_start[client_id] = 0.0

    def unregister(self, client_id: str):
        self._speakers.pop(client_id, None)
        self._last_silence_start.pop(client_id, None)
        if self._active_speaker == client_id:
            self._active_speaker = None

    def update(self, client_id: str, rms_energy: float) -> str | None:
        if client_id not in self._speakers:
            return None

        now = time.time()
        state = self._speakers[client_id]
        state.energy = rms_energy

        if rms_energy >= self.SPEECH_START_THRESHOLD:
            if not state.is_speaking:
                state.is_speaking = True
            state.last_spoke_at = now
            self._last_silence_start[client_id] = 0.0
            self._active_speaker = client_id
        elif state.is_speaking:
            if self._last_silence_start[client_id] == 0.0:
                self._last_silence_start[client_id] = now
            elif now - self._last_silence_start[client_id] > self.SILENCE_DURATION:
                state.is_speaking = False

        return self._active_speaker

    @property
    def active_speaker(self) -> str | None:
        return self._active_speaker

    @property
    def active_speakers(self) -> list[str]:
        return [cid for cid, s in self._speakers.items() if s.is_speaking]

    def both_speaking(self) -> bool:
        return len(self.active_speakers) >= 2
