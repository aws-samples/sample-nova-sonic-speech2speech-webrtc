#!/bin/bash
# Step 1: Prepare S3 Source
# 打包代码并上传到 S3

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
echo -e "${BLUE}Step 1: Prepare S3 Source${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Configuration
REGION="${AWS_REGION:-ap-northeast-1}"

print_status "Checking AWS credentials..."
if ! aws sts get-caller-identity &>/dev/null; then
    print_error "AWS credentials not configured"
    print_error "Please run: aws configure"
    exit 1
fi

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
print_success "AWS Account: $ACCOUNT_ID"
print_success "Region: $REGION"
echo ""

# Create S3 bucket
BUCKET_NAME="nova-webrtc-agentcore-source-${ACCOUNT_ID}"

print_status "Checking if S3 bucket exists..."
if aws s3 ls s3://$BUCKET_NAME &>/dev/null; then
    print_warning "Bucket '$BUCKET_NAME' already exists"
else
    print_status "Creating S3 bucket..."
    aws s3 mb s3://$BUCKET_NAME --region $REGION
    print_success "Bucket created: $BUCKET_NAME"
fi
echo ""

# Package code
print_status "Packaging code..."
ZIP_FILE="nova-webrtc-source.zip"

zip -r $ZIP_FILE . \
    -x "*.git*" \
    -x "*node_modules*" \
    -x "*__pycache__*" \
    -x "*.DS_Store" \
    -x "*logs/*" \
    -x "*.venv*" \
    -x "*.env" \
    -x "*toDelete_*" \
    -x "*.agentcore_arn" \
    -x "$ZIP_FILE" \
    -q

FILE_SIZE=$(ls -lh $ZIP_FILE | awk '{print $5}')
print_success "Code packaged: $ZIP_FILE ($FILE_SIZE)"
echo ""

# Upload to S3
print_status "Uploading to S3..."
aws s3 cp $ZIP_FILE s3://$BUCKET_NAME/source.zip --region $REGION

print_success "Uploaded to s3://$BUCKET_NAME/source.zip"
echo ""

# Clean up local zip
rm -f $ZIP_FILE

# Save configuration (preserve existing values from other steps)
print_status "Saving configuration..."
EXISTING_CONFIG=""
if [ -f "AgentCore/.config" ]; then
    # Preserve values not set by this step
    EXISTING_CONFIG=$(grep -v "^REGION=" AgentCore/.config | grep -v "^ACCOUNT_ID=" | grep -v "^S3_BUCKET=" | grep -v "^S3_KEY=" | grep -v "^$")
fi
cat > AgentCore/.config <<EOF
REGION=$REGION
ACCOUNT_ID=$ACCOUNT_ID
S3_BUCKET=$BUCKET_NAME
S3_KEY=source.zip
EOF
if [ -n "$EXISTING_CONFIG" ]; then
    echo "$EXISTING_CONFIG" >> AgentCore/.config
fi
print_success "Configuration saved to AgentCore/.config"
echo ""

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✅ Step 1 Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "S3 Source Information:"
echo "  Bucket: $BUCKET_NAME"
echo "  Key: source.zip"
echo "  Size: $FILE_SIZE"
echo ""
echo "Next step:"
echo "  Run: ./AgentCore/2-setup-codebuild.sh"
echo ""
