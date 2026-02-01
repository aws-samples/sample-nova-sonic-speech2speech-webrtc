#!/bin/bash
# Cleanup AgentCore Resources
# 清理 AgentCore 相关资源

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
echo -e "${RED}========================================${NC}"
echo -e "${RED}⚠️  Cleanup AgentCore Resources${NC}"
echo -e "${RED}========================================${NC}"
echo ""

print_warning "This will delete the following resources:"
echo "  - AgentCore Runtime"
echo "  - ECR Repository and Images"
echo "  - CodeBuild Project"
echo "  - CodeCommit Repository (optional)"
echo "  - IAM Service Role (optional)"
echo ""

read -p "Are you sure you want to continue? (yes/no): " CONFIRM

if [[ "$CONFIRM" != "yes" ]]; then
    print_status "Cleanup cancelled"
    exit 0
fi

# Load configuration
if [ ! -f "AgentCore/.config" ]; then
    print_warning "Configuration file not found, using defaults"
    REGION="${AWS_REGION:-ap-northeast-1}"
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
else
    source AgentCore/.config
fi

echo ""
print_status "Starting cleanup..."
echo ""

# 1. Delete AgentCore Runtime
if [ -n "$RUNTIME_NAME" ]; then
    print_status "Deleting AgentCore Runtime: $RUNTIME_NAME"
    if aws bedrock-agentcore delete-agent-runtime \
        --agent-runtime-name $RUNTIME_NAME \
        --region $REGION 2>/dev/null; then
        print_success "AgentCore Runtime deleted"
    else
        print_warning "AgentCore Runtime not found or already deleted"
    fi
else
    print_warning "Runtime name not found, skipping"
fi
echo ""

# 2. Delete ECR Repository
ECR_REPO="novasonic-s2s-webrtc-agentcore"
print_status "Deleting ECR Repository: $ECR_REPO"
if aws ecr delete-repository \
    --repository-name $ECR_REPO \
    --force \
    --region $REGION 2>/dev/null; then
    print_success "ECR Repository deleted"
else
    print_warning "ECR Repository not found or already deleted"
fi
echo ""

# 2.5. Delete base image ECR Repository
BASE_ECR_REPO="miniconda3-arm64"
print_status "Deleting base image ECR Repository: $BASE_ECR_REPO"
if aws ecr delete-repository \
    --repository-name $BASE_ECR_REPO \
    --force \
    --region $REGION 2>/dev/null; then
    print_success "Base image ECR Repository deleted"
else
    print_warning "Base image ECR Repository not found or already deleted"
fi
echo ""

# 2.6. Delete S3 bucket
if [ -n "$S3_BUCKET" ]; then
    read -p "Delete S3 bucket '$S3_BUCKET'? (yes/no): " DELETE_BUCKET
    if [[ "$DELETE_BUCKET" == "yes" ]]; then
        print_status "Deleting S3 bucket: $S3_BUCKET"
        if aws s3 rb s3://$S3_BUCKET --force --region $REGION 2>/dev/null; then
            print_success "S3 bucket deleted"
        else
            print_warning "S3 bucket not found or already deleted"
        fi
    else
        print_status "Keeping S3 bucket"
    fi
else
    print_warning "S3 bucket name not found, skipping"
fi
echo ""

# 3. Delete CodeBuild Project
if [ -n "$PROJECT_NAME" ]; then
    print_status "Deleting CodeBuild Project: $PROJECT_NAME"
    if aws codebuild delete-project \
        --name $PROJECT_NAME \
        --region $REGION 2>/dev/null; then
        print_success "CodeBuild Project deleted"
    else
        print_warning "CodeBuild Project not found or already deleted"
    fi
else
    print_warning "Project name not found, skipping"
fi
echo ""

# 4. Delete CodeCommit Repository (optional) - Not used anymore
# Keeping this section commented out for reference
# if [ -n "$REPO_NAME" ]; then
#     read -p "Delete CodeCommit Repository '$REPO_NAME'? (yes/no): " DELETE_REPO
#     if [[ "$DELETE_REPO" == "yes" ]]; then
#         print_status "Deleting CodeCommit Repository: $REPO_NAME"
#         aws codecommit delete-repository --repository-name $REPO_NAME --region $REGION 2>/dev/null
#         git remote remove codecommit 2>/dev/null || true
#     fi
# fi
echo ""

# 5. Delete IAM Service Role (optional)
SERVICE_ROLE_NAME="CodeBuildServiceRoleForAgentCore"
read -p "Delete IAM Service Role '$SERVICE_ROLE_NAME'? (yes/no): " DELETE_ROLE
if [[ "$DELETE_ROLE" == "yes" ]]; then
    print_status "Deleting IAM Service Role: $SERVICE_ROLE_NAME"
    
    # Delete inline policies first
    POLICIES=$(aws iam list-role-policies --role-name $SERVICE_ROLE_NAME --query 'PolicyNames' --output text 2>/dev/null || echo "")
    if [ -n "$POLICIES" ]; then
        for POLICY in $POLICIES; do
            aws iam delete-role-policy --role-name $SERVICE_ROLE_NAME --policy-name $POLICY 2>/dev/null || true
        done
    fi
    
    # Delete role
    if aws iam delete-role --role-name $SERVICE_ROLE_NAME 2>/dev/null; then
        print_success "IAM Service Role deleted"
    else
        print_warning "IAM Service Role not found or already deleted"
    fi
else
    print_status "Keeping IAM Service Role"
fi
echo ""

# 6. Clean up local files
print_status "Cleaning up local files..."
rm -f .agentcore_arn
rm -f agentcore_deployment_info.json
rm -f AgentCore/.config
print_success "Local files cleaned up"
echo ""

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✅ Cleanup Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
print_status "All resources have been cleaned up"
echo ""
