# AgentCore Runtime Architecture - Nova Sonic Speech-to-Speech WebRTC

## Solution Overview

This document describes the architecture for deploying the Nova Sonic speech-to-speech WebRTC solution on AWS Bedrock AgentCore Runtime with VPC networking.

The solution enables real-time voice conversations between a browser-based Viewer and Amazon Nova Sonic, with audio transported via WebRTC and processed through a Python server running in AgentCore Runtime.

## System Architecture

```
                                    AWS Cloud (ap-northeast-1)
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   Default VPC (172.31.0.0/16)                                               │
│   ┌───────────────────────────────────────────────────────────────────────┐  │
│   │                                                                       │  │
│   │   Public Subnet (172.31.16.0/20)                                      │  │
│   │   ┌──────────────┐     ┌──────────────────┐                           │  │
│   │   │  NAT Gateway │     │ Internet Gateway │                           │  │
│   │   │  (EIP)       │     │                  │                           │  │
│   │   └──────┬───────┘     └────────┬─────────┘                           │  │
│   │          │                      │                                     │  │
│   │   ───────┼──────────────────────┼───────────────────                  │  │
│   │          │                      │                                     │  │
│   │   Private Subnet (172.31.200.0/24)                                    │  │
│   │   ┌──────┴──────────────────────┴───────────────────────────────────┐ │  │
│   │   │                                                                 │ │  │
│   │   │   AgentCore Runtime Container (ARM64)                           │ │  │
│   │   │   ┌─────────────────────────────────────────────────────────┐   │ │  │
│   │   │   │  FastAPI (port 8080)                                    │   │ │  │
│   │   │   │  ├── POST /invocations  (start WebRTC session)          │   │ │  │
│   │   │   │  ├── GET /ping          (health check)                  │   │ │  │
│   │   │   │  └── GET /              (info)                          │   │ │  │
│   │   │   │                                                         │   │ │  │
│   │   │   │  KVSWebRTCMaster                                        │   │ │  │
│   │   │   │  ├── KVS Signaling (WSS) ──► KVS Signaling Service     │   │ │  │
│   │   │   │  ├── TURN Relay (UDP) ──────► KVS TURN Servers          │   │ │  │
│   │   │   │  └── aiortc Peer Connection                             │   │ │  │
│   │   │   │                                                         │   │ │  │
│   │   │   │  S2sSessionManager                                      │   │ │  │
│   │   │   │  └── Bidirectional Stream ──► Bedrock Runtime API       │   │ │  │
│   │   │   │      (aws-sdk-bedrock-runtime)   (Nova Sonic v1)        │   │ │  │
│   │   │   └─────────────────────────────────────────────────────────┘   │ │  │
│   │   │                                                                 │ │  │
│   │   │   Security Group: UDP 1-65535 (WebRTC), TCP 443 (signaling)     │ │  │
│   │   └─────────────────────────────────────────────────────────────────┘ │  │
│   │                                                                       │  │
│   └───────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│   ┌───────────────┐  ┌───────────────┐  ┌──────────────┐                    │
│   │ KVS Signaling │  │ KVS TURN      │  │ Bedrock      │                    │
│   │ Channel       │  │ Servers       │  │ Runtime API  │                    │
│   │ (WSS)         │  │ (UDP/443)     │  │ (Nova Sonic) │                    │
│   └───────────────┘  └───────────────┘  └──────────────┘                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

          │                                          ▲
          │ KVS Signaling (WSS)                      │ TURN Relay (UDP)
          │ + TURN relay                             │
          ▼                                          │
    ┌──────────────────────────────────┐
    │  Viewer (React WebRTC Client)    │
    │  ├── WebRTC PeerConnection       │
    │  ├── Audio capture (microphone)  │
    │  ├── Audio playback (speaker)    │
    │  └── Data channel (S2S events)   │
    └──────────────────────────────────┘
```

## Component Details

### 1. VPC Networking

