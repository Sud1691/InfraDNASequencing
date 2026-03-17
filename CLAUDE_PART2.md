# Infrastructure DNA Sequencing - Part 2: Usage & Implementation

**This is Part 2 - Continuation of CLAUDE.md**

---

## Usage Examples

### Example 1: Incident Investigation

**Scenario:** Payment service 100% error rate at 2 AM

```bash
# Step 1: Take snapshot of current (broken) state
python infra_dna_sequencer.py --mode snapshot --label incident_payment_503

# Step 2: Find last known good snapshot
python automated_sequencer.py find-last-good
# Output: snapshots/auto_20260317_0145.json

# Step 3: Analyze
python infra_dna_sequencer.py --mode analyze \
  --before snapshots/auto_20260317_0145.json \
  --after snapshots/incident_payment_503_*.json \
  --incident "Payment service 100% error rate, all transactions failing"
```

**Claude's Analysis:**

```
🧬 Direct Mutations
- aws_security_group.app-sg
  * Ingress rule modified
  * Port 6443, CIDR changed: 10.0.0.0/8 → 10.1.0.0/16
  * Changed at: 2026-03-17T01:58:23Z

🌊 Cascade Analysis

1st Order Effects:
- aws_instance.k8s-node-3 (IP: 10.2.5.1)
  * Now blocked from Kubernetes API server (10.2.5.10:6443)
  * Reason: IP 10.2.5.1 outside new CIDR range 10.1.0.0/16

2nd Order Effects:
- kubernetes_node.ip-10-0-1-50
  * Status changed: Ready → NotReady
  * Reason: Lost connection to API server
  * Pods on this node: 12 total

3rd Order Effects:
- kubernetes_pod.payment-api-7d8f9 (CrashLoopBackOff)
- kubernetes_pod.payment-api-9k2m4 (CrashLoopBackOff)
- kubernetes_pod.payment-worker-3n7q1 (CrashLoopBackOff)
  * All scheduled on node ip-10-0-1-50
  * Cannot reach node after NotReady status

4th Order Effects:
- kubernetes_service.payment
  * Healthy endpoints: 3 → 0
  * All pods unavailable

5th Order Effects:
- kubernetes_ingress.api-gateway
  * Returns: 503 Service Unavailable
  * No backend endpoints for /payment/* routes

🌐 External API Impact

CRITICAL - Stripe API Integration:
- payment-service makes Stripe API calls for transaction processing
- With payment-service down → 0 Stripe API calls
- Last successful Stripe call: 2026-03-17T01:59:45Z
- Estimated revenue impact: ~$2,300/minute (based on average)

DEGRADED - Twilio SMS:
- payment-service triggers SMS notifications via Twilio
- Notifications queue backing up
- 347 pending SMS in queue (normally <10)

🎯 Root Cause Hypothesis (98% confidence)

Security group change blocked Kubernetes node from API server access.
This is textbook K8s cluster failure mode when nodes lose API connectivity.

Evidence:
1. Timing: SG change at 01:58, pods failed at 02:00 (matches propagation)
2. Pattern: All pods on SINGLE node failed (node-level issue)
3. IP ranges: Node IP 10.2.5.1 outside new CIDR 10.1.0.0/16
4. No other infrastructure changes detected

🔗 Dependency Chain

ASG launch template (unchanged) →
Uses security group app-sg (CHANGED) →
Blocks port 6443 for IPs outside 10.1.0.0/16 →
Node 10.2.5.1 cannot reach API server →
Node enters NotReady state →
All pods on node fail →
Service has no healthy endpoints →
API gateway returns 503 →
External API calls cease →
Revenue stops

💡 Immediate Fix

Revert the security group change:

aws ec2 authorize-security-group-ingress \
  --group-id sg-abc123def456 \
  --protocol tcp \
  --port 6443 \
  --cidr 10.0.0.0/8

Expected recovery: 2-3 minutes
1. Node reconnects to API (30 seconds)
2. Pods restart (60-90 seconds)  
3. Service endpoints healthy (30 seconds)

⚠️ Hidden Risks

1. Same security group used on 15 other EC2 instances
   - Risk: If propagated, could affect other services
   - Check: aws ec2 describe-instances --filters "Name=instance.group-id,Values=sg-abc123def456"

2. No PodDisruptionBudget on payment service
   - Risk: All pods on single node = single point of failure
   - Recommendation: Add PDB with maxUnavailable: 1

3. No network policy validation in terraform pipeline
   - Risk: Similar mistakes in future
   - Recommendation: Add pre-apply check for K8s API accessibility

📊 Impact Summary

Services Affected:
- payment-service (100% down)
- notification-worker (degraded, queue backup)

External APIs Affected:
- Stripe (no calls, payment processing stopped)
- Twilio (degraded, SMS delayed)

Estimated Blast Radius: 53 resources
- 1 security group (direct)
- 1 EC2 instance (1st order)
- 1 K8s node (2nd order)
- 12 K8s pods (3rd order)
- 1 K8s service (4th order)
- 1 K8s ingress (5th order)
- 36 external API calls/min (stopped)

Business Impact:
- Transaction processing: STOPPED
- Revenue: ~$2,300/minute loss
- Customer notifications: DELAYED
- Support tickets: LIKELY SPIKE
```

