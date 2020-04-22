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

This Terraform setup will spawn an instance that is ready to be saved into an AMI to create a Jenkins slave.

# Steps
## Setup Terraform
### Fetch Terraform and unzip the binary

```
wget https://releases.hashicorp.com/terraform/0.12.24/terraform_0.12.24_linux_amd64.zip
sudo apt install unzip
unzip terraform_0.12.24_linux_amd64.zip
```

### Add to path
Add the binary to the environment variable 'PATH'. 
For example

```
sudo mv terraform /usr/local/bin/
mkdir /home/ubuntu/bin
mv /usr/local/bin/terraform /home/ubuntu/bin/terraform
```

### Verify 
Check whether the terraform binary is in the PATH variable

```
echo $PATH
```

Verify terraform is properly installed

```
$ terraform --version
Terraform v0.12.24
$ which terraform
/home/ubuntu/bin/terraform
```

## Python package requirements
Install the terraform python package

```
pip3 install python_terraform
```

## Fill the redacted information
- infrastructure.tf [Security groups]
- infrastructure.tfvars [`key_name`, `key_path`, `secret_manager_docker_hub_arn`]
- `~/.aws/config` [Isengard account profile]

## Run the AMI creation script

```
./create_slave.sh
```

- Enter the desired directory

## Create an AMI
- Login to AWS Console
- Instance would be created with the name used in `infrastructure.tfvars.instance_name`
- Wait for the instance till it's state is "Stopped". [Note : Don't manually stop the instance. Manually stopping the instance can cause the AMI to get corrupted. In case it doesn't change state to stop, there was likely an issue in AMI generation. Please refer /var/log/cloud-init-output.log for further debug]
- Once the instance is stopped, Select Instance -> Actions -> Image -> Create Image