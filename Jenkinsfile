pipeline {
    agent { label 'docker && linux' }

    parameters {
        booleanParam(
            name: 'DEPLOY_ENABLED',
            defaultValue: false,
            description: 'Deploy develop by pulling and building directly on the two EC2 hosts.'
        )
    }

    options {
        timestamps()
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    triggers {
        pollSCM('H/5 * * * *')
    }

    environment {
        COMPOSE_PROJECT_NAME = "gitjob-ci-${env.BUILD_NUMBER}"
        COMPOSE_FILES = "-f Infra/compose/compose.yaml -f Infra/compose/compose.wsl.yaml"
        // AI runs on a separate GPU server; Jenkins CI covers BE/FE only.
        COMPOSE_PROFILES = 'core,app'
    }

    stages {
        stage('Prepare CI environment') {
            steps {
                sh '''#!/usr/bin/env bash
                    set -Eeuo pipefail
                    test -f .env.ci.example
                    install -m 600 .env.ci.example .env.ci
                    java -version
                    node --version
                    npm --version
                    docker version
                    docker compose version
                    git --version
                '''
            }
        }

        stage('Validate') {
            steps {
                sh '''#!/usr/bin/env bash
                    set -Eeuo pipefail
                    docker compose --project-directory . --project-name "${COMPOSE_PROJECT_NAME}" --env-file .env.ci ${COMPOSE_FILES} \\
                      --profile core --profile app config --quiet
                '''
            }
        }

        stage('Backend test') {
            steps {
                sh '''#!/usr/bin/env bash
                    set -Eeuo pipefail
                    test -x BE/gradlew
                    (cd BE && ./gradlew --no-daemon test)
                '''
            }
        }

        stage('Frontend test') {
            steps {
                sh '''#!/usr/bin/env bash
                    set -Eeuo pipefail
                    test -f FE/package.json
                    cd FE
                    npm ci
                    if node -e "const packageJson = require('./package.json'); process.exit(packageJson.scripts?.test ? 0 : 1)"; then
                        npm test -- --runInBand
                    else
                        echo 'No frontend test script configured; skipping frontend test command.'
                    fi
                    npm run build
                '''
            }
            post {
                always {
                    sh 'rm -rf FE/node_modules'
                }
            }
        }

        stage('Deploy') {
            when {
                allOf {
                    branch 'develop'
                    expression { params.DEPLOY_ENABLED }
                }
            }
            steps {
                script {
                    if (!fileExists('Infra/scripts/deploy.sh')) {
                        error('DEPLOY_ENABLED=true but Infra/scripts/deploy.sh is not implemented')
                    }
                }
                withCredentials([
                    sshUserPrivateKey(
                        credentialsId: 'gitjob-ec2-ssh',
                        keyFileVariable: 'EC2_SSH_KEY',
                        usernameVariable: 'EC2_SSH_USER'
                    )
                ]) {
                    sh '''#!/usr/bin/env bash
                        set -Eeuo pipefail
                        deployment_mode="$(sed -n 's/^DEPLOYMENT_MODE=//p' .env.ci | tail -n 1)"
                        test "$deployment_mode" = split || {
                            echo 'This job supports DEPLOYMENT_MODE=split only: service EC2 plus data EC2.' >&2
                            exit 2
                        }
                        service_host="$(sed -n 's/^EC2_SERVICE_HOST=//p' .env.ci | tail -n 1)"
                        data_host="$(sed -n 's/^EC2_DATA_HOST=//p' .env.ci | tail -n 1)"
                        test -n "$service_host" && test -n "$data_host" || {
                            echo 'Split deploy requires EC2_SERVICE_HOST and EC2_DATA_HOST.' >&2
                            exit 2
                        }
                        Infra/scripts/deploy.sh
                    '''
                }
            }
        }
    }

    post {
        always {
            sh '''#!/usr/bin/env bash
                set +e
                if [ ! -f .env.ci ]; then
                    exit 0
                fi
                case "${COMPOSE_PROJECT_NAME:-}" in
                    gitjob-ci-*) ;;
                    *) echo 'Refusing CI cleanup for a non-CI Compose project.' >&2; exit 1 ;;
                esac
                # This cleanup is confined to the ephemeral Jenkins CI project.
                # It never runs on either remote EC2 host.
                docker compose --project-directory . --project-name "${COMPOSE_PROJECT_NAME}" --env-file .env.ci ${COMPOSE_FILES} \\
                  --profile core --profile app down --volumes
            '''
        }
    }
}
