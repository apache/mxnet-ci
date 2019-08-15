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
# Create temporary directory on the CI
ssh -C ubuntu@jenkins.mxnet-ci.amazon-ml.com "bash -s" << EOS
set -e
set -x
sudo su
rm -rf /home/ubuntu/jenkins/
mkdir /home/ubuntu/jenkins/
chown ubuntu.ubuntu /home/ubuntu/jenkins/
EOS

# Copy host files to the temp CI dir
rsync -zvaP jenkins/ ubuntu@jenkins.mxnet-ci.amazon-ml.com:jenkins/

# Stop running jenkins, preserve state-informations, deploy the changes and start Jenkins
ssh -C ubuntu@jenkins.mxnet-ci.amazon-ml.com "bash -s" <<EOF
set -e
set -x
sudo su
service jenkins stop
mv -t /home/ubuntu/jenkins /var/lib/jenkins/workspace/ /var/lib/jenkins/updates/
/var/lib/jenkins/logs/
/var/lib/jenkins/.cache//var/lib/jenkins/fingerprints//var/lib/jenkins/org.jenkinsci.plugins.github.GitHubPlugin.cache/
/var/lib/jenkins/builds/
rsync -vaP /home/ubuntu/jenkins/ /var/lib/jenkins/
rm -rf /home/ubuntu/jenkins/
chown -R jenkins.jenkins /var/lib/jenkins/
service jenkins start
EOF

