#!/usr/bin/env python

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

"""This script automatically generates the daily CI report. It will be sent out daily at 6AM UTC."""
from pprint import pprint

import json
import logging
import os
import re
import ssl
import sys
import urllib.request
from typing import Optional
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import boto3
import dateutil
import dateutil.parser
import dateutil.tz
from jinja2 import Template
from pydantic import BaseModel

__author__ = 'Pedro Larroy, Marco de Abreu, Anton Chernov, Jose Luis Contreras'
__version__ = '0.4'

ENABLED_BRANCHES = ['master', 'v1.4.x', 'v1.5.x']

ENABLED_JOBS = {
    'Broken_Link_Checker_Pipeline': None,
    'mxnet-validation/centos-cpu': ENABLED_BRANCHES,
    'mxnet-validation/centos-gpu': ENABLED_BRANCHES,
    'mxnet-validation/clang': ENABLED_BRANCHES,
    'mxnet-validation/edge': ENABLED_BRANCHES,
    'mxnet-validation/miscellaneous': ENABLED_BRANCHES,
    'mxnet-validation/sanity': ENABLED_BRANCHES,
    'mxnet-validation/unix-cpu': ENABLED_BRANCHES,
    'mxnet-validation/unix-gpu': ENABLED_BRANCHES,
    'mxnet-validation/website': ENABLED_BRANCHES,
    'mxnet-validation/windows-cpu': ENABLED_BRANCHES,
    'mxnet-validation/windows-gpu': ENABLED_BRANCHES,
    'NightlyTests': ENABLED_BRANCHES,
    'NightlyTestsForBinaries': ENABLED_BRANCHES,
    'restricted-backwards-compatibility-checker': None,
    'restricted-website-build': None,
    'restricted-website-publish': None
}

ENABLED_PIPELINES = set([x.partition('/')[0] for x in ENABLED_JOBS])


REGION_NAME = os.environ['REGION']
EMAIL_SENDER = os.environ['EMAIL_SENDER']
EMAIL_RECEIVER = os.environ['EMAIL_RECEIVER']
JENKINS_URL = os.environ['JENKINS_URL']
FLAKY_TESTS_URL = 'https://github.com/apache/incubator-mxnet/issues?q=is%3Aopen+is%3Aissue+label%3AFlaky'
DISABLED_TESTS_URL = 'https://github.com/apache/incubator-mxnet/issues?q=is%3Aopen+is%3Aissue+label%3A%22Disabled' \
                     '+test%22'

ci_report_template = Template(
    '<style>'
    'html *{ font-family: Helvetica, Arial, sans-serif !important;}'
    'table, th, td { border: 1px solid grey; border-collapse: collapse;}'
    'th, td { padding: 5px; }'
    'th { font-weight: bold; }'
    'h2 { margin-bottom: 0px; }'
    '</style>'
    '<h2>Daily CI report for {{ report_date.month }}/{{ report_date.day }}/{{ report_date.year }}</h2>'
    '<h3>Jenkins status</h3>'
    '<p>The table shows total number of passed and failed jenkins runs within 1 day period.</p>'
    '<p>NOTE: Nightly tests and mxnet-validation jobs are triggered <a href="http://jenkins.mxnet-ci.amazon-ml.com/job/DailyTrigger/">nightly</a> for the master branch and <a href="http://jenkins.mxnet-ci.amazon-ml.com/job/WeeklyTrigger">weekly</a> for release branches.</p>'
    '<table>'
    '<tr><th>Job</th><th>Branch</th><th>Status</th><th>Passed</th><th>Failed</th></tr>'
    '{% for test_result in test_results %}'
    '{% if not loop.previtem or loop.previtem.category != test_result.category %}'
    '    <tr>'
    '        <td colspan="5">'
    '            <span style="padding: 7px 5px 5px 0px; font-weight: bold;">{{ test_result.category }}</span>'
    '        </td>'
    '    </tr>'
    '{% endif %}'
    '    <tr>'
    '        {% if not loop.previtem or loop.previtem.job != test_result.job %}'
    '        <td><a href="{{ test_result.job_url }}">{{ test_result.job }}</a></td>'
    '        {% else %}'
    '        <td style="border-top-color: white"></td>'
    '        {% endif %}'
    '        <td>{% if test_result.branch %}'
    '            <a href="{{ test_result.branch_url }}">{{ test_result.branch }}</a>'
    '            {% endif %}'
    '        </td>'
    '        <td align="center">'
    '            {% if test_result.num_passed == 0 and test_result.num_failed == 0 %}'
    '                <span style="color: grey; ">–</span>'
    '            {% elif test_result.num_failed == 0 %}'
    '                <span style="color: green; ">pass</span>'
    '            {% else %}'
    '                <span style="color: red; ">fail</span>'
    '            {% endif %}'
    '        </td>'
    '        <td align="center">{{ test_result.num_passed }}</td>'
    '        <td align="center">{{ test_result.num_failed }}</td>'
    '    </tr>'
    '{% endfor %}'
    '</table>'
)

