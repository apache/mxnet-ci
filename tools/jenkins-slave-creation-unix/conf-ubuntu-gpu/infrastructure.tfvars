# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

key_name = "REDACTED"
key_path = "~/.ssh/REDACTED"
instance_type = "g4dn.4xlarge"

s3_config_bucket = "mxnet-ci-slave-dev"
s3_config_filename = "ubuntu-gpu-config.tar.bz2"
slave_install_script  = "conf-ubuntu-gpu/install.sh"
shell_variables_file = "conf-ubuntu-gpu/shell-variables.sh"
# Base AMI, defines the OS of the slave instance [here: Ubuntu18.04 base image]
ami = "ami-0d1cd67c26f5fca19" # Ubuntu/images/hvm-ssd/ubuntu-bionic-18.04-amd64-server-20200112
instance_name = "Slave-base_Ubuntu-GPU"
aws_region = "us-west-2"
secret_manager_docker_hub_arn = "arn:aws:secretsmanager:us-west-2:REDACTED:secret:REDACTED"