| Resource | Purpose |
|----------|---------|
| Default VPC | Reuses existing VPC to avoid VPC limit issues |
| Public Subnet | Hosts NAT Gateway for outbound internet access |
| Private Subnet (172.31.200.0/24) | AgentCore Runtime ENI placement |
| NAT Gateway + EIP | Outbound internet for container (Bedrock API, KVS, TURN) |
| Internet Gateway | Already attached to default VPC |
| Security Group | Inbound: UDP all ports (WebRTC), TCP 443 (signaling) |

**Route tables:**
- Private subnet: `0.0.0.0/0 → NAT Gateway` (outbound only)
- Public subnet: `0.0.0.0/0 → Internet Gateway` (bidirectional)

### 2. AgentCore Runtime

| Setting | Value |
|---------|-------|
| Network Mode | VPC |
| Subnet | Private subnet in default VPC |
| Security Group | UDP all ports + TCP 443 inbound |
| Container Platform | linux/arm64 |
| Protocol | HTTP (port 8080) |
| Idle Timeout | 900 seconds (15 min) |
| Max Lifetime | 28800 seconds (8 hr) |

### 3. WebRTC Connection Flow

```
1. Client invokes AgentCore Runtime (/invocations)
   └── Master connects to KVS signaling as MASTER role

2. Viewer connects to KVS signaling as VIEWER role
   └── Viewer sends SDP offer + ICE candidates

3. Master receives SDP offer (via signaling WebSocket)
   ├── Refreshes TURN credentials (KVS GetIceServerConfig)
   ├── Creates RTCPeerConnection with STUN + TURN servers
   ├── Adds Viewer ICE candidates (queued if arrived early)
   ├── Gathers local ICE candidates (host + srflx + relay)
   └── Sends SDP answer back to Viewer

4. ICE connectivity checks
   ├── Host candidates: 169.254.x.x (link-local, unreachable) ✗
   ├── Server-reflexive: NAT gateway IP (symmetric NAT) ✗
   └── Relay (TURN): via KVS TURN server ✓

5. WebRTC connected via TURN relay
   ├── Audio: Viewer ↔ TURN Server ↔ Master
   └── Data channel: S2S control events
```

### 4. Audio Pipeline

```
Viewer Microphone
    │ (48kHz Opus via WebRTC)
    ▼
KVS TURN Server (relay)
    │
    ▼
Master: aiortc receives RTP
    │
    ▼
AudioProcessor: decode → resample to 16kHz → PCM int16
    │
    ▼
S2sSessionManager: encode base64 → send to Nova Sonic
    │ (bidirectional stream via aws-sdk-bedrock-runtime)
    ▼
Nova Sonic: process speech → generate response
    │ (streaming audio chunks)
    ▼
S2sSessionManager: decode base64 → raw PCM
    │
    ▼
AudioOutputTrack: buffer → encode Opus → send via RTP
    │
    ▼
KVS TURN Server (relay)
    │
    ▼
Viewer Speaker
```

### 5. Credential Architecture

```
AgentCore Runtime
    │
    ├── Instance Metadata (IMDS) ──► IAM Role credentials
    │       │
    │       ├── boto3 (automatic) ──► KVS, CloudWatch, ECR
    │       │
    │       └── boto3.Session().get_credentials()
    │               │
    │               ▼
    │       StaticCredentialsResolver ──► aws-sdk-bedrock-runtime
    │       (Smithy SDK)                  (Nova Sonic streaming)
    │
    └── IAM Role: BedrockAgentCoreRuntimeRole_NovaSonic
            ├── ecr:GetAuthorizationToken, ecr:BatchGetImage, ...
            ├── kinesisvideo:*
            ├── bedrock:InvokeModel*  (includes bidirectional stream)
            ├── logs:*
            └── ec2:CreateNetworkInterface, ec2:Describe*, ...
```

## Build Pipeline

