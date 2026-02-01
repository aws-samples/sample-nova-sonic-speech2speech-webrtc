#!/bin/bash
# Step 2: Setup CodeBuild Project
# 创建 CodeBuild 项目用于构建 ARM64 Docker 镜像（使用 S3 源）

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
echo -e "${BLUE}Step 2: Setup CodeBuild Project${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Load configuration
if [ ! -f "AgentCore/.config" ]; then
    print_error "Configuration file not found"
    print_error "Please run: ./AgentCore/1-setup-codecommit.sh first"
    exit 1
fi

source AgentCore/.config

print_status "Loading configuration..."
print_status "  S3 Bucket: $S3_BUCKET"
print_status "  Region: $REGION"
print_status "  Account: $ACCOUNT_ID"
echo ""

# Configuration
PROJECT_NAME="nova-webrtc-agentcore-build"
SERVICE_ROLE_NAME="CodeBuildServiceRoleForAgentCore"

# Check if service role exists
print_status "Checking CodeBuild service role..."
if aws iam get-role --role-name $SERVICE_ROLE_NAME --region $REGION &>/dev/null; then
    print_success "Service role exists: $SERVICE_ROLE_NAME"
    ROLE_ARN=$(aws iam get-role --role-name $SERVICE_ROLE_NAME --query 'Role.Arn' --output text)
else
    print_status "Creating CodeBuild service role..."
    
    # Create trust policy
    cat > /tmp/codebuild-trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "codebuild.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

    # Create role
    aws iam create-role \
        --role-name $SERVICE_ROLE_NAME \
        --assume-role-policy-document file:///tmp/codebuild-trust-policy.json \
        --description "Service role for CodeBuild to build AgentCore images" \
        --region $REGION > /dev/null
    
    ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${SERVICE_ROLE_NAME}"
    
    print_success "Service role created: $SERVICE_ROLE_NAME"
    print_warning "Waiting 15 seconds for IAM role to propagate..."
    sleep 15
fi
echo ""

# Update IAM policy with S3, ECR, and Logs permissions
print_status "Updating IAM policy with S3, ECR, and Logs permissions..."

cat > /tmp/codebuild-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:GetObjectVersion",
        "s3:ListBucket",
        "s3:ListBucketVersions"
      ],
      "Resource": [
        "arn:aws:s3:::${S3_BUCKET}",
        "arn:aws:s3:::${S3_BUCKET}/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:PutImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:CreateRepository",
        "ecr:DescribeRepositories"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:/aws/codebuild/*"
    }
  ]
}
EOF

aws iam put-role-policy \
    --role-name $SERVICE_ROLE_NAME \
    --policy-name CodeBuildAgentCorePolicy \
    --policy-document file:///tmp/codebuild-policy.json

print_success "IAM policy updated"
print_warning "Waiting 10 seconds for policy to propagate..."
sleep 10
echo ""

# Check if CodeBuild project exists
print_status "Checking if CodeBuild project exists..."
if aws codebuild batch-get-projects --names $PROJECT_NAME --region $REGION --query 'projects[0].name' --output text 2>/dev/null | grep -q $PROJECT_NAME; then
    print_warning "CodeBuild project '$PROJECT_NAME' already exists"
    read -p "Do you want to update it? (yes/no): " UPDATE
    
    if [[ "$UPDATE" == "yes" || "$UPDATE" == "y" ]]; then
        print_status "Updating CodeBuild project..."
        aws codebuild update-project \
            --name $PROJECT_NAME \
            --source type=S3,location=${S3_BUCKET}/${S3_KEY},buildspec=AgentCore/buildspec.yml \
            --environment type=ARM_CONTAINER,image=aws/codebuild/amazonlinux2-aarch64-standard:3.0,computeType=BUILD_GENERAL1_LARGE,privilegedMode=true \
            --service-role $ROLE_ARN \
            --region $REGION > /dev/null
        print_success "CodeBuild project updated"
    else
        print_status "Skipping update"
    fi
else
    print_status "Creating CodeBuild project..."
    aws codebuild create-project \
        --name $PROJECT_NAME \
        --description "Build Nova S2S WebRTC for AgentCore Runtime (ARM64)" \
        --source type=S3,location=${S3_BUCKET}/${S3_KEY},buildspec=AgentCore/buildspec.yml \
        --artifacts type=NO_ARTIFACTS \
        --environment type=ARM_CONTAINER,image=aws/codebuild/amazonlinux2-aarch64-standard:3.0,computeType=BUILD_GENERAL1_LARGE,privilegedMode=true \
        --service-role $ROLE_ARN \
        --region $REGION > /dev/null
    
    print_success "CodeBuild project created: $PROJECT_NAME"
fi
echo ""

# Update configuration
cat >> AgentCore/.config <<EOF
PROJECT_NAME=$PROJECT_NAME
SERVICE_ROLE_ARN=$ROLE_ARN
EOF

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✅ Step 2 Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "CodeBuild Project Information:"
echo "  Name: $PROJECT_NAME"
echo "  Service Role: $SERVICE_ROLE_NAME"
echo "  Environment: ARM64 (amazonlinux2-aarch64-standard:3.0)"
echo "  Source: S3 ($S3_BUCKET/$S3_KEY)"
echo ""
echo "Next step:"
echo "  Run: ./AgentCore/3-build-image.sh"
echo ""
