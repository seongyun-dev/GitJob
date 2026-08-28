pipeline {
    agent { label 'docker && linux' }

    parameters {
        booleanParam(
            name: 'PUBLISH_IMAGES',
            defaultValue: false,
            description: 'Push images after registry credentials and image tags are configured.'
        )
        booleanParam(
            name: 'DEPLOY_ENABLED',
            defaultValue: false,
            description: 'Deploy only after the approved deployment wrapper and target are configured.'
        )
    }

    options {
        timestamps()
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    environment {
        COMPOSE_PROJECT_NAME = "gitjob-ci-${env.BUILD_NUMBER}"
        COMPOSE_FILES = "-f Infra/compose/compose.yaml -f Infra/compose/compose.wsl.yaml"
        COMPOSE_PROFILES = 'core,app,data'
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
                      --profile core --profile app --profile data config --quiet
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
                    npm test -- --runInBand
                    npm run build
                '''
            }
            post {
                always {
                    sh 'rm -rf FE/node_modules'
                }
            }
        }

        stage('Build images') {
            steps {
                sh '''#!/usr/bin/env bash
                    set -Eeuo pipefail
                    docker compose --project-directory . --project-name "${COMPOSE_PROJECT_NAME}" --env-file .env.ci ${COMPOSE_FILES} \\
                      --profile core --profile app --profile data build \\
                      backend frontend collector worker spark-master spark-worker
                '''
            }
        }

        stage('Push images') {
            when {
                allOf {
                    anyOf {
                        branch 'develop'
                        branch 'main'
                        buildingTag()
                    }
                    expression { params.PUBLISH_IMAGES }
                }
            }
            steps {
                withCredentials([
                    usernamePassword(
                        credentialsId: 'gitjob-registry',
                        usernameVariable: 'REGISTRY_USER',
                        passwordVariable: 'REGISTRY_PASSWORD'
                    )
                ]) {
                    sh '''#!/usr/bin/env bash
                        set -Eeuo pipefail
                        registry="${GITLAB_REGISTRY:-$(sed -n 's/^GITLAB_REGISTRY=//p' .env.ci | tail -n 1)}"
                        test -n "$registry" || { echo 'GITLAB_REGISTRY must be set in .env.ci' >&2; exit 2; }
                        registry_namespace="${GITLAB_REGISTRY_NAMESPACE:-$(sed -n 's/^GITLAB_REGISTRY_NAMESPACE=//p' .env.ci | tail -n 1)}"
                        registry_namespace="${registry_namespace%/}"
                        test -n "$registry_namespace" || { echo 'GITLAB_REGISTRY_NAMESPACE must be set in .env.ci' >&2; exit 2; }
                        image_tag="${GIT_COMMIT:-${BUILD_TAG:-${BUILD_NUMBER}}}"
                        image_tag="$(printf '%s' "$image_tag" | tr '/: ' '---')"
                        printf '%s' "$REGISTRY_PASSWORD" | docker login "$registry" \\
                          --username "$REGISTRY_USER" --password-stdin
                        trap 'docker logout "$registry" >/dev/null 2>&1 || true' EXIT
                        push_image() {
                            local env_key="$1"
                            local image_name="$2"
                            local local_image
                            local remote_image
                            local_image="$(sed -n "s/^${env_key}=//p" .env.ci | tail -n 1)"
                            test -n "$local_image" || { echo "${env_key} must be set in .env.ci" >&2; exit 2; }
                            remote_image="${registry_namespace}/${image_name}:${image_tag}"
                            docker tag "$local_image" "$remote_image"
                            docker push "$remote_image"
                        }
                        push_image BACKEND_IMAGE backend
                        push_image FRONTEND_IMAGE frontend
                        push_image COLLECTOR_IMAGE collector
                        push_image WORKER_IMAGE worker
                        push_image SPARK_IMAGE spark
                    '''
                }
            }
        }

        stage('Deploy') {
            when {
                allOf {
                    anyOf {
                        branch 'develop'
                        branch 'main'
                        buildingTag()
                    }
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
                        deploy_path="$(sed -n 's/^EC2_DEPLOY_PATH=//p' .env.ci | tail -n 1)"
                        test -n "$deploy_path" || { echo 'EC2_DEPLOY_PATH must be set in .env.ci' >&2; exit 2; }
                        if [ "$deployment_mode" = ha ]; then
                            node_a="$(sed -n 's/^EC2_NODE_A_HOST=//p' .env.ci | tail -n 1)"
                            node_b="$(sed -n 's/^EC2_NODE_B_HOST=//p' .env.ci | tail -n 1)"
                            test -n "$node_a" && test -n "$node_b" || { echo 'HA deploy requires both EC2 node hosts' >&2; exit 2; }
                        else
                            deploy_host="$(sed -n 's/^EC2_DEPLOY_HOST=//p' .env.ci | tail -n 1)"
                            test -n "$deploy_host" || { echo 'EC2_DEPLOY_HOST must be set in .env.ci' >&2; exit 2; }
                        fi
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
                docker compose --project-directory . --project-name "${COMPOSE_PROJECT_NAME}" --env-file .env.ci ${COMPOSE_FILES} \\
                  --profile core --profile app --profile data down --volumes
            '''
        }
    }
}
