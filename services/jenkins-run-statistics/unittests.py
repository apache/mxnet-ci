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
"""This script records unittest specific information"""
from pprint import pprint

__author__ = 'Chaitanya Bapat'
__version__ = '0.1'

import json
import logging
import os
import sys

import boto3
from urllib.parse import unquote_plus

import aws_utils

REGION_NAME = os.environ['REGION']
UNITTEST_ARTIFACT_REPOSITORY = os.environ['UNITTEST_ARTIFACT_REPOSITORY']


def _retrieve_s3_data(event):
    for record in event['Records']:
        bucket = record['s3']['bucket']['name']
        # key = unquote_plus(record['s3']['object']['key'])
        # download_path = '/tmp/{}{}'.format(uuid.uuid4(), key)
        print(record['s3']['object']['key'])


def _record_unit_test_duration(event, dynamo_db, cloudwatch):
    """
    Main handler to initiate the process of recording unit-test run durations
    :param dynamo_db:  Handle to Boto DynamoDB
    :param cloudwatch: Handle to Boto CloudWatch
    :return: Nothing
    """
    _retrieve_s3_data(event)


def _configure_logging():
    logging.basicConfig()
    logging.getLogger().setLevel(logging.INFO)


def main(event):
    _configure_logging()
    aws_service_objects = aws_utils.generate_aws_service_objects(region_name=REGION_NAME)
    logging.info('Starting gathering unit-test info')
    _record_unit_test_duration(event, dynamo_db=aws_service_objects.dynamo_db, cloudwatch=aws_service_objects.cloudwatch)
    logging.info('Unit-test info recorded')


def lambda_handler(event, context):
    try:
        main(event)
        return 'Lambda handler success'
    except Exception:  # pylint: disable=broad-except
        logging.exception('Unexpected exception')
        logging.fatal('Unexpected exception')
        return 'Error'

if __name__ == '__main__':
    sys.exit(main())
