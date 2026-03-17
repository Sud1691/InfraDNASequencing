#!/bin/bash
# deploy-with-dna.sh
# Kubernetes deployment with DNA sequencing analysis

set -e

MANIFEST=$1
NAMESPACE=${2:-default}

if [ -z "$MANIFEST" ]; then
    echo "Usage: $0 <manifest.yaml> [namespace]"
    exit 1
fi

echo "🔬 Starting DNA-tracked deployment"
echo "Manifest: $MANIFEST"
echo "Namespace: $NAMESPACE"

# Pre-deployment snapshot
echo ""
echo "📸 Taking pre-deployment snapshot..."
python3 automated_sequencer.py pre-deploy

# Apply manifest
echo ""
echo "🚀 Applying Kubernetes manifest..."
if kubectl apply -f "$MANIFEST" -n "$NAMESPACE"; then
    DEPLOY_STATUS="success"
    echo "✅ Deployment succeeded"
else
    DEPLOY_STATUS="failure"
    echo "❌ Deployment failed"
fi

# Post-deployment analysis
echo ""
echo "🔬 Running post-deployment analysis..."
python3 automated_sequencer.py post-deploy "$DEPLOY_STATUS"

# Display analysis
echo ""
echo "============================================================"
if [ -d "deployments" ]; then
    cat deployments/*/analysis.txt 2>/dev/null || echo "No analysis files found"
fi

# Exit with deployment status
if [ "$DEPLOY_STATUS" == "success" ]; then
    exit 0
else
    exit 1
fi
