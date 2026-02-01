#!/bin/bash
# Step 3: Build Docker Image
# 启动 CodeBuild 构建 ARM64 Docker 镜像

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
echo -e "${BLUE}Step 3: Build Docker Image${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Load configuration
if [ ! -f "AgentCore/.config" ]; then
    print_error "Configuration file not found"
    print_error "Please run previous steps first"
    exit 1
fi

source AgentCore/.config

print_status "Loading configuration..."
print_status "  Project: $PROJECT_NAME"
print_status "  Region: $REGION"
echo ""

# Start build
print_status "Starting CodeBuild..."
print_status "Using S3 source"

BUILD_ID=$(aws codebuild start-build \
    --project-name $PROJECT_NAME \
    --region $REGION \
    --query 'build.id' \
    --output text)

if [ -z "$BUILD_ID" ]; then
    print_error "Failed to start build"
    exit 1
fi

print_success "Build started: $BUILD_ID"
echo ""

# Save build ID
echo "BUILD_ID=$BUILD_ID" >> AgentCore/.config

# Monitor build
print_status "Monitoring build progress..."
print_warning "This will take 10-15 minutes. You can:"
print_warning "  - Wait here for completion"
print_warning "  - Press Ctrl+C to exit (build continues in background)"
print_warning "  - Check status later with: ./AgentCore/check-build-status.sh"
echo ""

read -p "Monitor build progress? (yes/no): " MONITOR

if [[ "$MONITOR" != "yes" && "$MONITOR" != "y" ]]; then
    print_status "Build running in background"
    print_status "Build ID: $BUILD_ID"
    
    # 即使后台运行，也保存预期的 IMAGE_URI
    ECR_REPO="novasonic-s2s-webrtc-agentcore"
    IMAGE_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}:latest"
    echo "IMAGE_URI=$IMAGE_URI" >> AgentCore/.config
    echo "ECR_REPO=$ECR_REPO" >> AgentCore/.config
    
    print_status "IMAGE_URI saved (will be available after build completes)"
    echo ""
    echo "To check status:"
    echo "  ./AgentCore/check-build-status.sh"
    echo ""
    echo "After build completes, run:"
    echo "  ./AgentCore/4-deploy-agentcore.sh"
    echo ""
    exit 0
fi

# Monitor loop
echo ""
print_status "Waiting for build to complete..."
echo ""

LAST_STATUS=""
while true; do
    BUILD_INFO=$(aws codebuild batch-get-builds --ids $BUILD_ID --region $REGION --output json)
    STATUS=$(echo $BUILD_INFO | jq -r '.builds[0].buildStatus')
    PHASE=$(echo $BUILD_INFO | jq -r '.builds[0].currentPhase')
    
    if [ "$STATUS" != "$LAST_STATUS" ]; then
        print_status "Status: $STATUS | Phase: $PHASE"
        LAST_STATUS=$STATUS
    fi
    
    case $STATUS in
        "SUCCEEDED")
            echo ""
            print_success "Build completed successfully!"
            
            # Get image URI
            ECR_REPO="novasonic-s2s-webrtc-agentcore"
            IMAGE_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}:latest"
            
            echo ""
            echo "Image Information:"
            echo "  Repository: $ECR_REPO"
            echo "  Image URI: $IMAGE_URI"
            echo ""
            
            # Save image URI
            echo "IMAGE_URI=$IMAGE_URI" >> AgentCore/.config
            echo "ECR_REPO=$ECR_REPO" >> AgentCore/.config
            
            echo -e "${GREEN}========================================${NC}"
            echo -e "${GREEN}✅ Step 3 Complete!${NC}"
            echo -e "${GREEN}========================================${NC}"
            echo ""
            echo "Next step:"
            echo "  Run: ./AgentCore/4-deploy-agentcore.sh"
            echo ""
            exit 0
            ;;
        "FAILED"|"FAULT"|"TIMED_OUT"|"STOPPED")
            echo ""
            print_error "Build failed with status: $STATUS"
            echo ""
            echo "To view detailed logs:"
            echo "  aws codebuild batch-get-builds --ids $BUILD_ID --region $REGION"
            echo ""
            echo "Or check CloudWatch Logs:"
            echo "  aws logs tail /aws/codebuild/nova-webrtc-agentcore --follow --region $REGION"
            echo ""
            exit 1
            ;;
        "IN_PROGRESS")
            # Continue monitoring
            ;;
    esac
    
    sleep 10
done
