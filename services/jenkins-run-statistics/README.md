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

# Jenkins run statistics
This script automatically generates CloudWatch metrics regarding the duration of Jenkins runs.

## Metrics
The metrics can be found in CloudWatch metrics. Check the environment.yml for the metric namespace.

## Logs
The logs are available in CloudWatch logs. Check the serverless.yml for the log namespace.

## Limitations
This tool processes all runs that are in the Jenkins database, but CloudWatch Metrics only allows to go back as far as 14 days. Thus, any runs that are older will be skipped. Please also note that for metrics, that are older than 24 hours, it may take them up to 48 hours until they are visible in the web interface. Consult https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/cloudwatch_concepts.html#Metric and https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_PutMetricData.html for more details regarding limitations.

If this lambda function times out due to too much data, it will automatically recover from that state and continue the work at the same point. This is achieved due to the DynamoDB backend in combination with Jenkins reporting the last build time of each job.

## Set up
- Install the Serverless framework

## Execution
Run deploy_lambda.sh

