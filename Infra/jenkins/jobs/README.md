# Jenkins jobs

The root `Jenkinsfile` is the pipeline entrypoint. A multibranch Pipeline or a
GitLab webhook job should point at the repository root. Job-specific secrets
belong in Jenkins Credentials, not in this directory.

For a two-EC2 deployment, set `DEPLOYMENT_MODE=ha`, provide both node targets and
`ALB_HEALTHCHECK_URL`, and keep `EC2_DEPLOY_STRATEGY=rolling`. The pipeline contract
is node-a → ALB health check → node-b; the actual SSH/deploy wrapper is intentionally
left for the EC2 credential and image registry setup.
