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

aws_access_key = "REDACTED"
aws_secret_key = "REDACTED"
key_name = "REDACTED"
key_path = "~/.ssh/REDACTED"
instance_type = "c5.4xlarge"
vpc_id = "02c00d7b"

additional_security_group_ids = [
  "sg-5d83d421", # VPC default
  "sg-REDACTED" # REDACTED
]

shell_variables_file = "test/variables.sh"
jenkins_config_bucket = "mxnet-ci-master-dev"
zone_id = "REDACTED"
domain = "mxnet-ci-dev.amazon-ml.com"
instance_name = "MXNet-CI-Master"
aws_region = "us-west-2"

# EBS volume and AZ have to be the same
aws_availability_zone = "us-west-2b"
ebs_volume_jenkins_master_state_volume_id = "vol-REDACTED"
