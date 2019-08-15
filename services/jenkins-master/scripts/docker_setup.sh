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

# To verify if these steps execute correctly, you can check /var/log/cloud-init-output.log in the instances
# Cloud init doesn't log anymore, so we log to user-data log and syslog

# UserData script which installs docker and code deploy agent in AML / Ubuntu

set -e
set -x

#Just log to cloud-init-output.log
#exec > >(tee -a /var/log/user-data.log|logger -t user-data ) 2>&1

DISTRO=$(awk -F= '/^NAME/{print $2}' /etc/os-release)
DISTRO=${DISTRO//\"/}

echo "Running on $DISTRO"

function install_docker_ubuntu() {
  #apt-get -y install docker docker.io
  export DEBIAN_FRONTEND=noninteractive
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
  add-apt-repository \
     "deb [arch=amd64] https://download.docker.com/linux/ubuntu \
        $(lsb_release -cs) \
           stable"
  apt-get update
  apt-get -y install docker-ce
  service docker restart
  usermod -a -G docker ubuntu
}

function install_docker_aml() {
    yum -y install docker.x86_64
    sudo usermod -a -G docker ec2-user
    service docker restart
}

function install_code_deploy_agent() {
  # Install code deploy agent
  pushd .
  TMP_INSTALL=/tmp/code_deploy
  mkdir -p $TMP_INSTALL
  cd $TMP_INSTALL
  wget https://aws-codedeploy-eu-central-1.s3.amazonaws.com/latest/install
  chmod +x ./install
  ./install auto
  popd
  rm -rf $TMP_INSTALL
}



case $DISTRO in
"Ubuntu")
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get -y install ruby wget vim-nox silversearcher-ag htop
  install_code_deploy_agent
  install_docker_ubuntu
  ;;
"Amazon Linux AMI")
  echo "AL"
  install_docker_aml
  install_code_deploy_agent
  yum -y install git python35
  ;;
*)
  echo "?"
  ;;
esac





# Use the ephemeral storage for docker so we don't run out of space
function setup_docker_ephemeral() {
  if mountpoint -q -- /mnt; then
    echo "Using /mnt/docker for docker storage"
    service docker stop
    mkdir -p /mnt/docker
    mount -o bind /mnt/docker/ /var/lib/docker/
    service docker start
  fi
}


function setup_ephemeral_raid() {
    METADATA_URL_BASE="http://169.254.169.254/2016-09-02/"
    DRIVE_SCHEME=`mount | perl -ne 'if(m#/dev/(xvd|sd).\d?#) { print "$1\n"; exit}'`

    drives=""
    ephemeral_count=0
    ephemerals=$(curl --silent $METADATA_URL_BASE/meta-data/block-device-mapping/ | grep ephemeral)
    for e in $ephemerals; do
        echo "Probing $e .."
        device_name=$(curl --silent $METADATA_URL_BASE/meta-data/block-device-mapping/$e)
        # might have to convert 'sdb' -> 'xvdb'
        device_name=$(echo $device_name | sed "s/sd/$DRIVE_SCHEME/")
        device_path="/dev/$device_name"

        # test that the device actually exists since you can request more ephemeral drives than are available
        # for an instance type and the meta-data API will happily tell you it exists when it really does not.
        if [ -b $device_path ]; then
            echo "Detected ephemeral disk: $device_path"
            drives="$drives $device_path"
            ephemeral_count=$((ephemeral_count + 1 ))
            umount $device_path || true
        else
            echo "Ephemeral disk $e, $device_path is not present. skipping"
        fi
    done

    if [ "$ephemeral_count" = 0 ]; then
        echo "No ephemeral disk detected."
        return 1
    fi

    # overwrite first few blocks in case there is a filesystem, otherwise mdadm will prompt for input
    for drive in $drives; do
        dd if=/dev/zero of=$drive bs=4096 count=1024
    done

    partprobe || true
    # Force in case there's only one drive
    mdadm --create --force --verbose /dev/md0 --level=0 -c256 --raid-devices=$ephemeral_count $drives
    echo DEVICE $drives | tee /etc/mdadm.conf
    mdadm --detail --scan | tee -a /etc/mdadm.conf
    blockdev --setra 65536 /dev/md0
    mkfs -t ext4 -m 0 /dev/md0
    mount -t ext4 -o noatime /dev/md0 /mnt

    # Remove xvdb/sdb from fstab
    chmod 777 /etc/fstab
    sed -i "/${DRIVE_SCHEME}b/d" /etc/fstab

    # Make raid appear on reboot
    echo "/dev/md0 /mnt ext4 noatime 0 0" | tee -a /etc/fstab
    return 0
}

# Add your custom initialization code below
(setup_ephemeral_raid && setup_docker_ephemeral) || true

echo "UserData initialization is done"