**Time to resolution:**
- Traditional investigation: 2-3 hours
- With DNA Sequencing: 5 minutes

---

### Example 2: Pre-Deployment Analysis

**Scenario:** Planning to change VPC CIDR range

```bash
# Step 1: Take snapshot before
python infra_dna_sequencer.py --mode snapshot --label before_vpc_change

# Step 2: Make change in test environment or plan it
terraform plan -out=plan.tfplan

# Step 3: Take snapshot after planning
python infra_dna_sequencer.py --mode snapshot --label after_vpc_change

# Step 4: Analyze predicted impact
python infra_dna_sequencer.py --mode analyze \
  --before snapshots/before_vpc_change_*.json \
  --after snapshots/after_vpc_change_*.json
```

**Claude's Predictive Analysis:**

```
🧬 Planned Change
- aws_vpc.main
  * CIDR block: 10.0.0.0/16 → 10.1.0.0/16

🌊 Predicted Impact

Platform Level:
├─ All EC2 instances will get new IPs (10.1.x.x range)
├─ Existing connections will break during transition
├─ DNS entries need updating (53 Route53 records)
└─ VPC peering connections need reconfiguration

Kubernetes Impact:
├─ All pod IPs will change
├─ Service ClusterIPs remain stable (good!)
├─ But NodePort services expose node IPs (will change)
└─ External access via NodePort will break

Database Impact:
├─ RDS instances remain in old subnets initially
├─ Application connectivity WILL BREAK
└─ Need subnet migration before VPC change

External API Impact:
├─ Outbound IPs change
├─ Partners with IP allowlists will BLOCK you
└─ Affected: Stripe, payment processor, fraud detection API

🎯 Predicted Failures (High Confidence)

CRITICAL:
1. Database connectivity lost (apps can't reach RDS)
2. External API calls blocked (IP allowlist mismatch)
3. Inter-service communication disrupted

IMPORTANT:
4. DNS resolution lag (TTL-dependent)
5. Load balancer health checks may fail during transition

💡 Required Actions BEFORE Change

Pre-requisites:
1. Contact external partners, update IP allowlists
   - Stripe: Add 10.1.0.0/16 to allowlist
   - Fraud detection: Update firewall rules
   - Payment processor: Submit IP change request (3-5 day SLA!)

2. Plan database migration
   - Create new subnets in 10.1.0.0/16
   - Migrate RDS to new subnets first
   - Test connectivity before VPC change

3. Update DNS records with low TTL (300s) 24h before
   - Reduces propagation delay during change

4. Schedule maintenance window
   - Recommended: 2-hour window
   - Expect 15-20 minute downtime

⚠️ Risk Assessment

This is a HIGH-RISK change with cascading effects across:
- 127 AWS resources
- 43 Kubernetes services
- 8 external API integrations
- Estimated downtime: 15-20 minutes (best case)

RECOMMENDATION: 
- Test in staging environment first
- Consider phased migration instead of big-bang
- Have rollback plan ready (keep old subnets available)
```

