# Nova S2S WebRTC - AgentCore Runtime Deployment Guide

## Overview

Deploy Nova Sonic speech-to-speech WebRTC solution to AWS Bedrock AgentCore Runtime with VPC networking for full WebRTC UDP connectivity.

**Key components:**
- S3 for code source (avoids CodeCommit auth issues)
- CodeBuild for ARM64 Docker images (no local Docker needed)
- VPC with private subnet + NAT gateway (required for WebRTC UDP)
- boto3 credential bridge for Smithy SDK (AgentCore IAM role support)

---

## Prerequisites

```bash
aws configure  # AWS credentials with admin access
```

## Quick Start

### One-Click Deployment

```bash
./AgentCore/deploy-all.sh
```

### Step-by-Step Deployment

```bash
# Step 1: Package and upload source to S3
./AgentCore/1-setup-codecommit.sh

# Step 2: Create CodeBuild project and IAM role
./AgentCore/2-setup-codebuild.sh

# Step 3: Build ARM64 Docker image (~3-5 min)
./AgentCore/3-build-image.sh

# Step 3.5: Create VPC networking (private subnet + NAT gateway)
./AgentCore/3.5-setup-vpc.sh

# Step 4: Deploy to AgentCore Runtime (VPC mode)
./AgentCore/4-deploy-agentcore.sh

# Step 5: Test the deployment
./AgentCore/5-test-agent.sh
```

---

## File Structure

```
AgentCore/
├── README.AGENTCORE.md          # This guide
├── 1-setup-codecommit.sh        # Step 1: S3 source upload
├── 2-setup-codebuild.sh         # Step 2: CodeBuild project
├── 3-build-image.sh             # Step 3: Docker image build
├── 3.5-setup-vpc.sh             # Step 3.5: VPC networking
├── 4-deploy-agentcore.sh        # Step 4: Deploy runtime (VPC mode)
├── 5-test-agent.sh              # Step 5: Test invocation
├── check-build-status.sh        # Helper: Check build status
├── cleanup.sh                   # Helper: Cleanup all resources
├── deploy-all.sh                # Helper: One-click deploy
├── buildspec.yml                # CodeBuild specification
├── .bedrock_agentcore.yaml      # AgentCore metadata
└── .config                      # Auto-generated deployment state
```

### Script Summary

| Script | Function | Duration |
|--------|----------|----------|
| `1-setup-codecommit.sh` | S3 bucket + source upload | ~1 min |
| `2-setup-codebuild.sh` | CodeBuild project + IAM role | ~30 sec |
| `3-build-image.sh` | ARM64 Docker image build | ~3-5 min |
| `3.5-setup-vpc.sh` | VPC + NAT gateway + security group | ~2 min |
| `4-deploy-agentcore.sh` | IAM role update + runtime deploy | ~1 min |
| `5-test-agent.sh` | Invoke runtime + verify | ~30 sec |

---

## Architecture

### Network Architecture (VPC Mode)

```
Internet
    │
    ├── Viewer (Browser/React Client)
    │       │
    │       │ WebRTC UDP (via TURN relay)
    │       │
    │       ▼
    │   KVS TURN Server ◄─── TURN allocation ──── AgentCore Container
    │                                                     │
    ├── KVS Signaling (WSS) ◄──────────────────────────── │
    │                                                     │
    └── NAT Gateway (public subnet)                       │
            │                                             │
            └── Private Subnet ───────────────────────────┘
                (AgentCore Runtime ENI)
```

**Why VPC is required:**
- AgentCore PUBLIC mode gives containers link-local IPs (169.254.x.x) - unreachable for WebRTC
- VPC mode with private subnet + NAT gateway enables:
  - Outbound internet access (Bedrock API, KVS signaling, TURN servers)
  - TURN relay for WebRTC media (UDP through NAT)
  - Proper ICE candidate gathering (srflx + relay candidates)

### Runtime Flow

```
AgentCore Runtime Container (ARM64)
    │
    ├── FastAPI starts on port 8080
    │
    ├── POST /invocations
    │       ├── Initialize WebRTC Master
    │       ├── Connect to KVS signaling channel (WSS)
    │       ├── Obtain TURN credentials from KVS
    │       └── Return immediately (async processing)
    │
    ├── Viewer connects via KVS signaling
    │       ├── Receive SDP offer
    │       ├── Refresh TURN credentials (they expire after 300s)
    │       ├── Create peer connection with TURN relay
    │       ├── Exchange ICE candidates (non-blocking)
    │       └── Establish WebRTC media connection
    │
    ├── Audio pipeline (after WebRTC connected)
    │       ├── Receive audio from Viewer via WebRTC
    │       ├── Forward to Nova Sonic via bidirectional stream
    │       ├── Receive Nova Sonic response audio
    │       └── Send back to Viewer via WebRTC
    │
    └── GET /ping → Health check (Healthy / HealthyBusy)
```

---

## Key Technical Details

### IAM Permissions

The runtime execution role (`BedrockAgentCoreRuntimeRole_NovaSonic`) requires:

| Permission | Purpose |
|-----------|---------|
| `ecr:GetAuthorizationToken`, `ecr:BatchGetImage`, etc. | Pull container image |
| `kinesisvideo:*` | KVS signaling, ICE server config |
| `bedrock:InvokeModel*` | Nova Sonic bidirectional streaming |
| `logs:*` | CloudWatch logging |
| `ec2:CreateNetworkInterface`, `ec2:Describe*`, etc. | VPC network interfaces |

