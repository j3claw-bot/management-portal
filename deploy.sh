#!/bin/bash
set -e

# ============================================================================
# Management Portal Deployment Script
# ============================================================================
# Automates: git commit → push → VPS pull → docker restart
# Usage: ./deploy.sh "Your commit message"
# ============================================================================

VPS_HOST="57.129.131.250"
VPS_USER="ubuntu"
VPS_PATH="/home/ubuntu/management-portal"
CONTAINER_NAME="kita-scheduler"
BRANCH="main"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if commit message provided
if [ -z "$1" ]; then
    echo -e "${RED}Error: Commit message required${NC}"
    echo "Usage: $0 \"Your commit message\""
    exit 1
fi

COMMIT_MSG="$1"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Management Portal Deployment${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Step 1: Check git status
echo -e "${YELLOW}[1/5] Checking git status...${NC}"
if ! git diff-index --quiet HEAD --; then
    echo -e "${GREEN}✓ Changes detected${NC}"
else
    echo -e "${YELLOW}⚠ No changes to commit${NC}"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 0
    fi
fi
echo ""

# Step 2: Stage, commit, and push
echo -e "${YELLOW}[2/5] Committing changes...${NC}"
git add -A
git commit -m "$COMMIT_MSG

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>" || {
    echo -e "${YELLOW}⚠ Nothing to commit (already committed?)${NC}"
}
echo ""

echo -e "${YELLOW}[3/5] Pushing to GitHub...${NC}"
git push origin $BRANCH
echo -e "${GREEN}✓ Pushed to origin/$BRANCH${NC}"
echo ""

# Step 3: Pull changes on VPS
echo -e "${YELLOW}[4/5] Pulling changes on VPS...${NC}"
ssh ${VPS_USER}@${VPS_HOST} "cd ${VPS_PATH} && git pull origin ${BRANCH}"
echo -e "${GREEN}✓ Changes pulled on VPS${NC}"
echo ""

# Step 4: Restart Docker container
echo -e "${YELLOW}[5/5] Restarting Docker container...${NC}"
ssh ${VPS_USER}@${VPS_HOST} "docker restart ${CONTAINER_NAME}"
echo -e "${GREEN}✓ Container restarted${NC}"
echo ""

# Step 5: Check container status
echo -e "${BLUE}Checking container status...${NC}"
sleep 3
STATUS=$(ssh ${VPS_USER}@${VPS_HOST} "docker ps --filter 'name=${CONTAINER_NAME}' --format '{{.Status}}'")
echo -e "Status: ${GREEN}${STATUS}${NC}"
echo ""

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Deployment Complete! 🚀${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "App is now live at: ${BLUE}https://jan-miller.de${NC}"
echo ""
echo "Useful commands:"
echo "  View logs:    ssh ${VPS_USER}@${VPS_HOST} 'docker logs -f ${CONTAINER_NAME}'"
echo "  Check status: ssh ${VPS_USER}@${VPS_HOST} 'docker ps --filter name=${CONTAINER_NAME}'"
echo ""
