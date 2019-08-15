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

provider "aws" {
  region = "us-west-2"
}

# TODO: MXBLN-358 Query for AWS Windows Base AMI ID
module "conf-windows-cpu-c5" {
  source = "./conf-windows-cpu-c5"
  document_name = "UpdateWindowsAMICPU"
  source_ami_id = "ami-019e99815e07ceb49"
  iam_instance_profile_name = "ManagedInstanceProfile"
  automation_assume_role = "arn:aws:iam::{{global:ACCOUNT_ID}}:role/AutomationServiceRole"
  target_ami_name = "windows-cpu-c5-{{global:DATE}}"
  instance_type = "c5.18xlarge"
  ebs_volume_size = "500"
  post_update_script_s3 = "https://s3.amazonaws.com/windows-post-install/post-install.py"
  slave_autoconnect_python_s3 = "https://s3.amazonaws.com/windows-post-install/slave-autoconnect.py"
  slave_autoconnect_bat_s3 = "https://s3.amazonaws.com/windows-post-install/run-auto-connect.bat"
  cudnn_install_s3 = "https://s3.amazonaws.com/windows-post-install/cudnn-9.2-windows10-x64-v7.4.2.24.zip"
  post_update_script_path = "C:\\\\post-install.py"
  slave_autoconnect_python_path = "C:\\\\slave-autoconnect.py"
  slave_autoconnect_bat_path = "C:\\\\run-auto-connect.bat"
  cudnn_install_path = "C:\\\\cudnn-9.2-windows10-x64-v7.4.2.24.zip"
  post_update_script_key = "post-install.py"
  slave_autoconnect_python_key = "slave-autoconnect.py"
  slave_autoconnect_bat_key = "run-auto-connect.bat"
  cudnn_install_key = "cudnn-9.2-windows10-x64-v7.4.2.24.zip"
}

module "conf-windows-gpu-g3" {
  source = "./conf-windows-gpu-g3"
  document_name = "UpdateWindowsAMIGPU"
  source_ami_id = "ami-019e99815e07ceb49"
  iam_instance_profile_name = "ManagedInstanceProfile"
  automation_assume_role = "arn:aws:iam::{{global:ACCOUNT_ID}}:role/AutomationServiceRole"
  target_ami_name = "windows-gpu-g3-{{global:DATE}}"
  instance_type = "g3.8xlarge"
  ebs_volume_size = "500"
  post_update_script_s3 = "https://s3.amazonaws.com/windows-post-install/post-install.py"
  slave_autoconnect_python_s3 = "https://s3.amazonaws.com/windows-post-install/slave-autoconnect.py"
  slave_autoconnect_bat_s3 = "https://s3.amazonaws.com/windows-post-install/run-auto-connect.bat"
  cudnn_install_s3 = "https://s3.amazonaws.com/windows-post-install/cudnn-9.2-windows10-x64-v7.4.2.24.zip"
  post_update_script_path = "C:\\\\post-install.py"
  slave_autoconnect_python_path = "C:\\\\slave-autoconnect.py"
  slave_autoconnect_bat_path = "C:\\\\run-auto-connect.bat"
  cudnn_install_path = "C:\\\\cudnn-9.2-windows10-x64-v7.4.2.24.zip"
  post_update_script_key = "post-install.py"
  slave_autoconnect_python_key = "slave-autoconnect.py"
  slave_autoconnect_bat_key = "run-auto-connect.bat"
  cudnn_install_key = "cudnn-9.2-windows10-x64-v7.4.2.24.zip"
}

resource "aws_iam_instance_profile" "ManagedInstanceProfile" {
  name = "ManagedInstanceProfile"
  role = "${aws_iam_role.SSMManagedInstanceRole.name}"
}

resource "aws_iam_role" "SSMManagedInstanceRole" {
  name = "SSMManagedInstanceRole"
  path = "/"

  assume_role_policy = <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Action": "sts:AssumeRole",
      "Principal": {
        "Service": [
            "ec2.amazonaws.com",
            "ssm.amazonaws.com"
        ]
      },
      "Effect": "Allow",
      "Sid": ""
    }
  ]
}
POLICY
}

data "aws_iam_policy" "AmazonEC2RoleforSSM" {
  arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2RoleforSSM"
}

resource "aws_iam_role_policy_attachment" "AmazonEC2RoleforSSMAttach" {
  role       = "${aws_iam_role.SSMManagedInstanceRole.name}"
  policy_arn = "${data.aws_iam_policy.AmazonEC2RoleforSSM.arn}"
}

