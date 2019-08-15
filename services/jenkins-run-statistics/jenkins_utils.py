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

JENKINS_ALL_RUNS_API = 'view/all/cc.xml?recursive'
JENKINS_RUN_METADATA_API = '{job_url}{run_id}/api/python'
JENKINS_RUN_BLUEOCEAN_API = '{jenkins_url}blue/rest/organizations/jenkins/{pipeline_paths}/runs/{run_id}/'
JENKINS_JOB_METADATA_API = '{jenkins_url}{job_paths}/api/python'

REGEX_URL_EXTRACT_JOB_NAME = re.compile(r'job\/([^\/]+)')


class JenkinsJob(object):
    """
    Object representing a Jenkins Job
    """

    def __init__(self, jenkins_url, last_run_id, job_url, full_job_name, last_build_time):
        self.jenkins_url = jenkins_url
        self.last_run_id = last_run_id
        self.job_url = job_url
        self.full_job_name = full_job_name
        self.last_scanned_run_id = 0
        self.last_build_time = dateutil.parser.parse(last_build_time)
        self.job_hierarchy = None  # Will be retrieved later if required

    def __repr__(self):
        return f'{self.full_job_name} @ {self.job_url}'

    def update_last_scanned_run_id(self, last_scanned_run_id):
        """
        Update the last scanned run id of this run.
        :param last_scanned_run_id: ID of the last scanned run
        :return: Nothing
        """
        self.last_scanned_run_id = last_scanned_run_id

    def get_job_hierarchy(self):
        """
        Query the jenkins API to get the real job hierarchy - e.g. which part of the job name is a folder, which one
        is the job name and which one is the branch name (if applicable). This is necessary because there are multiple
        methods to define Jenkins jobs.
        :return: Dictionary
        """
        if self.job_hierarchy:
            # Cached result
            return self.job_hierarchy

        # By looking at the parent job, if applicable, we can see whether we are currently part of a multi-branch job.
        # If we are, we have to take the last part of the job name as branch name instead.
        job_groups = REGEX_URL_EXTRACT_JOB_NAME.findall(self.job_url)

        self.job_hierarchy = {}
        if len(job_groups) > 1:
            # This job has a parent. Inspect it.
            job_paths = '/'.join(['job/' + job for job in job_groups[:-1]])
            url = JENKINS_JOB_METADATA_API.format(jenkins_url=self.jenkins_url, job_paths=job_paths)

            try:
                metadata = ast.literal_eval(
                    requests.get(
                        url=url,
                        params={'tree': '_class,fullName'}, allow_redirects=False).text)
            except SyntaxError:
                raise Exception(f'Unable to retrieve meta data for parent job of {self} at {url}')

            if metadata['_class'] == 'org.jenkinsci.plugins.workflow.multibranch.WorkflowMultiBranchProject':
                logging.debug('%s is part of a MultiBranchProject', self)
                branch_name = job_groups[-1]  # Last entry is the branch name
            else:
                logging.debug('%s is probably not part of a MultiBranchProject since the parent class is a %s. Thus,'
                              'considering it as independenct job.', self, metadata['_class'])
                branch_name = None

            job_name = metadata['fullName']
        else:
            logging.debug('%s has no parent, considering it a standalone job', self)
            branch_name = None
            job_name = job_groups[0]

        self.job_hierarchy['job_name'] = job_name
        self.job_hierarchy['branch_name'] = branch_name

        return self.job_hierarchy


    def get_outstanding_jenkins_runs(self):
        """
        Retrieve a list of Jenkins runs that have not been processed yet
        :return: Array of JenkinsRuns
        """
        return [JenkinsRun(parent_job=self, run_id=run_id) for run_id in
                range(self.last_scanned_run_id + 1, self.last_run_id)]


