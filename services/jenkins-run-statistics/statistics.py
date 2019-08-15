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
"""This script records statistics about Jenkins runs"""
from pprint import pprint

__author__ = 'Marco de Abreu'
__version__ = '0.1'

import json
import logging
import os
import ast
import re
import ssl
import sys
import time
import urllib.request
from typing import Optional
from datetime import datetime, timedelta, timezone
from typing import Dict, List
import dateutil

import boto3
from botocore.exceptions import ClientError
import botocore

import dateutil
import dateutil.parser
import dateutil.tz

import requests
from requests_xml import XMLSession

import jenkins_utils
import aws_utils

REGION_NAME = os.environ['REGION']
JENKINS_URL = os.environ['JENKINS_URL']
DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE_NAME']
CLOUDWATCH_METRIC_NAMESPACE = os.environ['CLOUDWATCH_METRIC_NAMESPACE']

MAXIMUM_LOOKBACK_TIMEFRAME_SECONDS = 60 * 60 * 24 * 7 * 2

DYNAMO_KEY_FULL_JOB_NAME = 'FULL_JOB_NAME'
DYNAMO_VALUE_LAST_SCANNED_RUN_ID = 'LAST_SCANNED_RUN_ID'


def record_jenkins_run_durations(dynamo_db, cloudwatch):
    """
    Main handler to initiate the process of recording Jenkins run durations
    :param dynamo_db: Handle to Boto DynamoDB
    :param cloudwatch:Handle to Boto CloudWatch
    :return: Nothing
    """
    # Basically get a list of all Jenkins jobs and their last run id. Then compare the last run id with our database
    # in order to determine jobs that we haven't scanned entirely or got new data in the meantime.
    # Then, retrieve all the new runs, record the metrics and update the database.
    jenkins_jobs = jenkins_utils._retrieve_jenkins_jobs(jenkins_url=JENKINS_URL)
    _process_jenkins_jobs(dynamo_db=dynamo_db, cloudwatch=cloudwatch, jenkins_jobs=jenkins_jobs)


def _process_jenkins_jobs(dynamo_db, cloudwatch, jenkins_jobs):
    """
    Process the passed Jenkins Jobs and record metrics of the underlying runs
    :param dynamo_db: Handle to Boto DynamoDB
    :param cloudwatch: Handle to Boto CloudWatch
    :param jenkins_jobs: List of Jenkins Jobs
    :return: Nothing
    """
    def generate_metric_dimensions():
        job_name = jenkins_job.get_job_hierarchy()['job_name']
        branch_name = jenkins_job.get_job_hierarchy()['branch_name']
        if branch_name and 'PR-' in branch_name:
            # Replace pull request branch names with a generalized name. We don't want to track PR branches individually
            branch_name = 'Pull Request'

        metric_dimensions = {'Job': job_name}
        if branch_name:
            metric_dimensions['Branch'] = branch_name

        return metric_dimensions

    table = dynamo_db.Table(DYNAMODB_TABLE)

    for jenkins_job in jenkins_jobs:
        time_diff = datetime.now(tz=timezone.utc) - jenkins_job.last_build_time
        if time_diff.total_seconds() >= MAXIMUM_LOOKBACK_TIMEFRAME_SECONDS:
            logging.debug('%s has last been run %d days ago, skipping since its more than two weeks', jenkins_job,
                          time_diff.days)
            continue

        last_processed_run_id = _dynamo_get_last_processed_jenkins_run_id(dynamo_table=table,
                                                                          jenkins_job_name=jenkins_job.full_job_name)
        if last_processed_run_id:
            jenkins_job.update_last_scanned_run_id(last_processed_run_id)

        outstanding_jenkins_runs = jenkins_job.get_outstanding_jenkins_runs()
        if not outstanding_jenkins_runs:
            logging.debug('%s has no outstanding runs', jenkins_job)
            continue

        metric_dimensions = generate_metric_dimensions()

        for jenkins_run in outstanding_jenkins_runs:
            if _process_jenkins_run(cloudwatch=cloudwatch, jenkins_run=jenkins_run,
                                    metric_dimensions=dict(metric_dimensions)):
                logging.info('%s has been processed, saving state in database', jenkins_run)
                _dynamo_set_last_processed_jenkins_run_id(dynamo_db=dynamo_db, jenkins_run=jenkins_run)
            else:
                logging.info('%s requested to not be processed further, aborting scan of job', jenkins_run)
                break


