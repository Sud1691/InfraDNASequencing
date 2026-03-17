pipeline {
    agent any
    
    environment {
        ANTHROPIC_API_KEY = credentials('anthropic-api-key')
        TERRAFORM_DIR = './terraform'
    }
    
    stages {
        stage('Setup') {
            steps {
                sh 'pip install -r requirements.txt'
            }
        }
        
        stage('Pre-Deploy Snapshot') {
            steps {
                sh 'python automated_sequencer.py pre-deploy'
            }
        }
        
        stage('Terraform Plan') {
            steps {
                dir('terraform') {
                    sh 'terraform init'
                    sh 'terraform plan -out=plan.tfplan'
                }
            }
        }
        
        stage('Approve Deployment') {
            steps {
                input message: 'Deploy to production?', ok: 'Deploy'
            }
        }
        
        stage('Terraform Apply') {
            steps {
                dir('terraform') {
                    sh 'terraform apply -auto-approve plan.tfplan'
                }
            }
        }
        
        stage('Post-Deploy Analysis') {
            steps {
                script {
                    def deployStatus = currentBuild.result == null ? 'success' : 'failure'
                    sh "python automated_sequencer.py post-deploy ${deployStatus}"
                }
            }
            post {
                always {
                    script {
                        // Archive analysis
                        archiveArtifacts artifacts: 'deployments/**/analysis.txt', allowEmptyArchive: true
                        
                        // Display analysis
                        sh '''
                        if [ -d "deployments" ]; then
                            echo "=== DEPLOYMENT ANALYSIS ==="
                            find deployments -name "analysis.txt" -exec cat {} \\;
                        fi
                        '''
                    }
                }
            }
        }
    }
    
    post {
        failure {
            echo 'Deployment failed - check analysis above for root cause'
        }
    }
}