class JenkinsRun(object):
    """
    Object representing a Jenkins Run
    """

    def __init__(self, parent_job, run_id):
        self.parent_job = parent_job
        self.run_id = run_id

    def __repr__(self):
        return f'{self.parent_job.full_job_name} #{self.run_id}'

    def retrieve_metadata(self, tree_filter_string):
        """
        Retrieve this runs' metadata.
        :param tree_filter_string: A string that limits which fields are being retrieved for performance reasons.
                                   This is a Jenkins Rest API feature.
        :return: Dictionary containing the requested meta data
        """
        try:
            return ast.literal_eval(
                requests.get(url=JENKINS_RUN_METADATA_API.format(job_url=self.parent_job.job_url, run_id=self.run_id),
                             params={'tree': tree_filter_string}, allow_redirects=False).text)
        except SyntaxError:
            # Jenkins prints a 404 as HTML with a 200 code...
            logging.debug('Run %s does not exist, skipping...', self)
            return None

    def _get_blue_ocean_api(self):
        """
        Get blue ocean API endpoint for this run
        :return: URL
        """
        job_groups = REGEX_URL_EXTRACT_JOB_NAME.findall(self.parent_job.job_url)

        pipeline_paths = '/'.join(['pipelines/' + job for job in job_groups])
        return JENKINS_RUN_BLUEOCEAN_API.format(jenkins_url=self.parent_job.jenkins_url, pipeline_paths=pipeline_paths,
                                                run_id=self.run_id)

    def retrieve_nodes(self):
        """
        Retrieve all Jenkins nodes associated with this run.
        :return: List JenkinsNode
        """
        try:
            response = requests.get(url=self._get_blue_ocean_api() + 'nodes',
                             allow_redirects=True).json()
        except json.decoder.JSONDecodeError:
            # Jenkins sometimes prints a 404 as HTML with a 200 code...
            return None

        if 'code' in response and response['code'] is not 200:
            logging.error('Error retrieving nodes for run %s: %s', self, response['message'])
            return None

        jenkins_nodes = list()

        for json_node_entry in response:
            if not json_node_entry['state']:
                logging.debug('Step %s of %s is empty, skipping', json_node_entry['displayName'], self)
                logging.debug(json_node_entry)
                continue

            jenkins_nodes.append(JenkinsNode(parent_run=self, json_node_entry=json_node_entry))

        return jenkins_nodes


class JenkinsNode(object):
    """
    Object representing a Jenkins node that is part of a Jenkins run
    """
    def __init__(self, parent_run, json_node_entry):
        self.parent_run = parent_run
        self.result = json_node_entry['result']
        self.type = json_node_entry['type']
        self.display_name = json_node_entry['displayName']
        self.start_timestamp = dateutil.parser.parse(json_node_entry['startTime']).timestamp()
        self.duration_ms = json_node_entry['durationInMillis']
        self._steps_api_link = json_node_entry['_links']['steps']['href']

    def get_steps(self):
        """
        Return the underlying steps that are being executed as part of this Jenkins node
        :return:
        """
        try:
            response = requests.get(url=self.parent_run.parent_job.jenkins_url + self._steps_api_link,
                                    allow_redirects=True).json()
        except json.decoder.JSONDecodeError:
            # Jenkins sometimes prints a 404 as HTML with a 200 code...
            return None

        return [JenkinsStep(parent_step=self, json_step_entry=json_step_entry) for json_step_entry in response]


class JenkinsStep(object):
    """
    Object representing a Jenkins step that is part of a Jenkins node
    """
    def __init__(self, parent_step, json_step_entry):
        self.parent_step = parent_step
        self.duration_ms = json_step_entry['durationInMillis']


def _retrieve_jenkins_jobs(jenkins_url):
    """
    Query the Jenkins server and return all jenkins jobs and the last run id
    :return: Array of JenkinsJobs
    """
    session = XMLSession()
    r = session.get(url=jenkins_url + JENKINS_ALL_RUNS_API)
    # <Project activity="Sleeping" lastBuildStatus="Success" lastBuildLabel="756"
    # webUrl="http://jenkins.mxnet-ci.amazon-ml.com/job/Broken_Link_Checker_Pipeline/"
    # name="Broken_Link_Checker_Pipeline" lastBuildTime="2018-11-30T01:12:59Z"/>
    #
    # <Project activity="Sleeping" lastBuildStatus="Success" lastBuildLabel="1"
    # webUrl="http://jenkins.mxnet-ci.amazon-ml.com/job/incubator-mxnet/job/PR-10008/"
    # name="incubator-mxnet » PR-10008" lastBuildTime="2018-03-06T18:19:44Z"/>

    return [JenkinsJob(jenkins_url=jenkins_url, last_run_id=int(run.attrs['lastBuildLabel']),
                       job_url=run.attrs['webUrl'], full_job_name=run.attrs['name'],
                       last_build_time=run.attrs['lastBuildTime'])
            for run in r.xml.xpath('//Project')]
