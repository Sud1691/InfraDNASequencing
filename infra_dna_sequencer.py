#!/usr/bin/env python3
"""
Infrastructure DNA Sequencer - Complete Implementation
Discovers ALL dependencies (AWS + External) and analyzes mutations
"""

import json
import boto3
import subprocess
from datetime import datetime, timedelta
from anthropic import Anthropic
import os
from pathlib import Path
import re
from urllib.parse import urlparse


class InfrastructureSnapshot:
    """Comprehensive snapshot collector"""
    
    def __init__(self):
        self.terraform_dir = os.getenv('TERRAFORM_DIR', './terraform')
        self.vpc_id = os.getenv('VPC_ID')
        self.repo_path = os.getenv('REPO_PATH', './')
        self.snapshots_dir = Path('snapshots')
        self.snapshots_dir.mkdir(exist_ok=True)
        
    def capture(self, label='current'):
        """Capture complete infrastructure state"""
        
        print(f"📸 Capturing infrastructure snapshot: {label}")
        
        snapshot = {
            'timestamp': datetime.utcnow().isoformat(),
            'label': label,
            'terraform_state': self.get_terraform_state(),
            'k8s_state': self.get_k8s_state(),
            'aws_resources': self.get_aws_snapshot(),
            'service_dependencies': self.discover_service_dependencies(),
            'external_dependencies': self.discover_external_dependencies(),
            'recent_changes': self.get_recent_changes()
        }
        
        # Save locally
        filename = self.snapshots_dir / f"{label}_{snapshot['timestamp'].replace(':', '-')}.json"
        
        with open(filename, 'w') as f:
            json.dump(snapshot, f, indent=2)
        
        print(f"✅ Snapshot saved: {filename}")
        
        return str(filename), snapshot
    
    def get_terraform_state(self):
        """Get terraform state"""
        print("  📋 Collecting Terraform state...")
        try:
            result = subprocess.run(
                ['terraform', 'show', '-json'],
                cwd=self.terraform_dir,
                capture_output=True,
                text=True,
                timeout=30
            )
            return json.loads(result.stdout) if result.returncode == 0 else {}
        except Exception as e:
            print(f"    ⚠️  Terraform state capture failed: {e}")
            return {}
    
    def get_k8s_state(self):
        """Get kubernetes state summary"""
        print("  ☸️  Collecting Kubernetes state...")
        try:
            k8s_state = {}
            
            # Deployments
            deployments = subprocess.run(
                ['kubectl', 'get', 'deployments', '-A', '-o', 'json'],
                capture_output=True,
                text=True,
                timeout=30
            )
            if deployments.returncode == 0:
                k8s_state['deployments'] = json.loads(deployments.stdout)
            
            # Services
            services = subprocess.run(
                ['kubectl', 'get', 'services', '-A', '-o', 'json'],
                capture_output=True,
                text=True,
                timeout=30
            )
            if services.returncode == 0:
                k8s_state['services'] = json.loads(services.stdout)
            
            # Problem pods only
            pods = subprocess.run(
                ['kubectl', 'get', 'pods', '-A', 
                 '--field-selector=status.phase!=Running,status.phase!=Succeeded', 
                 '-o', 'json'],
                capture_output=True,
                text=True,
                timeout=30
            )
            if pods.returncode == 0:
                k8s_state['problem_pods'] = json.loads(pods.stdout)
            
            # ConfigMaps (for dependency discovery)
            configmaps = subprocess.run(
                ['kubectl', 'get', 'configmaps', '-A', '-o', 'json'],
                capture_output=True,
                text=True,
                timeout=30
            )
            if configmaps.returncode == 0:
                k8s_state['configmaps'] = json.loads(configmaps.stdout)
            
            return k8s_state
            
        except Exception as e:
            print(f"    ⚠️  K8s state capture failed: {e}")
            return {}
    
    def get_aws_snapshot(self):
        """Get comprehensive AWS resources using Resource Groups Tagging API"""
        print("  ☁️  Collecting AWS resources...")
        try:
            tagging = boto3.client('resourcegroupstaggingapi')
            
            # Get ALL resources
            all_resources = []
            pagination_token = None
            
            while True:
                params = {'ResourcesPerPage': 100}
                if pagination_token:
                    params['PaginationToken'] = pagination_token
                
                response = tagging.get_resources(**params)
                all_resources.extend(response['ResourceTagMappingList'])
                
                pagination_token = response.get('PaginationToken')
                if not pagination_token:
                    break
            
            # Organize by service
            by_service = {}
            for resource in all_resources:
                arn = resource['ResourceARN']
                parts = arn.split(':')
                
                if len(parts) >= 6:
                    service = parts[2]
                    
                    if service not in by_service:
                        by_service[service] = []
                    
                    by_service[service].append({
                        'arn': arn,
                        'tags': {tag['Key']: tag['Value'] for tag in resource.get('Tags', [])}
                    })
            
            print(f"    Found {len(all_resources)} AWS resources across {len(by_service)} services")
            
            return by_service
            
        except Exception as e:
            print(f"    ⚠️  AWS snapshot failed: {e}")
            return {}
    
    def discover_service_dependencies(self):
        """Discover per-service dependencies from K8s ConfigMaps"""
        print("  🔗 Discovering service dependencies...")
        
        dependencies = {}
        
        try:
            from kubernetes import client, config
            config.load_kube_config()
            v1 = client.CoreV1Api()
            apps_v1 = client.AppsV1Api()
            
            # Get all deployments
            deployments = apps_v1.list_deployment_for_all_namespaces()
            
            for deployment in deployments.items:
                service_name = deployment.metadata.name
                namespace = deployment.metadata.namespace
                
                service_deps = {
                    'namespace': namespace,
                    'aws_resources': [],
                    'external_apis': [],
                    'k8s_services': [],
                    'databases': [],
                    'queues': [],
                    'caches': []
                }
                
                # Extract env vars from deployment
                containers = deployment.spec.template.spec.containers
                
                for container in containers:
                    if container.env:
                        for env in container.env:
                            # Parse env var for dependencies
                            self._parse_env_var_for_deps(env, service_deps)
                
                dependencies[f"{namespace}/{service_name}"] = service_deps
            
            print(f"    Discovered dependencies for {len(dependencies)} services")
            
        except Exception as e:
            print(f"    ⚠️  Service dependency discovery failed: {e}")
        
        return dependencies
    
    def _parse_env_var_for_deps(self, env, service_deps):
        """Parse single env var and extract dependency info"""
        
        name = env.name
        value = env.value if env.value else ''
        
        # Database connections
        if any(db in name.upper() for db in ['DATABASE', 'DB_', 'POSTGRES', 'MYSQL', 'RDS']):
            if value:
                service_deps['databases'].append({
                    'env_var': name,
                    'connection': value,
                    'resource': self._extract_resource_name(value)
                })
        
        # Queues
        if any(q in name.upper() for q in ['QUEUE', 'SQS', 'SNS']):
            if value:
                service_deps['queues'].append({
                    'env_var': name,
                    'url': value,
                    'resource': value.split('/')[-1] if '/' in value else value
                })
        
        # Caches
        if any(c in name.upper() for c in ['REDIS', 'CACHE', 'ELASTICACHE']):
            if value:
                service_deps['caches'].append({
                    'env_var': name,
                    'endpoint': value,
                    'resource': value.split('.')[0] if '.' in value else value
                })
        
        # External APIs
        if value.startswith('http') and 'amazonaws.com' not in value:
            provider = self._extract_provider_from_url(value)
            service_deps['external_apis'].append({
                'env_var': name,
                'url': value,
                'provider': provider
            })
    
    def _extract_resource_name(self, connection_string):
        """Extract AWS resource name from connection string"""
        
        if 'rds.amazonaws.com' in connection_string:
            # postgresql://payment-db.abc.rds.amazonaws.com:5432
            host = connection_string.split('@')[-1].split(':')[0]
            return host.split('.')[0]
        
        return None
    
    def _extract_provider_from_url(self, url):
        """Extract provider name from URL"""
        
        parsed = urlparse(url)
        hostname = parsed.hostname or ''
        hostname = hostname.replace('api.', '').replace('www.', '')
        
        parts = hostname.split('.')
        if len(parts) >= 2:
            return parts[-2]  # e.g., 'stripe' from 'api.stripe.com'
        
        return hostname
    
    def discover_external_dependencies(self):
        """Discover all external/third-party dependencies"""
        print("  🌐 Discovering external dependencies...")
        
        external_deps = {
            'payment_providers': [],
            'communication': [],
            'auth_providers': [],
            'observability': [],
            'collaboration': [],
            'analytics': [],
            'partner_apis': []
        }
        
        try:
            # Method 1: Scan code for external API libraries
            external_deps = self._scan_package_dependencies(external_deps)
            
            # Method 2: Scan environment variables (already done in service_dependencies)
            # Will be cross-referenced
            
            # Method 3: DNS query logs (if available)
            if self.vpc_id:
                dns_deps = self._analyze_dns_queries()
                external_deps = self._merge_dns_deps(external_deps, dns_deps)
            
            print(f"    Discovered {sum(len(v) for v in external_deps.values())} external dependencies")
            
        except Exception as e:
            print(f"    ⚠️  External dependency discovery failed: {e}")
        
        return external_deps
    
    def _scan_package_dependencies(self, external_deps):
        """Scan package.json, requirements.txt for external libraries"""
        
        # Known external service libraries
        npm_libs = {
            'stripe': ('Stripe', 'payment_providers'),
            '@stripe/stripe-js': ('Stripe', 'payment_providers'),
            'twilio': ('Twilio', 'communication'),
            '@sendgrid/mail': ('SendGrid', 'communication'),
            'auth0': ('Auth0', 'auth_providers'),
            '@auth0/auth0-react': ('Auth0', 'auth_providers'),
            '@slack/web-api': ('Slack', 'collaboration'),
            'dd-trace': ('Datadog', 'observability'),
            '@sentry/node': ('Sentry', 'observability'),
            'pagerduty': ('PagerDuty', 'collaboration')
        }
        
        pip_libs = {
            'stripe': ('Stripe', 'payment_providers'),
            'twilio': ('Twilio', 'communication'),
            'sendgrid': ('SendGrid', 'communication'),
            'auth0-python': ('Auth0', 'auth_providers'),
            'slack-sdk': ('Slack', 'collaboration'),
            'ddtrace': ('Datadog', 'observability'),
            'sentry-sdk': ('Sentry', 'observability'),
            'pdpyras': ('PagerDuty', 'collaboration')
        }
        
        # Scan package.json
        package_json = Path(self.repo_path) / 'package.json'
        if package_json.exists():
            try:
                with open(package_json) as f:
                    data = json.load(f)
                    deps = {**data.get('dependencies', {}), **data.get('devDependencies', {})}
                    
                    for dep, version in deps.items():
                        if dep in npm_libs:
                            provider, category = npm_libs[dep]
                            external_deps[category].append({
                                'provider': provider,
                                'library': dep,
                                'version': version,
                                'detection_method': 'package.json'
                            })
            except Exception:
                pass
        
        # Scan requirements.txt
        requirements = Path(self.repo_path) / 'requirements.txt'
        if requirements.exists():
            try:
                with open(requirements) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            package = line.split('==')[0].split('>=')[0].split('~=')[0].strip()
                            
                            if package in pip_libs:
                                provider, category = pip_libs[package]
                                external_deps[category].append({
                                    'provider': provider,
                                    'library': package,
                                    'detection_method': 'requirements.txt'
                                })
            except Exception:
                pass
        
        return external_deps
    
    def _analyze_dns_queries(self):
        """Analyze DNS queries from Route 53 Resolver logs"""
        
        # This would query CloudWatch Logs for Route 53 Resolver Query Logs
        # Simplified version - returns empty for now
        # Full implementation would query logs and classify domains
        
        return []
    
    def _merge_dns_deps(self, external_deps, dns_deps):
        """Merge DNS-discovered dependencies"""
        
        # Would merge DNS query data with existing external_deps
        return external_deps
    
    def get_recent_changes(self):
        """Get recent git commits, terraform applies, deployments"""
        
        changes = []
        
        # Git commits (last 10)
        try:
            git_log = subprocess.run(
                ['git', 'log', '--oneline', '-10', '--all'],
                cwd=self.terraform_dir,
                capture_output=True,
                text=True,
                timeout=10
            )
            if git_log.returncode == 0:
                changes.append({
                    'source': 'git',
                    'commits': git_log.stdout.strip().split('\n')
                })
        except Exception:
            pass
        
        # Argo CD apps
        try:
            argocd = subprocess.run(
                ['argocd', 'app', 'list', '-o', 'json'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if argocd.returncode == 0:
                changes.append({
                    'source': 'argocd',
                    'apps': json.loads(argocd.stdout)
                })
        except Exception:
            pass
        
        return changes


class DNASequencer:
    """LLM-powered mutation analyzer"""
    
    def __init__(self, api_key=None):
        self.client = Anthropic(api_key=api_key or os.getenv('ANTHROPIC_API_KEY'))
        
    def analyze_mutation(self, snapshot_before, snapshot_after, incident_description=None):
        """Use Claude to analyze infrastructure mutations"""
        
        prompt = self._build_analysis_prompt(
            snapshot_before, 
            snapshot_after, 
            incident_description
        )
        
        print("🔬 Analyzing infrastructure mutations with Claude...\n")
        
        # Call Claude
        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )
        
        analysis = response.content[0].text
        
        return analysis
    
    def _build_analysis_prompt(self, before, after, incident_desc):
        """Build comprehensive analysis prompt for Claude"""
        
        before_summary = self._summarize_snapshot(before)
        after_summary = self._summarize_snapshot(after)
        
        prompt = f"""You are an expert SRE analyzing infrastructure mutations that may have caused an incident.

## Context
{f"Incident: {incident_desc}" if incident_desc else "Analyzing infrastructure changes between two time points"}

Time Before: {before['timestamp']}
Time After: {after['timestamp']}

## Infrastructure State BEFORE

### Terraform Resources
{json.dumps(before_summary['terraform'], indent=2)[:5000]}

### Kubernetes State
{json.dumps(before_summary['k8s'], indent=2)[:3000]}

### AWS Resources
{json.dumps(before_summary['aws'], indent=2)[:3000]}

### Service Dependencies
{json.dumps(before_summary['service_deps'], indent=2)[:2000]}

### External Dependencies
{json.dumps(before_summary['external_deps'], indent=2)[:2000]}

---

## Infrastructure State AFTER

### Terraform Resources
{json.dumps(after_summary['terraform'], indent=2)[:5000]}

### Kubernetes State
{json.dumps(after_summary['k8s'], indent=2)[:3000]}

### AWS Resources
{json.dumps(after_summary['aws'], indent=2)[:3000]}

### Service Dependencies
{json.dumps(after_summary['service_deps'], indent=2)[:2000]}

### External Dependencies
{json.dumps(after_summary['external_deps'], indent=2)[:2000]}

---

## Your Task: Infrastructure DNA Sequencing

Analyze these snapshots and identify:

1. **Direct Mutations**: Resources that changed between snapshots
2. **Cascade Effects**: How did direct changes affect downstream resources?
3. **Hidden Dependencies**: What unexpected connections exist?
4. **Nth-Order Effects**: Track changes through 2-6 degrees of separation
5. **External API Impact**: Which third-party services are affected?
6. **Root Cause Hypothesis**: What likely caused the incident?

Think like a detective. Look for:
- Security group changes that blocked traffic
- Auto-scaling changes that affected target groups
- K8s deployments that triggered cascading pod failures
- Resource deletions that broke dependencies
- Configuration changes with unexpected side effects
- Network changes blocking external APIs (Stripe, Twilio, etc.)

## Output Format

### 🧬 Direct Mutations
[List resources that directly changed with specific details]

### 🌊 Cascade Analysis
Trace downstream effects through multiple degrees:
- **1st order**: Immediate dependencies affected
- **2nd order**: Dependencies of dependencies
- **3rd+ order**: Further propagation

For each cascade, show:
- What changed
- Why it changed (connection to direct mutation)
- Impact severity

### 🌐 External API Impact
[Which external services (Stripe, Twilio, Auth0, etc.) are affected and why]

### 🎯 Root Cause Hypothesis
[Most likely cause with confidence level 0-100%]

Include reasoning:
- Why this is the root cause
- What evidence supports this
- Alternative explanations considered

### 🔗 Dependency Chain
[Show exact path from change → incident]
Example: "ASG change → Launch template → Security group → Node isolation → Pod failure → Service down → Stripe API calls fail"

### 💡 Recommendations
[Specific fixes to try, ordered by likelihood of success]

Include exact commands where possible:
```bash
# Example fix
aws ec2 authorize-security-group-ingress --group-id sg-abc123 ...
```

### ⚠️ Hidden Risks
[Other mutations that didn't cause this incident but could cause future problems]

### 📊 Impact Summary
- Services affected: [list]
- External APIs affected: [list]
- Estimated blast radius: [number of resources]
- Business impact: [if determinable]

Be specific. Use actual resource names, ARNs, IDs from the snapshots.
"""
        
        return prompt
    
    def _summarize_snapshot(self, snapshot):
        """Compress snapshot to essential info for token efficiency"""
        
        summary = {
            'terraform': {},
            'k8s': {},
            'aws': {},
            'service_deps': {},
            'external_deps': {}
        }
        
        # Terraform summary
        tf_state = snapshot.get('terraform_state', {})
        if 'values' in tf_state and 'root_module' in tf_state['values']:
            resources = tf_state['values']['root_module'].get('resources', [])
            
            for resource in resources[:50]:  # Limit for tokens
                res_type = resource.get('type', 'unknown')
                res_name = resource.get('name', 'unknown')
                
                if res_type not in summary['terraform']:
                    summary['terraform'][res_type] = []
                
                summary['terraform'][res_type].append({
                    'name': res_name,
                    'address': resource.get('address'),
                    'key_attributes': self._extract_key_attributes(resource)
                })
        
        # K8s summary
        k8s = snapshot.get('k8s_state', {})
        
        if 'deployments' in k8s and 'items' in k8s['deployments']:
            summary['k8s']['deployments'] = [
                {
                    'name': d['metadata']['name'],
                    'namespace': d['metadata']['namespace'],
                    'replicas': d['spec'].get('replicas'),
                    'available': d['status'].get('availableReplicas', 0)
                }
                for d in k8s['deployments']['items'][:20]
            ]
        
        if 'problem_pods' in k8s and 'items' in k8s['problem_pods']:
            summary['k8s']['problem_pods'] = [
                {
                    'name': p['metadata']['name'],
                    'namespace': p['metadata']['namespace'],
                    'phase': p['status'].get('phase'),
                    'reason': p['status'].get('reason')
                }
                for p in k8s['problem_pods']['items'][:10]
            ]
        
        # AWS summary (by service type)
        aws = snapshot.get('aws_resources', {})
        for service, resources in list(aws.items())[:15]:  # Limit services
            summary['aws'][service] = len(resources)  # Just count for now
        
        # Service dependencies summary
        service_deps = snapshot.get('service_dependencies', {})
        for svc, deps in list(service_deps.items())[:10]:
            summary['service_deps'][svc] = {
                'databases': len(deps.get('databases', [])),
                'queues': len(deps.get('queues', [])),
                'external_apis': [api['provider'] for api in deps.get('external_apis', [])]
            }
        
        # External dependencies summary
        external = snapshot.get('external_dependencies', {})
        for category, deps in external.items():
            if deps:
                summary['external_deps'][category] = [
                    d.get('provider', 'unknown') for d in deps
                ]
        
        return summary
    
    def _extract_key_attributes(self, resource):
        """Extract important attributes from terraform resource"""
        
        values = resource.get('values', {})
        res_type = resource.get('type', '')
        
        if 'aws_security_group' in res_type:
            return {
                'vpc_id': values.get('vpc_id'),
                'ingress': len(values.get('ingress', [])),
                'egress': len(values.get('egress', []))
            }
        elif 'aws_autoscaling_group' in res_type:
            return {
                'min': values.get('min_size'),
                'max': values.get('max_size'),
                'desired': values.get('desired_capacity')
            }
        else:
            return {k: v for k, v in values.items() if k in ['name', 'id', 'arn']}
    
    def interactive_investigation(self, snapshot_before, snapshot_after):
        """Interactive Q&A session about mutations"""
        
        print("🔬 Infrastructure DNA Sequencing - Interactive Mode")
        print("=" * 60)
        print("\nInitial analysis running...\n")
        
        # Initial analysis
        initial_analysis = self.analyze_mutation(snapshot_before, snapshot_after)
        print(initial_analysis)
        print("\n" + "=" * 60)
        
        # Interactive loop
        conversation_history = [
            {
                "role": "user",
                "content": self._build_analysis_prompt(snapshot_before, snapshot_after, None)
            },
            {
                "role": "assistant",
                "content": initial_analysis
            }
        ]
        
        print("\n💬 Ask follow-up questions (type 'exit' to quit):\n")
        
        while True:
            question = input("You: ").strip()
            
            if question.lower() in ['exit', 'quit', 'q']:
                break
            
            if not question:
                continue
            
            conversation_history.append({
                "role": "user",
                "content": question
            })
            
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                messages=conversation_history
            )
            
            answer = response.content[0].text
            
            conversation_history.append({
                "role": "assistant",
                "content": answer
            })
            
            print(f"\nClaude: {answer}\n")


