#!/bin/bash
# Check CodeBuild Status
# 检查 CodeBuild 构建状态

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

print_status() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Check CodeBuild Status${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Load configuration
if [ ! -f "AgentCore/.config" ]; then
    print_error "Configuration file not found"
    exit 1
fi

source AgentCore/.config

if [ -z "$BUILD_ID" ]; then
    print_error "No build ID found in configuration"
    print_error "Please run: ./AgentCore/3-build-image.sh first"
    exit 1
fi

print_status "Checking build: $BUILD_ID"
echo ""

# Get build info
BUILD_INFO=$(aws codebuild batch-get-builds --ids $BUILD_ID --region $REGION --output json)
STATUS=$(echo $BUILD_INFO | jq -r '.builds[0].buildStatus')
PHASE=$(echo $BUILD_INFO | jq -r '.builds[0].currentPhase')
START_TIME=$(echo $BUILD_INFO | jq -r '.builds[0].startTime')
END_TIME=$(echo $BUILD_INFO | jq -r '.builds[0].endTime')

echo "Build Information:"
echo "  Build ID: $BUILD_ID"
echo "  Status: $STATUS"
echo "  Phase: $PHASE"
echo "  Started: $START_TIME"

if [ "$END_TIME" != "null" ]; then
    echo "  Ended: $END_TIME"
fi
echo ""

case $STATUS in
    "SUCCEEDED")
        print_success "Build completed successfully!"
        
        # Get image URI
        ECR_REPO="novasonic-s2s-webrtc-agentcore"
        IMAGE_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}:latest"
        
        echo ""
        echo "Image URI: $IMAGE_URI"
        echo ""
        echo "Next step:"
        echo "  ./AgentCore/4-deploy-agentcore.sh"
        echo ""
        ;;
    "FAILED"|"FAULT"|"TIMED_OUT"|"STOPPED")
        print_error "Build failed with status: $STATUS"
        echo ""
        echo "To view logs:"
        echo "  aws logs tail /aws/codebuild/nova-webrtc-agentcore --follow --region $REGION"
        echo ""
        ;;
    "IN_PROGRESS")
        print_status "Build is still in progress..."
        echo ""
        echo "To monitor:"
        echo "  watch -n 10 ./AgentCore/check-build-status.sh"
        echo ""
        ;;
esac
