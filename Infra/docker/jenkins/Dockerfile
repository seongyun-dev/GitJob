# Jenkins controller image with the plugins required by the planned GitLab
# pipeline. Plugin versions should be locked before the EC2 rollout.

FROM jenkins/jenkins:lts-jdk21

# The base image runs this build step as the unprivileged `jenkins` user.
# Keep the copied manifest readable so jenkins-plugin-cli can actually
# install the requested plugins into the reference directory.
COPY --chown=jenkins:jenkins Infra/jenkins/plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt
