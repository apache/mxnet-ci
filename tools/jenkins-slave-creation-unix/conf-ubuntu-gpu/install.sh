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

#Install htop
sudo apt-get update
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

#Install nvidia drivers
#Chose the latest nvidia driver supported on Tesla driver for Ubuntu18.04
#Refer : https://www.nvidia.com/Download/driverResults.aspx/158191/en-us
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu1804/x86_64/cuda-ubuntu1804.pin
sudo mv cuda-ubuntu1804.pin /etc/apt/preferences.d/cuda-repository-pin-600
sudo apt-key adv --fetch-keys https://developer.download.nvidia.com/compute/cuda/repos/ubuntu1804/x86_64/7fa2af80.pub
sudo add-apt-repository "deb http://developer.download.nvidia.com/compute/cuda/repos/ubuntu1804/x86_64/ /"
sudo apt-get update
sudo apt-get -y install cuda-drivers

# TODO: - Disabled nvidia updates @ /etc/apt/apt.conf.d/50unattended-upgrades
#Unattended-Upgrade::Package-Blacklist {
#"nvidia-384";
#"nvidia-opencl-icd-384";

echo "Installed nvidia drivers"

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
# Get latest docker-compose; Ubuntu 18.04 has latest docker in bionic-updates, but not docker-compose and rather ships v1.17 from 2017
# See https://github.com/docker/compose/releases for latest release
# /usr/local/bin is not on the PATH in Jenkins, thus place binary in /usr/bin
sudo curl -L "https://github.com/docker/compose/releases/download/1.25.5/docker-compose-$(uname -s)-$(uname -m)" -o /usr/bin/docker-compose
sudo chmod +x /usr/bin/docker-compose
echo "Installed docker engine and docker-compose"

# Add nvidia-docker and nvidia-docker-plugin
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | \
  sudo apt-key add -
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list
sudo apt-get update

# Install nvidia docker related packages and reload the Docker daemon configuration
# Install nvidia-container toolkit and reload the Docker daemon configuration
# Refer Nvidia Docker : https://github.com/NVIDIA/nvidia-docker
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker

# Install & add nvidia container runtime to the Docker daemon
# Refer https://github.com/nvidia/nvidia-container-runtime#docker-engine-setup
sudo apt-get install nvidia-container-runtime
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo tee /etc/systemd/system/docker.service.d/override.conf <<EOF
[Service]
ExecStart=/usr/bin/dockerd --host=fd:// --add-runtime=nvidia=/usr/bin/nvidia-container-runtime
EOF
sudo systemctl daemon-reload
sudo systemctl restart docker

# Download additional scripts
sudo apt-get -y install awscli
tmpdir=$(mktemp -d)
aws s3 cp --quiet s3://$S3_CONFIG_BUCKET/$S3_CONFIG_FILE $tmpdir/scripts.tar.bz2

mkdir /home/jenkins_slave/scripts
tar -C /home/jenkins_slave/scripts -xjf $tmpdir/scripts.tar.bz2
find /home/jenkins_slave/scripts -type f -exec chmod 744 {} \;
chown -R jenkins_slave.jenkins_slave /home/jenkins_slave

# Set up swap of 50GB
fallocate -l 50G /swapfile
chown root:root /swapfile
chmod 0600 /swapfile
mkswap /swapfile
swapon /swapfile
echo /swapfile none swap sw 0 0 >> /etc/fstab

# Add auto-connecting to slave to startup
touch /home/jenkins_slave/auto-connect.log
chown -R jenkins_slave:jenkins_slave /home/jenkins_slave/
echo "@reboot jenkins_slave /home/jenkins_slave/scripts/launch-autoconnect.sh" > /etc/cron.d/jenkins-start-slave

# Write instructions to home dir
readme="Please use the following command in your cloud-init-script to specify the jenkins master
address:
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