---

### Example 3: Interactive Investigation

```bash
python infra_dna_sequencer.py --mode interactive \
  --before snapshots/before.json \
  --after snapshots/after.json
```

**Interactive Session:**

```
You: Which security group change is most critical?

Claude: The most critical is aws_security_group.app-sg where the ingress 
rule for port 6443 was modified from 10.0.0.0/8 to 10.1.0.0/16. This is 
critical because:

1. Port 6443 is the Kubernetes API server port
2. Blocking it prevents nodes from communicating with control plane
3. This causes cascading pod failures across the entire cluster
4. Impact: All services on affected nodes go down

The change affects 12 nodes, running 147 pods total.

You: How do I fix this quickly without reverting the entire security group?

Claude: Quick fix - add a specific ingress rule for the blocked IP range:

aws ec2 authorize-security-group-ingress \
  --group-id sg-abc123def456 \
  --protocol tcp \
  --port 6443 \
  --cidr 10.2.0.0/16 \
  --description "Temporary: Allow K8s nodes in 10.2.x.x range"

This adds the missing range without touching existing rules. After recovery:
1. Identify why nodes are in 10.2.x.x (seems like wrong subnet)
2. Properly migrate nodes to 10.1.x.x range
3. Remove temporary rule

You: What if I can't access AWS console right now?

Claude: Alternative fixes in order of preference:

1. Via kubectl (if you have access):
   # Cordon the affected node to prevent new pods
   kubectl cordon ip-10-0-1-50
   
   # Drain pods to healthy nodes
   kubectl drain ip-10-0-1-50 --ignore-daemonsets
   
   This moves traffic to healthy nodes while you fix the SG.

2. Via terraform (if you have the code):
   # Revert the security group change in code
   git revert abc123
   terraform apply
   
   Takes 3-5 minutes but is auditable.

3. Contact teammate with AWS access:
   Send them the exact command from my first response.
   
You: Could this have been prevented?

Claude: Yes, three prevention strategies:

1. Pre-apply validation in CI/CD:
   # Add to terraform pipeline
   python check_k8s_api_access.py --security-groups changed.json
   
   This would catch SG changes that block K8s API.

2. Canary deployment for infrastructure:
   # Test SG change on 1 node first
   - Apply to test node
   - Wait 5 minutes
   - Check pod health
   - If OK, apply to rest

3. Automated rollback:
   # Monitor node health after SG changes
   if node_not_ready_after_sg_change:
       auto_revert_security_group()
   
Would you like me to generate code for any of these?

You: Yes, show me the pre-apply validation script

Claude: Here's a pre-apply validation script:

[Claude generates complete Python script with logic to check if SG changes
would block K8s API access by comparing changed rules against known node IPs]
```

---

## CI/CD Integration Patterns

### Pattern 1: Terraform Pipeline with Analysis

**Complete GitLab CI Example:**

