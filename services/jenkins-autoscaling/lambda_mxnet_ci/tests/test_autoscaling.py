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

# pylint: disable=missing-docstring
import datetime
import logging
import os
import pprint
import random
import string
import threading
import time
import unittest
import unittest.mock
from collections import defaultdict

import math
from typing import Dict, Any

import boto3
from botocore.exceptions import ClientError
import jenkinsapi
import placebo

# import lambda_mxnet_ci.autoscaling.handler as autoscaling
import autoscaling.handler as autoscaling

EC2_PLACE_ACCOUNT_NAME = 'mxnet-ci-dev'

QUEUE_WHY_FORMULATIONS = [
    'There are no nodes with the label ‘{}’',
    'Waiting for next available executor on {}',
    'All nodes of label ‘{}’ are offline',
    'Waiting for next available executor on {}',
    'Waiting for next available executor on ‘{}’',
    'mxnetlinux-cpu_0123456 doesn’t have label {}; node2 doesn’t have label blabla; node3 is offline',
    '{} is offline'
]

# Thread locks have to be at this level because of joblib/pickle
MOCK_FILTER_NON_IDLE_OFFLINE_NODES_THREAD_LOCK = threading.Lock()
MOCK_CONVERT_JENKINS_NODES_THREAD_LOCK = threading.Lock()
MOCK_JENKINS_POST_CONFIRM_THREAD_LOCK = threading.Lock()


class MockJenkinsServer(object):
    def __init__(self, baseurl):
        self.requester = self
        self.baseurl = baseurl
        self.nb_post_called = 0

    # pylint: disable=unused-argument
    def post_and_confirm_status(self, url, params=None, data=None, files=None, headers=None,
                                valid=None, allow_redirects=True):
        with MOCK_JENKINS_POST_CONFIRM_THREAD_LOCK:
            self.nb_post_called += 1

        # TODO: save data to validate it


