#!/usr/bin/env python3
"""
Automated Snapshot Scheduler
Runs continuously, takes snapshots before/after key events
"""

import time
import json
import subprocess
from datetime import datetime
from pathlib import Path
from infra_dna_sequencer import InfrastructureSnapshot, DNASequencer
import os


class AutomatedSequencer:
    """Runs in background, auto-captures snapshots and analyzes incidents"""
    
    def __init__(self):
        self.collector = InfrastructureSnapshot()
        self.sequencer = DNASequencer()
        self.snapshots_dir = Path('snapshots')
        self.last_snapshot = None
        self.retention_hours = {
            'hourly': 24,    # Keep hourly for 24 hours
            'daily': 30,     # Keep daily for 30 days
            'weekly': 12     # Keep weekly for 12 weeks
        }
        
    def run_continuous_monitoring(self, interval_minutes=15):
        """Take snapshots every N minutes"""
        
        print(f"🔄 Starting continuous monitoring (snapshot every {interval_minutes} min)")
        print(f"📦 Retention: {self.retention_hours}")
        
        while True:
            try:
                # Take snapshot
                label = f"auto_{datetime.utcnow().strftime('%Y%m%d_%H%M')}"
                filename, snapshot = self.collector.capture(label)
                
                print(f"📸 Snapshot: {filename}")
                
                # Apply retention policy
                self.apply_retention_policy()
                
                # Check for incidents (Prometheus alerts, PagerDuty, etc.)
                incidents = self.check_for_incidents()
                
                if incidents and self.last_snapshot:
                    print(f"🚨 Incident detected: {incidents[0]['name']}")
                    print(f"   Running DNA analysis...")
                    
                    # Analyze
                    analysis = self.sequencer.analyze_mutation(
                        self.last_snapshot,
                        snapshot,
                        incident_description=incidents[0]['description']
                    )
                    
                    # Save analysis
                    self.save_incident_analysis(incidents[0], analysis)
                    
                    # Alert SRE team
                    self.send_alert(incidents[0], analysis)
                
                self.last_snapshot = snapshot
                
                # Sleep
                time.sleep(interval_minutes * 60)
                
            except Exception as e:
                print(f"❌ Error: {e}")
                time.sleep(60)
    
    def apply_retention_policy(self):
        """Keep snapshots based on retention policy"""
        
        snapshots = sorted(self.snapshots_dir.glob('auto_*.json'))
        now = datetime.utcnow()
        
        daily_keepers = set()
        weekly_keepers = set()
        
        for snapshot in snapshots:
            # Parse timestamp from filename: auto_20260317_1430.json
            try:
                timestamp_str = snapshot.stem.split('_', 1)[1]  # 20260317_1430
                timestamp = datetime.strptime(timestamp_str, '%Y%m%d_%H%M')
            except Exception:
                continue
            
            age = now - timestamp
            
            # Keep all from last 24 hours
            if age.total_seconds() < 24 * 3600:
                continue
            
            # Keep one per day for last 30 days
            if age.days < 30:
                day_key = timestamp.strftime('%Y%m%d')
                if day_key not in daily_keepers:
                    daily_keepers.add(day_key)
                    continue
                else:
                    snapshot.unlink()
                    continue
            
            # Keep one per week for last 12 weeks
            if age.days < 90:
                week_key = timestamp.strftime('%Y%W')  # Year + week number
                if week_key not in weekly_keepers:
                    weekly_keepers.add(week_key)
                    continue
                else:
                    snapshot.unlink()
                    continue
            
            # Delete everything older than 90 days
            snapshot.unlink()
    
    def check_for_incidents(self):
        """Check Prometheus for firing critical alerts"""
        
        incidents = []
        
        prometheus_url = os.getenv('PROMETHEUS_URL', 'http://prometheus:9090')
        
        try:
            import requests
            
            response = requests.get(
                f"{prometheus_url}/api/v1/alerts",
                timeout=5
            )
            
            if response.status_code == 200:
                data = response.json()
                
                for alert in data.get('data', {}).get('alerts', []):
                    if alert.get('state') == 'firing':
                        severity = alert.get('labels', {}).get('severity', '')
                        
                        if severity in ['critical', 'error']:
                            incidents.append({
                                'source': 'prometheus',
                                'name': alert['labels'].get('alertname', 'Unknown'),
                                'description': alert.get('annotations', {}).get('description', ''),
                                'severity': severity,
                                'labels': alert.get('labels', {})
                            })
        except Exception as e:
            print(f"    ⚠️  Failed to check Prometheus: {e}")
        
        return incidents
    
    def save_incident_analysis(self, incident, analysis):
        """Save analysis for later review"""
        
        incident_dir = Path(f"incidents/{datetime.utcnow().strftime('%Y%m%d_%H%M')}_{incident['name']}")
        incident_dir.mkdir(parents=True, exist_ok=True)
        
        with open(incident_dir / 'analysis.txt', 'w') as f:
            f.write(analysis)
        
        with open(incident_dir / 'incident.json', 'w') as f:
            json.dump(incident, f, indent=2)
        
        print(f"💾 Analysis saved: {incident_dir}")
    
    def send_alert(self, incident, analysis):
        """Send analysis to Slack/email"""
        
        # Extract key findings (first 500 chars)
        summary = analysis[:500] + "..." if len(analysis) > 500 else analysis
        
        message = f"""
🔬 **Infrastructure DNA Analysis**

**Incident:** {incident['name']}
**Severity:** {incident['severity']}

**Initial Analysis:**
{summary}

Full analysis saved in incidents/ directory.
"""
        
        # Send to Slack (if webhook configured)
        slack_webhook = os.getenv('SLACK_WEBHOOK_URL')
        if slack_webhook:
            try:
                import requests
                requests.post(slack_webhook, json={'text': message}, timeout=5)
                print("📨 Alert sent to Slack")
            except Exception:
                print("📨 Slack notification failed")
        else:
            print("📨 Alert would be sent (no webhook configured)")


