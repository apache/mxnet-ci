#!/usr/bin/env python
# -*- coding: utf-8 -*-
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

import time
from datetime import datetime, timedelta, timezone
import logging
from collections import namedtuple

import boto3
from botocore.exceptions import ClientError


AwsServiceObjectsTuple = namedtuple('AwsServiceObjectsTuple', ['dynamo_db', 'cloudwatch'])

CLOUDWATCH_MAXIMUM_LOOKBACK_TIMEFRAME_SECONDS = 60 * 60 * 24 * 7 * 2


def generate_aws_service_objects(region_name):
    """
    Generate AWS Boto objects
    :return: AwsServiceObjectsTuple object
    """
    dynamo_db = boto3.resource('dynamodb', region_name=region_name)
    cloudwatch = boto3.client('cloudwatch')

    return AwsServiceObjectsTuple(dynamo_db=dynamo_db, cloudwatch=cloudwatch)


def publish_cloudwatch_metric(cloudwatch, metric_namespace, metric_name, value, unix_timestamp, dimensions, unit='Milliseconds'):
    # CloudWatch does not allow submission older than 2 weeks.
    if time.time() - unix_timestamp >= CLOUDWATCH_MAXIMUM_LOOKBACK_TIMEFRAME_SECONDS:
        logging.info('Skipping submission of CloudWatch metric that was older than 2 weeks.')
        return

    try:
        cloudwatch.put_metric_data(
            MetricData=[
                {
                    'MetricName': metric_name,
                    'Dimensions': [{'Name': name, 'Value': value} for name, value in dimensions.items()],
                    'Unit': unit,
                    'Value': value,
                    'Timestamp': datetime.utcfromtimestamp(unix_timestamp)
                }
            ],
            Namespace=metric_namespace
        )
    except ClientError as e:
        if e.response['Error']['Code'] == 'InvalidParameterValue':
            logging.info('Skipping submission of CloudWatch metric that was older than 2 weeks.')
            logging.exception('Exception:')
        else:
            raise
