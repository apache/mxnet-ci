#!/usr/bin/env python3

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

# -*- coding: utf-8 -*-

import os
import boto3
import logging

from PRStatusBot import PRStatusBot, GithubObj

logging.getLogger().setLevel(logging.INFO)
logging.getLogger('boto3').setLevel(logging.CRITICAL)
logging.getLogger('botocore').setLevel(logging.CRITICAL)

SQS_CLIENT = boto3.client('sqs')


def send_to_sqs(event, context):

    response = (SQS_CLIENT.send_message(
        QueueUrl=os.getenv('SQS_URL'),
        MessageBody=str(event)
    ))

    logging.info('Response: {}'.format(response))
    status = response['ResponseMetadata']['HTTPStatusCode']
    if status == 200:
        logging.info('Enqueued to SQS')
    else:
        logging.error('Unable to enqueue to SQS')

    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"}
    }


def run_lambda(event, context):
    logging.info(f'event {event}')
    github_obj = GithubObj(apply_secret=True)
    pr_status_bot = PRStatusBot(github_obj=github_obj.github_object, apply_secret=True)

    try:
        pr_status_bot.parse_webhook_data(event)
    except Exception as e:
        logging.error("CI bot raised an exception! %s", exc_info=e)
    logging.info("Lambda triggered successfully")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    run_lambda(None, None)