```
Local Machine
    │
    ├── 1-setup-codecommit.sh
    │       └── zip source → upload to S3
    │
    ├── 2-setup-codebuild.sh
    │       └── create CodeBuild project (ARM64) + IAM role
    │
    ├── 3-build-image.sh
    │       └── trigger CodeBuild
    │               ├── pull base image (public.ecr.aws/python:3.12-slim)
    │               ├── install Miniconda + conda env
    │               ├── install pip dependencies (no ultralytics)
    │               ├── build ARM64 Docker image (~874 MB)
    │               └── push to ECR
    │
    ├── 3.5-setup-vpc.sh
    │       └── create NAT Gateway + private subnet + security group
    │           (in default VPC)
    │
    ├── 4-deploy-agentcore.sh
    │       ├── create/update IAM role (bedrock:InvokeModel*)
    │       └── create/update AgentCore Runtime (VPC mode)
    │
    └── 5-test-agent.sh
            └── invoke runtime + verify response
```

## Configuration State (.config)

The `AgentCore/.config` file tracks deployment state across steps. Each step appends its values, and step 1 preserves existing values when re-running.

```bash
REGION=ap-northeast-1
ACCOUNT_ID=585306731051
S3_BUCKET=nova-webrtc-agentcore-source-585306731051
S3_KEY=source.zip
PROJECT_NAME=nova-webrtc-agentcore-build
SERVICE_ROLE_ARN=arn:aws:iam::585306731051:role/CodeBuildServiceRoleForAgentCore
IMAGE_URI=585306731051.dkr.ecr.ap-northeast-1.amazonaws.com/novasonic-s2s-webrtc-agentcore:latest
ECR_REPO=novasonic-s2s-webrtc-agentcore
VPC_ID=vpc-...
PRIVATE_SUBNET_ID=subnet-...
SECURITY_GROUP_ID=sg-...
NAT_GW_ID=nat-...
EIP_ALLOC_ID=eipalloc-...
RUNTIME_ID=NovaSonic_S2S_KVSWebRTC-...
```

## Key Design Decisions

### Why VPC instead of PUBLIC mode?
AgentCore PUBLIC mode assigns link-local IPs (169.254.x.x) to containers. These are unreachable from the internet, making WebRTC peer-to-peer impossible. VPC mode with NAT gateway provides outbound internet access and enables TURN relay for WebRTC media.

### Why TURN relay instead of direct P2P?
The container sits behind a NAT gateway (symmetric NAT). Direct UDP from the Viewer cannot reach the container. TURN relay via KVS TURN servers provides a relay path: Viewer → TURN Server → Container.

### Why boto3 credential bridge?
The `aws-sdk-bedrock-runtime` Smithy SDK uses `EnvironmentCredentialsResolver` by default (reads `AWS_ACCESS_KEY_ID` env vars). AgentCore provides credentials via IMDS (instance metadata), which boto3 discovers automatically but the Smithy SDK cannot. Bridging via `boto3.Session().get_credentials()` → `StaticCredentialsResolver` solves this.

### Why exclude ultralytics/PyTorch from Docker image?
ultralytics pulls in PyTorch + CUDA (~3 GB), pushing the image past AgentCore's max image size quota. The AgentCore runtime only runs the WebRTC Master (server side) which doesn't use YOLO/phone detection. That feature is Viewer-side only.

### Why non-blocking SDP offer handling?
The signaling message loop (`async for message in websocket`) processes messages sequentially. If `_handle_sdp_offer` blocks for 5 seconds during ICE gathering, incoming ICE candidates from the Viewer are buffered but not read. By processing the SDP offer as a background task, the loop continues reading, and early ICE candidates are queued and applied after the peer connection is created.

### Why refresh TURN credentials per connection?
KVS TURN credentials have a 300-second TTL. The Master obtains them at initialization time. If a Viewer connects after 5 minutes, the TURN allocation fails with stale credentials. Refreshing before each peer connection ensures valid credentials.

## Operational Notes

### Deploying Code Updates
After `update_agent_runtime`, running containers are NOT replaced. They continue with old code until idle timeout (15 min). To force new containers:
1. Stop active sessions via `stop_runtime_session` API
2. Or wait for the 15-minute idle timeout

### Log Propagation Delay
CloudWatch logs from AgentCore Runtime containers have ~3-5 minutes propagation delay. When debugging, wait before checking logs.

### NAT Gateway Cost
NAT Gateway incurs hourly charges (~$0.045/hr + data processing). Consider deleting VPC resources during development when not testing: `./AgentCore/cleanup.sh`.