def main():
    """Main CLI interface"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Infrastructure DNA Sequencer')
    parser.add_argument('--mode', choices=['snapshot', 'analyze', 'interactive'], 
                       required=True,
                       help='Operation mode')
    parser.add_argument('--label', help='Label for snapshot')
    parser.add_argument('--before', help='Path to before snapshot')
    parser.add_argument('--after', help='Path to after snapshot')
    parser.add_argument('--incident', help='Incident description')
    
    args = parser.parse_args()
    
    if args.mode == 'snapshot':
        collector = InfrastructureSnapshot()
        filename, _ = collector.capture(label=args.label or 'manual')
        print(f"\n✅ Snapshot complete: {filename}")
        
    elif args.mode == 'analyze':
        if not args.before or not args.after:
            print("❌ Error: --before and --after required for analysis")
            return
        
        with open(args.before) as f:
            before = json.load(f)
        
        with open(args.after) as f:
            after = json.load(f)
        
        sequencer = DNASequencer()
        analysis = sequencer.analyze_mutation(before, after, args.incident)
        
        print("\n" + "=" * 60)
        print("INFRASTRUCTURE MUTATION ANALYSIS")
        print("=" * 60)
        print(analysis)
        
    elif args.mode == 'interactive':
        if not args.before or not args.after:
            print("❌ Error: --before and --after required for interactive mode")
            return
        
        with open(args.before) as f:
            before = json.load(f)
        
        with open(args.after) as f:
            after = json.load(f)
        
        sequencer = DNASequencer()
        sequencer.interactive_investigation(before, after)


if __name__ == '__main__':
    main()
