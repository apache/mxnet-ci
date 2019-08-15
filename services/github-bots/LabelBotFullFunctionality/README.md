<!--- Licensed to the Apache Software Foundation (ASF) under one -->
<!--- or more contributor license agreements.  See the NOTICE file -->
<!--- distributed with this work for additional information -->
<!--- regarding copyright ownership.  The ASF licenses this file -->
<!--- to you under the Apache License, Version 2.0 (the -->
<!--- "License"); you may not use this file except in compliance -->
<!--- with the License.  You may obtain a copy of the License at -->

<!---   http://www.apache.org/licenses/LICENSE-2.0 -->

<!--- Unless required by applicable law or agreed to in writing, -->
<!--- software distributed under the License is distributed on an -->
<!--- "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY -->
<!--- KIND, either express or implied.  See the License for the -->
<!--- specific language governing permissions and limitations -->
<!--- under the License. -->

# label bot
This bot serves to help non-committers add labels to GitHub issues.

"Hi @mxnet-label-bot add [operator, feature request]"

"Hi @mxnet-label-bot remove [operator, feature request]"

"Hi @mxnet-label-bot update [operator, feature request]"

"Hi @mxnet-label-bot replace [operator, feature request]"

## Setup
**Make sure that all settings is in the same *AWS region***
#### 1. Store a secret
*Create a secret using Terraform*
* Configure ***variables.tf***
    1. In variable "github_credentials", fill in github_user and github_oauth_token. If you don't want to fill in here, then you can leave them blank.
       After you set up a secret, you can go to [AWS Secrets Manager Console](https://console.aws.amazon.com/secretsmanager) console to manually fill in secret values.
    2. In configuring a webhook for github, confirm that the content type you have set is of application/json and that the appropriate events that you would like to
       trigger the webhook for are set. As an additional security measure,  under Content type configure a secret for your webhook. 
       Be sure to include this secret as well in the variables.tf file (as a part of webhook_secret). Similarly, you can leave this blank and fill it in
       later in the secrets manager console. 
    3. In variable "secret_name", fill in the name of your secret. ie:"github/credentials"

**Note:** Do *not*  commit credentials that you have assigned in variables.tf to the GitHub repo

* Run `terraform apply`. It will create the secret. Once setup, it will output the secret ARN. Write it down. 
 <div align="center">
        <img src="https://s3-us-west-2.amazonaws.com/email-boy-images/Screen+Shot+2018-08-02+at+9.42.56+PM.png" ><br>
 </div>


#### 2. Deploy Lambda Function
*Deploy this label bot using the serverless framework*
* Configure ***severless.yml***
    1. Under ***iamRolesStatements***, replace ***Resource*** with the secret ARN 
    2. Under ***environment***
        1. Set ***region_name*** as the same region of your secret.
        2. Replace ***secret_name*** with the secret name. (Same as the secret name you set in step1)
        3. Replace ***repo*** with the repo's name you want to test.
* Deploy    
Open terminal, go to current directory. run 
```
./deploy_bot.sh
```
Then it will set up those AWS services:
* An IAM role for label bot with policies:
```
1.secretsmanager:ListSecrets 
2.secretsmanager:DescribeSecret
3.secretsmanager:GetSecretValue 
4.cloudwatchlogs:CreateLogStream
5.cloudwatchlogs:PutLogEvents
```
One thing to mention: this IAM role only has ***Read*** access to the secret created in step1.
* A Lambda function will all code needed.
* A CloudWatch event which will trigger the lambda function every 5 minutes.  

#### 3.Play with this bot
* Go to the repo, under an **unlabeled** issue, comment "@mxnet-label-bot, please add labels:[bug]". One thing to mention, this bot can only add labels which **exist** in the repo.
* Go to the lambda function's console, click **Test**. 
* Then labels will be added.
    <div align="center">
        <img src="https://s3-us-west-2.amazonaws.com/email-boy-images/Screen+Shot+2018-11-13+at+1.56.17+PM.png" width="600" height="150"><br>
    </div>

#### 4. DNS Service
* In serverless.yml within the customDomain section specify the domain name you would like to use.
* Similarly, specify the basePath and the stage (this correlates to your API Gateway function) i.e. dev and dev stage.
* You will need to request a Certificate for your new domain, so under AWS Certificate Manager add your domain name and validate using DNS service.
* To install the plugin, run ``npm install serverless-domain-manager --save-dev``.
* After this run ``serverless create_domain`` (process may take some time and is meant to only run once)
* Afterwards run serverless deploy -v
* Specify this domain name (and the specific endpoint where your function points to in the API Gateway Console)

***Note:*** Verify that ACM certificate is created in us-east-1 (for edge apis) and is present and matches the certificate in the certificate section of API Gateway (Custom Domain Names).
As well, make sure to set the appropriate CNAME certificate from Certificate Manager for the route53 domain.

When wanting to update the stack using serverless deploy after initial launch, comment out
in serverless.yml file the section regarding customDomain and plugins.
***Note:*** Confirm in each update that the basePath is set to /dev and point it to corret lambda under Custom Domain Names in API Gateway.


#### 5. CloudWatch Log Access
* In (deploy.sh) fill in the variables 
    - dest_account="AWS_ACCOUNT_NUM" with the AWS account of the destination of the logs
    - bot_account="AWS_ACCOUNT_NUM" with the AWS account of the bot account
* Then, the destination log account proceeds to assume the role (to have view access of the logs)
* After assuming the role proceed to view the logs by navigating to the appropriate section in the CloudWatch console
   - [Label Logs](https://us-west-2.console.aws.amazon.com/cloudwatch/home?region=us-west-2#logStream:group=/aws/lambda/LabelBotFull-dev-label)
   - [Send Logs](https://us-west-2.console.aws.amazon.com/cloudwatch/home?region=us-west-2#logStream:group=/aws/lambda/LabelBotFull-dev-send)