```yaml
stages:
  - validate
  - snapshot-pre
  - plan
  - approve
  - apply
  - snapshot-post
  - verify

variables:
  TF_DIR: ./terraform
  PYTHON_VERSION: "3.11"

.setup_dna: &setup_dna
  - pip install -r requirements.txt
  - export ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}

validate_terraform:
  stage: validate
  image: hashicorp/terraform:latest
  script:
    - cd ${TF_DIR}
    - terraform fmt -check
    - terraform validate
  only:
    - merge_requests
    - main

snapshot_before:
  stage: snapshot-pre
  image: python:${PYTHON_VERSION}
  before_script: *setup_dna
  script:
    - python automated_sequencer.py pre-deploy
  artifacts:
    paths:
      - /tmp/pre_deploy_snapshot.txt
      - snapshots/
    expire_in: 2 hours
  only:
    - main

terraform_plan:
  stage: plan
  image: hashicorp/terraform:latest
  script:
    - cd ${TF_DIR}
    - terraform init -backend-config="key=${CI_PROJECT_NAME}/${CI_COMMIT_REF_NAME}"
    - terraform plan -out=tfplan
    - terraform show -json tfplan > tfplan.json
  artifacts:
    paths:
      - ${TF_DIR}/tfplan
      - ${TF_DIR}/tfplan.json
    expire_in: 2 hours
  only:
    - main

# Manual approval gate
approve_deployment:
  stage: approve
  script:
    - echo "Review terraform plan before approving"
    - cat ${TF_DIR}/tfplan.json
  when: manual
  only:
    - main
  dependencies:
    - terraform_plan

terraform_apply:
  stage: apply
  image: hashicorp/terraform:latest
  script:
    - cd ${TF_DIR}
    - terraform init -backend-config="key=${CI_PROJECT_NAME}/${CI_COMMIT_REF_NAME}"
    - terraform apply -auto-approve tfplan
  dependencies:
    - terraform_plan
    - approve_deployment
  only:
    - main

snapshot_after:
  stage: snapshot-post
  image: python:${PYTHON_VERSION}
  before_script: *setup_dna
  script:
    - python automated_sequencer.py post-deploy ${CI_JOB_STATUS}
  artifacts:
    paths:
      - deployments/
    reports:
      dotenv: deployment.env
  when: always
  dependencies:
    - snapshot_before
    - terraform_apply
  only:
    - main

verify_deployment:
  stage: verify
  image: python:${PYTHON_VERSION}
  script:
    - |
      echo "=== DEPLOYMENT DNA ANALYSIS ==="
      find deployments -name "analysis.txt" -exec cat {} \;
      
      # Check for critical issues in analysis
      if grep -q "CRITICAL" deployments/*/analysis.txt; then
        echo "⚠️  Critical issues detected in deployment"
        exit 1
      fi
  when: always
  dependencies:
    - snapshot_after
  only:
    - main

# Notification
notify_team:
  stage: verify
  image: appropriate/curl:latest
  script:
    - |
      ANALYSIS=$(cat deployments/*/analysis.txt | head -c 1000)
      curl -X POST ${SLACK_WEBHOOK_URL} \
        -H 'Content-Type: application/json' \
        -d "{\"text\": \"Deployment Analysis:\n\`\`\`${ANALYSIS}\`\`\`\"}"
  when: always
  only:
    - main
```

---

### Pattern 2: Kubernetes Deployment with Analysis

**Example for kubectl-based deployments:**

```bash
#!/bin/bash
# deploy-with-dna.sh

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
python automated_sequencer.py pre-deploy

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
python automated_sequencer.py post-deploy "$DEPLOY_STATUS"

# Display analysis
echo ""
echo "=" * 60
if [ -d "deployments" ]; then
    cat deployments/*/analysis.txt
fi

# Exit with deployment status
if [ "$DEPLOY_STATUS" == "success" ]; then
    exit 0
else
    exit 1
fi
```

Usage:
```bash
./deploy-with-dna.sh manifests/payment-service.yaml production
```

---

### Pattern 3: Continuous Monitoring with Alerting

**Deploy as Kubernetes DaemonSet:**

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: infra-dna-monitor
  namespace: platform
