# Multi-Party Nova Sonic Conversation

Two participants join via KVS WebRTC and converse with each other and a shared Nova Sonic AI agent.

## Architecture

- Leverages `../webrtc/KVSWebRTCMaster` for WebRTC connection management (signaling, peer connections, audio output tracks, data channels)
- Single shared S2S session (both participants talk to same AI)
- S2S session starts lazily when first participant joins (avoids Nova Sonic timeout)
- Audio from each participant is sent directly to Nova Sonic
- AI responses (audio + text) are broadcast to all participants
- `SpeakerTracker` detects active speaker via RMS energy

## Setup

### Server

```bash
cd python-webrtc-server
pip install -r requirements.txt
```

Ensure `python-webrtc-server/.env` has valid AWS credentials and `KVS_CHANNEL_NAME` set.

### Client

```bash
cd react-webrtc-client
npm install
```

Ensure `react-webrtc-client/.env` has matching AWS credentials and `REACT_APP_KVS_CHANNEL_NAME`.

## Run

### 1. Start the server

```bash
cd python-webrtc-server
python multi-party-example/main.py
```

### 2. Start the multi-party viewer

```bash
cd react-webrtc-client
npm run start:multi-party
```

Opens at http://localhost:3001 with two participant panels (Alice & Bob). Click "Join" on each to connect.

## Notes

- Both panels share the same KVS signaling channel and connect to the same server
- Audio relay between participants is disabled by default (to avoid echo when testing on same machine)
- The `{ "interrupted" : true }` JSON messages from Nova Sonic are filtered out in the UI
- For multi-device usage, re-enable audio relay in `multi-party-example/main.py`
