#!/bin/bash
# Step 5: Test Agent
set -e
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'
print_status() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }

# 解析命令行参数
LOG_LEVEL="INFO"
while [[ $# -gt 0 ]]; do
    case $1 in
        --log-level)
            LOG_LEVEL="$2"
            shift 2
            ;;
        --debug|-d)
            LOG_LEVEL="DEBUG"
            shift
            ;;
        *)
            print_error "Unknown option: $1"
            echo "Usage: $0 [--log-level LEVEL | --debug|-d]"
            echo "  --log-level LEVEL  Set log level (DEBUG, INFO, WARNING, ERROR)"
            echo "  --debug, -d        Enable DEBUG logging"
            exit 1
            ;;
    esac
done
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Step 5: Test Agent${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
source AgentCore/.config

if [ -z "$RUNTIME_ID" ]; then
    print_error "RUNTIME_ID not found in .config"
    print_error "Please run ./AgentCore/4-deploy-agentcore.sh first"
    exit 1
fi

print_status "Runtime ID: $RUNTIME_ID"
print_status "Region: $REGION"
print_status "Log Level: $LOG_LEVEL"
echo ""
# Check status
print_status "Checking runtime status..."
python3 <<EOFPY
import boto3
client = boto3.client('bedrock-agentcore-control', region_name='${REGION}')
runtime = client.get_agent_runtime(agentRuntimeId='${RUNTIME_ID}', agentRuntimeVersion='1')
print(f"✅ Runtime Status: {runtime['status']}")
print(f"   ARN: {runtime.get('agentRuntimeArn')}")
EOFPY
echo ""
# Test invocation
TEST_CHANNEL="${KVS_CHANNEL_NAME:-nova-s2s-webrtc-test}"
print_status "Testing invocation..."
print_status "  Channel: $TEST_CHANNEL"
echo ""
read -p "Continue? (yes/no): " CONFIRM
if [[ "$CONFIRM" != "yes" && "$CONFIRM" != "y" ]]; then
    exit 0
fi
echo ""
python3 <<EOFPY
import boto3, json, uuid
REGION = '${REGION}'
RUNTIME_ID = '${RUNTIME_ID}'
CHANNEL = '${TEST_CHANNEL}'
LOG_LEVEL = '${LOG_LEVEL}'
print(f"🚀 Invoking agent...")
print(f"   Runtime: {RUNTIME_ID}")
print(f"   Channel: {CHANNEL}")
print(f"   Log Level: {LOG_LEVEL}")
print()
try:
    # Get runtime ARN
    control_client = boto3.client('bedrock-agentcore-control', region_name=REGION)
    runtime = control_client.get_agent_runtime(agentRuntimeId=RUNTIME_ID, agentRuntimeVersion='1')
    runtime_arn = runtime['agentRuntimeArn']
    print(f"   ARN: {runtime_arn}")
    print()
    
    # Invoke runtime
    client = boto3.client('bedrock-agentcore', region_name=REGION)
    payload = json.dumps({
        "channel_name": CHANNEL,
        "log_level": LOG_LEVEL
    }).encode('utf-8')
    response = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        runtimeSessionId=str(uuid.uuid4()),
        payload=payload
    )
    content = []
    for chunk in response.get('response', []):
        content.append(chunk.decode('utf-8'))
    result = json.loads(''.join(content))
    print("✅ Response received:")
    print(json.dumps(result, indent=2))
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
EOFPY
if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}✅ Step 5 Complete!${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo "🎉 All steps completed successfully!"
    echo ""
fi
