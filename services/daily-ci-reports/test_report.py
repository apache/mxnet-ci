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

import dateutil.tz
import json
import unittest
from datetime import datetime, timedelta

from daily_reports.report import JenkinsQuery, MultiBranchPipeline, Pipeline


def all_same(items):
    return all(x == items[0] for x in items)


class TestJenkinsQuery(unittest.TestCase):
    def setUp(self):
        with open('org.json') as json_data:
            self.org_data = json.load(json_data)
        self.query = JenkinsQuery(org_data=self.org_data)

        self.expected_pipeline_names = [
            'incubator-mxnet',
            'NightlyTests',
            'NightlyTestsForBinaries',
            'restricted-BackwardsCompatibilityChecker',
            'restricted-docker-cache-refresh',
        ]

    def test_all_pipelines(self):
        all_pipelines = self.query.all_pipelines()
        pipeline_names = list(map(lambda n: n.name, all_pipelines))

        self.assertListEqual(sorted(pipeline_names), sorted(self.expected_pipeline_names))


class TestPipeline(unittest.TestCase):
    def setUp(self):
        with open('runs.json') as json_data:
            self.runs_data = json.load(json_data)

        name = 'Broken_Link_Checker_Pipeline'
        url = f'blue/rest/organizations/jenkins/pipelines/{name}/'
        runs_url = f'blue/rest/organizations/jenkins/pipelines/{name}/runs/'

        self.pipeline = Pipeline(name=name, url=url, runs_url=runs_url, runs_data=self.runs_data)

        self.expected_runs = ['277', '276', '275', '274', '273']

    def test_filter_runs(self):
        today = datetime(year=2018, month=9, day=1)
        end = datetime(today.year, today.month, today.day, tzinfo=dateutil.tz.tzutc())
        start = end - timedelta(days=1.0)

        runs = self.pipeline.filter_runs(self.pipeline.all_runs(), start=start, end=end)
        run_ids = list(map(lambda n: n['id'], runs))

        self.assertListEqual(run_ids, self.expected_runs)


class TestMultiBranchPipeline(unittest.TestCase):
    def setUp(self):
        with open('branches.json') as json_data:
            self.branches_data = json.load(json_data)

        self.branches_runs_data = dict()

        with open('master_runs.json') as json_data:
            self.branches_runs_data['master'] = json.load(json_data)

        with open('v1.3.x_runs.json') as json_data:
            self.branches_runs_data['v1.3.x'] = json.load(json_data)

        name = 'incubator-mxnet'
        url = f'blue/rest/organizations/jenkins/pipelines/{name}/'
        runs_url = f'blue/rest/organizations/jenkins/pipelines/{name}/runs/'
        branch_url = f'blue/rest/organizations/jenkins/pipelines/{name}/branches/'
        branch_names = []

        self.pipeline = MultiBranchPipeline(name=name,
                                            url=url,
                                            runs_url=runs_url,
                                            branches_data=self.branches_data,
                                            branches_url=branch_url,
                                            branch_names=branch_names,
                                            branches_runs_data=self.branches_runs_data)

        self.expected_branches = ['master', 'v1.3.x']

        self.expected_runs = dict()
        self.expected_runs['master'] = ['1546', '1545', '1544', '1543']
        self.expected_runs['v1.3.x'] = []

    def test_all_branches(self):
        branches = self.pipeline.all_branches()
        branches = list(filter(lambda b: Pipeline.filter_branch_name(b['name']), branches))
        branch_names = list(set(map(lambda b: b['name'], branches)))

        self.assertListEqual(sorted(branch_names), sorted(self.expected_branches))

    def test_branch_runs(self):
        today = datetime(year=2018, month=9, day=1)
        end = datetime(today.year, today.month, today.day, tzinfo=dateutil.tz.tzutc())
        start = end - timedelta(days=1.0)

        for branch in ['master', 'v1.3.x']:
            all_runs = self.pipeline.all_branch_runs(branch)
            runs = self.pipeline.filter_runs(all_runs, start=start, end=end)
            run_ids = list(map(lambda n: n['id'], runs))

            self.assertListEqual(run_ids, self.expected_runs[branch])


if __name__ == "__main__":
    unittest.main()
