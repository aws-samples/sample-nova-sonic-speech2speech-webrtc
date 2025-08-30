# API Reference

This document provides a comprehensive reference for the Nova S2S WebRTC Workshop APIs, including WebSocket events, HTTP endpoints, and configuration parameters.

## Table of Contents

- [Overview](#overview)
- [WebRTC Signaling API](#webrtc-signaling-api)
- [Data Channel Events](#data-channel-events)
- [S2S Session Events](#s2s-session-events)
- [Audio Processing API](#audio-processing-api)
- [Configuration Parameters](#configuration-parameters)
- [Error Codes](#error-codes)
- [Authentication](#authentication)

## Overview

The Nova S2S WebRTC Workshop provides a real-time speech-to-speech conversation system using Amazon Kinesis Video Streams (KVS) WebRTC for media transport and Amazon Nova Sonic for AI-powered conversation processing.

### Architecture Components

- **WebRTC Master Server**: Python-based server handling KVS WebRTC signaling and media processing
- **React WebRTC Client**: Browser-based client for audio capture and playback
- **S2S Session Manager**: Manages bidirectional streaming with Amazon Bedrock Nova Sonic
- **Event Bridge**: Handles data channel messaging between client and server

### Base URLs

- **WebRTC Signaling**: `wss://[kvs-endpoint]/[channel-name]`
- **Data Channel**: WebRTC data channel named `kvsDataChannel`

## WebRTC Signaling API

### Connection Flow

1. **Channel Discovery**
   ```javascript
   // Get signaling channel ARN
   const response = await kinesisVideoClient.describeSignalingChannel({
       ChannelName: channelName
   }).promise();
   ```

2. **Endpoint Resolution**
   ```javascript
   // Get WebSocket signaling endpoint
   const endpoints = await kinesisVideoClient.getSignalingChannelEndpoint({
       ChannelARN: channelARN,
       SingleMasterChannelEndpointConfiguration: {
           Protocols: ['WSS', 'HTTPS'],
           Role: 'VIEWER'
       }
   }).promise();
   ```

3. **ICE Server Configuration**
   ```javascript
   // Get TURN/STUN servers
   const iceConfig = await signalingClient.getIceServerConfig({
       ChannelARN: channelARN,
       ClientId: clientId
   }).promise();
   ```

### Signaling Messages

#### SDP Offer (Client → Server)
```json
{
    "action": "SDP_OFFER",
    "messagePayload": "base64-encoded-sdp-offer",
    "recipientClientId": "MASTER"
}
```

#### SDP Answer (Server → Client)
```json
{
    "action": "SDP_ANSWER", 
    "messagePayload": "base64-encoded-sdp-answer",
    "recipientClientId": "client-id"
}
```

#### ICE Candidate Exchange
```json
{
    "action": "ICE_CANDIDATE",
    "messagePayload": "base64-encoded-ice-candidate",
    "recipientClientId": "target-client-id"
}
```

## Data Channel Events

All data channel messages use the `kvsDataChannel` WebRTC data channel with JSON format.

### Client → Server Events

#### Session Configuration
```json
{
    "type": "CONFIGURATION_UPDATE",
    "config": {
        "voiceId": "matthew",
        "systemPrompt": "You are a helpful assistant...",
        "temperature": 0.7,
        "maxTokens": 1024
    },
    "timestamp": 1640995200000
}
```

#### Barge-in Request
```json
{
    "type": "BARGE_IN",
    "timestamp": 1640995200000
}
```

#### Session Control
```json
{
    "type": "SESSION_CONTROL",
    "command": "restart|pause|resume",
    "timestamp": 1640995200000
}
```

#### Test Audio Request
```json
{
    "type": "TEST_AUDIO_REQUEST",
    "timestamp": 1640995200000
}
```

### Server → Client Events

#### Configuration Acknowledgment
```json
{
    "type": "CONFIGURATION_ACK",
    "status": "success|error",
    "message": "Optional error message",
    "timestamp": 1640995200000
}
```

#### Nova Sonic Events (Forwarded)
All Nova Sonic events are forwarded directly to the client:

```json
{
    "textOutput": {
        "content": "Hello! How can I help you today?",
        "contentName": "response_content",
        "promptName": "webrtc_prompt"
    }
}
```

```json
{
    "audioOutput": {
        "content": "base64-encoded-audio-data",
        "contentName": "audio_response", 
        "promptName": "webrtc_prompt"
    }
}
```

```json
{
    "completionStart": {
        "promptName": "webrtc_prompt"
    }
}
```

```json
{
    "completionEnd": {
        "promptName": "webrtc_prompt"
    }
}
```

## S2S Session Events

These events are sent to Amazon Nova Sonic via the S2S Session Manager.

### Session Lifecycle

#### Session Start
```json
{
    "event": {
        "sessionStart": {
            "inferenceConfiguration": {
                "maxTokens": 1024,
                "topP": 0.95,
                "temperature": 0.7
            }
        }
    }
}
```

#### Prompt Start
```json
{
    "event": {
        "promptStart": {
            "promptName": "webrtc_prompt",
            "textOutputConfiguration": {
                "mediaType": "text/plain"
            },
            "audioOutputConfiguration": {
                "mediaType": "audio/lpcm",
                "sampleRateHertz": 24000,
                "sampleSizeBits": 16,
                "channelCount": 1,
                "voiceId": "matthew",
                "encoding": "base64",
                "audioType": "SPEECH"
            },
            "toolUseOutputConfiguration": {
                "mediaType": "application/json"
            },
            "toolConfiguration": {
                "tools": [
                    {
                        "toolSpec": {
                            "name": "getDateTool",
                            "description": "get information about the current day",
                            "inputSchema": {
                                "json": "{\"type\":\"object\",\"properties\":{},\"required\":[]}"
                            }
                        }
                    }
                ]
            }
        }
    }
}
```

#### Content Start (Audio)
```json
{
    "event": {
        "contentStart": {
            "promptName": "webrtc_prompt",
            "contentName": "audio_input",
            "type": "AUDIO",
            "interactive": true,
            "audioInputConfiguration": {
                "mediaType": "audio/lpcm",
                "sampleRateHertz": 16000,
                "sampleSizeBits": 16,
                "channelCount": 1,
                "audioType": "SPEECH",
                "encoding": "base64"
            }
        }
    }
}
```

#### Audio Input
```json
{
    "event": {
        "audioInput": {
            "promptName": "webrtc_prompt",
            "contentName": "audio_input",
            "content": "base64-encoded-audio-data"
        }
    }
}
```

#### Session End
```json
{
    "event": {
        "sessionEnd": {}
    }
}
```

### Tool Integration Events

#### Tool Use Detection
```json
{
    "event": {
        "toolUse": {
            "toolName": "getBookingDetails",
            "toolUseId": "tool-use-123",
            "content": "{\"operation\":\"get_booking\",\"booking_id\":\"12345\"}"
        }
    }
}
```

#### Tool Result Response
```json
{
    "event": {
        "toolResult": {
            "promptName": "webrtc_prompt",
            "contentName": "tool_content_456",
            "content": "{\"result\":\"Booking found: Hotel ABC, Check-in: 2024-01-15\"}"
        }
    }
}
```

## Audio Processing API

### Audio Configuration

#### Input Audio Format
- **Sample Rate**: 16 kHz
- **Bit Depth**: 16-bit
- **Channels**: Mono (1 channel)
- **Encoding**: Base64-encoded PCM
- **Frame Size**: ~100ms chunks (1600 samples)

#### Output Audio Format  
- **Sample Rate**: 24 kHz
- **Bit Depth**: 16-bit
- **Channels**: Mono (1 channel)
- **Encoding**: Base64-encoded PCM

### Audio Processing Flow

1. **Client Audio Capture**
   ```javascript
   // WebRTC MediaStream constraints
   const constraints = {
       audio: {
           sampleRate: 16000,
           channelCount: 1,
           echoCancellation: true,
           noiseSuppression: true,
           autoGainControl: true
       }
   };
   ```

2. **Server Audio Processing**
   ```python
   # Audio packet structure
   audio_packet = {
       'client_id': 'client-123',
       'audioData': 'base64-encoded-pcm',
       'size_bytes': 3200,
       'sample_rate': 16000,
       'channels': 1,
       'timestamp': 1640995200000
   }
   ```

3. **Nova Sonic Audio Response**
   ```json
   {
       "event": {
           "audioOutput": {
               "content": "base64-encoded-response-audio",
               "contentName": "audio_response",
               "promptName": "webrtc_prompt"
           }
       }
   }
   ```

### Loopback Mode

For testing purposes, the server supports loopback mode where audio is echoed back without S2S processing:

```bash
python webrtc_server.py --loopback
```

## Configuration Parameters

### Server Configuration

#### Environment Variables
```bash
# AWS Configuration
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key

# KVS Configuration  
KVS_CHANNEL_NAME=nova-s2s-webrtc-test

# Logging Configuration
LOGLEVEL=INFO
LOG_FILE=logs/webrtc_server.log

# Audio Debug (optional)
AUDIO_DEBUG_SAVE=false
```

#### Command Line Arguments
```bash
python webrtc_server.py \
    --region us-east-1 \
    --channel-name nova-s2s-webrtc-test \
    --model-id amazon.nova-sonic-v1:0 \
    --loopback
```

### Client Configuration

#### WebRTC Configuration
```javascript
const config = {
    channelName: 'nova-s2s-webrtc-test',
    region: 'us-east-1',
    clientId: 'viewer-' + Math.random().toString(36).substring(7),
    sendAudio: true,
    credentials: {
        accessKeyId: 'your-access-key',
        secretAccessKey: 'your-secret-key'
    }
};
```

#### Audio Configuration
```javascript
const audioConfig = {
    sampleRate: 16000,
    channelCount: 1,
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true
};
```

### Nova Sonic Configuration

#### Voice Options
- `matthew` (default)
- `joanna`
- `amy`
- `brian`
- `emma`

#### Inference Parameters
```json
{
    "maxTokens": 1024,
    "topP": 0.95,
    "temperature": 0.7
}
```

## Error Codes

### WebRTC Connection Errors

| Code | Description | Resolution |
|------|-------------|------------|
| `SIGNALING_CONNECTION_FAILED` | Failed to connect to KVS signaling | Check AWS credentials and channel name |
| `ICE_CONNECTION_FAILED` | ICE connection establishment failed | Check network connectivity and firewall |
| `PEER_CONNECTION_FAILED` | WebRTC peer connection failed | Check browser WebRTC support |
| `DATA_CHANNEL_ERROR` | Data channel communication error | Check connection stability |

### Audio Processing Errors

| Code | Description | Resolution |
|------|-------------|------------|
| `MICROPHONE_ACCESS_DENIED` | Browser denied microphone access | Grant microphone permissions |
| `AUDIO_PROCESSING_ERROR` | Server audio processing failed | Check server logs and audio format |
| `SAMPLE_RATE_MISMATCH` | Audio sample rate incompatible | Ensure 16kHz input audio |
| `AUDIO_BUFFER_OVERFLOW` | Audio buffer exceeded capacity | Reduce audio input rate |

### S2S Session Errors

| Code | Description | Resolution |
|------|-------------|------------|
| `SESSION_INITIALIZATION_FAILED` | Failed to start Nova Sonic session | Check AWS credentials and model access |
| `BEDROCK_CONNECTION_ERROR` | Bedrock service connection failed | Check AWS service availability |
| `MODEL_INVOCATION_ERROR` | Nova Sonic model invocation failed | Check model ID and parameters |
| `TOOL_EXECUTION_ERROR` | Tool integration execution failed | Check tool configuration and permissions |

### Configuration Errors

| Code | Description | Resolution |
|------|-------------|------------|
| `INVALID_CHANNEL_NAME` | KVS channel name invalid or not found | Verify channel exists and name is correct |
| `INVALID_CREDENTIALS` | AWS credentials invalid or expired | Update AWS credentials |
| `INVALID_REGION` | AWS region not supported | Use supported AWS region |
| `INVALID_MODEL_ID` | Nova Sonic model ID not found | Verify model ID and access permissions |

## Authentication

### AWS Credentials

The system supports multiple AWS credential methods:

#### 1. Environment Variables
```bash
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key
export AWS_SESSION_TOKEN=your-session-token  # Optional for temporary credentials
```

#### 2. AWS Credentials File
```ini
# ~/.aws/credentials
[default]
aws_access_key_id = your-access-key
aws_secret_access_key = your-secret-key
```

#### 3. IAM Roles (EC2/ECS)
When running on AWS infrastructure, IAM roles are automatically detected.

#### 4. Programmatic Credentials
```javascript
// Client-side credential configuration
const credentials = {
    accessKeyId: 'your-access-key',
    secretAccessKey: 'your-secret-key',
    sessionToken: 'your-session-token'  // Optional
};
```

### Required IAM Permissions

#### KVS WebRTC Permissions
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "kinesisvideo:DescribeSignalingChannel",
                "kinesisvideo:GetSignalingChannelEndpoint",
                "kinesisvideo:CreateSignalingChannel"
            ],
            "Resource": "arn:aws:kinesisvideo:*:*:channel/nova-s2s-webrtc-*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "kinesisvideo:GetIceServerConfig"
            ],
            "Resource": "*"
        }
    ]
}
```

#### Bedrock Permissions
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "bedrock:InvokeModelWithBidirectionalStream"
            ],
            "Resource": "arn:aws:bedrock:*::foundation-model/amazon.nova-sonic-v1:0"
        }
    ]
}
```

### Security Considerations

1. **Credential Management**: Never expose AWS credentials in client-side code
2. **Channel Access**: Use unique channel names per session for isolation
3. **Network Security**: Use HTTPS/WSS for all communications
4. **Session Timeout**: Implement appropriate session timeouts
5. **Rate Limiting**: Monitor and limit API usage to prevent abuse

## Usage Examples

### Basic Connection Setup

```javascript
// Initialize WebRTC Manager
const webrtcManager = new WebRTCManager();

// Set up event handlers
webrtcManager.onConnectionStateChange = (state) => {
    console.log('Connection state:', state);
};

webrtcManager.onDataChannelMessage = (message) => {
    console.log('Received message:', message);
};

// Connect to WebRTC
await webrtcManager.connect({
    channelName: 'nova-s2s-webrtc-test',
    region: 'us-east-1',
    clientId: 'viewer-123',
    sendAudio: true,
    credentials: credentials
});
```

### Sending Configuration Updates

```javascript
// Update voice configuration
const configUpdate = {
    type: 'CONFIGURATION_UPDATE',
    config: {
        voiceId: 'joanna',
        temperature: 0.8
    },
    timestamp: Date.now()
};

webrtcManager.sendDataChannelMessage(configUpdate);
```

### Handling Nova Sonic Responses

```javascript
webrtcManager.onDataChannelMessage = (message) => {
    if (message.textOutput) {
        // Display text response
        displayTextResponse(message.textOutput.content);
    }
    
    if (message.audioOutput) {
        // Play audio response
        playAudioResponse(message.audioOutput.content);
    }
    
    if (message.completionStart) {
        // Nova Sonic started generating response
        showThinkingIndicator();
    }
    
    if (message.completionEnd) {
        // Nova Sonic finished generating response
        hideThinkingIndicator();
    }
};
```

This API reference provides comprehensive documentation for integrating with the Nova S2S WebRTC Workshop system. For additional examples and troubleshooting, refer to the [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) guide.