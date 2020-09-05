# Run
```
./deploy_lambda.sh
```

# Testing on Dev environment
In order to test on dev environment
1. Update environment variable in environment.yml
E.g. secret name, repo_name
Repo_name configured currently points to ChaiBapchya/incubator-mxnet but configure it for your personal fork for testing.
2. Update secret in AWS Secret Manager of mxnet-ci-dev account
Specifically : webhook secret
3. Configure github webhook to point to mxnet-ci-bot Domain along with the newly configured secret