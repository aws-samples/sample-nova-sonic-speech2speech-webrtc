#!/bin/bash
# Step 4: Deploy to AgentCore Runtime
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
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Step 4: Deploy to AgentCore Runtime${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
source AgentCore/.config
if [ -z "$IMAGE_URI" ]; then
    print_error "IMAGE_URI not found"
    exit 1
fi
print_status "Image: $IMAGE_URI"
print_status "Region: $REGION"
echo ""
RUNTIME_NAME="NovaSonic_S2S_KVSWebRTC"
ROLE_NAME="BedrockAgentCoreRuntimeRole_NovaSonic"
# Step 4.1: Create/Update IAM role
print_status "Step 4.1: Preparing IAM role..."
python3 <<'EOFPY'
import boto3, json, time
ROLE_NAME = "BedrockAgentCoreRuntimeRole_NovaSonic"
ACCOUNT_ID = "585306731051"
REGION = "ap-northeast-1"
iam = boto3.client('iam')
trust = {"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"bedrock-agentcore.amazonaws.com"},"Action":"sts:AssumeRole"}]}
policy = {"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["ecr:GetAuthorizationToken","ecr:BatchGetImage","ecr:GetDownloadUrlForLayer","ecr:BatchCheckLayerAvailability","kinesisvideo:*","bedrock:InvokeModelWithResponseStream","logs:*"],"Resource":"*"}]}
try:
    role = iam.get_role(RoleName=ROLE_NAME)
    print(f"✅ Role exists, updating policy...")
    iam.put_role_policy(RoleName=ROLE_NAME,PolicyName='Policy',PolicyDocument=json.dumps(policy))
    print(f"✅ Policy updated")
    time.sleep(5)
    role_arn = role['Role']['Arn']
except:
    print(f"📦 Creating role...")
    role = iam.create_role(RoleName=ROLE_NAME,AssumeRolePolicyDocument=json.dumps(trust))
    role_arn = role['Role']['Arn']
    iam.put_role_policy(RoleName=ROLE_NAME,PolicyName='Policy',PolicyDocument=json.dumps(policy))
    print(f"✅ Role created")
    time.sleep(15)
with open('/tmp/role_arn.txt','w') as f: f.write(role_arn)
print(f"   ARN: {role_arn}")
EOFPY
ROLE_ARN=$(cat /tmp/role_arn.txt)
echo ""

# Step 4.2: Create or Update Runtime
print_status "Step 4.2: Deploying Runtime..."

# Check if runtime ID already exists (check both .agentcore_runtime_id file and .config)
EXISTING_RUNTIME_ID=""

if [ -f ".agentcore_runtime_id" ]; then
    EXISTING_RUNTIME_ID=$(cat .agentcore_runtime_id)
    print_status "Found runtime ID in .agentcore_runtime_id: $EXISTING_RUNTIME_ID"
elif [ ! -z "$RUNTIME_ID" ]; then
    EXISTING_RUNTIME_ID=$RUNTIME_ID
    print_status "Found runtime ID in .config: $EXISTING_RUNTIME_ID"
fi

if [ ! -z "$EXISTING_RUNTIME_ID" ]; then
    print_warning "Will update existing runtime: $EXISTING_RUNTIME_ID"
else
    print_status "No existing runtime found, will create new one"
fi

echo ""
print_warning "This will create/update resources in AWS"
echo ""
read -p "Continue? (yes/no): " CONFIRM
if [[ "$CONFIRM" != "yes" && "$CONFIRM" != "y" ]]; then
    print_warning "Cancelled"
    exit 0
fi
echo ""

export REGION=$REGION
export IMAGE_URI=$IMAGE_URI
export ROLE_ARN=$ROLE_ARN
export RUNTIME_NAME=$RUNTIME_NAME
export EXISTING_RUNTIME_ID=$EXISTING_RUNTIME_ID

python3 <<'EOFPY'
import boto3, json, sys, os
REGION = os.environ['REGION']
IMAGE_URI = os.environ['IMAGE_URI']
ROLE_ARN = os.environ['ROLE_ARN']
RUNTIME_NAME = os.environ['RUNTIME_NAME']
EXISTING_RUNTIME_ID = os.environ.get('EXISTING_RUNTIME_ID', '')
print(f"🚀 Deploying Runtime...")
print(f"   Name: {RUNTIME_NAME}")
print(f"   Image: {IMAGE_URI}")
print()
try:
    client = boto3.client('bedrock-agentcore-control', region_name=REGION)
    if EXISTING_RUNTIME_ID:
        print(f"🔄 Updating runtime (ID: {EXISTING_RUNTIME_ID})...")
        response = client.update_agent_runtime(
            agentRuntimeId=EXISTING_RUNTIME_ID,
            agentRuntimeArtifact={'containerConfiguration':{'containerUri':IMAGE_URI}},
            roleArn=ROLE_ARN,
            networkConfiguration={'networkMode':'PUBLIC'}
        )
        runtime_id = EXISTING_RUNTIME_ID
        print(f"✅ Runtime updated!")
    else:
        print(f"📦 Creating new runtime...")
        response = client.create_agent_runtime(
            agentRuntimeName=RUNTIME_NAME,
            agentRuntimeArtifact={'containerConfiguration':{'containerUri':IMAGE_URI}},
            roleArn=ROLE_ARN,
            networkConfiguration={'networkMode':'PUBLIC'}
        )
        runtime_id = response['agentRuntimeId']
        print(f"✅ Runtime created!")
    status = response.get('status', 'UNKNOWN')
    print(f"   ID: {runtime_id}")
    print(f"   Status: {status}")
    with open('.agentcore_runtime_id','w') as f: f.write(runtime_id)
    with open('AgentCore/.config','a') as f: f.write(f"\nRUNTIME_ID={runtime_id}\nRUNTIME_NAME={RUNTIME_NAME}\n")
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
EOFPY
if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}✅ Step 4 Complete!${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo "Next: ./AgentCore/5-test-agent.sh"
    echo ""
else
    print_error "Failed"
    exit 1
fi
