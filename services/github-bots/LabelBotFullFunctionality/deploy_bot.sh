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

# Script to deploy the label bot to our dev account
set -e
export AWS_PROFILE=mxnet-ci-dev

dest_account="REDACTED"
bot_account="REDACTED"

sed "s/###HERE###/$dest_account/g" log-access-trust-policy.json-template > log-access-trust-policy.json
sed "s/###HERE###/$bot_account/g" log-access-policy.json-template > log-access-policy.json

aws iam create-role --role-name LabelBotLogAccessRole --assume-role-policy-document file://log-access-trust-policy.json
aws iam create-policy --policy-name LabelBotLogAccessPolicy --policy-document file://log-access-policy.json
aws iam attach-role-policy --policy-arn arn:aws:iam::$bot_account:policy/LabelBotLogAccessPolicy --role-name LabelBotLogAccessRole

sls deploy -v
