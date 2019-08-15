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

echo "Deployment stage (test, prod)"
read config_dir

if [ "$config_dir" == "test" ]; then
    echo "Deploying to test"
    export AWS_PROFILE=mxnet-ci-dev
    sls deploy -s test
elif [ "$config_dir" == "prod" ]; then
    echo "Deploying to prod"
    export AWS_PROFILE=mxnet-ci
    sls deploy -s prod
else
    echo "Unrecognized stage: ${config_dir}"
fi