resource "aws_iam_role_policy" "passrole" {
  name = "passrole"
  role = "${aws_iam_role.AutomationServiceRole.id}"

  policy = <<EOF
{
   "Version":"2012-10-17",
   "Statement":[
      {
         "Action":[
            "iam:PassRole"
         ],
         "Resource":[
            "${aws_iam_role.SSMManagedInstanceRole.arn}"
         ],
         "Effect":"Allow"
      },
      {
         "Effect":"Allow",
         "Action":[
            "iam:PassRole"
         ],
         "Resource":"${aws_iam_role.AutomationServiceRole.arn}",
         "Condition":{
            "StringLikeIfExists":{
               "iam:PassedToService":"ssm.amazonaws.com"
            }
         }
      }
   ]
}
EOF
}

resource "aws_iam_role" "AutomationServiceRole" {
  name = "AutomationServiceRole"
  path = "/"

  assume_role_policy = <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Action": "sts:AssumeRole",
      "Principal": {
        "Service": [
            "ec2.amazonaws.com",
            "ssm.amazonaws.com",
            "events.amazonaws.com"
        ]
      },
      "Effect": "Allow",
      "Sid": ""
    }
  ]
}
POLICY
}

data "aws_iam_policy" "AmazonSSMAutomationRole" {
  arn = "arn:aws:iam::aws:policy/service-role/AmazonSSMAutomationRole"
}

resource "aws_s3_bucket" "windows-post-install" {
  bucket = "windows-post-install"
}

resource "aws_s3_bucket_object" "post-install-script-windows" {
  bucket = "windows-post-install"
  key    = "post-install.py"
  source = "./post-install.py"
  etag   = "${md5(file("./post-install.py"))}"
}

resource "aws_s3_bucket_object" "slave-autoconnect-script" {
  bucket = "windows-post-install"
  key    = "slave-autoconnect.py"
  source = "../infrastructure_slave_creation/scripts/deploy/slave-autoconnect.py"
  etag   = "${md5(file("../infrastructure_slave_creation/scripts/deploy/slave-autoconnect.py"))}"
}

resource "aws_s3_bucket_object" "slave-autoconnect-bat" {
  bucket = "windows-post-install"
  key    = "run-auto-connect.bat"
  source = "../run-auto-connect.bat"
  etag   = "${md5(file("../run-auto-connect.bat"))}"
}

# BUG: This will not work unless you have the cuDNN 9.2 Windows 10 zip located in the infrastructure_slave_windows folder
resource "aws_s3_bucket_object" "cudnn-install-zip" {
  bucket = "windows-post-install"
  key    = "cudnn-9.2-windows10-x64-v7.4.2.24.zip"
  source = "./cudnn-9.2-windows10-x64-v7.4.2.24.zip"
  etag   = "${md5(file("./cudnn-9.2-windows10-x64-v7.4.2.24.zip"))}"
}

resource "aws_iam_role_policy_attachment" "AmazonSSMAutomationRoleAttach" {
  role       = "${aws_iam_role.AutomationServiceRole.name}"
  policy_arn = "${data.aws_iam_policy.AmazonSSMAutomationRole.arn}"
}

resource "aws_cloudwatch_event_rule" "UpdateWindowsAMI" {
  name        = "update-windows-ami"
  description = "Kicks off ami creation automation document every week"
  schedule_expression = "rate(7 days)"
  role_arn = "${aws_iam_role.AutomationServiceRole.arn}"
}

# BUG: Terraform sees this as an SSM Run Command rather than an SSM Automation
# resource "aws_cloudwatch_event_target" "WindowsSSMAutomationCPU" {
#   rule      = "${aws_cloudwatch_event_rule.UpdateWindowsAMI.name}"
#   target_id = "SSMAutomation"
#   arn       = "arn:aws:ssm:us-west-2:139068448383:document/UpdateWindowsAMICPU"
# }

# resource "aws_cloudwatch_event_target" "WindowsSSMAutomationGPU" {
#   rule      = "${aws_cloudwatch_event_rule.UpdateWindowsAMI.name}"
#   target_id = "SSMAutomation"
#   arn       = "arn:aws:ssm:us-west-2:139068448383:document/UpdateWindowsAMIGPU"
# }

resource "aws_cloudwatch_event_rule" "UpdateWindowsAMIFailure" {
  name        = "update-windows-ami-failure"
  description = "Sends SNS topic if automation fails or times out"

  event_pattern = <<PATTERN
{
  "source": [
    "aws.ssm"
  ],
  "detail-type": [
    "EC2 Automation Execution Status-change Notification"
  ],
  "detail": {
    "Status": [
      "Failed",
      "TimedOut"
    ]
  }
}
PATTERN
}

resource "aws_cloudwatch_event_target" "sns" {
  rule      = "${aws_cloudwatch_event_rule.UpdateWindowsAMIFailure.name}"
  target_id = "SendToSNS"
  arn       = "${aws_sns_topic.aws_logins.arn}"
}

resource "aws_sns_topic" "aws_logins" {
  name = "amicreate-failure"
}
