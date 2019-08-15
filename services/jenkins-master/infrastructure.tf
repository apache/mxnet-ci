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

variable "vpc_id" {
  type = "string"
}

variable "additional_security_group_ids" {
 type = "list"
}

variable "jenkins_config_bucket" {
  type = "string"
}

variable "zone_id" {
  type = "string"
}

variable "domain" {
  type = "string"
}

variable "shell_variables_file" {
  type = "string"
}

# AMI IDs can be retrieved at
# ftp://64.50.236.216/pub/ubuntu-cloud-images/query/xenial/server/released.txt
variable "ami" {
  type = "string"
  default = "ami-bd8f33c5" # Ubuntu 16.04 from 20180122
}

variable "instance_name" {
  type = "string"
}

variable "aws_availability_zone" {
  type = "string"
}

variable "aws_region" {
  type = "string"
}

variable "aws_access_key" {
  type = "string"
}

variable "aws_secret_key" {
  type = "string"
}

variable "ebs_volume_jenkins_master_state_volume_id" {
  type = "string"
}

provider "aws" {
  access_key = "${var.aws_access_key}"
  secret_key = "${var.aws_secret_key}"
  region = "${var.aws_region}"
}

# Store terraform state in S3 instead of local.
terraform {
	backend "s3" {
	    key = "terraform.tfstate"

        # TODO: Lock statefile using dynamo db to prevent overriding statefiles if multiple
        # people run terraform at the same time
        # dynamodb_table = "terraform-state-${var.jenkins_config_bucket}-dynamo"

        # Remaining config is defined in $CONFIG_DIR/infrastructure_backend.tfvars
        # See https://www.terraform.io/docs/backends/config.html for more details
    }
}

data "template_cloudinit_config" "user_data" {
    # gzip = true
    base64_encode = true

    # Important: This part has to be in first place as it gets mapped to
    # /var/lib/cloud/instance/scripts/part-001
    # This is a hack, but there's no other way to reference other scripts
    part {
        content_type = "text/x-shellscript"
        content = "${file("${var.shell_variables_file}")}"
    }

    # part-002
    part {
        content_type = "text/x-shellscript"
        content = "${file("temp/jenkins_symlinks.sh")}"
    }


    # No Docker required on jenkins master
    #part {
    #    content_type = "text/x-shellscript"
    #    content = "${file("scripts/docker_setup.sh")}"
    #}
    part {
        content_type = "text/x-shellscript"
        content = "${file("scripts/jenkins_setup.sh")}"
    }
}

# Require in order to allow attaching policies, so called trust relationship policy document
resource "aws_iam_role" "jenkins_master_role" {
  name               = "jenkins_master_role"
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

resource "aws_iam_policy" "jenkins_master_s3_read_policy" {
  name        = "jenkins_master_s3_read_policy"
  description = "Policy to grant Jenkins Master S3 read-access to the associated bucket"
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
                "arn:aws:s3:::${var.jenkins_config_bucket}"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject"
            ],
            "Resource": [
                "arn:aws:s3:::${var.jenkins_config_bucket}/*"
            ]
        }
    ]
}
POLICY
}

resource "aws_iam_policy_attachment" "jenkins_master_s3_read_policy_attach" {
  name       = "jenkins_master_s3_read_policy_attach"
  roles      = ["${aws_iam_role.jenkins_master_role.name}"]
  policy_arn = "${aws_iam_policy.jenkins_master_s3_read_policy.arn}"
}

resource "aws_iam_instance_profile" "jenkins_master_profile" {
  name  = "jenkins_master_profile"
  role = "${aws_iam_role.jenkins_master_role.name}"
}

resource "aws_security_group" "allow_all_https" {
  name        = "tf_allow_all_https2"
  description = "Allow all inbound traffic to https"

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }
}

resource "aws_security_group" "allow_all_www" {
  name        = "tf_allow_all_www2"
  description = "Allow all inbound traffic to www"

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }
}


