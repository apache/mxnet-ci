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

#
# Sync modifications to jenkins configuration to local
#


set -e
set -x

# Work around permissions of /var/lib/jenkins
ssh -C ubuntu@jenkins.mxnet-ci.amazon-ml.com "bash -s" <<EOS
set -e
set -x
sudo su
mkdir -p /home/ubuntu/jenkins
rsync --delete --exclude="workspace/" --exclude="updates/" --exclude="logs/" --exclude=".cache/" --exclude="fingerprints/" --exclude="org.jenkinsci.plugins.github.GitHubPlugin.cache/" --exclude="builds/" -vaP /var/lib/jenkins/ /home/ubuntu/jenkins
chown -R ubuntu.ubuntu /home/ubuntu/jenkins
EOS

rsync --delete -zvaP ubuntu@jenkins.mxnet-ci.amazon-ml.com:jenkins/ jenkins/
rm -rf jenkins/.cache
rm -rf jenkins/logs
rm -rf jenkins/fingerprints
rm -rf jenkins/org.jenkinsci.plugins.github.GitHubPlugin.cache/*



ssh -C ubuntu@jenkins.mxnet-ci.amazon-ml.com "bash -s" <<EOS
rm -rf /home/ubuntu/jenkins
EOS
