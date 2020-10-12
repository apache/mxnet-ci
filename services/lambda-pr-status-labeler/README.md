# Deploy the lambda function
Deploy this lambda function for labeling PRs based on the CI status using _serverless framework_
- Configure AWS profile [mxnet-ci or mxnet-ci-dev] based on the stage **[dev/prod]**
- Deploy
```
./deploy_lambda.sh
```

# Manual Steps
1. Creation of Domain name
- In `serverless.yml` within the customDomain section specify the domain name you would like to use.
- Similarly, specify the `basePath` and the `stage` (this correlates to your API Gateway function) i.e. dev and dev stage.
- You will need to request a Certificate for your new domain, so under AWS Certificate Manager add your domain name and validate using DNS service.
# Note
Make sure to create the certificate in us-east-1 N. Virginia
- To install the plugin, run `npm install serverless-domain-manager --save-dev`.
- After this run `serverless create_domain` (process may take some time and is meant to only run once)
- Afterwards run `serverless deploy -v`
- Specify this domain name (and the specific endpoint where your function points to in the API Gateway Console)