resource "aws_instance" "mxnet-ci" {
  # The connection block tells our provisioner how to
  # communicate with the resource (instance)
  connection {
    # The default username for our AMI
    user = "ubuntu"

    # The path to your keyfile
    key_file = "${var.key_path}"
  }

  # subnet ID for our VPC TODO
  # subnet_id = "${var.vpc_id}"
  # the instance type we want, comes from rundeck
  instance_type = "${var.instance_type}"

  availability_zone = "${var.aws_availability_zone}"

  # Spot instance params:
  #spot_price = "${var.spot_price}"
  #wait_for_fulfillment = "true"

  # Lookup the correct AMI based on the region
  # we specified
  ami = "${var.ami}"

  iam_instance_profile   = "${aws_iam_instance_profile.jenkins_master_profile.name}"
  # The name of our SSH keypair you've created and downloaded
  # from the AWS console.
  #
  # https://console.aws.amazon.com/ec2/v2/home?region=us-west-2#KeyPairs:
  #
  key_name = "${var.key_name}"

  #vpc_security_group_ids = "${var.security_groups_ids}"

  vpc_security_group_ids =  ["${
    concat(
      list(aws_security_group.allow_all_https.id),
      list(aws_security_group.allow_all_www.id),
      var.additional_security_group_ids
    )
  }"]
  user_data = "${data.template_cloudinit_config.user_data.rendered}"

  # We set the name as a tag. Not supported for spot instances:
  # See https://github.com/hashicorp/terraform/issues/3263
  tags {
    "Name" = "${var.instance_name}"
  }


  root_block_device {
    volume_type = "gp2"
    volume_size = 1000
    #iops = 15000
    delete_on_termination = true
  }

  # Wait for S3 bucket as it's needed during startup
  depends_on = [
    "aws_s3_bucket_object.jenkins_config_s3",
    "aws_s3_bucket_object.jenkins_plugins_s3"
  ]
}

resource "aws_s3_bucket" "jenkins_config_bucket" {
  bucket = "${var.jenkins_config_bucket}"
  acl    = "private"
}

resource "aws_s3_bucket_object" "jenkins_config_s3" {
  bucket = "${aws_s3_bucket.jenkins_config_bucket.id}"
  key    = "jenkins/jenkins.tar.bz2"
  source = "temp/jenkins.tar.bz2"
  etag   = "${md5(file("temp/jenkins.tar.bz2"))}"
}

resource "aws_s3_bucket_object" "jenkins_plugins_s3" {
  bucket = "${aws_s3_bucket.jenkins_config_bucket.id}"
  key    = "jenkins/jenkins_plugins.tar.bz2"
  source = "temp/jenkins_plugins.tar.bz2"
  etag   = "${md5(file("temp/jenkins_plugins.tar.bz2"))}"
}

# TODO: Check for race conditions. Just in case:
# https://github.com/hashicorp/terraform/issues/2740#issuecomment-288549352
resource "aws_volume_attachment" "ebs_jenkins_master_state" {
  device_name = "/dev/sdf"
  volume_id   = "${var.ebs_volume_jenkins_master_state_volume_id}"
  instance_id = "${aws_instance.mxnet-ci.id}"
}

#output "user_data" {
#    value = "${data.template_cloudinit_config.user_data.rendered}"
#}


resource "aws_route53_record" "mxnet-ci" {
  zone_id = "${var.zone_id}"
  name    = "jenkins.${var.domain}"
  type    = "A"
  ttl     = "60"
  records = ["${aws_instance.mxnet-ci.public_ip}"]
}

resource "aws_route53_record" "mxnet-ci-private" {
  zone_id = "${var.zone_id}"
  name    = "jenkins-priv.${var.domain}"
  type    = "A"
  ttl     = "60"
  records = ["${aws_instance.mxnet-ci.private_ip}"]
}

output "address" {
  value = "${aws_instance.mxnet-ci.public_dns}"
}

output "mxnet-ci" {
  value = "${aws_route53_record.mxnet-ci.fqdn}"
}
