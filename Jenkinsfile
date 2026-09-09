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
                    # Report every missing mandatory variable up front. Compose
                    # stops at the first one and phrases it as an interpolation
                    # error, which hides that the env file is what needs fixing.
                    bash Infra/scripts/check-required-env.sh .env.ci \\
                      Infra/compose/compose.yaml Infra/compose/compose.wsl.yaml
                    docker compose --project-directory . --project-name "${COMPOSE_PROJECT_NAME}" --env-file .env.ci ${COMPOSE_FILES} \\
                      --profile core --profile app config --quiet
                '''
            }
        }

        stage('Start CI dependencies') {
            steps {
                sh '''#!/usr/bin/env bash
                    set -Eeuo pipefail

                    ci_compose() {
                        docker compose --project-directory . --project-name "${COMPOSE_PROJECT_NAME}" \\
                          --env-file .env.ci ${COMPOSE_FILES} "$@"
                    }

                    # Backend tests run directly in the Jenkins agent, so attach
                    # that agent to the isolated CI network after PostgreSQL is
                    # started. The production service database is never used.
                    ci_compose --profile core up -d --wait --wait-timeout 60 postgres

                    ci_network="${COMPOSE_PROJECT_NAME}_default"
                    agent_container="$(hostname)"
                    if ! docker network connect "$ci_network" "$agent_container" 2>/dev/null; then
                        docker network inspect "$ci_network" --format '{{json .Containers}}' \\
                          | grep -q "$agent_container" || {
                            echo "Failed to connect Jenkins agent to CI network: $ci_network" >&2
                            exit 1
                        }
                    fi
                '''
            }
        }

        stage('Backend test') {
            steps {
                sh '''#!/usr/bin/env bash
                    set -Eeuo pipefail

                    env_value() {
                        local key="$1"
                        sed -n "s/^${key}=//p" .env.ci | tail -n 1
                    }

                    db_host="$(env_value DB_HOST)"
                    db_port="$(env_value DB_PORT)"
                    db_name="$(env_value POSTGRES_DB)"
                    db_user="$(env_value POSTGRES_USER)"
                    db_password="$(env_value POSTGRES_PASSWORD)"
                    aes_symmetric_key="$(env_value AES_SYMMETRIC_KEY)"
                    aes_salt="$(env_value AES_SALT)"
                    test -n "$db_host" && test -n "$db_port" && test -n "$db_name" \\
                      && test -n "$db_user" && test -n "$db_password" \\
                      && test -n "$aes_symmetric_key" && test -n "$aes_salt"

                    # .env.ci is a Compose input file; copying it does not export
                    # its values to the Gradle process. Pass the datasource
                    # settings plus the AES pair, which application.yaml requires
                    # with no fallback, so the context-load test can start.
                    (
                        export SPRING_PROFILES_ACTIVE=docker
                        export SPRING_DATASOURCE_URL="jdbc:postgresql://${db_host}:${db_port}/${db_name}"
                        export SPRING_DATASOURCE_USERNAME="$db_user"
                        export SPRING_DATASOURCE_PASSWORD="$db_password"
                        export AES_SYMMETRIC_KEY="$aes_symmetric_key"
                        export AES_SALT="$aes_salt"
                        cd BE
                        test -x ./gradlew
                        ./gradlew --no-daemon test
                    )
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
                    # oxlint is already a devDependency and FE exposes it as `lint`,
                    # but nothing was calling it. `npm run build` type-checks; this is
                    # the only thing in CI that looks at the code itself.
                    npm run lint
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
                // This is a single Pipeline job, not a Multibranch Pipeline.
                // The job's SCM branch is configured in Jenkins; validate the
                // checked-out commit against origin/develop below instead of
                // relying on the Multibranch-only branch condition.
                expression { params.DEPLOY_ENABLED }
            }
            steps {
                script {
                    if (!fileExists('Infra/scripts/deploy.sh')) {
                        error('DEPLOY_ENABLED=true but Infra/scripts/deploy.sh is not implemented')
                    }
                }
                sh '''#!/usr/bin/env bash
                    set -Eeuo pipefail
                    git show-ref --verify --quiet refs/remotes/origin/develop || {
                        echo 'Deploy requires origin/develop to be available in the checkout.' >&2
                        exit 2
                    }
                    git merge-base --is-ancestor HEAD refs/remotes/origin/develop || {
                        echo 'Deploy requires the checked-out commit to be reachable from origin/develop.' >&2
                        exit 2
                    }
                '''
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
                ci_network="${COMPOSE_PROJECT_NAME}_default"
                agent_container="$(hostname)"
                docker network disconnect "$ci_network" "$agent_container" >/dev/null 2>&1 || true
                docker compose --project-directory . --project-name "${COMPOSE_PROJECT_NAME}" --env-file .env.ci ${COMPOSE_FILES} \\
                  --profile core --profile app down --volumes
            '''
        }
    }
}
