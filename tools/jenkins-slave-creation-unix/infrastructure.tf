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

variable "key_name" {
  type = "string"
}

variable "key_path" {
  type = "string"
}

variable "instance_type" {
  type = "string"
}

variable "secret_manager_docker_hub_arn" {
  type = "string"
}

variable "s3_config_bucket" {
  type = "string"
}

variable "s3_config_filename" {
  type = "string"
}

variable "slave_install_script" {
  type = "string"
}

variable "shell_variables_file" {
  type = "string"
}

# ftp://64.50.236.216/pub/ubuntu-cloud-images/query/xenial/server/released.txt
# https://cloud-images.ubuntu.com/locator/ec2/
variable "ami" {
  type = "string"
}

variable "instance_name" {
  type = "string"
}

variable "aws_region" {
  type = "string"
}

# Input variables (done by script)
variable "slave_config_tar_path" {
  type = "string"
}

provider "aws" {
  region = "${var.aws_region}"
}

# Store terraform state in S3 instead of local.
terraform {
	backend "s3" {
	    encrypt = true
        key = "terraform.tfstate"
        # Remaining config is defined in $CONFIG_DIR/infrastructure_backend.tfvars
        # See https://www.terraform.io/docs/backends/config.html for more details
    }
}

data "template_cloudinit_config" "user_data" {
	base64_encode = true

    # Important: This part has to be in first place as it gets mapped to
    # /var/lib/cloud/instance/scripts/part-001
    # This is a hack, but there's no other way to reference other scripts
    part {
        content_type = "text/x-shellscript"
        content = "${file("${var.shell_variables_file}")}"
    }

	
    part {
        content_type = "text/x-shellscript"
        content = "${file("${var.slave_install_script}")}"
    }
}

resource "aws_iam_role" "jenkins_slave_role" {
  name               = "jenkins_slave_role"
  assume_role_policy = <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Action": "sts:AssumeRole",
      "Principal": {
        "Service": "ec2.amazonaws.com"
      },
      "Effect": "Allow",
      "Sid": ""
    }
  ]
}
POLICY
}

resource "aws_iam_role" "jenkins_restricted_slave_role" {
  name               = "jenkins_restricted_slave_role"
  assume_role_policy = <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Action": "sts:AssumeRole",
      "Principal": {
        "Service": "ec2.amazonaws.com"
      },
      "Effect": "Allow",
      "Sid": ""
    }
  ]
}
POLICY
}


resource "aws_iam_policy" "jenkins_slave_s3_read_policy" {
    name        = "jenkins_slave_s3_read_policy"
    description = "Policy to grant Jenkins Slave S3 read-access to the associated bucket"
    policy      = <<POLICY
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetBucketLocation",
                "s3:ListAllMyBuckets"
            ],
            "Resource": "arn:aws:s3:::*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::${var.s3_config_bucket}"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject"
            ],
            "Resource": [
                "arn:aws:s3:::${var.s3_config_bucket}/*"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "ec2:CreateTags"
            ],
            "Resource": [
                "arn:aws:s3:::instance/*"
            ]
        }

        
    ]
}
POLICY
}


resource "aws_iam_policy_attachment" "jenkins_slave_s3_read_policy_attach" {
  name       = "jenkins_slave_s3_read_policy_attach"
  roles      = [
    "${aws_iam_role.jenkins_slave_role.name}",
    "${aws_iam_role.jenkins_restricted_slave_role.name}"
  ]
  policy_arn = "${aws_iam_policy.jenkins_slave_s3_read_policy.arn}"
}

resource "aws_iam_policy" "jenkins_slave_ec2_create_tags" {
    name        = "jenkins_slave_ec2_create_tags"
    description = "Policy to grant Jenkins Slave permission to create tags in order to rename an instance"
    policy      = <<POLICY
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "ec2:CreateTags"
            ],
            "Resource": [
                "arn:aws:ec2:*:*:instance/*"
            ]
        }

        
    ]
}
POLICY
}

resource "aws_iam_policy_attachment" "jenkins_slave_ec2_create_tags_attach" {
  name       = "jenkins_slave_ec2_create_tags_attach"
  roles      = [
      "${aws_iam_role.jenkins_slave_role.name}",
      "${aws_iam_role.jenkins_restricted_slave_role.name}"
  ]
  policy_arn = "${aws_iam_policy.jenkins_slave_ec2_create_tags.arn}"
}

resource "aws_iam_policy" "jenkins_restricted_slave_secrets_docker_cache" {
    name        = "jenkins_restricted_slave_secrets_docker_cache"
    description = "Policy to grant restricted Jenkins Slave permission to the Secret Manager to do Docker Hub credential retrieval for distributed Docker cache"
    policy      = <<POLICY
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "secretsmanager:DescribeSecret",
                "secretsmanager:List*"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": "secretsmanager:*",
            "Resource": [
                "${var.secret_manager_docker_hub_arn}"
            ]
        }
    ]
}
POLICY
}

# Only apply this permission to restricted slaves!!!
resource "aws_iam_policy_attachment" "jenkins_restricted_slave_secrets_docker_cache_attach" {
  name       = "jenkins_restricted_slave_secrets_docker_cache_attach"
  roles      = ["${aws_iam_role.jenkins_restricted_slave_role.name}"]
  policy_arn = "${aws_iam_policy.jenkins_restricted_slave_secrets_docker_cache.arn}"
}

resource "aws_iam_instance_profile" "jenkins_slave_profile" {
  name  = "jenkins_slave_profile"
  role = "${aws_iam_role.jenkins_slave_role.name}"
}

resource "aws_iam_instance_profile" "jenkins_restricted_slave_profile" {
  name  = "jenkins_restricted_slave_profile"
  role = "${aws_iam_role.jenkins_restricted_slave_role.name}"
}

resource "aws_instance" "mxnet-slave" {
  instance_type = "${var.instance_type}"
  ami = "${var.ami}"
  iam_instance_profile   = "${aws_iam_instance_profile.jenkins_slave_profile.name}"

  # The name of our SSH keypair you've created and downloaded
  # from the AWS console.
  #
  # https://console.aws.amazon.com/ec2/v2/home?region=us-west-2#KeyPairs:
  #
  key_name = "${var.key_name}"

  vpc_security_group_ids =  [
    "REDACTED",
    "REDACTED"
  ]

  user_data = "${data.template_cloudinit_config.user_data.rendered}"

  tags = {
    "Name" = "${var.instance_name}"
  }

  
  root_block_device {
    volume_type = "gp2"
    volume_size = 350
    delete_on_termination = true
  }

  # Wait for S3 bucket as it's needed during startup
  depends_on = [
    "aws_s3_bucket_object.slave_config_s3"
  ]
}

resource "aws_s3_bucket" "slave_config_bucket" {
  bucket = "${var.s3_config_bucket}"
  acl    = "private"
}

resource "aws_s3_bucket_object" "slave_config_s3" {
  bucket = "${aws_s3_bucket.slave_config_bucket.id}"
  key    = "${var.s3_config_filename}"
  source = "${var.slave_config_tar_path}"
  etag   = "${filemd5(var.slave_config_tar_path)}"
}
