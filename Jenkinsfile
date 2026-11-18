
pipeline {
    agent any

    options {
        timestamps()
    }

    // Check GitHub for changes every minute
    triggers {
        pollSCM('H/1 * * * *')
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Install dependencies') {
            steps {
                sh '''
                    python3 -m venv .venv
                    .venv/bin/pip install --upgrade pip
                    .venv/bin/pip install -r requirements-dev.txt
                '''
            }
        }

        stage('Run automated tests') {
            steps {
                sh '''
                    mkdir -p reports
                    .venv/bin/pytest -v --junitxml=reports/junit.xml
                '''
            }
        }

        stage('Package application') {
            steps {
                sh '''
                    mkdir -p dist
                    tar --exclude=.git \
                        --exclude=.venv \
                        --exclude='*.db' \
                        --exclude=.pytest_cache \
                        --exclude=dist \
                        -czf dist/price-radar-source.tar.gz .
                '''

                archiveArtifacts(
                    artifacts: 'dist/price-radar-source.tar.gz',
                    fingerprint: true
                )
            }
        }
    }

    post {
        always {
            junit(
                allowEmptyResults: true,
                testResults: 'reports/junit.xml'
            )
        }
    }
}