class TestMetrics(unittest.TestCase):
    @staticmethod
    def _util_create_node(display_name, assigned_labels, nb_executors, is_offline=False, temporarily_offline=False,
                          is_idle=False, architecture='Linux (amd64)',
                          offline_cause_class='hudson.slaves.OfflineCause$UserCause', offline_reason=''):
        assigned_labels.insert(0, display_name)  # A node always has its own name as well as the labels as labels

        node = dict()
        node['displayName'] = display_name
        node['assignedLabels'] = [{'name': label} for label in assigned_labels]
        node['offline'] = is_offline
        node['temporarilyOffline'] = temporarily_offline
        node['offlineCause'] = {'_class': offline_cause_class}
        node['offlineCauseReason'] = offline_reason
        node['monitorData'] = dict()
        node['monitorData']['hudson.node_monitors.ArchitectureMonitor'] = architecture
        node['idle'] = is_idle
        if nb_executors:
            executors = list()
            for _ in range(0, nb_executors):
                executors.append(None)
            node['executors'] = executors

        return node

    @staticmethod
    def _util_create_queue_item(reason: str, in_queue_duration_sec: int) -> Dict[str, Any]:
        queue_item = dict()
        queue_item['why'] = reason
        queue_item['id'] = 0
        queue_item['inQueueSince'] = 1000 * (time.time() - in_queue_duration_sec)  # Stored in milliseconds
        return queue_item

    @staticmethod
    def _util_get_placebo_session(current_file, test_name, record=False):
        if record:
            session = boto3.Session(profile_name=EC2_PLACE_ACCOUNT_NAME)
        else:
            session = boto3.Session()
        placebo_dir = os.path.join(os.path.dirname(current_file), 'placebo',
                                   os.path.splitext(os.path.basename(current_file))[0],
                                   test_name)
        os.makedirs(name=placebo_dir, exist_ok=True)

        pill = placebo.attach(session, data_path=placebo_dir)
        if record:
            pill.record()
        else:
            pill.playback()

        return session

    def setUp(self):
        # Make sure to properly override all functions that are creating external connections or would retrieve
        # real credentials
        get_jenkins_credentials_mock_method = unittest.mock.MagicMock()
        get_jenkins_credentials_mock_method.return_value = {
            'github_username': 'github_username',
            'github_token': 'github_token',
            'jenkins_url': 'jenkins_url',
            'jenkins_priv_url': 'jenkins_priv_url'
        }
        autoscaling._get_jenkins_credentials = get_jenkins_credentials_mock_method
        autoscaling._get_aws_session = unittest.mock.MagicMock()
        autoscaling._get_jenkins_handle = unittest.mock.MagicMock()
        os.environ['LAUNCH_TEMPLATES'] = \
            '{"mxnetlinux-cpu":{"id":"lt-06a15945813ad44f2","version":"5"},' \
            '"restricted-mxnetlinux-cpu":{"id":"lt-06a15945813ad44f2","version":"5"},' \
            '"mxnetlinux-gpu":{"id":"lt-0c22f238c0edb58ab","version":"8"},' \
            '"mxnetlinux-gpu-p3":{"id":"lt-00c83ee5d7aeaf4ab","version":"4"},' \
            '"restricted-mxnetlinux-gpu-p3":{"id":"lt-0f893d7f3f2660c1c","version":"2"},' \
            '"mxnetlinux-gpu-p3-8xlarge":{"id":"lt-00c83ee5d7aeaf4ab","version":"4"},' \
            '"mxnetwindows-cpu":{"id":"lt-09dff2fff6b5586f0","version":"4"},' \
            '"mxnetwindows-gpu":{"id":"lt-0ce229129d0d3be27","version":"6"},' \
            '"restricted-mxnetlinux-gpu":{"id":"lt-0c22f238c0edb58ab","version":"1"} }'
        os.environ['EXECUTORS_PER_LABEL'] = \
            '{"mxnetlinux-cpu":3,"restricted-mxnetlinux-cpu":3,"mxnetlinux-gpu":1,"mxnetlinux-gpu-p3":1,' \
            '"restricted-mxnetlinux-gpu-p3":1,"mxnetlinux-gpu-p3-8xlarge":1,"mxnetwindows-cpu":4,' \
            '"mxnetwindows-gpu":1,"utility":30,"restricted-utility":30,' \
            '"restricted-mxnetlinux-gpu":1}'
        os.environ['JENKINS_PRIV_TUNNEL'] = 'localhost:48593'
        os.environ['IGNORED_JENKINS_NODE_NAMES'] = '["master"]'
        os.environ['WARM_POOL_SIZE'] = \
            '{"mxnetlinux-cpu":1,"restricted-mxnetlinux-cpu":0,"mxnetlinux-gpu":0,"mxnetlinux-gpu-p3":0,' \
            '"restricted-mxnetlinux-gpu-p3":0,"mxnetlinux-gpu-p3-8xlarge":0,"mxnetwindows-cpu":1,"mxnetwindows-gpu":0,' \
            '"restricted-mxnetlinux-gpu":0}'
        os.environ['MINIMUM_QUEUE_TIMES_SEC'] = \
            '{"mxnetlinux-cpu":30,"restricted-mxnetlinux-cpu":30,"mxnetlinux-gpu":30,"mxnetlinux-gpu-p3":30,' \
            '"restricted-mxnetlinux-gpu-p3":30,"mxnetlinux-gpu-p3-8xlarge":30,"mxnetwindows-cpu":30,' \
            '"mxnetwindows-gpu":30,' \
            '"restricted-mxnetlinux-gpu":30}'
        os.environ['MANAGED_JENKINS_NODE_LABELS'] = \
            '["mxnetlinux-cpu","restricted-mxnetlinux-cpu","mxnetlinux-gpu","mxnetwindows-cpu","mxnetwindows-gpu",' \
            '"mxnetlinux-gpu-p3","restricted-mxnetlinux-gpu-p3","mxnetlinux-gpu-p3-8xlarge",' \
            '"restricted-mxnetlinux-gpu"]'
        os.environ['MAXIMUM_STARTUP_TIME_SEC'] = \
            '{"mxnetlinux-cpu":300,"restricted-mxnetlinux-cpu":300,"mxnetlinux-gpu":300,"mxnetlinux-gpu-p3":300,' \
            '"restricted-mxnetlinux-gpu-p3":300,"mxnetlinux-gpu-p3-8xlarge":300,"mxnetwindows-cpu":1800,' \
            '"mxnetwindows-gpu":1800,'\
            '"restricted-mxnetlinux-gpu": 300}'
        os.environ['CCACHE_EFS_DNS'] = \
            '{"mxnetlinux-cpu":"NONE","restricted-mxnetlinux-cpu":"NONE","mxnetlinux-gpu":"NONE",' \
            '"mxnetlinux-gpu-p3":"NONE","restricted-mxnetlinux-gpu-p3":"NONE","mxnetlinux-gpu-p3-8xlarge":"NONE",' \
            '"mxnetwindows-cpu":"NONE","mxnetwindows-gpu":"NONE", "restricted-mxnetlinux-gpu": "NONE"}'
        os.environ['IGNORED_JENKINS_NODE_LABELS'] = '["mxnetlinux","mxnetwindows","master"]'

    def test_get_starting_node_names(self):
        connected_nodes = [
            self._util_create_node(display_name='mxnetlinux-gpu10', is_offline=False, assigned_labels=[],
                                   nb_executors=1, temporarily_offline=False),
            self._util_create_node(display_name='mxnetlinux-cpu10', is_offline=False, assigned_labels=[],
                                   nb_executors=1, temporarily_offline=False),
            self._util_create_node(display_name='mxnetlinux-cpu11', is_offline=True, assigned_labels=[],
                                   nb_executors=1, temporarily_offline=False),
            self._util_create_node(display_name='mxnetlinux-gpu11', is_offline=True, assigned_labels=[],
                                   nb_executors=1, temporarily_offline=False),
            self._util_create_node(display_name='mxnetlinux-gpu12', is_offline=True, assigned_labels=[],
                                   nb_executors=1, temporarily_offline=False),
            self._util_create_node(display_name='mxnetlinux-gpu-temp-offline1', is_offline=True, assigned_labels=[],
                                   nb_executors=1, temporarily_offline=True),
            self._util_create_node(display_name='mxnetlinux-gpu-temp-offline2', is_offline=True, assigned_labels=[],
                                   nb_executors=1, temporarily_offline=True),
        ]

        instance_running_durations = {
            'mxnetlinux-gpu10': 10, 'mxnetlinux-cpu10': 10, 'mxnetlinux-cpu11': 10, 'mxnetlinux-gpu11': 10,
            'mxnetlinux-gpu12': 10, 'mxnetlinux-gpu-temp-offline1': 10, 'mxnetlinux-gpu-temp-offline2': 10
        }

        # Data in placebo/test_metrics/test_get_starting_nodes
        session = self._util_get_placebo_session(current_file=__file__, test_name='test_get_starting_nodes',
                                                 record=False)
        ec2_resource = session.resource('ec2')

        starting_nodes = autoscaling._unconnected_instances(nodes=connected_nodes, ec2_resource=ec2_resource,
                                                            instance_uptime=instance_running_durations)
        assert len(starting_nodes['mxnetlinux-cpu']) == 1, \
            'Should be 1 starting cpu node, got {}'.format(starting_nodes['mxnetlinux-cpu'])
        assert len(starting_nodes['mxnetlinux-gpu']) == 2, \
            'Should be 2 starting gpu nodes, got {}'.format(starting_nodes['mxnetlinux-gpu'])

    def test_determine_scale_up_nodes(self):
        def execute(nb_queue_items_cpu, nb_queue_items_gpu, nb_starting_nodes_cpu, nb_starting_nodes_gpu):
            count_expected_error_messages = 0
            nb_executors_cpu = autoscaling._get_nb_executors_per_label()['mxnetlinux-cpu']
            nb_executors_gpu = autoscaling._get_nb_executors_per_label()['mxnetlinux-gpu']

            queue_items = [
                # Add some garbage that should not be recognized
                self._util_create_queue_item(reason='Something mxnetlinux-gpu', in_queue_duration_sec=60000),
                self._util_create_queue_item(reason='Something mxnetlinux-bla', in_queue_duration_sec=60000),

                # Restricted jobs. It might be possible that there are jobs in the queue although there are nodes
                # available.
                # This might be happen if an unrestricted job tries to schedule a job onto a restricted node. This
                # should not
                # trigger a scale up but instead throw an error so somebody can investigate
                self._util_create_queue_item(
                    reason=random.choice(QUEUE_WHY_FORMULATIONS).format('restricted-mxnetlinux-cpu'),
                    in_queue_duration_sec=60000),
            ]
            count_expected_error_messages += 1  # Restricted jobs

            # Add some items that are not old enough and should thus not be picked up
            NB_IMMATURE_QUEUE_ITEMS = 20
            IMMATURE_QUEUE_DURATION_SEC = -15
            for _ in range(0, NB_IMMATURE_QUEUE_ITEMS):
                queue_items.append(self._util_create_queue_item(
                    reason=random.choice(QUEUE_WHY_FORMULATIONS).format('mxnetlinux-cpu'),
                    in_queue_duration_sec=IMMATURE_QUEUE_DURATION_SEC))

            for _ in range(0, nb_queue_items_cpu):
                queue_items.append(self._util_create_queue_item(
                    reason=random.choice(QUEUE_WHY_FORMULATIONS).format('mxnetlinux-cpu'),
                    in_queue_duration_sec=autoscaling._minimum_queue_times_sec()['mxnetlinux-cpu'] + 10))

            for _ in range(0, nb_queue_items_gpu):
                queue_items.append(self._util_create_queue_item(
                    reason=random.choice(QUEUE_WHY_FORMULATIONS).format('mxnetlinux-gpu'),
                    in_queue_duration_sec=autoscaling._minimum_queue_times_sec()['mxnetlinux-gpu'] + 10))

            nodes = [
                # Mis-configured node with multiple labels. Should be ignored.
                self._util_create_node(display_name='multiple-assigned-labels-node',
                                       assigned_labels=['mxnetlinux-cpu', 'mxnetlinux-gpu'],
                                       nb_executors=10),

                # Valid nodes
                self._util_create_node(display_name='mxnet-linux-cpu10', assigned_labels=['mxnetlinux-cpu'],
                                       nb_executors=nb_executors_cpu),
                self._util_create_node(display_name='mxnet-linux-gpu10', assigned_labels=['garbage', 'mxnetlinux-gpu'],
                                       nb_executors=nb_executors_gpu)
            ]

            starting_node_names = {
                'mxnetlinux-cpu': ['starting-cpu' + str(i) for i in range(nb_starting_nodes_cpu)],
                'mxnetlinux-gpu': ['starting-gpu' + str(i) for i in range(nb_starting_nodes_gpu)]
            }

            # Restricted nodes (see above for comment)
            for i in range(5):
                node = self._util_create_node(display_name='restricted-slave-' + str(i),
                                              assigned_labels=
                                              ['restricted-mxnetlinux-cpu'],
                                              nb_executors=nb_executors_cpu, is_offline=False, is_idle=True)
                nodes.append(node)

            # Calculate estimated results
            estimated_cpu = max(0, math.ceil(nb_queue_items_cpu / nb_executors_cpu) - nb_starting_nodes_cpu)
            estimated_gpu = max(0, math.ceil(nb_queue_items_gpu / nb_executors_gpu) - nb_starting_nodes_gpu)

            with self.assertLogs(level='ERROR') as log_manager:
                scale_up_nb_nodes = autoscaling.determine_scale_up_nodes(
                    queue_items=queue_items,
                    nodes=nodes,
                    unconnected=starting_node_names)

                assert len(log_manager.records) == count_expected_error_messages, \
                    "Expected {} log messages, got {}: {}". \
                        format(count_expected_error_messages, len(log_manager.records),
                               [record.message for record in log_manager.records])
                logging.error("Hack to make sure the with-assert does not fail - we assert manually...")

            if estimated_cpu > 0:
                assert scale_up_nb_nodes['mxnetlinux-cpu'] == estimated_cpu, \
                    "Expected {} mxnetlinux-cpu nodes, got {}".format(estimated_cpu,
                                                                      scale_up_nb_nodes['mxnetlinux-cpu'])
            else:
                assert 'mxnetlinux-cpu' not in scale_up_nb_nodes, \
                    "mxnetlinux-cpu should not be in scale_up_nb_nodes, got {}".format(
                        scale_up_nb_nodes['mxnetlinux-cpu'])

            if estimated_gpu > 0:
                assert scale_up_nb_nodes['mxnetlinux-gpu'] == estimated_gpu, \
                    "Expected {} mxnetlinux-gpu nodes, got {}".format(estimated_gpu,
                                                                      scale_up_nb_nodes['mxnetlinux-gpu'])
            else:
                assert 'mxnetlinux-gpu' not in scale_up_nb_nodes, \
                    "mxnetlinux-gpu should not be in scale_up_nb_nodes, got {}".format(
                        scale_up_nb_nodes['mxnetlinux-gpu'])

        execute(nb_queue_items_cpu=20, nb_queue_items_gpu=20, nb_starting_nodes_cpu=2, nb_starting_nodes_gpu=2)
        execute(nb_queue_items_cpu=20, nb_queue_items_gpu=20, nb_starting_nodes_cpu=0, nb_starting_nodes_gpu=1)
        execute(nb_queue_items_cpu=5, nb_queue_items_gpu=5, nb_starting_nodes_cpu=5, nb_starting_nodes_gpu=5)
        execute(nb_queue_items_cpu=10, nb_queue_items_gpu=2, nb_starting_nodes_cpu=2, nb_starting_nodes_gpu=2)
        execute(nb_queue_items_cpu=0, nb_queue_items_gpu=0, nb_starting_nodes_cpu=2, nb_starting_nodes_gpu=2)
        execute(nb_queue_items_cpu=0, nb_queue_items_gpu=0, nb_starting_nodes_cpu=0, nb_starting_nodes_gpu=0)

    def test_determine_scale_down_nodes(self):
        def execute(nb_offline, nb_idle_linux, nb_non_idle_linux, nb_idle_windows_ready, nb_idle_windows_not_ready):
            label_linux = 'mxnetlinux-cpu'
            label_windows = 'mxnetwindows-cpu'

            nb_executors_linux = autoscaling._get_nb_executors_per_label()[label_linux]
            nb_executors_windows = autoscaling._get_nb_executors_per_label()[label_windows]

            instance_running_durations = {}
            nb_expected_error_messages = 0

            nodes = []
            for i in range(0, nb_offline):
                nodes.append(self._util_create_node(display_name='offline' + str(i), assigned_labels=[label_linux],
                                                    nb_executors=nb_executors_linux, is_offline=True, is_idle=True))

            for i in range(0, nb_idle_linux):
                node = self._util_create_node(display_name='idle_linux' + str(i), assigned_labels=[label_linux],
                                              nb_executors=nb_executors_linux, is_offline=False, is_idle=True)
                instance_running_durations[node['displayName']] = random.randint(0, 500000)
                nodes.append(node)

            # Windows slave within the timeframe which allows shutdown due to hourly billing
            for i in range(0, nb_idle_windows_ready):
                node = self._util_create_node(display_name='idle_windows_ready' + str(i),
                                              assigned_labels=[label_windows],
                                              nb_executors=nb_executors_windows, is_offline=False, is_idle=True,
                                              architecture='Windows NT (unknown) (amd64)')
                instance_running_durations[node['displayName']] = \
                    random.randint(autoscaling.WINDOWS_MIN_PARTIAL_RUNTIME_SECONDS + 1, 60 * 60 - 1) + \
                    random.randint(0, 10) * (60 * 60)
                nodes.append(node)

            # Windows slave outside the timeframe which allows shutdown due to hourly billing
            for i in range(0, nb_idle_windows_not_ready):
                node = self._util_create_node(display_name='idle_windows_not_ready' + str(i),
                                              assigned_labels=[label_windows],
                                              nb_executors=nb_executors_windows, is_offline=False, is_idle=True,
                                              architecture='Windows NT (unknown) (amd64)')
                instance_running_durations[node['displayName']] = \
                    1 + random.randint(0, 10) * (60 * 60)
                nodes.append(node)

            for i in range(0, nb_non_idle_linux):
                node = self._util_create_node(display_name='non-idle' + str(i), assigned_labels=[label_linux],
                                              nb_executors=nb_executors_linux, is_offline=False, is_idle=False)
                instance_running_durations[node['displayName']] = random.randint(0, 500000)
                nodes.append(node)

            # Error testing: Windows slave without a known running duration
            for i in range(0, 5):
                nb_expected_error_messages += 1
                node = self._util_create_node(display_name='idle_windows_no_duration' + str(i),
                                              assigned_labels=[label_windows],
                                              nb_executors=nb_executors_windows, is_offline=False, is_idle=True,
                                              architecture='Windows NT (unknown) (amd64)')
                nodes.append(node)

            # Error testing: Slave without label
            for i in range(0, 5):
                nb_expected_error_messages += 1
                node = self._util_create_node(display_name='slave_without_label' + str(i),
                                              assigned_labels=[],
                                              nb_executors=1, is_offline=False, is_idle=True)
                nodes.append(node)

            # Error testing: Slave with unmanaged label
            for i in range(0, 5):
                # Don't check this message since it's only debug. Just make sure this node does not get processed
                node = self._util_create_node(display_name='slave_unmanaged_label' + str(i),
                                              assigned_labels=
                                              [random.choice(autoscaling._ignored_jenkins_node_labels())],
                                              nb_executors=1, is_offline=False, is_idle=True)
                nodes.append(node)

            # Since offline and non-idle nodes should be ignored, we expect only nb_idle - buffer to be
            # turned off. Additionally, we check that only windows slaves within the WINDOWS_MIN_PARTIAL_RUNTIME_SECONDS
            # timeframe are turned off. The buffer should still consider idle windows nodes that are currently not
            # eligible to be turned off.
            estimated_linux_turned_off = max(nb_idle_linux - autoscaling._warm_pool_node_counts()[label_linux], 0)
            estimated_windows_turned_off = \
                max(nb_idle_windows_ready -
                    max(0, autoscaling._warm_pool_node_counts()[label_windows] - nb_idle_windows_not_ready), 0)

            with self.assertLogs(level='ERROR') as log_manager:
                scale_down_nodes = autoscaling.determine_scale_down_nodes(nodes, instance_running_durations)

                assert len(log_manager.records) == nb_expected_error_messages, "Expected {} log messages, got {}: {}". \
                    format(nb_expected_error_messages, len(log_manager.records),
                           [record.message for record in log_manager.records])
                logging.error("Hack to make sure the with-assert does not fail - we assert manually...")

            estimated_length = 0

            if estimated_linux_turned_off > 0:
                estimated_length += 1
                assert len(scale_down_nodes[label_linux]) == estimated_linux_turned_off, \
                    "Expected {} {} nodes to be turned off, got {}". \
                        format(nb_executors_linux, label_linux, len(scale_down_nodes[label_linux]))

            if estimated_windows_turned_off > 0:
                estimated_length += 1
                assert len(scale_down_nodes[label_windows]) == estimated_windows_turned_off, \
                    "Expected {} {} nodes to be turned off, got {}". \
                        format(estimated_windows_turned_off, label_windows, len(scale_down_nodes[label_windows]))

            assert len(scale_down_nodes) == estimated_length, "Expected {} scale down node types, got {}". \
                format(estimated_length, len(scale_down_nodes))

        execute(nb_offline=5, nb_idle_linux=5, nb_idle_windows_ready=5, nb_idle_windows_not_ready=5,
                nb_non_idle_linux=5)
        execute(nb_offline=5, nb_idle_linux=5, nb_idle_windows_ready=5, nb_idle_windows_not_ready=15,
                nb_non_idle_linux=5)
        execute(nb_offline=0, nb_idle_linux=5, nb_idle_windows_ready=0, nb_idle_windows_not_ready=0,
                nb_non_idle_linux=5)
        execute(nb_offline=5, nb_idle_linux=0, nb_idle_windows_ready=5, nb_idle_windows_not_ready=5,
                nb_non_idle_linux=5)
        execute(nb_offline=5, nb_idle_linux=0, nb_idle_windows_ready=5, nb_idle_windows_not_ready=3,
                nb_non_idle_linux=5)
        execute(nb_offline=0, nb_idle_linux=0, nb_idle_windows_ready=0, nb_idle_windows_not_ready=0,
                nb_non_idle_linux=5)
        execute(nb_offline=0, nb_idle_linux=1, nb_idle_windows_ready=1, nb_idle_windows_not_ready=1,
                nb_non_idle_linux=0)
        execute(nb_offline=0, nb_idle_linux=0, nb_idle_windows_ready=0, nb_idle_windows_not_ready=0,
                nb_non_idle_linux=0)

    def test_instance_uptime(self):
        session = self._util_get_placebo_session(current_file=__file__, test_name='test_instance_uptime',
                                                 record=False)
        ec2_resource = session.resource('ec2')

        startup_times = {
            'node1': datetime.datetime(year=2018, month=4, day=1, hour=5),
            'node2': datetime.datetime(year=2018, month=3, day=1, hour=5, minute=10),
            'node3': datetime.datetime(year=2018, month=3, day=5, hour=15, minute=5)
        }

        results = autoscaling._instance_uptime(ec2_resource=ec2_resource)

        assert len(results) == len(startup_times), 'Expected {} results, got {}'. \
            format(len(startup_times), len(results))

        current_time = datetime.datetime.now()
        for name, startup_time in startup_times.items():
            expected_duration = (current_time - startup_time).total_seconds()
            returned_duration = results[name]
            duration_diff = abs(returned_duration - expected_duration)
            assert duration_diff < 10, 'Duration {}s of {} does not match expected {}s. Diff: {}s'. \
                format(returned_duration, name, expected_duration, duration_diff)

    def test_calculate_nb_required_nodes(self):
        def execute(nb_linux_cpu, nb_linux_gpu):
            dict_required_executors = dict()

            # Add some garbage
            dict_required_executors['mxnetlinux-cpu111'] = 100
            dict_required_executors['blabla'] = 100

            # Should be ignored
            dict_required_executors['mxnetlinux'] = 100

            dict_required_executors['mxnetlinux-cpu'] = nb_linux_cpu
            dict_required_executors['mxnetlinux-gpu'] = nb_linux_gpu

            expected_linux_cpu = \
                max(0, math.ceil(nb_linux_cpu / autoscaling._get_nb_executors_per_label()['mxnetlinux-cpu']))
            expected_linux_gpu = \
                max(0, math.ceil(nb_linux_gpu / autoscaling._get_nb_executors_per_label()['mxnetlinux-gpu']))

            with self.assertLogs(level='ERROR') as log_manager:
                dict_required_nodes = autoscaling._calculate_nb_required_nodes(
                    dict_required_executors=dict_required_executors)

            # Expect 4 error messages for the two times of garbage
            assert len(log_manager.records) == 4, "Expected 4 log messages, got {}: {}". \
                format(len(log_manager.records), [record.message for record in log_manager.records])

            if expected_linux_cpu > 0:
                assert dict_required_nodes['mxnetlinux-cpu'] == expected_linux_cpu, \
                    "Expected {} mxnetlinux-cpu nodes, got {}". \
                        format(expected_linux_cpu, dict_required_nodes['mxnetlinux-cpu'])
            else:
                assert 'mxnetlinux-cpu' not in dict_required_nodes, "Expected no mxnetlinux-cpu nodes, got {}". \
                    format(dict_required_nodes['mxnetlinux-cpu'])

            if expected_linux_gpu > 0:
                assert dict_required_nodes['mxnetlinux-gpu'] == expected_linux_gpu, \
                    "Expected {} mxnetlinux-gpu nodes, got {}". \
                        format(expected_linux_gpu, dict_required_nodes['mxnetlinux-gpu'])
            else:
                assert 'mxnetlinux-gpu' not in dict_required_nodes, "Expected no mxnetlinux-gpu nodes, got {}". \
                    format(dict_required_nodes['mxnetlinux-gpu'])

        execute(nb_linux_cpu=0, nb_linux_gpu=0)
        execute(nb_linux_cpu=1, nb_linux_gpu=1)
        execute(nb_linux_cpu=100, nb_linux_gpu=100)
        execute(nb_linux_cpu=0, nb_linux_gpu=100)
        execute(nb_linux_cpu=100, nb_linux_gpu=0)
        execute(nb_linux_cpu=10, nb_linux_gpu=5)
        execute(nb_linux_cpu=0, nb_linux_gpu=5)
        execute(nb_linux_cpu=0, nb_linux_gpu=100)

    def test_extract_type_label_from_queue_item(self):
        # Invalid reason
        def execute_invalid_reason():
            # Invalid reasons should not log an error but just return None. There are a lot of valid other queue reasons
            reason = 'This is a random queue reason with a {} label'. \
                format(random.choice(list(autoscaling._managed_jenkins_node_labels())))
            queue_item = self._util_create_queue_item(reason=reason, in_queue_duration_sec=0)
            label = autoscaling._label_from_queued_job(nodes=[], queue_item=queue_item)
            assert label is None, "Expected {} as label for '{}', got {}". \
                format(None, reason, label)

        # All reasons with valid labels
        def execute_all_reasons_valid_labels():
            for queue_formulation in QUEUE_WHY_FORMULATIONS:
                expected_label = random.choice(list(autoscaling._managed_jenkins_node_labels()))
                reason = queue_formulation.format(expected_label)
                queue_item = self._util_create_queue_item(reason=reason, in_queue_duration_sec=0)
                label = autoscaling._label_from_queued_job(nodes=[], queue_item=queue_item)
                assert label == expected_label, "Expected {} as label for '{}', got {}". \
                    format(expected_label, reason, label)

        # Reason with invalid label
        def execute_one_reason_invalid_labels():
            garbage_label = "something123"
            reason = random.choice(QUEUE_WHY_FORMULATIONS).format(garbage_label)
            queue_item = self._util_create_queue_item(reason=reason, in_queue_duration_sec=0)

            with self.assertLogs(level='ERROR') as log_manager:
                label = autoscaling._label_from_queued_job(nodes=[], queue_item=queue_item)

            # Expect 1 error message, describing it could not associate label with a node and thus marking it as invalid
            assert len(log_manager.records) == 1, "Expected 1 log message, got {}: {}". \
                format(len(log_manager.records), [record.message for record in log_manager.records])

            assert label is None, "Expected {} as label for '{}', got {}". \
                format(None, reason, label)

        # Reason which contains existing node name
        def execute_reason_existing_node_name():
            valid_label = random.choice(list(autoscaling._managed_jenkins_node_labels()))
            node_name = valid_label + '10'
            nodes = [self._util_create_node(display_name=node_name, assigned_labels=[valid_label], nb_executors=1)]
            reason = random.choice(QUEUE_WHY_FORMULATIONS).format(node_name)
            queue_item = self._util_create_queue_item(reason=reason, in_queue_duration_sec=0)

            label = autoscaling._label_from_queued_job(nodes=nodes, queue_item=queue_item)

            assert label == valid_label, "Expected {} as label for '{}', got {}". \
                format(valid_label, reason, label)

        # Reason which contains non-existing node name
        def execute_reason_nonexisting_node_name():
            # Similar to execute_one_reason_invalid_labels, just going with node data in this case.
            node_name = 'mxnetwindows-cpu10'
            reason = random.choice(QUEUE_WHY_FORMULATIONS).format(node_name)

            # Fake nodes data, it should not matter and never be used since it does not match
            nodes = [self._util_create_node(display_name="mxnetlinux-cpu10", assigned_labels=['mxnetlinux-cpu'],
                                            nb_executors=1)]

            queue_item = self._util_create_queue_item(reason=reason, in_queue_duration_sec=0)

            with self.assertLogs(level='ERROR') as log_manager:
                label = autoscaling._label_from_queued_job(nodes=nodes, queue_item=queue_item)

            # Expect 1 error message, describing it could not associate label with a node and thus marking it as invalid
            assert len(log_manager.records) == 1, "Expected 1 log message, got {}: {}". \
                format(len(log_manager.records), [record.message for record in log_manager.records])

            assert label is None, "Expected {} as label for '{}', got {}". \
                format(None, reason, label)

        # Reason which contains existing node name but node has no labels
        def execute_reason_existing_node_no_labels():
            node_name = 'mxnetlinux-cpu10'
            nodes = [self._util_create_node(display_name=node_name, assigned_labels=[], nb_executors=1)]
            reason = random.choice(QUEUE_WHY_FORMULATIONS).format(node_name)
            queue_item = self._util_create_queue_item(reason=reason, in_queue_duration_sec=0)

            with self.assertLogs(level='ERROR') as log_manager:
                label = autoscaling._label_from_queued_job(nodes=nodes, queue_item=queue_item)

            # Expect 1 error message, describing it could not extract valid label from that node
            assert len(log_manager.records) == 1, "Expected 1 log message, got {}: {}". \
                format(len(log_manager.records), [record.message for record in log_manager.records])

            assert label is None, "Expected {} as label for '{}', got {}". \
                format(None, reason, label)

        # Special case when the jenkins master contains no nodes
        def execute_no_running_nodes():
            reason = 'Waiting for next available executor'
            queue_item = self._util_create_queue_item(reason=reason, in_queue_duration_sec=0)
            with self.assertLogs(level='DEBUG') as log_manager:
                label = autoscaling._label_from_queued_job(nodes=[], queue_item=queue_item)

            # Expect 1 error message, describing it could not extract valid label from that node
            assert len(log_manager.records) == 1, "Expected 1 log message, got {}: {}". \
                format(len(log_manager.records), [record.message for record in log_manager.records])

            assert label == 'mxnetlinux-cpu', "Expected {} as label for '{}', got {}". \
                format('mxnetlinux-cpu', reason, label)

        execute_invalid_reason()
        execute_all_reasons_valid_labels()
        execute_one_reason_invalid_labels()
        execute_reason_existing_node_name()
        execute_reason_nonexisting_node_name()
        execute_reason_existing_node_no_labels()
        execute_no_running_nodes()

    # Create mock class for test_mark_nodes_offline/online. Has to be at this scope due to pickle restrictions
    class MockMarkNodesClass(object):
        def __init__(self):
            self.called = False
            self.reason = None
            self.name = None

        def set_offline(self, reason):
            self.called = True
            self.reason = reason

        def set_online(self):
            self.called = True

    def test_mark_nodes_offline(self):
        def execute(nb_nodes):
            nodes = []
            for _ in range(0, nb_nodes):
                nodes.append(self.MockMarkNodesClass())

            offline_reason = 'RANDOM REASON'
            autoscaling._mark_nodes_offline(offline_nodes=nodes, reason=offline_reason)

            for node_obj in nodes:
                assert node_obj.called, "Expected set_offline to be called"
                assert node_obj.reason == offline_reason, "Expected {} as offline reason, got {}". \
                    format(offline_reason, node_obj.reason)

        execute(0)
        execute(1)
        execute(10)
        execute(20)
        execute(50)
        execute(150)
        execute(500)
        execute(5000)

    def test_mark_nodes_online(self):
        def execute(nb_nodes):
            nodes = []
            for _ in range(0, nb_nodes):
                nodes.append(self.MockMarkNodesClass())

            autoscaling._mark_nodes_online(online_nodes=nodes)

            for node_obj in nodes:
                assert node_obj.called, "Expected set_online to be called"

        execute(0)
        execute(1)
        execute(10)
        execute(20)
        execute(50)
        execute(150)
        execute(500)
        execute(5000)

    # Create mock class for test_mark_nodes_offline. Has to be at this scope due to pickle restrictions
    class MockConvertJenkinsNodeServer(object):
        def __init__(self):
            self.baseurl = 'http://0.0.0.0/'

    def test_convert_jenkins_nodes(self):
        def execute(nb_nodes):
            MAGIC_RETURN_VALUE = {'magic': True}
            mock_server = self.MockConvertJenkinsNodeServer()

            node_names = set()
            for _ in range(0, nb_nodes):
                node_names.add(''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(20)))

            expected_nb_nodes_obj = len(node_names)

            # Test whether poll was called as often as we have nodes. This ensures the parallelization is working
            # and no additional requests are being sent
            with unittest.mock.patch.object(jenkinsapi.jenkinsbase.JenkinsBase, attribute='_poll') as mock_method:
                call_count = 0

                # pylint: disable=unused-argument
                def increment_call_count(**kwargs):
                    nonlocal call_count
                    with MOCK_CONVERT_JENKINS_NODES_THREAD_LOCK:
                        call_count += 1

                    return MAGIC_RETURN_VALUE

                # We can't use mock_method.call_count because it is not threadsafe
                mock_method.side_effect = increment_call_count
                nodes_obj = autoscaling._convert_to_jenkins_nodes(server=mock_server, instances=list(node_names))

                for name, node_obj in nodes_obj.items():
                    assert node_obj._data == MAGIC_RETURN_VALUE, 'Poll has not been called for {}'.format(name)
                    node_names.remove(name)  # Throws an exception if name does not exist. This should not happen

                assert call_count == nb_nodes, 'Expected {} poll calls, got {}'. \
                    format(nb_nodes, mock_method.call_count)
                assert len(nodes_obj) == expected_nb_nodes_obj, 'Expected {} resulting objects, got {}'. \
                    format(expected_nb_nodes_obj, len(nodes_obj))

        execute(nb_nodes=0)
        execute(nb_nodes=1)
        execute(nb_nodes=5)
        execute(nb_nodes=10)
        execute(nb_nodes=50)
        execute(nb_nodes=150)
        execute(nb_nodes=500)
        execute(nb_nodes=5000)

    class MockRemoveNonIdleOfflineNodes(object):
        def __init__(self, is_idle, is_online):
            self.nb_updates = 0
            self.idle = is_idle
            self.online = is_online

        def poll(self):
            with MOCK_FILTER_NON_IDLE_OFFLINE_NODES_THREAD_LOCK:
                self.nb_updates += 1

        def is_idle(self):
            return self.idle

        def is_online(self):
            return self.online

    def test_filter_non_idle_offline_nodes(self):
        def execute(nb_idle_offline, nb_non_idle_offline, nb_idle_online, nb_non_idle_online):
            node_objs = []

            for _ in range(0, nb_idle_offline):
                node_objs.append(self.MockRemoveNonIdleOfflineNodes(is_idle=True, is_online=False))
            for _ in range(0, nb_non_idle_offline):
                node_objs.append(self.MockRemoveNonIdleOfflineNodes(is_idle=False, is_online=False))
            for _ in range(0, nb_idle_online):
                node_objs.append(self.MockRemoveNonIdleOfflineNodes(is_idle=True, is_online=True))
            for _ in range(0, nb_non_idle_online):
                node_objs.append(self.MockRemoveNonIdleOfflineNodes(is_idle=False, is_online=True))

            with self.assertLogs(level='INFO') as log_manager:
                filtered_node_objs, non_idle_nodes = autoscaling._partition_non_idle(node_objs)

                # Expect 1 warning message if there were any non-idle or online nodes
                expected_messages = 1 if (nb_non_idle_offline + nb_idle_online + nb_non_idle_online) > 0 else 0
                assert len(log_manager.records) == expected_messages, "Expected {} log message, got {}: {}". \
                    format(expected_messages, len(log_manager.records),
                           [record.message for record in log_manager.records])
                logging.warning("Hack to make sure the with-assert does not fail - we assert manually...")

            assert len(filtered_node_objs) == nb_idle_offline, "Expected {} filtered nodes, got {}". \
                format(nb_idle_offline, len(filtered_node_objs))

            nb_filtered = nb_non_idle_offline + nb_idle_online + nb_non_idle_online
            assert len(non_idle_nodes) == nb_filtered, "Expected {} unfiltered nodes, got {}". \
                format(nb_non_idle_offline, len(non_idle_nodes))

            for node_obj in filtered_node_objs:
                assert node_obj.nb_updates == 1, "Expected 1 node update, got {}".format(node_obj.nb_updates)

        execute(nb_idle_offline=5, nb_non_idle_offline=5, nb_idle_online=5, nb_non_idle_online=5)
        execute(nb_idle_offline=0, nb_non_idle_offline=5, nb_idle_online=5, nb_non_idle_online=5)
        execute(nb_idle_offline=50, nb_non_idle_offline=0, nb_idle_online=0, nb_non_idle_online=0)
        execute(nb_idle_offline=5, nb_non_idle_offline=0, nb_idle_online=0, nb_non_idle_online=5)
        execute(nb_idle_offline=5000, nb_non_idle_offline=5000, nb_idle_online=5000, nb_non_idle_online=5000)
        execute(nb_idle_offline=0, nb_non_idle_offline=0, nb_idle_online=0, nb_non_idle_online=0)

    def test_launch_ec2_instances(self):
        special_case_in_exception = '12345678901234567890throwexception'

        class MockEc2RunInstancesClass(object):
            def __init__(self):
                # Small hack to get to meta.client.run_instances
                self.meta = self
                self.meta.client = self
                self.calls = []

            def run_instances(self, **kwargs):
                for tag_dict in kwargs['TagSpecifications'][0]['Tags']:
                    if tag_dict['Key'] == 'Name' and tag_dict['Value'] == special_case_in_exception:
                        # Special case which should throw an exception
                        raise ClientError(error_response=unittest.mock.MagicMock(), operation_name='test2')

                self.calls.append(kwargs)

        def execute(nb_invalid_labels, nb_valid_entries):
            valid_label = random.choice(list(autoscaling._managed_jenkins_node_labels()))
            scale_up_slots = defaultdict(list)
            expected_messages = nb_invalid_labels

            # Invalid labels
            for _ in range(0, nb_invalid_labels):
                invalid_label = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(20))
                instance_name = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(20))
                scale_up_slots[invalid_label].append(instance_name)

            # Valid entries
            for _ in range(0, nb_valid_entries):
                instance_name = valid_label + '_' + \
                                ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(20))
                scale_up_slots[valid_label].append(instance_name)

            # Make a special case which will result in an exception, thrown by our mock.
            scale_up_slots[valid_label].append(special_case_in_exception)
            expected_messages += 1

            run_instances_mock = MockEc2RunInstancesClass()
            with self.assertLogs(level='ERROR') as log_manager:
                started_instances = autoscaling._launch_ec2_instances(scale_up_slots, run_instances_mock)
                assert len(log_manager.records) == expected_messages, "Expected {} log message, got {}: {}". \
                    format(expected_messages, len(log_manager.records),
                           [record.message for record in log_manager.records])
                logging.error("Hack to make sure the with-assert does not fail - we assert manually...")

            assert len(run_instances_mock.calls) == nb_valid_entries, 'Expected {} run_instances_mock.calls, got {}'. \
                format(nb_valid_entries, len(run_instances_mock.calls))
            assert len(started_instances) == nb_valid_entries, 'Expected {} started instances, got {}'. \
                format(nb_valid_entries, len(started_instances))
            # TODO: Validate content of these calls (e.g. label being set, right template etc)

        execute(nb_invalid_labels=5, nb_valid_entries=5)
        execute(nb_invalid_labels=0, nb_valid_entries=50)
        execute(nb_invalid_labels=50, nb_valid_entries=0)
        execute(nb_invalid_labels=0, nb_valid_entries=0)
        execute(nb_invalid_labels=50, nb_valid_entries=50)

    def test_format_ec2_user_data_command(self):
        with self.assertLogs(level='ERROR') as log_manager:
            for managed_label in autoscaling._managed_jenkins_node_labels():
                command = autoscaling._format_ec2_user_data_command(label=managed_label,
                                                                    target_instance_name='instance')
                assert command is not None, "Expected a user data command for {}, got None".format(managed_label)

            assert not log_manager.records, "Expected {} log message, got {}: {}". \
                format(0, len(log_manager.records), [record.message for record in log_manager.records])

            # Now input a non-existent label and ensure an error is getting printed
            command = autoscaling._format_ec2_user_data_command(label='garbage-label', target_instance_name='instance')
            assert command is None, "Expected None as user data command, got {}".format(command)
            assert len(log_manager.records) == 1, "Expected {} log message, got {}: {}". \
                format(1, len(log_manager.records), [record.message for record in log_manager.records])

    def test_create_jenkins_node_slots(self):
        def execute(nb_invalid_label, nb_valid_instances):
            jenkins_server = MockJenkinsServer(baseurl='http://0.0.0.0/')
            scale_up_nb_nodes = dict()
            valid_label = random.choice(list(autoscaling._get_slave_configuration()))

            # Invalid label without config
            for _ in range(0, nb_invalid_label):
                invalid_label = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(20))
                scale_up_nb_nodes[invalid_label] = random.randint(1, 10)

            # Valid label
            scale_up_nb_nodes[valid_label] = nb_valid_instances

            with self.assertLogs(level='ERROR') as log_manager:
                node_slots = autoscaling._create_jenkins_node_slots(jenkins_server, scale_up_nb_nodes)
                expected_messages = nb_invalid_label
                assert len(log_manager.records) == expected_messages, "Expected {} log message, got {}: {}". \
                    format(expected_messages, len(log_manager.records),
                           [record.message for record in log_manager.records])
                logging.error("Hack to make sure the with-assert does not fail - we assert manually...")

            if nb_valid_instances > 0:
                assert len(node_slots[valid_label]) == nb_valid_instances, \
                    "Expected {} valid instances, got {}".format(nb_valid_instances, len(node_slots[valid_label]))
            else:
                assert valid_label not in node_slots, \
                    "Expected 0 valid instances, got {}".format(len(node_slots[valid_label]))

            # Check if the invalid slots have been processed
            expected_node_slots_length = 1 if nb_valid_instances > 0 else 0
            assert len(node_slots) == expected_node_slots_length, \
                "Expected {} valid node slot label, got {}".format(expected_node_slots_length, len(node_slots))

            # TODO: Validate post requests
            assert jenkins_server.nb_post_called == nb_valid_instances, "Expected {} slot creations, got {}". \
                format(nb_valid_instances, jenkins_server.nb_post_called)

        execute(nb_invalid_label=5, nb_valid_instances=5)
        execute(nb_invalid_label=5000, nb_valid_instances=5000)
        execute(nb_invalid_label=0, nb_valid_instances=0)
        execute(nb_invalid_label=5, nb_valid_instances=0)
        execute(nb_invalid_label=0, nb_valid_instances=5)

    def test_extract_node_type_label(self):
        def execute(log_threshhold, nb_log_messages, assigned_labels, expected_label):
            data = self._util_create_node(display_name='invalid', nb_executors=1, assigned_labels=assigned_labels)

            with self.assertLogs(level=log_threshhold) as log_manager:
                type_label = autoscaling._managed_node_label(data)
                expected_messages = nb_log_messages
                assert len(log_manager.records) == expected_messages, "Expected {} log message, got {}: {}". \
                    format(expected_messages, len(log_manager.records),
                           [record.message for record in log_manager.records])
                logging.error("Hack to make sure the with-assert does not fail - we assert manually...")

            assert type_label == expected_label, \
                'Expected {} as returned label, got {}'.format(expected_label, type_label)

        def launch_blacklisted_label():
            blacklisted_label = random.choice(list(autoscaling._ignored_jenkins_node_labels()))
            execute(log_threshhold='DEBUG', nb_log_messages=1, assigned_labels=[blacklisted_label],
                    expected_label=blacklisted_label)

            valid_label = random.choice(list(autoscaling._managed_jenkins_node_labels()))
            execute(log_threshhold='DEBUG', nb_log_messages=1, assigned_labels=[valid_label, blacklisted_label],
                    expected_label=blacklisted_label)
            execute(log_threshhold='DEBUG', nb_log_messages=1, assigned_labels=[blacklisted_label, valid_label],
                    expected_label=blacklisted_label)

            random_label = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(20))
            execute(log_threshhold='DEBUG', nb_log_messages=1,
                    assigned_labels=[valid_label, blacklisted_label, random_label],
                    expected_label=blacklisted_label)
            execute(log_threshhold='DEBUG', nb_log_messages=1,
                    assigned_labels=[blacklisted_label, random_label, valid_label],
                    expected_label=blacklisted_label)
            execute(log_threshhold='DEBUG', nb_log_messages=1,
                    assigned_labels=[random_label, blacklisted_label, valid_label],
                    expected_label=blacklisted_label)

        def launch_multiple_managed_label():
            valid_labels_iter = iter(autoscaling._managed_jenkins_node_labels())
            valid_label_1 = valid_labels_iter.__next__()
            valid_label_2 = valid_labels_iter.__next__()
            random_label = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(20))

            execute(log_threshhold='ERROR', nb_log_messages=1, assigned_labels=[valid_label_1, valid_label_2],
                    expected_label=None)
            execute(log_threshhold='ERROR', nb_log_messages=1, assigned_labels=[valid_label_2, valid_label_1],
                    expected_label=None)

            execute(log_threshhold='ERROR', nb_log_messages=1,
                    assigned_labels=[random_label, valid_label_1, valid_label_2],
                    expected_label=None)
            execute(log_threshhold='ERROR', nb_log_messages=1,
                    assigned_labels=[valid_label_2, random_label, valid_label_1],
                    expected_label=None)

        def launch_no_managed_labels():
            execute(log_threshhold='WARNING', nb_log_messages=1, assigned_labels=[
                ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(20)),
                ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(20)),
                ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(20)),
                ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(20))],
                    expected_label=None)

        def launch_no_labels():
            execute(log_threshhold='WARNING', nb_log_messages=1, assigned_labels=[], expected_label=None)

        def launch_one_managed_label():
            label = random.choice(list(autoscaling._managed_jenkins_node_labels()))
            random_label = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(20))
            execute(log_threshhold='WARNING', nb_log_messages=0, assigned_labels=[label], expected_label=label)
            execute(log_threshhold='WARNING', nb_log_messages=0, assigned_labels=[label, random_label],
                    expected_label=label)
            execute(log_threshhold='WARNING', nb_log_messages=0, assigned_labels=[random_label, label],
                    expected_label=label)

        launch_blacklisted_label()
        launch_multiple_managed_label()
        launch_no_managed_labels()
        launch_no_labels()
        launch_one_managed_label()

    def test_delete_jenkins_node_objects(self):
        class MockJenkinsNode(object):
            def __init__(self, jenkins, name, is_online):
                self.online = is_online
                self.name = name
                self.baseurl = 'http://0.0.0.0/'
                self.jenkins = jenkins

            def is_online(self):
                return self.online

        def execute(nb_online, nb_offline):
            jenkins_server = MockJenkinsServer(baseurl='http://0.0.0.0/')
            node_objs = {}

            for _ in range(0, nb_online):
                name = 'online' + ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(20))
                node_objs[name] = MockJenkinsNode(name=name, jenkins=jenkins_server, is_online=True)

            for _ in range(0, nb_offline):
                name = 'offline' + ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(20))
                node_objs[name] = MockJenkinsNode(name=name, jenkins=jenkins_server, is_online=False)

            with self.assertLogs(level='ERROR') as log_manager:
                autoscaling._delete_jenkins_node_objects(node_objs)
                expected_messages = nb_online
                assert len(log_manager.records) == expected_messages, "Expected {} log message, got {}: {}". \
                    format(expected_messages, len(log_manager.records),
                           [record.message for record in log_manager.records])
                logging.error("Hack to make sure the with-assert does not fail - we assert manually...")

            assert jenkins_server.nb_post_called == nb_offline, "Expected {} slave deletions, got {}". \
                format(nb_offline, jenkins_server.nb_post_called)

        execute(nb_offline=0, nb_online=0)
        execute(nb_offline=5, nb_online=5)
        execute(nb_offline=0, nb_online=10)
        execute(nb_offline=10, nb_online=0)
        execute(nb_offline=1000, nb_online=0)
        execute(nb_offline=0, nb_online=1000)
        execute(nb_offline=1000, nb_online=1000)

    # pylint: disable=no-self-use
    def test_apply_upscale_limit(self):
        def execute(limit, nb_scale_up_nodes, nb_labels):
            nodes = dict()
            nodes['empty'] = 0
            slots_left = nb_scale_up_nodes
            for i in range(0, nb_labels):
                label = 'label' + str(i)
                if i == nb_labels - 1:
                    nb_nodes = slots_left
                else:
                    nb_nodes = random.randint(0, slots_left)
                slots_left -= nb_nodes
                nodes[label] = nb_nodes

            new_scale_up_nb_nodes = autoscaling._apply_upscale_limit(limit, nodes)

            nb_total_nodes = sum(new_scale_up_nb_nodes.values())
            assert nb_total_nodes <= limit, "Expected {} nodes at most, got {}. Nodes: {}". \
                format(limit, nb_total_nodes, pprint.pprint(new_scale_up_nb_nodes))
            if nb_scale_up_nodes >= limit:
                assert nb_total_nodes == limit, "Expected {} nodes, got {}. Nodes: {}". \
                    format(limit, nb_total_nodes, pprint.pprint(new_scale_up_nb_nodes))
            else:
                assert nb_total_nodes == nb_scale_up_nodes, "Expected {} nodes, got {}. Nodes: {}". \
                    format(nb_scale_up_nodes, nb_total_nodes, pprint.pprint(new_scale_up_nb_nodes))

            # Ensure we got no unexpected labels back
            for label in new_scale_up_nb_nodes.keys():
                assert label in nodes.keys(), "Found unexpected label {}. Expected labels: {}". \
                    format(label, nodes.keys())

        execute(limit=10, nb_scale_up_nodes=10, nb_labels=5)
        execute(limit=1, nb_scale_up_nodes=10, nb_labels=5)
        execute(limit=10, nb_scale_up_nodes=10, nb_labels=1)
        execute(limit=10, nb_scale_up_nodes=50, nb_labels=1)
        for i in range(0, 100):
            execute(limit=10, nb_scale_up_nodes=i, nb_labels=5)

    # pylint: disable=no-self-use
    def test_apply_downscale_limit(self):
        def execute(limit, nb_scale_down_nodes, nb_labels):
            nodes = dict()
            nodes['empty'] = list()
            slots_left = nb_scale_down_nodes
            for i in range(0, nb_labels):
                label = 'label' + str(i)
                if i == nb_labels - 1:
                    nb_nodes = slots_left
                else:
                    nb_nodes = random.randint(0, slots_left)
                slots_left -= nb_nodes

                nodes[label] = list()
                for j in range(0, nb_nodes):
                    nodes[label].append(j)  # j is a dummy object

            new_scale_down_nodes = autoscaling._apply_downscale_limit(limit, scale_down_nodes=nodes)

            nb_total_nodes = sum([len(lst) for lst in new_scale_down_nodes.values()])
            assert nb_total_nodes <= limit, "Expected {} nodes at most, got {}. Nodes: {}". \
                format(limit, nb_total_nodes, pprint.pformat(new_scale_down_nodes))
            if nb_total_nodes == limit:
                assert nb_total_nodes == limit, "Expected {} nodes, got {}. Nodes: {}". \
                    format(limit, nb_total_nodes, pprint.pformat(new_scale_down_nodes))

        execute(limit=10, nb_scale_down_nodes=10, nb_labels=5)
        execute(limit=1, nb_scale_down_nodes=10, nb_labels=5)
        execute(limit=10, nb_scale_down_nodes=10, nb_labels=1)
        execute(limit=10, nb_scale_down_nodes=50, nb_labels=5)
        execute(limit=10, nb_scale_down_nodes=50, nb_labels=1)

    def test_determine_faulty_nodes(self):
        nodes_data = [
            # Master
            self._util_create_node(display_name='master', assigned_labels=['master'],
                                   nb_executors=0, temporarily_offline=False, is_offline=False),

            # OK instances
            self._util_create_node(display_name='fresh_instance1', assigned_labels=['mxnetlinux-cpu'],
                                   nb_executors=1, temporarily_offline=False, is_offline=False),
            self._util_create_node(display_name='fresh_instance2', assigned_labels=['mxnetlinux-cpu'],
                                   nb_executors=1, temporarily_offline=False, is_offline=False),
            self._util_create_node(display_name='fresh_instance3', assigned_labels=['mxnetlinux-cpu'],
                                   nb_executors=1, temporarily_offline=False, is_offline=True,
                                   offline_cause_class='hudson.node_monitors.ResponseTimeMonitor$Data',
                                   offline_reason='Timed out for last 5 attempts'),

            # Dont shut down manually taken offline instances
            self._util_create_node(display_name='offline_ignore1', assigned_labels=['mxnetlinux-cpu'],
                                   nb_executors=1, temporarily_offline=True, is_offline=False,
                                   offline_reason='Custom offline1'),
            self._util_create_node(display_name='offline_ignore2', assigned_labels=['mxnetlinux-cpu'],
                                   nb_executors=1, temporarily_offline=True, is_offline=False,
                                   offline_reason='Custom offline2'),

            # Timeout during start
            self._util_create_node(display_name='start_timeout1', assigned_labels=['mxnetlinux-cpu'],
                                   nb_executors=1, temporarily_offline=False, is_offline=False),
            self._util_create_node(display_name='start_timeout2', assigned_labels=['mxnetlinux-cpu'],
                                   nb_executors=1, temporarily_offline=False, is_offline=False),
            self._util_create_node(display_name='start_timeout3', assigned_labels=['mxnetlinux-cpu'],
                                   nb_executors=1, temporarily_offline=False, is_offline=False),

            # Taken offline (e.g. low disk space)
            self._util_create_node(display_name='taken_offline_unhealthy1', assigned_labels=['mxnetlinux-cpu'],
                                   nb_executors=1, temporarily_offline=True, is_offline=False,
                                   offline_cause_class='hudson.node_monitors.DiskSpaceMonitorDescriptor$DiskSpace',
                                   offline_reason='Disk space is too low. Only 49.633GB left on /home/jenkins_slave.'),
            self._util_create_node(display_name='taken_offline_unhealthy2', assigned_labels=['mxnetlinux-cpu'],
                                   nb_executors=1, temporarily_offline=True, is_offline=False,
                                   offline_cause_class='hudson.node_monitors.DiskSpaceMonitorDescriptor$DiskSpace',
                                   offline_reason='Disk space is too low. Only 49.633GB left on /home/jenkins_slave.'),
            self._util_create_node(display_name='taken_offline_unhealthy3', assigned_labels=['mxnetlinux-cpu'],
                                   nb_executors=1, temporarily_offline=True, is_offline=False,
                                   offline_cause_class='hudson.node_monitors.Something$Something',
                                   offline_reason='Something is unhealthy'),

            # Marked as offline for downscaling but not actually scaled down ([DOWNSCALE])
            self._util_create_node(display_name='prepared_downscale1', assigned_labels=['mxnetlinux-cpu'],
                                   nb_executors=1, temporarily_offline=True, is_offline=False,
                                   offline_reason=autoscaling.DOWNSCALE_REASON),
            self._util_create_node(display_name='prepared_downscale2', assigned_labels=['mxnetlinux-cpu'],
                                   nb_executors=1, temporarily_offline=True, is_offline=False,
                                   offline_reason=autoscaling.DOWNSCALE_MANUAL_REASON + ' Reason2'),
            self._util_create_node(display_name='prepared_downscale3', assigned_labels=['mxnetlinux-cpu'],
                                   nb_executors=1, temporarily_offline=True, is_offline=False,
                                   offline_reason=autoscaling.DOWNSCALE_MANUAL_REASON + ' Reason3'),

            # Created but never started instance
            self._util_create_node(display_name='never_created1', assigned_labels=['mxnetlinux-cpu'],
                                   nb_executors=1, temporarily_offline=False, is_offline=True),
            self._util_create_node(display_name='never_created2', assigned_labels=['mxnetlinux-cpu'],
                                   nb_executors=1, temporarily_offline=False, is_offline=True),
            self._util_create_node(display_name='never_created3', assigned_labels=['mxnetlinux-cpu'],
                                   nb_executors=1, temporarily_offline=False, is_offline=True),

            # Unmanaged slave (e.g. physical devices)
            self._util_create_node(display_name='unmanaged1', assigned_labels=['unmanaged'],
                                   nb_executors=1, temporarily_offline=False, is_offline=False),
            self._util_create_node(display_name='unmanaged2', assigned_labels=['unmanaged'],
                                   nb_executors=1, temporarily_offline=False, is_offline=False)

        ]

        instance_uptime = {
            'fresh_instance1': 10, 'fresh_instance2': 10, 'fresh_instance3': 10,
            'offline_ignore1': 10, 'offline_ignore2': 500000,
            'start_timeout1': 50000000, 'start_timeout2': 50000000, 'start_timeout3': 50000000,
            'taken_offline_unhealthy1': 10, 'taken_offline_unhealthy2': 500, 'taken_offline_unhealthy3': 50000,
            'prepared_downscale1': 10, 'prepared_downscale2': 500, 'prepared_downscale3': 50000,
            'orphan1': 10, 'orphan2': 1023901
        }

        unconnected = {'mxnetlinux-cpu': ['start_timeout1', 'start_timeout2', 'start_timeout3', 'orphan1', 'orphan2']}

        (faulty_nodes, orphaned) = autoscaling._determine_faulty_nodes(
            nodes=nodes_data,
            unconnected_instances=unconnected,
            instance_uptime=instance_uptime)

        count_expected_filtered_nodes = 12
        self.assertEqual(orphaned, ['orphan1', 'orphan2'])
        assert len(faulty_nodes.keys()) == 1, \
            'Expected mxnetlinux-cpu as only faulty_nodes key, got {}'.format(pprint.pformat(faulty_nodes.keys()))
        assert len(faulty_nodes['mxnetlinux-cpu']) == count_expected_filtered_nodes, \
            'Expected {} filtered nodes, got {}: {}'.format(count_expected_filtered_nodes,
                                                            len(faulty_nodes['mxnetlinux-cpu']),
                                                            pprint.pformat(faulty_nodes['mxnetlinux-cpu']))

    def test_merge_dicts_nested_lists(self):
        # Partial insect
        assert autoscaling._merge_dicts_nested_lists(
            dict1={1: ['a', 'b'], 2: ['c', 'd']},
            dict2={2: ['d', 'e'], 3: ['f', 'g']}
        ) == {1: ['a', 'b'], 2: ['c', 'd', 'd', 'e'], 3: ['f', 'g']}

        # No intersect
        assert autoscaling._merge_dicts_nested_lists(
            dict1={1: ['a', 'b']},
            dict2={2: ['d', 'e']}
        ) == {1: ['a', 'b'], 2: ['d', 'e']}

        # Partial null
        assert autoscaling._merge_dicts_nested_lists(
            dict1=None,
            dict2={2: ['d', 'e']}
        ) == {2: ['d', 'e']}

        # Full null
        assert autoscaling._merge_dicts_nested_lists(
            dict1=None,
            dict2=None
        ) == {}

        # Empty lists
        assert autoscaling._merge_dicts_nested_lists(
            dict1={1: []},
            dict2={2: []}
        ) == {1: [], 2: []}

        # Same reference
        dict_same = {1: ['a', 'b'], 2: ['c', 'd']}
        assert autoscaling._merge_dicts_nested_lists(
            dict1=dict_same,
            dict2=dict_same
        ) == {1: ['a', 'b', 'a', 'b'], 2: ['c', 'd', 'c', 'd']}


if __name__ == '__main__':
    import nose2

    nose2.main()