test_report_template = Template(
    '<style>'
    'html *{ font-family: Helvetica, Arial, sans-serif !important;}'
    'table, th, td { border: 1px solid grey; border-collapse: collapse;}'
    'th, td { padding: 5px; }'
    'th { font-weight: bold; }'
    'h2 { margin-bottom: 0px; }'
    '</style>'
    '<h2>Daily Test report for {{ report_date.month }}/{{ report_date.day }}/{{ report_date.year }}</h2>'
    '<h3>Github status</h3>'
    '<p>The number of github issues being labeled with a certain tag:</p>'
    '<b>Total flaky tests: <a href="{{ flaky_tests_url }}">{{ num_flaky_tests }}</a></b></br>'
    '<b>Disabled tests: <a href="{{ disabled_tests_url }}">{{disabled_tests|length}}</a></b>'
    '<ul>'
    '{% for disabled_test in disabled_tests %}'
    '<li>'
    '<a href="{{ disabled_test.url }}">{{ disabled_test.title }}</a> - last response '
    '{% if disabled_test.last_response < 7 %}'
    '<span style="color: green; ">{{ disabled_test.last_response }}</span>'
    '{% elif disabled_test.last_response < 14 %}'
    '<span style="color: orange; ">{{ disabled_test.last_response }}</span>'
    '{% else %}'
    '<span style="color: red; "><b>{{ disabled_test.last_response }}</b></span>'
    '{% endif %}'
    ' days ago'
    '</li>'
    '{% endfor %}'
    '</ul>'
)


class TestResults(BaseModel):
    job: str
    job_url: str
    branch: Optional[str] = ''
    branch_url: Optional[str]
    num_passed: Optional[int] = 0
    num_failed: Optional[int] = 0
    category: Optional[str] = ''


class Pipeline(BaseModel):
    name: str
    url: str
    runs_url: str
    runs_data: Optional[List[object]] = None

    class Config:
        arbitrary_types_allowed = True

    @staticmethod
    def filter_branch_name(name: str) -> bool:
        matcher = re.compile('(master)|(^v[0-9]+\..*$)')
        return matcher.fullmatch(name)

    def all_runs(self):
        # This call is the absolute master of slowness and brother of the infamous 'SELECT *'.
        # If you want to eat your RAM, overload the Jenkins master (this causes a global system lock) and be super slow,
        # continue to ask it to return and iterate over it's entire database.
        # If a job has 5000 runs but we are only in 30, we requested 99,4% data that we didn't even need.
        # TODO: Convert this entire construct (the upstream code that calls all_runs in combination with filter_runs)
        # to a method that queries specific runs and has a proper termination logic (aka what's done in filter_runs)
        # instead of filtering the data locally after everything has been retrieved.
        if self.runs_data is not None:
            return self.runs_data

        resource = urllib.request.urlopen(f'{JENKINS_URL}{self.runs_url}')
        self.runs_data = json.load(resource)

        return self.runs_data

    @staticmethod
    def filter_runs(runs: List[object], start: datetime, end: datetime):
        if not runs:
            return []

        def predicate(run: object) -> bool:
            if 'state' not in run or run['state'] != 'FINISHED':
                return
            time = dateutil.parser.parse(run['startTime'])
            return start < time <= end

        return list(filter(predicate, runs))