def _process_jenkins_run(cloudwatch, jenkins_run, metric_dimensions):
    """
    Process a single Jenkins run and record metrics accordingly
    :param jenkins_run:
    :return: True if we should continue or False if job should no longer be crawled, e.g. due to running jobs
    """
    def process_stage(jenkins_node):
        """
        Process the Jenkins node that is being considered a stage
        :param jenkins_node: Jenkins node
        :return: New stage name
        """
        # The nodes are always in the correct order, so we can use that fact to preserve the
        # information about the stage we are currently in during parallel steps.
        current_stage = jenkins_node.display_name
        stage_metric_dimensions = dict(node_metric_dimensions)
        stage_metric_dimensions['Stage'] = current_stage
        aws_utils.publish_cloudwatch_metric(
            cloudwatch=cloudwatch, metric_name='Stage Duration',
            metric_namespace=CLOUDWATCH_METRIC_NAMESPACE, value=jenkins_node.duration_ms / 1000,
            unix_timestamp=unix_timestamp, dimensions=stage_metric_dimensions, unit='Seconds')
        logging.info('= STAGE %s took %s',
                     current_stage, str(timedelta(milliseconds=jenkins_node.duration_ms)))
        return current_stage

    def process_parallel(jenkins_node):
        """
        Process the Jenkins node that is being considered a parallel node
        :param jenkins_node:
        :return:
        """
        # Determine duration of each parallel-entry by making the sum of all steps. This is
        # necessary because durationInMillis contains garbage for these nodes. Thanks, Jenkins!
        steps = jenkins_node.get_steps()
        if not steps:
            logging.error('No steps available')
            return

        parallel_duration_ms = 0
        for step in steps:
            parallel_duration_ms += step.duration_ms

        step_metric_dimensions = dict(node_metric_dimensions)
        step_metric_dimensions['Stage'] = current_stage
        step_metric_dimensions['Step'] = jenkins_node.display_name
        aws_utils.publish_cloudwatch_metric(
            cloudwatch=cloudwatch, metric_name='Step Duration', unit='Seconds',
            value=int(parallel_duration_ms / 1000), unix_timestamp=unix_timestamp,
            metric_namespace=CLOUDWATCH_METRIC_NAMESPACE, dimensions=step_metric_dimensions)

        logging.info('== STEP %s ran for %s',
                     jenkins_node.display_name, str(timedelta(milliseconds=parallel_duration_ms)))

    metadata = jenkins_run.retrieve_metadata(tree_filter_string='duration,building,timestamp,result')

    if metadata and metadata['building']:
        logging.info('%s is still running, skipping...', jenkins_run)
        return False

    # Make sure to not return eagerly because the DynamoDB entry creation has to happen to mark the run as processed

    if not metadata:
        logging.debug('Run %s does not exist, skipping...', jenkins_run)
    else:
        total_duration_ms = metadata['duration']
        unix_timestamp = metadata['timestamp'] / 1000

        time_diff = time.time() - unix_timestamp
        if time_diff >= MAXIMUM_LOOKBACK_TIMEFRAME_SECONDS:
            logging.info('Run %s is from %d days ago, skipping since its more than two weeks',
                         jenkins_run, int(time_diff/60/60/24))
        else:
            run_metric_dimensions = dict(metric_dimensions)
            run_metric_dimensions['Result'] = metadata['result']
            aws_utils.publish_cloudwatch_metric(cloudwatch=cloudwatch, metric_namespace=CLOUDWATCH_METRIC_NAMESPACE,
                                                metric_name='Total Run Duration', unix_timestamp=unix_timestamp,
                                                dimensions=run_metric_dimensions, unit='Seconds',
                                                value=total_duration_ms/1000)
            logging.info('Run %s has been running for %s', jenkins_run, str(timedelta(milliseconds=total_duration_ms)))

            nodes = jenkins_run.retrieve_nodes()

            if not nodes:
                logging.debug('Run %s has no child stages', jenkins_run)
            else:
                current_stage = 'Unknown stage'
                for jenkins_node in nodes:
                    node_metric_dimensions = dict(metric_dimensions)
                    if jenkins_node.result:  # This is none if the stage has not been reached
                        # Make sure to differentiate metrics by whether the step was successful or not. Otherwise,
                        # time measurements would be off since some jobs did not run until the end.
                        node_metric_dimensions['Result'] = jenkins_node.result
                        unix_timestamp = jenkins_node.start_timestamp

                        if jenkins_node.type == 'STAGE':
                            current_stage = process_stage(jenkins_node)
                        elif jenkins_node.type == 'PARALLEL':
                            process_parallel(jenkins_node)
                        else:
                            logging.error('Unknown stage: %s for %s', jenkins_node.type, jenkins_node)

    return True


