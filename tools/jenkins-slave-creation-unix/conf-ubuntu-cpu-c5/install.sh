#!/bin/bash

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

set -e
set -x

# Load variables
source /var/lib/cloud/instance/scripts/part-001

whoami

#Setup jenkins user
sudo useradd jenkins_slave

#Prevent log in
sudo usermod -L jenkins_slave
sudo mkdir -p /home/jenkins_slave/remoting
sudo chown -R jenkins_slave:jenkins_slave /home/jenkins_slave

#Remove preinstalled packaged
sudo apt-get -y purge openjdk*
sudo apt-get -y purge nvidia*
echo "Purged packages"

#Add third party repositories
sudo add-apt-repository -y ppa:graphics-drivers/ppa
sudo curl -fsSL https://apt.dockerproject.org/gpg | sudo apt-key add -
sudo apt-key fingerprint 58118E89F3A912897C070ADBF76221572C52609D
sudo add-apt-repository "deb https://apt.dockerproject.org/repo/  ubuntu-xenial main"
sudo apt-get update
echo "Added third party repositories"

#Install htop
sudo apt-get -y install htop

#Install java
sudo apt-get -y install openjdk-8-jre

#Install git
sudo apt-get -y install git
sudo -H -S -u jenkins_slave git config --global user.email "mxnet-ci"
sudo -H -S -u jenkins_slave git config --global user.name "mxnet-ci"

#Install python3, pip3 and dependencies for auto-connect.py
sudo apt-get -y install python3 python3-pip
sudo pip3 install boto3 python-jenkins joblib docker

echo "Installed htop, java, git and python"


#Install docker engine
sudo apt-get install -y apt-transport-https ca-certificates curl software-properties-common
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
sudo apt-key fingerprint 0EBFCD88
sudo add-apt-repository \
   "deb [arch=amd64] https://download.docker.com/linux/ubuntu \
   $(lsb_release -cs) \
   stable"
sudo apt-get update
sudo apt-get install -y docker-ce
sudo usermod -aG docker jenkins_slave
sudo systemctl enable docker #Enable docker to start on startup
sudo service docker restart
echo "Installed docker engine"

# Download additional scripts
sudo apt-get -y install awscli
tmpdir=$(mktemp -d)
aws s3 cp --quiet s3://$S3_CONFIG_BUCKET/$S3_CONFIG_FILE $tmpdir/scripts.tar.bz2

mkdir /home/jenkins_slave/scripts
tar -C /home/jenkins_slave/scripts -xjf $tmpdir/scripts.tar.bz2
find /home/jenkins_slave/scripts -type f -exec chmod 744 {} \;
chown -R jenkins_slave.jenkins_slave /home/jenkins_slave

# Set up swap of 100GB
fallocate -l 100G /swapfile
chown root:root /swapfile
chmod 0600 /swapfile
mkswap /swapfile
swapon /swapfile
echo /swapfile none swap sw 0 0 >> /etc/fstab

# Add auto-connecting to slave to startup
touch /home/jenkins_slave/auto-connect.log
chown -R jenkins_slave:jenkins_slave /home/jenkins_slave/
echo "@reboot jenkins_slave /home/jenkins_slave/scripts/launch-autoconnect.sh" > /etc/cron.d/jenkins-start-slave

# Install NFS client for EFS
sudo apt-get -y install nfs-common

# Auto-mount EFS on startup
echo "@reboot root /home/jenkins_slave/scripts/launch-ccache-mount-efs.sh" > /etc/cron.d/ccache-mount-efs

# Write instructions to home dir
readme="Please use the following command in your cloud-init-script to specify the jenkins master address:
#!/bin/bash
echo 'http://jenkins.mxnet-ci.amazon-ml.com/' > /home/jenkins_slave/jenkins_master_url
echo 'http://jenkins-priv.mxnet-ci.amazon-ml.com/' > /home/jenkins_slave/jenkins_master_private_url


Optional:
echo 'mxnet-linux-cpu10' > /home/jenkins_slave/jenkins_slave_name
"
echo "$readme" > /home/ubuntu/readme.txt


echo "Setup completed"

# For testing use reboot, but lateron just turn off the instance to prepare AMI generation
# reboot
shutdown -h now
