# Setup Guide

Step-by-step instructions for installing, configuring, and deploying Infrastructure DNA Sequencing.

## Prerequisites

- **Python 3.9+**
- **Anthropic API key** - Get one at https://console.anthropic.com
- **AWS credentials** (optional) - IAM user or role with read access
- **kubectl** (optional) - Configured to connect to your cluster
- **Terraform** (optional) - Installed and initialized in your project

The tool works with any combination of these sources. If a source is unavailable, that collector is skipped and the rest proceed normally.

## 1. Installation

```bash
# Clone the repository
git clone <your-repo-url>
cd infra-dna-sequencer

# Create a virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Dependencies

| Package | Purpose |
|---------|---------|
| `anthropic` | Claude API client for mutation analysis |
| `boto3` | AWS resource discovery |
| `kubernetes` | Kubernetes API client for service dependency discovery |
| `python-dotenv` | Environment variable loading from `.env` |
| `requests` | Optional -- needed for Prometheus incident detection and Slack notifications |

Install `requests` separately if you plan to use continuous monitoring with Prometheus or Slack alerts:

```bash
pip install requests
```

## 2. Configuration

Copy the example environment file, fill in your values, and export them into your shell:

```bash
cp .env.example .env
# Edit .env with your values, then:
export $(grep -v '^#' .env | xargs)
```

**Note:** The code reads environment variables via `os.getenv()`. The `.env` file is not auto-loaded at runtime, so variables must be exported in your shell (or loaded via your CI/CD system, systemd `EnvironmentFile`, etc.).

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes | - | Your Anthropic API key |
| `TERRAFORM_DIR` | No | `./terraform` | Path to your Terraform project directory |
| `AWS_ACCESS_KEY_ID` | No | - | AWS access key (or use IAM roles / `~/.aws/credentials`) |
| `AWS_SECRET_ACCESS_KEY` | No | - | AWS secret key |
| `AWS_DEFAULT_REGION` | No | `us-east-1` | AWS region to query |
| `VPC_ID` | No | - | VPC ID for DNS-based dependency discovery |
| `REPO_PATH` | No | `./` | Path to application code for package dependency scanning |
| `PROMETHEUS_URL` | No | `http://prometheus:9090` | Prometheus endpoint for incident detection |
| `SLACK_WEBHOOK_URL` | No | - | Slack incoming webhook for alert notifications |
| `KUBECONFIG` | No | `~/.kube/config` | Path to Kubernetes config |

## 3. Verify Access

Test each infrastructure source to confirm connectivity.

### Anthropic API

```bash
python3 -c "from anthropic import Anthropic; print(Anthropic().messages.create(model='claude-sonnet-4-20250514', max_tokens=10, messages=[{'role':'user','content':'hi'}]).content[0].text)"
```

### AWS

```bash
aws sts get-caller-identity
```

Required IAM permissions:
- `resourcegroupstaggingapi:GetResources` (for resource discovery)
- `ec2:Describe*`, `rds:Describe*`, `elasticloadbalancing:Describe*` (for detailed state, if extending)

### Kubernetes

```bash
kubectl get nodes
kubectl auth can-i get pods --all-namespaces
```

### Terraform

```bash
cd $TERRAFORM_DIR
terraform show -json | head -c 200
```

## 4. Take Your First Snapshot

```bash
python infra_dna_sequencer.py --mode snapshot --label test
```

Expected output:

```
Capturing infrastructure snapshot: test
  Collecting Terraform state...
  Collecting Kubernetes state...
  Collecting AWS resources...
  Discovering service dependencies...
  Discovering external dependencies...
Snapshot saved: snapshots/test_2026-03-17T14-30-00.json
```

Warnings for unavailable sources (e.g., "Terraform state capture failed") are normal if you haven't configured that source.

Inspect the snapshot:

```bash
python -m json.tool snapshots/test_*.json | head -50
```

## 5. Run an Analysis

To test the full pipeline, take two snapshots around a change:

```bash
# Before
python infra_dna_sequencer.py --mode snapshot --label before

# Make a change (terraform apply, kubectl edit, etc.)

# After
python infra_dna_sequencer.py --mode snapshot --label after

# Analyze
python infra_dna_sequencer.py --mode analyze \
  --before snapshots/before_*.json \
  --after snapshots/after_*.json \
  --incident "describe what happened"
```

## 6. Deployment Wrapper Scripts

### Terraform

The `terraform-with-dna.sh` script wraps any Terraform command with automatic before/after snapshots:

```bash
chmod +x terraform-with-dna.sh

# Use instead of bare terraform commands
./terraform-with-dna.sh plan
./terraform-with-dna.sh apply -auto-approve
```

### Kubernetes

The `deploy-with-dna.sh` script wraps `kubectl apply`:

```bash
chmod +x deploy-with-dna.sh

# Usage: ./deploy-with-dna.sh <manifest> [namespace]
./deploy-with-dna.sh manifests/app.yaml production
```

## 7. Continuous Monitoring