class PreDeploymentHook:
    """Captures snapshot before/after deployments"""
    
    def __init__(self):
        self.collector = InfrastructureSnapshot()
        self.state_file = Path('/tmp/pre_deploy_snapshot.txt')
    
    def before_deployment(self):
        """Call before terraform apply / kubectl apply"""
        
        print("=" * 60)
        print("PRE-DEPLOYMENT SNAPSHOT")
        print("=" * 60)
        
        filename, _ = self.collector.capture('pre_deploy')
        
        # Store filename for post-deployment comparison
        self.state_file.write_text(filename)
        
        print(f"\n✅ Pre-deployment snapshot saved")
        print(f"   Proceed with deployment...")
        
        return filename
    
    def after_deployment(self, success=True):
        """Call after terraform apply / kubectl apply"""
        
        print("\n" + "=" * 60)
        print("POST-DEPLOYMENT ANALYSIS")
        print("=" * 60)
        
        filename, snapshot = self.collector.capture('post_deploy')
        
        # Get pre-deployment snapshot
        try:
            if not self.state_file.exists():
                print("⚠️  No pre-deployment snapshot found")
                return
            
            pre_snapshot_file = self.state_file.read_text().strip()
            
            with open(pre_snapshot_file) as f:
                pre_snapshot = json.load(f)
            
            # Analyze
            sequencer = DNASequencer()
            
            incident_desc = "Deployment failed - analyzing what changed" if not success else "Deployment impact analysis"
            
            analysis = sequencer.analyze_mutation(
                pre_snapshot,
                snapshot,
                incident_description=incident_desc
            )
            
            print("\n" + analysis)
            
            # Save analysis
            analysis_dir = Path('deployments') / datetime.utcnow().strftime('%Y%m%d_%H%M')
            analysis_dir.mkdir(parents=True, exist_ok=True)
            
            with open(analysis_dir / 'analysis.txt', 'w') as f:
                f.write(analysis)
            
            if not success:
                print("\n" + "=" * 60)
                print("⚠️  DEPLOYMENT FAILED")
                print("=" * 60)
                print("Analysis above may show root cause of failure")
            else:
                print("\n" + "=" * 60)
                print("✅ DEPLOYMENT SUCCEEDED")
                print("=" * 60)
                print("Review analysis above for unexpected side effects")
            
        except Exception as e:
            print(f"❌ Could not compare snapshots: {e}")
        finally:
            # Cleanup
            if self.state_file.exists():
                self.state_file.unlink()