spec:
  selector:
    matchLabels:
      app: infra-dna-monitor
  template:
    metadata:
      labels:
        app: infra-dna-monitor
    spec:
      serviceAccountName: infra-dna-sequencer
      containers:
      - name: monitor
        image: your-registry/infra-dna-sequencer:latest
        command:
        - python
        - automated_sequencer.py
        - monitor
        - "15"  # Snapshot every 15 minutes
        env:
        - name: ANTHROPIC_API_KEY
          valueFrom:
            secretKeyRef:
              name: anthropic-secret
              key: api-key
        - name: PROMETHEUS_URL
          value: "http://prometheus.monitoring:9090"
        - name: SLACK_WEBHOOK_URL
          valueFrom:
            secretKeyRef:
              name: slack-secret
              key: webhook-url
        volumeMounts:
        - name: snapshots
          mountPath: /app/snapshots
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "500m"
      volumes:
      - name: snapshots
        persistentVolumeClaim:
          claimName: snapshots-pvc
```

---

## Week-by-Week Implementation Plan

### Week 1: Core Functionality

**Day 1-2: Setup + Basic Snapshots**
- [x] Create project structure
- [x] Install dependencies (anthropic, boto3, kubernetes)
- [x] Configure `.env` with API keys
- [x] Test basic terraform state collection
- [x] Test basic K8s state collection
- [x] Verify snapshots contain useful data

**Day 3-4: LLM Integration**
- [x] Test Claude API connectivity
- [x] Build analysis prompt template
- [x] Test with sample snapshots (before/after)
- [x] Refine prompt based on output quality
- [x] Add error handling for API failures
- [x] Optimize for token usage

**Day 5: Testing & Validation**
- [x] Create test snapshots from real infrastructure
- [x] Make simple change (e.g., add security group rule)
- [x] Verify analysis finds the change
- [x] Test with actual incident scenario
- [x] Document example outputs

**Weekend:** Review and iterate on prompts

---

### Week 2: Automation + Production Readiness

**Day 1-2: Automated Monitoring**
- [ ] Build continuous monitoring script
- [ ] Integrate Prometheus alert checking
- [ ] Test incident detection workflow
- [ ] Configure Slack notifications
- [ ] Set up retention policy

**Day 3: CI/CD Integration**
- [ ] Create pre/post deployment hooks
- [ ] Test in GitLab/Jenkins pipeline
- [ ] Add terraform wrapper script
- [ ] Document integration patterns
- [ ] Create example pipelines

**Day 4: AWS Resource Discovery**
- [ ] Implement Resource Groups Tagging API integration
- [ ] Add IAM policy analyzer
- [ ] Test CloudTrail event analysis
- [ ] Verify comprehensive resource discovery

**Day 5: External Dependency Discovery**
- [ ] Implement env var parser
- [ ] Add package dependency scanner
- [ ] Test DNS query analysis (if available)
- [ ] Verify external API detection

**Weekend:** Polish, documentation, prepare demo

---

### Week 3: Team Rollout (Optional)

**Day 1: Documentation**
- [ ] Create internal wiki page
- [ ] Record demo video
- [ ] Write runbook for common scenarios
- [ ] Document troubleshooting steps

**Day 2: Training**
- [ ] Present to platform team
- [ ] Live demo on staging
- [ ] Q&A session
- [ ] Collect feedback

**Day 3-4: Pilot Deployment**
- [ ] Deploy to staging environment
- [ ] Monitor for 48 hours
- [ ] Address any issues
- [ ] Refine based on real usage

**Day 5: Production Deployment**
- [ ] Deploy continuous monitoring
- [ ] Integrate into terraform pipelines
- [ ] Set up dashboards/alerts
- [ ] Document success metrics

---

## Success Metrics

Track these KPIs to measure impact:

**Incident Response:**
- Mean Time To Resolution (MTTR)
  - Before: 2-4 hours
  - Target: 15-30 minutes
  
- Root Cause Identification Time
  - Before: 1-3 hours
  - Target: 5-10 minutes

**Preventive:**
- Issues caught pre-deployment
  - Target: 3-5 per month
  
- Deployment failures prevented
  - Target: 1-2 per month

**Operational:**
- Cost: ~$5-10/month (Claude API)
- Engineering time saved: 30-40 hours/month
- ROI: ~500x

---

**[End of Part 2 - Continue to Part 3 for Team Presentation Guide]**