**Important:** `bedrock:InvokeModelWithResponseStream` alone is NOT sufficient. The bidirectional stream API requires `bedrock:InvokeModelWithBidirectionalStream` (use `bedrock:InvokeModel*`).

### Credential Bridging (Smithy SDK)

The `aws-sdk-bedrock-runtime` (Smithy-based SDK for Nova Sonic streaming) does NOT use boto3's credential chain. AgentCore provides IAM role credentials via instance metadata (IMDS), which boto3 picks up automatically but the Smithy SDK does not.

**Solution:** Bridge credentials from boto3 to Smithy SDK:
```python
import boto3
from smithy_aws_core.identity.static import StaticCredentialsResolver

session = boto3.Session()
creds = session.get_credentials().get_frozen_credentials()
config = Config(
    aws_access_key_id=creds.access_key,
    aws_secret_access_key=creds.secret_key,
    aws_session_token=creds.token,
    aws_credentials_identity_resolver=StaticCredentialsResolver(),
)
```

### WebRTC ICE Handling

Two critical fixes for WebRTC in VPC:

1. **TURN credential refresh:** KVS TURN credentials expire after 300 seconds. They must be refreshed before each peer connection (not just at initialization).

2. **Non-blocking SDP offer handling:** The signaling message loop must not block during ICE gathering (~5 seconds). SDP offer processing runs as a background task so ICE candidates from the Viewer are received and queued properly.

### Docker Image

- **Base:** `public.ecr.aws/docker/library/python:3.12-slim` + Miniconda (avoids Docker Hub rate limits)
- **Size:** ~874 MB (ultralytics/PyTorch excluded - not needed for Master)
- **Conda TOS:** Accepted automatically in Dockerfile
- **Key dependencies:** aiortc, boto3, fastapi, aws-sdk-bedrock-runtime

---

## Redeploy After Code Update

```bash
# 1. Upload new source
./AgentCore/1-setup-codecommit.sh

# 2. Rebuild image
echo "yes" | ./AgentCore/3-build-image.sh

# 3. Update runtime
echo "yes" | ./AgentCore/4-deploy-agentcore.sh

# 4. IMPORTANT: Stop old sessions to force new container
python3 -c "
import boto3
client = boto3.client('bedrock-agentcore', region_name='ap-northeast-1')
client.stop_runtime_session(
    agentRuntimeArn='YOUR_RUNTIME_ARN',
    runtimeSessionId='YOUR_SESSION_ID'
)
"

# 5. Invoke fresh session and test
./AgentCore/5-test-agent.sh
```

**Note:** `update_agent_runtime` does NOT replace running containers. You must stop active sessions or wait for the 15-minute idle timeout.

---

## Monitoring

### Runtime Logs

```bash
# CloudWatch log group
/aws/bedrock-agentcore/runtimes/<RUNTIME_ID>-DEFAULT

# View recent logs
aws logs tail /aws/bedrock-agentcore/runtimes/NovaSonic_S2S_KVSWebRTC-vLGD8tHJIH-DEFAULT \
  --since 5m --region ap-northeast-1
```

### Check Runtime Status

```bash
source .venv/bin/activate
python3 -c "
import boto3
client = boto3.client('bedrock-agentcore-control', region_name='ap-northeast-1')
rt = client.get_agent_runtime(agentRuntimeId='NovaSonic_S2S_KVSWebRTC-vLGD8tHJIH')
print(f'Status: {rt[\"status\"]}')
print(f'Network: {rt[\"networkConfiguration\"]}')
print(f'Version: {rt[\"agentRuntimeVersion\"]}')
"
```

### Stop Active Session

```bash
source .venv/bin/activate
python3 -c "
import boto3
client = boto3.client('bedrock-agentcore', region_name='ap-northeast-1')
client.stop_runtime_session(
    agentRuntimeArn='arn:aws:bedrock-agentcore:ap-northeast-1:585306731051:runtime/NovaSonic_S2S_KVSWebRTC-vLGD8tHJIH',
    runtimeSessionId='YOUR_SESSION_ID'
)
"
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Build fails: Docker Hub rate limit | Base image pull rate-limited | Uses `public.ecr.aws` base image (already fixed) |
| Build fails: conda TOS error | Conda channels require TOS acceptance | `conda tos accept` in Dockerfile (already fixed) |
| Container crash: `No module named 'fastapi'` | Wrong Python used (base vs conda) | CMD uses full path `/opt/conda/envs/.../python` |
| Image too large (>3GB) | ultralytics pulls PyTorch+CUDA | Excluded from Dockerfile (not needed for Master) |
| 403 AccessDeniedException from Bedrock | IAM missing `InvokeModelWithBidirectionalStream` | Use `bedrock:InvokeModel*` in IAM policy |
| SmithyIdentityError | Smithy SDK can't find credentials | Use boto3 credential bridge (see above) |
| WebRTC: ICE stuck at "checking" | TURN credentials expired | Refresh TURN creds before each peer connection |
| WebRTC: Viewer ICE candidates lost | Message loop blocked during SDP handling | SDP offer processed as background task |
| No audio response | Session manager not created (credential error) | Check CloudWatch logs for init errors |
| Old code still running after deploy | AgentCore reuses running containers | Stop sessions via API or wait 15 min idle timeout |

---

## Cleanup

```bash
./AgentCore/cleanup.sh
```

Deletes: AgentCore Runtime, ECR repository, CodeBuild project, S3 bucket, IAM roles, VPC resources (NAT gateway, subnets, security groups, route tables, EIP).