class SnapshotManager:
    """Manage snapshots and find last known good state"""
    
    def __init__(self):
        self.snapshots_dir = Path('snapshots')
    
    def find_last_good_snapshot(self, before_time=None):
        """Find last snapshot where system was healthy"""
        
        if before_time is None:
            before_time = datetime.utcnow()
        
        snapshots = sorted(self.snapshots_dir.glob('auto_*.json'), reverse=True)
        
        for snapshot_file in snapshots:
            # Parse timestamp
            try:
                timestamp_str = snapshot_file.stem.split('_', 1)[1]
                snapshot_time = datetime.strptime(timestamp_str, '%Y%m%d_%H%M')
            except Exception:
                continue
            
            # Must be before incident time
            if snapshot_time >= before_time:
                continue
            
            # Load and check if healthy
            try:
                with open(snapshot_file) as f:
                    snapshot = json.load(f)
                
                if self.is_healthy_snapshot(snapshot):
                    return str(snapshot_file), snapshot
            except Exception:
                continue
        
        return None, None
    
    def is_healthy_snapshot(self, snapshot):
        """Heuristics to determine if snapshot represents healthy state"""
        
        # Check K8s problem pods
        k8s = snapshot.get('k8s_state', {})
        problem_pods = k8s.get('problem_pods', {}).get('items', [])
        
        # If more than 5 pods have problems, not healthy
        if len(problem_pods) > 5:
            return False
        
        # Check critical deployments
        deployments = k8s.get('deployments', {}).get('items', [])
        for deploy in deployments:
            labels = deploy.get('metadata', {}).get('labels', {})
            
            # Check if critical tier
            if labels.get('tier') == 'critical':
                available = deploy.get('status', {}).get('availableReplicas', 0)
                desired = deploy.get('spec', {}).get('replicas', 1)
                
                # Critical deployment must have all replicas available
                if available < desired:
                    return False
        
        # Passed basic health checks
        return True
    
    def list_snapshots(self, limit=10):
        """List recent snapshots"""
        
        snapshots = sorted(self.snapshots_dir.glob('*.json'), reverse=True)
        
        print("\n📸 Recent Snapshots:")
        print("=" * 60)
        
        for i, snapshot in enumerate(snapshots[:limit]):
            with open(snapshot) as f:
                data = json.load(f)
            
            timestamp = data.get('timestamp', 'Unknown')
            label = data.get('label', 'Unknown')
            
            # Check health
            health = "✅ Healthy" if self.is_healthy_snapshot(data) else "⚠️  Issues detected"
            
            print(f"{i+1}. {snapshot.name}")
            print(f"   Time: {timestamp}")
            print(f"   Label: {label}")
            print(f"   Health: {health}")
            print()


def main():
    """Main CLI interface for automated operations"""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python automated_sequencer.py monitor [interval_minutes]")
        print("  python automated_sequencer.py pre-deploy")
        print("  python automated_sequencer.py post-deploy [success|failure]")
        print("  python automated_sequencer.py find-last-good")
        print("  python automated_sequencer.py list-snapshots")
        return
    
    command = sys.argv[1]
    
    if command == 'monitor':
        # Run continuous monitoring
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else 15
        monitor = AutomatedSequencer()
        monitor.run_continuous_monitoring(interval_minutes=interval)
        
    elif command == 'pre-deploy':
        # Pre-deployment hook
        hook = PreDeploymentHook()
        hook.before_deployment()
        
    elif command == 'post-deploy':
        # Post-deployment hook
        success = True
        if len(sys.argv) > 2:
            success = sys.argv[2].lower() == 'success'
        
        hook = PreDeploymentHook()
        hook.after_deployment(success)
        
    elif command == 'find-last-good':
        # Find last known good snapshot
        manager = SnapshotManager()
        filename, snapshot = manager.find_last_good_snapshot()
        
        if filename:
            print(f"✅ Last known good snapshot: {filename}")
            print(f"   Timestamp: {snapshot['timestamp']}")
        else:
            print("❌ No healthy snapshot found")
    
    elif command == 'list-snapshots':
        # List recent snapshots
        manager = SnapshotManager()
        manager.list_snapshots()


if __name__ == '__main__':
    main()