def _dynamo_set_last_processed_jenkins_run_id(dynamo_db, jenkins_run):
    """
    Mark the passed Jenkins run as processed in the database. This allows to avoid duplicate processing in future.
    It's important that runs are processed from oldest to latest (and not in parallel) since we expect to only increase
    the 'last scanned run id'.
    :param dyanmo_db: Boto DynamoDB handle
    :param jenkins_run: Jenkins run
    :return: Nothing
    """
    table = dynamo_db.Table(DYNAMODB_TABLE)
    table.update_item(
                Key={
                    DYNAMO_KEY_FULL_JOB_NAME: jenkins_run.parent_job.full_job_name
                },
                UpdateExpression=f"set {DYNAMO_VALUE_LAST_SCANNED_RUN_ID} = :id",
                ExpressionAttributeValues={
                    ':id': jenkins_run.run_id
                }
            )


def _dynamo_get_last_processed_jenkins_run_id(dynamo_table, jenkins_job_name):
    response = dynamo_table.get_item(
        Key={
            DYNAMO_KEY_FULL_JOB_NAME: jenkins_job_name
        }
    )
    if 'Item' in response and DYNAMO_VALUE_LAST_SCANNED_RUN_ID in response['Item']:
        return int(response['Item'][DYNAMO_VALUE_LAST_SCANNED_RUN_ID])
    else:
        logging.debug('%s has not been recorded yet', jenkins_job_name)
        return None


def _configure_logging():
    logging.basicConfig()
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger('botocore').setLevel(logging.INFO)
    logging.getLogger('boto3').setLevel(logging.INFO)
    logging.getLogger('urllib3').setLevel(logging.INFO)
    logging.getLogger('requests').setLevel(logging.ERROR)
    logging.getLogger('botocore.vendored.requests.packages.urllib3.connectionpool').setLevel(logging.ERROR)


def main():
    _configure_logging()
    aws_service_objects = aws_utils.generate_aws_service_objects(region_name=REGION_NAME)
    logging.info('Starting gathering statistics')
    record_jenkins_run_durations(dynamo_db=aws_service_objects.dynamo_db, cloudwatch=aws_service_objects.cloudwatch)
    logging.info('Statistics recorded')


def lambda_handler(event, context):
    try:
        main()
        return 'Done'
    except Exception:  # pylint: disable=broad-except
        logging.exception('Unexpected exception')
        logging.fatal('Unexpected exception')
        return 'Error'
        # This try-catch is important because we have to catch all exceptions. Otherwise, the exceptions bubble up to
        # lambda and the service retries executing multiple times. We only want exactly one execution per request.



if __name__ == '__main__':
    sys.exit(main())