### Local / VM

Run the automated sequencer as a long-running process:

```bash
# Snapshot every 15 minutes, auto-analyze on Prometheus alerts
python automated_sequencer.py monitor 15
```

For production use, run as a systemd service:

```ini
# /etc/systemd/system/infra-dna.service
[Unit]
Description=Infrastructure DNA Sequencer
After=network.target

[Service]
Type=simple
User=platform
WorkingDirectory=/opt/infra-dna-sequencer
ExecStart=/opt/infra-dna-sequencer/.venv/bin/python automated_sequencer.py monitor 15
Restart=always
EnvironmentFile=/opt/infra-dna-sequencer/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now infra-dna
```

### Kubernetes CronJob

Deploy the included CronJob manifest to run monitoring inside your cluster:

```bash
# Create secrets first
kubectl create namespace platform

kubectl create secret generic anthropic-secret \
  -n platform \
  --from-literal=api-key=$ANTHROPIC_API_KEY

kubectl create secret generic slack-secret \
  -n platform \
  --from-literal=webhook-url=$SLACK_WEBHOOK_URL

# Deploy
kubectl apply -f k8s-monitoring-cronjob.yaml
```

This creates:
- A `ServiceAccount` with read-only cluster access
- A `CronJob` running every 15 minutes
- A `PersistentVolumeClaim` for snapshot storage

## 8. CI/CD Integration

### Jenkins

The included `Jenkinsfile` provides a full pipeline with DNA sequencing. It expects an `anthropic-api-key` credential in Jenkins. The analysis is archived as a build artifact.

Pipeline stages:
1. Install Python dependencies
2. Pre-deployment snapshot
3. Terraform plan
4. Manual approval gate
5. Terraform apply
6. Post-deployment analysis (archived as artifact)

### Other CI/CD Systems

For GitHub Actions, GitLab CI, or other systems, use the wrapper scripts in your pipeline steps:

```yaml
# Example: generic CI steps
- run: pip install -r requirements.txt
- run: python automated_sequencer.py pre-deploy
- run: terraform apply -auto-approve
- run: python automated_sequencer.py post-deploy success
```

Or use `./terraform-with-dna.sh apply -auto-approve` which handles the full before/after cycle automatically.

## 9. Snapshot Retention

The automated sequencer manages snapshot retention automatically:

| Age | Retention |
|-----|-----------|
| < 24 hours | Keep all (every snapshot) |
| 1-30 days | Keep one per day |
| 30-90 days | Keep one per week |
| > 90 days | Deleted |

Storage estimate: ~500 MB/month at 15-minute intervals. ~6 GB for one year of retention.

## 10. Slack Notifications

When an incident is detected during continuous monitoring, the tool sends a summary to Slack.

1. Create an [Incoming Webhook](https://api.slack.com/messaging/webhooks) in your Slack workspace
2. Set `SLACK_WEBHOOK_URL` in your `.env`

The notification includes the incident name, severity, and the first 500 characters of the analysis. Full reports are saved to the `incidents/` directory.

## Troubleshooting

### "Terraform state is empty"

```bash
# Verify TERRAFORM_DIR points to an initialized Terraform project
ls $TERRAFORM_DIR/.terraform

# Test manually
cd $TERRAFORM_DIR && terraform show -json
```

### "K8s state capture failed"

```bash
# Check kubeconfig
echo $KUBECONFIG
kubectl cluster-info

# Check permissions
kubectl auth can-i list pods --all-namespaces
kubectl auth can-i list deployments --all-namespaces
```

### "AWS snapshot failed"

```bash
# Verify credentials
aws sts get-caller-identity

# Check the required permission
aws resourcegroupstaggingapi get-resources --resources-per-page 1
```

### "Claude API errors"

- Verify `ANTHROPIC_API_KEY` is set and valid
- Check rate limits (the tool uses a single request per analysis)
- If snapshots are too large, reduce resource limits in `infra_dna_sequencer.py` (search for `[:50]`, `[:20]`, etc.)

### Snapshots too large

Reduce the number of resources captured by adjusting limits in `infra_dna_sequencer.py`:

```python
# Line ~614: Terraform resources
for resource in resources[:30]:  # reduce from 50

# Line ~638: K8s deployments
for d in k8s['deployments']['items'][:10]:  # reduce from 20
```

Or filter AWS resources by tag to include only critical ones.

## Security Notes

- **Secrets**: Never commit `.env` to version control. It is already in `.gitignore`.
- **Snapshots**: May contain resource ARNs, endpoint URLs, and configuration details. Store on encrypted volumes and restrict access.
- **API keys**: Use a secrets manager (AWS Secrets Manager, HashiCorp Vault) in production rather than environment files.
- **Snapshot data sent to Claude**: Infrastructure metadata (resource types, names, counts, tags) is sent to the Anthropic API for analysis. Review your organization's data policies. Sensitive values in env vars are not automatically masked -- extend `_parse_env_var_for_deps` if needed.