class MultiBranchPipeline(Pipeline):
    branches_url: str
    branch_names: List[str]
    branches_data: Optional[List[object]] = None
    branches_runs_data: Optional[dict] = dict()

    class Config:
        arbitrary_types_allowed = True

    def all_branches(self):
        if self.branches_data is not None:
            return self.branches_data

        resource = urllib.request.urlopen(f'{JENKINS_URL}{self.branches_url}')
        self.branches_data = json.load(resource)

        return self.branches_data

    def all_branch_runs(self, branch: str) -> List[object]:
        if branch in self.branches_runs_data:
            return self.branches_runs_data[branch]

        resource = urllib.request.urlopen(f'{JENKINS_URL}{self.branches_url}{branch}/runs')
        self.branches_runs_data[branch] = json.load(resource)

        return self.branches_runs_data[branch]


class JenkinsQuery(BaseModel):
    pipelines: Optional[List[str]] = None
    org_data: Optional[List[object]] = None

    class Config:
        arbitrary_types_allowed = True

    def query_org(self) -> List[object]:
        if self.org_data is not None:
            return self.org_data

        resource = urllib.request.urlopen(f'{JENKINS_URL}blue/rest/organizations/jenkins/pipelines/')
        self.org_data = json.load(resource)
        return self.org_data

    def all_pipelines(self) -> List[Pipeline]:
        if self.pipelines is not None:
            return self.pipelines

        def map_pipeline(obj):
            name = str(obj['name'])

            if all(name not in job for job, _ in ENABLED_JOBS.items()):
                logging.info(f'skipping pipeline {name}')
                return

            if 'MultiBranchPipelineImpl' in obj['_class']:
                branches = list(filter(Pipeline.filter_branch_name, obj['branchNames']))
                if not branches:
                    return

                yield MultiBranchPipeline(name=str(obj['name']),
                                          url=str(obj['_links']['self']['href']),
                                          runs_url=str(obj['_links']['runs']['href']),
                                          branches_url=str(obj['_links']['branches']['href']),
                                          branch_names=branches)
                return

            if 'PipelineImpl' in obj['_class']:
                yield Pipeline(name=str(obj['name']),
                               url=str(obj['_links']['self']['href']),
                               runs_url=str(obj['_links']['runs']['href']))
                return

            if 'io.jenkins.blueocean.service.embedded.rest.PipelineFolderImpl' in obj['_class']:
                subfolders = [folder for folder in obj['pipelineFolderNames'] if folder is not None]
                for child_name in subfolders:
                    child_url = f"{JENKINS_URL}{obj['_links']['self']['href']}pipelines/{child_name}"
                    child_pipeline = json.load(urllib.request.urlopen(child_url))
                    # Use recursive calls to map nested folders and children
                    mapped_child_pipelines = map_pipeline(child_pipeline)
                    for mapped_child_pipeline in mapped_child_pipelines:
                        # Rewrite children to preprend parent folder name
                        mapped_child_pipeline.name = f"{obj['name']}/{child_pipeline['name']}"
                        yield mapped_child_pipeline
                return

            logging.warning('Unsupported pipeline type %s for %s', obj['_class'], obj['name'])

            return

        self.pipelines = list()
        for pipeline in self.query_org():
            for mapped_pipeline in map_pipeline(pipeline):
                self.pipelines.append(mapped_pipeline)

        return self.pipelines


