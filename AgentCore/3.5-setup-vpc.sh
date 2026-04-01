#!/bin/bash
# Step 3.5: Setup VPC networking for AgentCore Runtime
# Uses default VPC, creates: private subnet + NAT gateway + security group
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
echo -e "${BLUE}Step 3.5: Setup VPC for AgentCore${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

source AgentCore/.config

if [ -z "$REGION" ]; then
    print_error "REGION not found in .config"
    exit 1
fi

# Check if VPC already exists from previous run
if [ ! -z "$PRIVATE_SUBNET_ID" ] && [ ! -z "$SECURITY_GROUP_ID" ]; then
    print_warning "VPC already configured:"
    print_status "  VPC: $VPC_ID"
    print_status "  Private Subnet: $PRIVATE_SUBNET_ID"
    print_status "  Security Group: $SECURITY_GROUP_ID"
    echo ""
    read -p "Skip VPC setup? (yes/no): " SKIP
    if [[ "$SKIP" == "yes" || "$SKIP" == "y" ]]; then
        print_status "Skipping VPC setup"
        exit 0
    fi
    print_warning "Will create new VPC resources (old ones not deleted)"
fi

# Use default VPC to avoid VPC limit issues
print_status "Finding default VPC..."
VPC_ID=$(aws ec2 describe-vpcs \
    --filters "Name=is-default,Values=true" \
    --region $REGION \
    --query 'Vpcs[0].VpcId' \
    --output text)

if [ -z "$VPC_ID" ] || [ "$VPC_ID" == "None" ]; then
    print_error "No default VPC found in $REGION"
    exit 1
fi

VPC_CIDR=$(aws ec2 describe-vpcs \
    --vpc-ids $VPC_ID \
    --region $REGION \
    --query 'Vpcs[0].CidrBlock' \
    --output text)

print_success "Using default VPC: $VPC_ID ($VPC_CIDR)"

# Find existing IGW
IGW_ID=$(aws ec2 describe-internet-gateways \
    --filters "Name=attachment.vpc-id,Values=$VPC_ID" \
    --region $REGION \
    --query 'InternetGateways[0].InternetGatewayId' \
    --output text)
print_status "Internet Gateway: $IGW_ID"

# Find a public subnet (for NAT Gateway)
PUBLIC_SUBNET_ID=$(aws ec2 describe-subnets \
    --filters "Name=vpc-id,Values=$VPC_ID" "Name=map-public-ip-on-launch,Values=true" \
    --region $REGION \
    --query 'Subnets[0].SubnetId' \
    --output text)

PUBLIC_SUBNET_AZ=$(aws ec2 describe-subnets \
    --subnet-ids $PUBLIC_SUBNET_ID \
    --region $REGION \
    --query 'Subnets[0].AvailabilityZone' \
    --output text)

print_status "Public subnet for NAT: $PUBLIC_SUBNET_ID ($PUBLIC_SUBNET_AZ)"

PRIVATE_SUBNET_CIDR="172.31.200.0/24"
VPC_NAME="agentcore-novasonic"

echo ""
echo "This will create in default VPC ($VPC_ID):"
echo "  - NAT Gateway in $PUBLIC_SUBNET_ID"
echo "  - Private subnet ($PRIVATE_SUBNET_CIDR) for AgentCore Runtime"
echo "  - Route table for private subnet"
echo "  - Security Group (UDP + TCP 443)"
echo ""
read -p "Continue? (yes/no): " CONFIRM
if [[ "$CONFIRM" != "yes" && "$CONFIRM" != "y" ]]; then
    print_warning "Cancelled"
    exit 0
fi
echo ""

# Step 1: Allocate Elastic IP and create NAT Gateway
print_status "Creating NAT Gateway (this may take 1-2 minutes)..."
EIP_ALLOC_ID=$(aws ec2 allocate-address \
    --domain vpc \
    --region $REGION \
    --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=${VPC_NAME}-nat-eip}]" \
    --query 'AllocationId' \
    --output text)
print_status "Elastic IP allocated: $EIP_ALLOC_ID"

NAT_GW_ID=$(aws ec2 create-nat-gateway \
    --subnet-id $PUBLIC_SUBNET_ID \
    --allocation-id $EIP_ALLOC_ID \
    --region $REGION \
    --tag-specifications "ResourceType=natgateway,Tags=[{Key=Name,Value=${VPC_NAME}-nat}]" \
    --query 'NatGateway.NatGatewayId' \
    --output text)
print_status "Waiting for NAT Gateway to become available: $NAT_GW_ID"
aws ec2 wait nat-gateway-available --nat-gateway-ids $NAT_GW_ID --region $REGION
print_success "NAT Gateway ready: $NAT_GW_ID"

# Step 2: Create Private Subnet (same AZ as public subnet)
print_status "Creating private subnet..."
PRIVATE_SUBNET_ID=$(aws ec2 create-subnet \
    --vpc-id $VPC_ID \
    --cidr-block $PRIVATE_SUBNET_CIDR \
    --availability-zone $PUBLIC_SUBNET_AZ \
    --region $REGION \
    --tag-specifications "ResourceType=subnet,Tags=[{Key=Name,Value=${VPC_NAME}-private}]" \
    --query 'Subnet.SubnetId' \
    --output text)
print_success "Private subnet created: $PRIVATE_SUBNET_ID"

# Step 3: Create private route table with NAT Gateway route
print_status "Configuring private route table..."
PRIVATE_RTB_ID=$(aws ec2 create-route-table \
    --vpc-id $VPC_ID \
    --region $REGION \
    --tag-specifications "ResourceType=route-table,Tags=[{Key=Name,Value=${VPC_NAME}-private-rtb}]" \
    --query 'RouteTable.RouteTableId' \
    --output text)
aws ec2 create-route \
    --route-table-id $PRIVATE_RTB_ID \
    --destination-cidr-block 0.0.0.0/0 \
    --nat-gateway-id $NAT_GW_ID \
    --region $REGION > /dev/null
aws ec2 associate-route-table \
    --route-table-id $PRIVATE_RTB_ID \
    --subnet-id $PRIVATE_SUBNET_ID \
    --region $REGION > /dev/null
print_success "Private route table configured: $PRIVATE_RTB_ID"

# Step 4: Create Security Group
print_status "Creating security group..."
SG_ID=$(aws ec2 create-security-group \
    --group-name "${VPC_NAME}-sg" \
    --description "Security group for AgentCore NovaSonic Runtime" \
    --vpc-id $VPC_ID \
    --region $REGION \
    --tag-specifications "ResourceType=security-group,Tags=[{Key=Name,Value=${VPC_NAME}-sg}]" \
    --query 'GroupId' \
    --output text)

# Allow all outbound traffic (needed for KVS WebRTC, Bedrock API, ECR)
# Outbound is allowed by default, but be explicit
aws ec2 authorize-security-group-egress \
    --group-id $SG_ID \
    --protocol -1 \
    --cidr 0.0.0.0/0 \
    --region $REGION 2>/dev/null || true

# Allow UDP for WebRTC media (STUN/TURN typically uses 3478 and high ports)
aws ec2 authorize-security-group-ingress \
    --group-id $SG_ID \
    --protocol udp \
    --port 1-65535 \
    --cidr 0.0.0.0/0 \
    --region $REGION \
    --tag-specifications "ResourceType=security-group-rule,Tags=[{Key=Name,Value=webrtc-udp}]"
print_status "Allowed inbound UDP (all ports) for WebRTC"

# Allow TCP for HTTPS/WebSocket signaling
aws ec2 authorize-security-group-ingress \
    --group-id $SG_ID \
    --protocol tcp \
    --port 443 \
    --cidr 0.0.0.0/0 \
    --region $REGION \
    --tag-specifications "ResourceType=security-group-rule,Tags=[{Key=Name,Value=https-tcp}]"
print_status "Allowed inbound TCP 443 for signaling"

print_success "Security group created: $SG_ID"

# Save to .config
cat >> AgentCore/.config <<EOF
VPC_ID=$VPC_ID
VPC_NAME=$VPC_NAME
IGW_ID=$IGW_ID
PUBLIC_SUBNET_ID=$PUBLIC_SUBNET_ID
EIP_ALLOC_ID=$EIP_ALLOC_ID
NAT_GW_ID=$NAT_GW_ID
PRIVATE_SUBNET_ID=$PRIVATE_SUBNET_ID
PRIVATE_RTB_ID=$PRIVATE_RTB_ID
SECURITY_GROUP_ID=$SG_ID
EOF

print_success "VPC configuration saved to AgentCore/.config"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Step 3.5 Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "VPC Resources Created (in default VPC $VPC_ID):"
echo "  NAT Gateway:     $NAT_GW_ID"
echo "  Private Subnet:  $PRIVATE_SUBNET_ID ($PRIVATE_SUBNET_CIDR)"
echo "  Route Table:     $PRIVATE_RTB_ID"
echo "  Security Group:  $SG_ID"
echo ""
echo "Next: ./AgentCore/4-deploy-agentcore.sh"
echo ""
