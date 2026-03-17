#!/bin/bash
# Terraform wrapper with DNA sequencing
# Usage: ./terraform-with-dna.sh [terraform command]

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}===========================================================${NC}"
echo -e "${GREEN}Terraform with DNA Sequencing${NC}"
echo -e "${GREEN}===========================================================${NC}"

# Pre-deployment snapshot
echo -e "\n${YELLOW}Taking pre-deployment snapshot...${NC}"
python3 automated_sequencer.py pre-deploy

# Store exit code file
EXIT_CODE_FILE="/tmp/terraform_exit_code.txt"

# Run terraform
echo -e "\n${YELLOW}Running terraform $@...${NC}"
if terraform "$@"; then
    echo "0" > "$EXIT_CODE_FILE"
    SUCCESS=true
else
    echo "$?" > "$EXIT_CODE_FILE"
    SUCCESS=false
fi

# Post-deployment analysis
echo -e "\n${YELLOW}Running post-deployment analysis...${NC}"
if [ "$SUCCESS" = true ]; then
    python3 automated_sequencer.py post-deploy success
else
    python3 automated_sequencer.py post-deploy failure
fi

# Exit with terraform's exit code
EXIT_CODE=$(cat "$EXIT_CODE_FILE")
rm -f "$EXIT_CODE_FILE"

if [ "$EXIT_CODE" -eq 0 ]; then
    echo -e "\n${GREEN}===========================================================${NC}"
    echo -e "${GREEN}Deployment completed successfully${NC}"
    echo -e "${GREEN}===========================================================${NC}"
else
    echo -e "\n${RED}===========================================================${NC}"
    echo -e "${RED}Deployment failed (exit code: $EXIT_CODE)${NC}"
    echo -e "${RED}===========================================================${NC}"
fi

exit $EXIT_CODE