class GitHubResults:
    def disabled_tests(self) -> Dict:
        """
        Get a list of issues marked as "Disabled Test"
        :return: Issue information
        """
        disabled_tests_issues = self._retrieve_api_data(
            url='https://api.github.com/search/issues?q='
                'repo:apache/incubator-mxnet%20'
                'is:open%20'
                'type:issue%20'
                'label:%22Disabled%20test%22'
        )
        assert disabled_tests_issues['total_count'] < 100, \
            "Expected less than 100 issues. Implement GitHub pagination to support a higher amount."

        assert not disabled_tests_issues['incomplete_results']

        res = [{"title": x['title'],
                "url": x['html_url'],
                "updated_at": dateutil.parser.parse(x['updated_at'])}
               for x in disabled_tests_issues['items']]
        return res

    def num_flaky_tests(self) -> int:
        """
        Return number of flaky tests
        :return:
        """
        flaky_test_issues = self._retrieve_api_data(
            url='https://api.github.com/search/issues?q='
                'repo:apache/incubator-mxnet%20'
                'is:open%20'
                'type:issue%20'
                'label:%22Flaky%22'
        )
        return flaky_test_issues['total_count']

    @staticmethod
    def _retrieve_api_data(url):
        resource = urllib.request.urlopen(url, context=ssl.SSLContext(ssl.PROTOCOL_SSLv23))
        return json.load(resource)


def send_email(title, sender, recipient, html_body):
    CHARSET = "UTF-8"

    # Create a new SES resource and specify a region.
    client = boto3.client('ses', region_name=REGION_NAME)

    client.send_email(
        Destination={
            'ToAddresses': [
                recipient,
            ],
        },
        Message={
            'Body': {
                'Html': {
                    'Charset': CHARSET,
                    'Data': html_body,
                },
                'Text': {
                    'Charset': CHARSET,
                    'Data': 'Please use HTML to view this email.',
                },
            },
            'Subject': {
                'Charset': CHARSET,
                'Data': title,
            },
        },
        Source=sender
    )


def explicit_filter_and_group(test_results: List[TestResults]) -> List[TestResults]:
    test_results = list(filter(lambda tr: tr.job in ENABLED_JOBS, test_results))
    test_results = list(filter(lambda tr: not tr.branch or tr.branch in ENABLED_JOBS[tr.job], test_results))

    job_groups = {
        'Broken_Link_Checker_Pipeline': 'Website',
        'mxnet-validation/centos-cpu': 'Unit Tests',
        'mxnet-validation/centos-gpu': 'Unit Tests',
        'mxnet-validation/clang': 'Unit Tests',
        'mxnet-validation/edge': 'Unit Tests',
        'mxnet-validation/miscellaneous': 'Unit Tests',
        'mxnet-validation/sanity': 'Unit Tests',
        'mxnet-validation/unix-cpu': 'Unit Tests',
        'mxnet-validation/unix-gpu': 'Unit Tests',
        'mxnet-validation/website': 'Unit Tests',
        'mxnet-validation/windows-cpu': 'Unit Tests',
        'mxnet-validation/windows-gpu': 'Unit Tests',
        'NightlyTests': 'Nightly Tests',
        'NightlyTestsForBinaries': 'Nightly Tests',
        'restricted-backwards-compatibility-checker': 'Website',
        'restricted-website-build': 'Website',
        'restricted-website-publish': 'Website'
    }

    for result in test_results:
        result.category = job_groups[result.job]

    test_results.sort(key=lambda r: r.category + r.job + r.branch)

    return test_results


