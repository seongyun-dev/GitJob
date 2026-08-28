# The agent is the only service that receives the Docker socket in the local
# scaffold. Replace socket access with an isolated builder before production.

FROM docker:29.6.2-cli AS docker-cli
FROM node:22.14.0-bookworm-slim AS node-runtime

FROM jenkins/inbound-agent:jdk21

USER root
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/lib/docker/cli-plugins/docker-compose
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY Infra/docker/jenkins/agent-entrypoint.sh /usr/local/bin/gitjob-jenkins-agent
RUN set -eux; \
  rm -f /usr/local/bin/npm /usr/local/bin/npx; \
  ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm; \
  ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx; \
  chmod +x /usr/local/bin/gitjob-jenkins-agent; \
  test -x /usr/local/bin/docker; \
  test -x /usr/local/lib/docker/cli-plugins/docker-compose; \
  command -v curl; \
  command -v git; \
  command -v ssh; \
  test -f /etc/ssl/certs/ca-certificates.crt
USER jenkins
