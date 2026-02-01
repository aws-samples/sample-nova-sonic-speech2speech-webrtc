#!/bin/bash
# One-Click Deployment to AgentCore Runtime
# 一键部署到 AgentCore Runtime

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
echo -e "${BLUE}🚀 AgentCore Runtime Deployment${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

print_status "This script will:"
echo "  1. Setup CodeCommit repository"
echo "  2. Setup CodeBuild project"
echo "  3. Build ARM64 Docker image (10-15 min)"
echo "  4. Deploy to AgentCore Runtime"
echo "  5. Test the deployment"
echo ""

read -p "Continue with deployment? (yes/no): " CONFIRM

if [[ "$CONFIRM" != "yes" && "$CONFIRM" != "y" ]]; then
    print_warning "Deployment cancelled"
    exit 0
fi

echo ""
print_status "Starting deployment process..."
echo ""

# Step 1: Setup CodeCommit
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 1/5: Setup CodeCommit${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
./AgentCore/1-setup-codecommit.sh
if [ $? -ne 0 ]; then
    print_error "Step 1 failed"
    exit 1
fi

# Step 2: Setup CodeBuild
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 2/5: Setup CodeBuild${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo "yes" | ./AgentCore/2-setup-codebuild.sh
if [ $? -ne 0 ]; then
    print_error "Step 2 failed"
    exit 1
fi

# Step 3: Build Image
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 3/5: Build Docker Image${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
# Auto-confirm monitoring
echo "yes" | ./AgentCore/3-build-image.sh
if [ $? -ne 0 ]; then
    print_error "Step 3 failed"
    exit 1
fi

# Step 4: Deploy to AgentCore
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 4/5: Deploy to AgentCore${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo "yes" | ./AgentCore/4-deploy-agentcore.sh
if [ $? -ne 0 ]; then
    print_error "Step 4 failed"
    exit 1
fi

# Step 5: Test Agent
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Step 5/5: Test Agent${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
# Auto-confirm test
echo "yes" | ./AgentCore/5-test-agent.sh
if [ $? -ne 0 ]; then
    print_warning "Step 5 failed, but deployment is complete"
    print_warning "You can test manually later"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}🎉 Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
print_success "Your AgentCore Runtime is ready!"
echo ""
echo "Configuration saved in: AgentCore/.config"
echo ""
echo "Next steps:"
echo "  - Connect WebRTC client to test"
echo "  - Monitor logs in CloudWatch"
echo "  - Check README.AGENTCORE.md for details"
echo ""