def generate_ci_report(start, end):
    """
    Generate the email report for CI results
    :param start: Starttime
    :return: Nothing
    """
    test_results = []

    query = JenkinsQuery()

    all_pipelines = query.all_pipelines()

    for pipeline in all_pipelines:
        if isinstance(pipeline, MultiBranchPipeline):
            branches = pipeline.all_branches()
            branches = list(filter(lambda b: Pipeline.filter_branch_name(b['name']), branches))
            branches = list(filter(lambda b: b['name'] in ENABLED_BRANCHES, branches))
            branch_names = sorted(list(set(map(lambda b: b['name'], branches))))

            if not branch_names:
                logging.warning(f'no branches for {pipeline.name} found')
                continue

            for branch in branch_names:
                jobify = lambda x: '/job/'.join(x)
                names = pipeline.name.split('/')
                job_url = f'{JENKINS_URL}job/{jobify(names)}'
                branch_url = f'{job_url}/job/{branch}'

                test_result = TestResults(job=pipeline.name,
                                          job_url=job_url,
                                          branch=branch,
                                          branch_url=branch_url)
                runs = pipeline.filter_runs(pipeline.all_branch_runs(branch), start=start, end=end)
                for run in runs:
                    if run['result'] == 'FAILURE':
                        test_result.num_failed += 1
                    if run['result'] == 'SUCCESS':
                        test_result.num_passed += 1
                pprint(test_result)
                test_results.append(test_result)

            continue

        if isinstance(pipeline, Pipeline):
            test_result = TestResults(job=pipeline.name, job_url=f'{JENKINS_URL}job/{pipeline.name}')
            runs = pipeline.filter_runs(pipeline.all_runs(), start=start, end=end)
            for run in runs:
                if run['result'] == 'FAILURE':
                    test_result.num_failed += 1
                if run['result'] == 'SUCCESS':
                    test_result.num_passed += 1
            pprint(test_result)
            test_results.append(test_result)

            continue

        raise Exception('Unknown pipeline type!')

    test_results = explicit_filter_and_group(test_results)

    ci_report_html_output = ci_report_template.render(
        test_results=test_results,
        report_date=start)

    send_email(title=f'[Daily CI Report] {start.month:d}/{start.day:d}/{start.year:d}', sender=EMAIL_SENDER,
               recipient=EMAIL_RECEIVER, html_body=ci_report_html_output)


def generate_github_report(start):
    """
    Generate the email report for GitHub issues
    :param start: Starttime
    :return: Nothing
    """
    github_results = GitHubResults()

    disabled_tests = github_results.disabled_tests()
    disabled_tests.sort(key=lambda x: x['updated_at'])
    disabled_tests_data = []
    logging.info('%d disabled tests', len(disabled_tests))
    for disabled_test in disabled_tests:
        disabled_tests_data.append(
            {'url': disabled_test['url'], 'title': disabled_test['title'],
             'last_response': (datetime.now(timezone.utc) - disabled_test['updated_at']).days})

    num_flaky_tests = github_results.num_flaky_tests()
    logging.info('%d flaky tests', num_flaky_tests)

    test_report_html_output = test_report_template.render(
        report_date=start,
        disabled_tests=disabled_tests_data,
        num_flaky_tests=num_flaky_tests,
        disabled_tests_url=DISABLED_TESTS_URL,
        flaky_tests_url=FLAKY_TESTS_URL)

    send_email(title=f'[Daily Test Report] {start.month:d}/{start.day:d}/{start.year:d}', sender=EMAIL_SENDER,
               recipient=EMAIL_RECEIVER, html_body=test_report_html_output)


def main(task):
    """
    Main handler
    :param task: Which task should be executed
    :return: Nothing
    """
    logging.basicConfig()
    logging.getLogger().setLevel(logging.INFO)

    logging.info(f'Considering following jobs:')

    for job, branches in ENABLED_JOBS.items():
        logging.info(f'{job}')
        if branches is None:
            continue

        for branch in branches:
            logging.info(f'  {branch}')

    logging.info(f'In the following pipelines:')

    for pipe in ENABLED_PIPELINES:
        logging.info(f'{pipe}')

    today = datetime.utcnow().date()
    end = datetime(today.year, today.month, today.day, tzinfo=dateutil.tz.tzutc())
    start = end - timedelta(1)

    logging.info(f'Considering time frame from {start} till {end}')

    if task == 'ci_report':
        generate_ci_report(start=start, end=end)
    elif task == 'github_report':
        generate_github_report(start=start)
    else:
        raise Exception('Unknown task: %s', task)


def lambda_handler_ci_report(event, context):
    main(task='ci_report')
    return 'Done'


def lambda_handler_github_report(event, context):
    main(task='github_report')
    return 'Done'


if __name__ == '__main__':
    sys.exit(main(task='ci_report') and main(task='github_report'))
