#!/bin/sh

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

set -ex
mkdir /efs-ccache

# Wait until config file is available (on startup)
EFS_CONFIG_FILE_PATH=/home/jenkins_slave/ccache_efs_address
MAX_TIMEOUT=300
timeout_counter=0
while [ "$timeout_counter" -lt $MAX_TIMEOUT -a ! -e $EFS_CONFIG_FILE_PATH ]; do
  sleep 1
  timeout_counter=$((timeout_counter+1))
done
if [ -e $EFS_CONFIG_FILE_PATH ]
then
   EFS_DNS=`cat $EFS_CONFIG_FILE_PATH`
   echo "Found $EFS_CONFIG_FILE_PATH with content $EFS_DNS after $timeout_counter seconds"
   sudo mount -t nfs4 -o nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2 $EFS_DNS:/ /efs-ccache
   sudo chown jenkins_slave:jenkins_slave /efs-ccache
else
   echo "Timeout looking for $EFS_CONFIG_FILE_PATH" >&2
fi

