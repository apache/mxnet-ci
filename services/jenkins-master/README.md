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

This is the Terraform setup we used to create the Jenkins master. This script is **VERY** outdated!

# Create infrastructure

Warning: this will destroy the current DNS entries.

```
./init.sh
terraform init
terraform apply
```


With difference instance type (overriding variables)

```
terraform apply -var instance_type=c1.xlarge
```

# Notes

- The CI master server is responsible for updating the CI check status to GitHub in each of the PRs. Using EC2's default DNS sometimes result in DNS resolution failure and thus a failed status update. It's better to have multiple reliable DNS servers as backup. The following servers are recommended:
```
1.1.1.1 # Cloudflare
8.8.8.8 # Google
208.67.222.222 # OpenDNS
```
