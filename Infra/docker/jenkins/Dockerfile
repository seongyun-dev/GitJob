# Jenkins controller image with the plugins required by the planned GitLab
# pipeline. Plugin versions should be locked before the EC2 rollout.

FROM jenkins/jenkins:lts-jdk21

COPY Infra/jenkins/plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt
