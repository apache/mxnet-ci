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

# Lambda function for automatic rotatation of DockerHub credentials in AWS SecretsManager
This repository sets up a Lambda function that allows to autoamtically change a DockerHub password.

## Deployment
These are the deployment instructions.

### Installation
You need to have NodeJS (npm) and serverless installed. Additional npm packages are required and can be installed as follows:
```npm install serverless-python-requirements```
```npm install serverless-s3-remover```

### Provisioning
Run ```deploy_lambda.sh``` and enter the deployment stage

## Usage
Log into SecretsManager, open the secret of your choice, go to the category "Rotation configuration", click on "Edit rotation", enable the automatic rotation, enter an interval of your choice and select the previously provisioned Lambda function. Then press on "Save"; note that this will trigger an immediate rotation of the credentials.

If you would like to trigger a manual immediate rotation, click on "Rotate secret immediately" in the secret detail windows.

## Debugging
If you'd like to debug this script, go to CloudWatch logs and look for the "	
/aws/lambda/SecretsManager_docker_hub_change_password_function" log group. 