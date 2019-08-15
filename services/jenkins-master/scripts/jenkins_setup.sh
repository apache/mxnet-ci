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

set -x
set -e

# Just log to cloud-init-output.log
# exec > >(tee -a /var/log/user-data.log|logger -t user-data ) 2>&1

export DEBIAN_FRONTEND=noninteractive

#########################
# Import variables
source /var/lib/cloud/instance/scripts/part-001

# Validate that environment variables are set
if [ -z "$DNS_ADDRESS" ]; then
    echo "Need to set DNS_ADDRESS"
    exit 1
fi

if [ -z "$S3_MASTER_BUCKET" ]; then
    echo "Need to set S3_MASTER_BUCKET"
    exit 1
fi

#########################

#########################
# Hostname
echo $DNS_ADDRESS > /etc/hostname
hostname $DNS_ADDRESS
echo 'search $DNS_ADDRESS' >> /etc/resolv.conf

#########################
# Install jenkins. Use weekly instead of stable due to high number of security vulnerabilities
wget -q -O - https://pkg.jenkins.io/debian/jenkins.io.key | sudo apt-key add -
echo deb http://pkg.jenkins.io/debian binary/ > /etc/apt/sources.list.d/jenkins.list
apt-get update
apt-get -y install openjdk-8-jre-headless
apt-get -y install jenkins mailutils
service jenkins stop

#########################
rm -rf /var/lib/jenkins
mkdir /var/lib/jenkins
chown -R jenkins.jenkins /var/lib/jenkins
#########################

#########################
#Port 1-1000 are only acccessible as root. Jenkins does not run as root, thus port forwarding is
#required
network_interface=$(ip link | awk -F: '$0 !~ "lo|vir|wl|^[^0-9]"{print $2}')
iptables -t nat -I PREROUTING -p tcp -i $network_interface --dport 80 -j REDIRECT --to-ports 8080
iptables -t nat -I PREROUTING -p tcp -i $network_interface --dport 443 -j REDIRECT --to-ports 8081
apt-get -y install iptables-persistent
#########################

#########################
# Attach Jenkins state EBS volume
mkdir /ebs_jenkins_state

# Wait until volume mounted
until [ -e /dev/nvme1n1 ]
do
    echo 'Waiting for /dev/nvme1n1 to be mounted'
    sleep 1
done

mount /dev/nvme1n1 /ebs_jenkins_state/

# Ensure volume is mounted upon restart
sudo su root -c '(crontab -l 2>/dev/null; echo "@reboot /bin/mount /dev/nvme1n1 /ebs_jenkins_state") | crontab -'

chown -R jenkins.jenkins /ebs_jenkins_state
#########################

#########################
# Unpack preconfigured jenkins
apt-get -y install awscli
tmpdir=$(mktemp -d)
aws s3 cp --quiet s3://$S3_MASTER_BUCKET/jenkins/jenkins.tar.bz2 $tmpdir
aws s3 cp --quiet s3://$S3_MASTER_BUCKET/jenkins/jenkins_plugins.tar.bz2 $tmpdir

# Softlink state and cache files
source /var/lib/cloud/instance/scripts/part-002
chown -R jenkins.jenkins /ebs_jenkins_state

# Copy preconfigured jenkins
tar -C /var/lib/jenkins -xjf $tmpdir/jenkins.tar.bz2
tar -C /var/lib/jenkins -xjf $tmpdir/jenkins_plugins.tar.bz2
chown -R jenkins.jenkins /var/lib/jenkins
#########################



#########################
# Set jenkins arguments (enable https)
sed -i 's#JENKINS_ARGS.*#JENKINS_ARGS="--webroot=/var/cache/$NAME/war --httpPort=8080 --httpsPort=8081"#' /etc/default/jenkins
sed -i 's#JAVA_ARGS.*#JAVA_ARGS="-Xmx8192m -Xms512m -XX:+CMSClassUnloadingEnabled -XX:+UseConcMarkSweepGC -Djava.awt.headless=true"#' /etc/default/jenkins
#########################

service jenkins start
echo "Jenkins setup completed successfully"
