# Infrastructure DNA Sequencing

LLM-powered infrastructure mutation analysis that discovers ALL dependencies (AWS, Kubernetes, external APIs) and traces cascade effects through 2-6 degrees of separation that humans miss.

## The Problem

When infrastructure breaks, you know **what** changed but miss **how** it cascaded:

```
You changed: aws_security_group.app-sg (added one ingress rule)

Traditional view:
  Security group updated

DNA Sequencing view:
  aws_security_group.app-sg (mutation)
    -> aws_instance.k8s-node-3 (network connectivity)
      -> kubernetes_pod.payment-xyz (application health)
        -> kubernetes_service.payment (service availability)
          -> Stripe API calls (external dependency)
            -> Revenue (business impact)
```

Traditional tools show direct changes. DNA Sequencing traces mutations through the full dependency chain across Terraform resources, Kubernetes objects, AWS runtime state, and external APIs like Stripe, Twilio, and Auth0.

## How It Works

1. **Snapshot** infrastructure state (Terraform, K8s, AWS, external deps) at a point in time
2. **Compare** two snapshots (before/after a change or incident)
3. **Analyze** mutations using Claude to trace cascade effects, identify root cause, and recommend fixes

```
Snapshot Collection          Infrastructure Genome          Claude Analysis          Output
+-----------------+         +------------------+          +----------------+       +--------+
| Terraform State |         |                  |          |                |       | Report |
| Kubernetes API  |  --->   | Complete state   |  --->    | Compare genomes|  -->  | Root   |
| AWS Resources   |         | at point in time |          | Find mutations |       | cause  |
| External APIs   |         |                  |          | Trace cascades |       | Fixes  |
+-----------------+         +------------------+          +----------------+       +--------+
```

## Quick Start

```bash
# Install
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY

# Snapshot before change
python infra_dna_sequencer.py --mode snapshot --label before_change

# Make your infrastructure change (terraform apply, kubectl edit, etc.)

# Snapshot after change
python infra_dna_sequencer.py --mode snapshot --label after_change

# Analyze
python infra_dna_sequencer.py --mode analyze \
  --before snapshots/before_change_*.json \
  --after snapshots/after_change_*.json \
  --incident "API gateway returning 503 errors"
```

See [SETUP.md](SETUP.md) for detailed installation and configuration instructions.

## Example Output

```
Direct Mutations
- aws_security_group.app-sg: Ingress port 6443 cidr changed

Cascade Analysis
1st order: aws_instance.k8s-node-3 blocked from K8s API
2nd order: kubernetes_node.ip-10-0-1-50 NotReady
3rd order: kubernetes_pod.payment-xyz CrashLoopBackOff
4th order: kubernetes_service.payment 0 healthy endpoints
5th order: Stripe API calls failing (payment-service down)

Root Cause (95% confidence)
Security group blocked K8s API access -> cascading failures

Fix
aws ec2 authorize-security-group-ingress --group-id sg-abc123 ...
```

## Usage Modes

### Manual Analysis

Compare two snapshots with an optional incident description:

```bash
python infra_dna_sequencer.py --mode analyze \
  --before snapshots/before.json \
  --after snapshots/after.json \
  --incident "Payment service returning 503"
```

### Interactive Investigation

Start a conversational session where you can ask follow-up questions about the mutations:

```bash
python infra_dna_sequencer.py --mode interactive \
  --before snapshots/before.json \
  --after snapshots/after.json
```

### Continuous Monitoring

Run as a background service that takes periodic snapshots and auto-analyzes when Prometheus alerts fire:

```bash
python automated_sequencer.py monitor 15  # snapshot every 15 minutes
```

### Deployment Hooks

Wrap Terraform or Kubernetes deployments to automatically capture before/after snapshots:

```bash
# Terraform
./terraform-with-dna.sh apply -auto-approve

# Kubernetes
./deploy-with-dna.sh manifests/deployment.yaml production
```

### Snapshot Management

```bash
# List recent snapshots with health status
python automated_sequencer.py list-snapshots

# Find last known healthy snapshot
python automated_sequencer.py find-last-good
```

## What Gets Captured

Each snapshot collects:

| Source | Data |
|--------|------|
| **Terraform** | Full state (all managed resources) |
| **Kubernetes** | Deployments, services, problem pods, configmaps |
| **AWS** | All tagged resources via Resource Groups Tagging API |
| **Service Deps** | Per-deployment database, queue, cache, and API dependencies (extracted from env vars) |
| **External APIs** | Third-party services detected from package files (Stripe, Twilio, Auth0, Datadog, etc.) and DNS queries |
| **Recent Changes** | Git commits, Argo CD app state |

## CI/CD Integration

Pre-built integrations are included for:

- **GitHub Actions** - `.github/workflows/terraform-deploy.yml`
- **GitLab CI** - `.gitlab-ci.yml`
- **Jenkins** - `Jenkinsfile`

Each pipeline captures a snapshot before deployment, runs the deployment, captures a snapshot after, and produces a mutation analysis report. See [SETUP.md](SETUP.md) for configuration details.

## Project Structure

```
infra-dna-sequencer/
  infra_dna_sequencer.py       # Core snapshot collector + LLM analyzer
  automated_sequencer.py       # Continuous monitoring, deployment hooks, snapshot management
  terraform-with-dna.sh        # Terraform wrapper script
  deploy-with-dna.sh           # Kubernetes deployment wrapper
  k8s-monitoring-cronjob.yaml  # K8s CronJob for continuous monitoring
  requirements.txt             # Python dependencies
  .env.example                 # Environment variable template
  .github/workflows/           # GitHub Actions workflow
  .gitlab-ci.yml               # GitLab CI pipeline
  Jenkinsfile                  # Jenkins pipeline
  snapshots/                   # Snapshot storage (gitignored)
  incidents/                   # Incident analysis reports (gitignored)
  deployments/                 # Deployment analysis reports (gitignored)
```

## Requirements

- Python 3.9+
- Anthropic API key
- AWS credentials (for AWS resource discovery)
- kubectl configured (for Kubernetes state collection)
- Terraform installed (for Terraform state collection)

All infrastructure sources are optional -- the tool gracefully degrades if any source is unavailable.

## Cost

Claude API usage is minimal. Each analysis uses ~15K input tokens and ~2K output tokens, costing roughly $0.09 per analysis. Continuous monitoring with 15-minute snapshots and 10 incidents/month costs approximately $2/month.

## License

MIT
