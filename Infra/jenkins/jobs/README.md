# Jenkins jobs

The root `Jenkinsfile` is the pipeline entrypoint. Create a Pipeline from SCM
job that points at the repository root and polls SCM. For the one-time
infrastructure test, use `infra/S15P21E102-75-infra-ec2`; switch the job back
to `develop` before enabling production deployment. GitLab's Jenkins
Integration is not required for this job. Job-specific secrets belong in
Jenkins Credentials, not in this directory.

For the current split deployment, set `DEPLOYMENT_MODE=split` and
`EC2_DEPLOY_REF=develop`. The pipeline contract is service core health → data
server build/up → service app build/up when deployment is explicitly enabled.
The default Jenkins build validates the service stack plus BE/FE only; AI runs
in a separate GPU-server pipeline and is not built or tested by default.
The deploy wrapper uses `gitjob-ec2-ssh` to pull the source and build locally on
each EC2; no image registry is involved.
