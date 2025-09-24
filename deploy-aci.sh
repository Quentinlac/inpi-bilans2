#!/bin/bash

# Lightweight OCR Service - Azure Container Instance Deployment
# Lower resource requirements than PPStructure version

# Load environment variables
source .env

# Azure settings
RESOURCE_GROUP="lightweight-ocr-rg"
ACR_NAME="lightweightocracr"
IMAGE="${ACR_NAME}.azurecr.io/lightweight-ocr-worker:latest"
LOCATION="westeurope"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Lightweight OCR Service Deployment${NC}"
echo "======================================"

# Check if resource group exists, create if not
echo -e "${YELLOW}Checking resource group...${NC}"
if ! az group show --name $RESOURCE_GROUP &>/dev/null; then
    echo "Creating resource group $RESOURCE_GROUP..."
    az group create --name $RESOURCE_GROUP --location $LOCATION
fi

# Check if ACR exists, create if not
echo -e "${YELLOW}Checking Azure Container Registry...${NC}"
if ! az acr show --name $ACR_NAME --resource-group $RESOURCE_GROUP &>/dev/null; then
    echo "Creating ACR $ACR_NAME..."
    az acr create --resource-group $RESOURCE_GROUP --name $ACR_NAME --sku Basic
fi

# Get ACR credentials
ACR_PASSWORD=$(az acr credential show --name $ACR_NAME --query "passwords[0].value" -o tsv)

# Build and push image
echo -e "${YELLOW}Building and pushing Docker image...${NC}"
az acr build --registry $ACR_NAME --image lightweight-ocr-worker:latest .

# Function to create lightweight ACI instance
create_lightweight_aci() {
    local INSTANCE_NAME=$1
    echo -e "${GREEN}Creating lightweight ACI instance: $INSTANCE_NAME${NC}"

    az container create \
        --resource-group $RESOURCE_GROUP \
        --name $INSTANCE_NAME \
        --image $IMAGE \
        --cpu 1 \
        --memory 2 \
        --os-type Linux \
        --registry-login-server ${ACR_NAME}.azurecr.io \
        --registry-username $ACR_NAME \
        --registry-password $ACR_PASSWORD \
        --environment-variables \
            WORKERS_PER_CONTAINER=4 \
            GPU_DEVICE=cpu \
            DB_HOST="$DB_HOST" \
            DB_PORT="$DB_PORT" \
            DB_NAME="$DB_NAME" \
            DB_USER="$DB_USER" \
            DB_PASSWORD="$DB_PASSWORD" \
            S3_ACCESS_KEY="$S3_ACCESS_KEY" \
            S3_SECRET_KEY="$S3_SECRET_KEY" \
            S3_REGION="${S3_REGION:-eu-west-1}" \
            S3_BUCKET="$S3_BUCKET" \
            OUTPUT_FORMAT=clean \
            ACI_NAME="$INSTANCE_NAME" \
        --location $LOCATION \
        --restart-policy OnFailure \
        --output table
}

# Check command line arguments
if [ $# -eq 0 ]; then
    echo -e "${RED}Usage: $0 <number_of_instances>${NC}"
    echo "Example: $0 10    # Creates 10 lightweight ACI instances"
    echo ""
    echo "Resource usage per instance:"
    echo "  - CPU: 1 core"
    echo "  - Memory: 2 GB"
    echo "  - Workers: 4 concurrent OCR workers"
    echo ""
    echo "Compared to PPStructure version:"
    echo "  - 50% less CPU"
    echo "  - 75% less memory"
    echo "  - 4x more workers per container"
    exit 1
fi

NUM_INSTANCES=$1

echo -e "${GREEN}Deploying $NUM_INSTANCES lightweight OCR instances...${NC}"
echo "Total resources:"
echo "  - CPU cores: $NUM_INSTANCES"
echo "  - Memory: $((NUM_INSTANCES * 2)) GB"
echo "  - Total workers: $((NUM_INSTANCES * 4))"

# Create instances in parallel (max 5 at a time)
for i in $(seq 1 $NUM_INSTANCES); do
    create_lightweight_aci "lightweight-ocr-$i" &

    # Limit parallel deployments
    if [ $((i % 5)) -eq 0 ]; then
        wait
    fi
done

# Wait for remaining deployments
wait

echo -e "${GREEN}✓ All $NUM_INSTANCES lightweight instances deployed!${NC}"
echo ""
echo "Useful commands:"
echo "  List instances:  az container list --resource-group $RESOURCE_GROUP --output table"
echo "  View logs:       az container logs --resource-group $RESOURCE_GROUP --name lightweight-ocr-1"
echo "  Monitor CPU:     az monitor metrics list --resource lightweight-ocr-1 --resource-group $RESOURCE_GROUP --metric CPUUsage --output table"
echo "  Delete all:      az container list --resource-group $RESOURCE_GROUP --query '[].name' -o tsv | xargs -I {} az container delete --resource-group $RESOURCE_GROUP --name {} --yes"