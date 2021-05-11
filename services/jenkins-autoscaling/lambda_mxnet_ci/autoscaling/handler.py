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

"""
Handler for auto scaling of MXNets CI system. Deployed using Lambda
"""

import datetime
import json
import logging
import os
import random
import re
import string
import time
from collections import defaultdict, OrderedDict
from urllib import parse
from typing import DefaultDict, Dict, Any, List, Optional
from itertools import filterfalse, tee

import math
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
import jenkinsapi
from joblib import Parallel, delayed

DOWNSCALE_REASON = '[AUTOSCALING] Downscale'
DOWNSCALE_MANUAL_REASON = '[DOWNSCALE]'

# Queue reasons being output by Jenkins.
RE_NO_AVAILABLE_NODE = [
    r"(There are no nodes with the label ‘(?P<label>[^\s;\\]*)’)",
    r"(All nodes of label ‘(?P<label>[^\s;\\]*)’ are offline)",
    r"(doesn’t have label (?P<label>[^\s;\\]*))",
    r"(Waiting for next available executor on (?P<label>[^\s;\\]*))",
    r"((?P<label>[^\s;\\]*) is offline)",
]
RE_NO_AVAILABLE_NODES = r"(^Waiting for next available executor$)"

# Offline cause for nodes that have been taken offline by the jenkins monitoring
NODE_MONITOR_OFFLINE_CAUSE = 'hudson.node_monitors'

# Since windows got hourly billing, we only want to consider instances which are running close to the full hour
WINDOWS_MIN_PARTIAL_RUNTIME_SECONDS = 55 * 60

# EC2s API only allows a specific number of filters. This constant defines the chunk size for these requests
EC2_FILTER_CHUNK_SIZE = 40

# Only try to scale up X number of instances per round. Otherwise, we might run into problems due to exceeding the
# maximum execution time of lambda
NUM_UPSCALES_PER_ROUND = 20

# Only try to scale down X number of instances per round. Otherwise, we might run into problems due to exceeding the
# maximum execution time of lambda
NUM_DOWNSCALES_PER_ROUND = 40

# Limit the number of parallel requests for AWS; otherwise, we might get our requests declined by the API
AWS_PARALLEL_REQUESTS_LIMIT = 3

# Limit the number of parallel requests for Jenkins; otherwise, we might be DOSing our own server
JENKINS_PARALLEL_REQUESTS_LIMIT = 100

# Limit the number of parallel create request for Jenkins. It tends to get into race conditions since the create
# action is not threadsafe.....
JENKINS_PARALLEL_CREATE_REQUESTS_LIMIT = 10

# Seconds a Jenkins request might have until it times out
JENKINS_REQUEST_TIMEOUT_SECONDS = 300


def partition(predicate, iterable):
    xs, ys = tee(iterable)
    return list(filter(predicate, xs)), list(filterfalse(predicate, ys))


def memoize(cached_function):
    """ Memoization decorator for functions taking one or more arguments. """

    # http://code.activestate.com/recipes/578231-probably-the-fastest-memoization-decorator-in-the-/

    class MemoDict(dict):
        def __init__(self, cached_function):
            super().__init__()
            self.cached_function = cached_function

        def __call__(self, *args):
            return self[args]

        def __missing__(self, key):
            ret = self[key] = self.cached_function(*key)
            return ret

    return MemoDict(cached_function)


def execute_scale_up_logic(jenkins_server, ec2_resource, scale_up_nb_nodes):
    if not scale_up_nb_nodes:
        logging.info('No scale up required')
        return

    # Scale up: Create jenkins node slots
    _scale_up_slots = _create_jenkins_node_slots(jenkins_server=jenkins_server, label2num_instances=scale_up_nb_nodes)

    # Scale up: Start nodes
    started_instance_names = _launch_ec2_instances(scale_up_slots=_scale_up_slots, ec2_resource=ec2_resource)
    not_started_instance_names = set([name for label, name_list in _scale_up_slots.items() for name in name_list]). \
        difference(set(started_instance_names))

    # Delete jenkins slave node entries which have not been started
    if not_started_instance_names:
        logging.warning('The following instances have not been started: %s', ', '.join(not_started_instance_names))
        not_started_node_objs = _convert_to_jenkins_nodes(server=jenkins_server, instances=not_started_instance_names)
        _delete_jenkins_node_objects(node_objs=not_started_node_objs)


def execute_scale_down_logic(jenkins_server, ec2_resource, scale_down_nodes):
    if not scale_down_nodes:
        logging.info('No scale down required')
        return

    # Extract all display names from scale_down_nodes. Node is an api internal dictionary,
    # coming from jenkinsapi.computers._data
    scale_down_node_names = [node['displayName'] for nodes in scale_down_nodes.values() for node in nodes]
    scale_down_nodes_list = list(_convert_to_jenkins_nodes(jenkins_server, scale_down_node_names).values())

    (nodes_online, nodes_offline) = partition(lambda node: not node._data['offline'], scale_down_nodes_list)

    # Mark nodes as offline to prevent builds being scheduled
    _mark_nodes_offline(offline_nodes=nodes_online, reason=DOWNSCALE_REASON)

    # Nodes that are offline but executing jobs are marked online again
    # Scale down: Validate nodes are properly taken offline and no builds are going to be interrupted
    final_scale_down_nodes_list, non_idle_offline_nodes = _partition_non_idle(nodes_online)
    # Re-enable filtered nodes
    logging.debug('Re-enabling %d non-idle nodes: %s', len(non_idle_offline_nodes), non_idle_offline_nodes)
    _mark_nodes_online(online_nodes=non_idle_offline_nodes)

    final_scale_down_nodes_list.extend(nodes_offline)

    # Scale down: Shutdown node instances
    shutdown_ec2_instance_name_list = [node.name for node in final_scale_down_nodes_list]
    logging.debug('Shutting down %d instances: %s', len(shutdown_ec2_instance_name_list),
                  shutdown_ec2_instance_name_list)

    #########################################################
    _terminate_ec2_instances(
        instance_names=shutdown_ec2_instance_name_list,
        ec2_resource=ec2_resource)
    #########################################################

    terminated_nodes = _convert_to_jenkins_nodes(
        server=jenkins_server,
        instances=shutdown_ec2_instance_name_list)

    logging.debug('Deleting %d jenkins nodes: %s', len(terminated_nodes), terminated_nodes)
    #########################################################
    _delete_jenkins_node_objects(node_objs=terminated_nodes)
    #########################################################


def determine_scale_up_nodes(queue_items: List[Dict[str, Any]], nodes: List[Dict[str, Any]],
                             unconnected: Dict[str, List[str]]) -> Dict[str, int]:
    """
    Determine the number of nodes which are required of each label
    :param queue_items: Currently enqueued items
    :param nodes: Currently connected nodes
    :param unconnected: instances which are starting or not yet connected
    :return: Dict(label, nb_required_nodes)
    """
    dict_required_executors: DefaultDict[str, int] = defaultdict(int)

    idle_nodes_per_label = _get_idle_nodes_per_label(nodes_data=nodes)

    cur_time_s = time.time()
    for queue_item in queue_items:
        # Make sure we're only processing queue items that are related to resource starvation
        label = _label_from_queued_job(nodes=nodes, queue_item=queue_item)
        if label:
            if label not in _minimum_queue_times_sec():  # pragma: no cover
                logging.error("Label %s from queue reason '%s' is not part of MINIMUM_QUEUE_TIMES_SEC - skipping..",
                              label, queue_item['why'])
                continue

            # Only consider items which have been in the queue for a specific time. This ensure we're not scaling
            # too aggressively.
            queue_duration_s = cur_time_s - (queue_item['inQueueSince'] / 1000)
            if queue_duration_s < _minimum_queue_times_sec()[label]:
                logging.debug('Queue duration of item %s is not mature enough: %d<%d',
                              queue_item['id'], queue_duration_s, _minimum_queue_times_sec()[label])
                continue

            # See if there are actually no nodes available or if the problem is actually that this job has no permission
            # to run on a restricted node. Unfortunately, we can't access the individual executors, so we have to rely
            # on the is_idle metric. TODO: Find out if we can get more detailed data or maybe even blacklist a job
            # Unfortunately, this will trigger a ping-pong in scale up and down since we're unable to determine ahead of
            # time whether a job is actually lacking nodes to run on or whether it's just ineligible. For now, we will
            # throw an error. In future, this could automatically be handled by another job. Also, an investigation
            # should be kicked off since this could mean somebody is trying to run on a restricted slave without
            # permission.
            if label in idle_nodes_per_label and idle_nodes_per_label[label] > 0:
                logging.error('Queue item %s is scheduled for label %s, but there are %d idle nodes available. This is '
                              'most likely somebody unauthorized trying to schedule an unrestricted job onto a '
                              'restricted slave. Please investigate by checking the job queue.',
                              queue_item['id'], label, idle_nodes_per_label[label])
                continue

            dict_required_executors[label] = dict_required_executors.get(label, 0) + 1
        else:
            logging.debug('Queue item %s is not related to resource starvation: %s',
                          queue_item['id'], queue_item['why'])

    label2num_instances = _calculate_nb_required_nodes(dict_required_executors=dict_required_executors)

    # substract the number of unconnected instances
    for label, names in unconnected.items():
        logging.debug('%d nodes of type %s currently starting', len(names), label)
        resulting_number = label2num_instances.get(label, 0) - len(names)
        resulting_number = max(0, resulting_number)  # Take negative numbers into account
        if resulting_number > 0:
            label2num_instances[label] = resulting_number
            logging.debug('%d new nodes for %s required (down from %d)', resulting_number, label, len(names))
        else:
            if label in label2num_instances:
                label2num_instances.pop(label)
                logging.debug('No new nodes for %s required (down from %d)', label, len(names))

    return label2num_instances


def determine_scale_down_nodes(nodes_data: List[Dict[str, Any]], instance_uptime: Dict[str, int]) \
        -> Dict[str, List[str]]:
    """
    Determine which instances should be shut down due to idle
    :param nodes_data: Currently connected nodes (List of dicts)
    :param instance_uptime: Duration about how long each node has been running
    :return: Dict(label, list(nodes_to_disable))
    """
    nodes_to_disable: DefaultDict[str, list] = defaultdict(list)
    considered_nodes: DefaultDict[str, list] = defaultdict(list)

    for node_data in nodes_data:
        if not node_data['offline'] and node_data['idle']:
            display_name = node_data['displayName']
            label = _managed_node_label(node_data)
            if not label:
                logging.error('Could not extract the managed label for node %s', display_name)
                continue

            # Check if label is managed - otherwise skip
            if label not in _managed_jenkins_node_labels():
                logging.debug('Label %s is not managed, skipping...', label)
                continue

            # TODO: Add a label that marks reserved instances

            if node_data['monitorData']['hudson.node_monitors.ArchitectureMonitor'] is None:
                # Sometimes, the architecture monitor is not set. This is a race condition and can be
                # ignored since the information is available within the next turn
                logging.info('Architecture has not been propagated for %s, ignoring until next scale_down check',
                             display_name)
                continue

            # Windows instances are getting billed hourly and need special handling
            if 'Windows' in node_data['monitorData']['hudson.node_monitors.ArchitectureMonitor']:
                if display_name not in instance_uptime:
                    logging.error('Unable to find uptime for %s', display_name)
                    continue

                running_duration_seconds = instance_uptime[display_name]
                running_duration_partial = running_duration_seconds % (60 * 60)
                # Don't shutdown instances below XXh50min uptime to make use of hourly billing
                if running_duration_partial < WINDOWS_MIN_PARTIAL_RUNTIME_SECONDS:
                    considered_nodes[label].append(node_data)
                    logging.debug(
                        'Ignoring %s because partial runtime %ds is below limit of %ds (hourly billing). Total '
                        'runtime: %ds',
                        display_name, running_duration_partial, WINDOWS_MIN_PARTIAL_RUNTIME_SECONDS,
                        running_duration_seconds)
                    continue

            # TODO: Check for how long an instance has been idling. There is no built-in API for now and the
            # only way is to go through the entire Jenkins build history. Save this up for later.

            nodes_to_disable[label].append(node_data)
            considered_nodes[label].append(node_data)

    # Leave some buffer for warm pool. This code makes sure to always leave X instances in idle while scaling down.
    # For example: 5 instances running, 3 in idle, WARM_POOL_SIZE set to 2. This code will remove only 1 instance,
    # leading to 4 instances running and 2 in idle.
    for warm_label, warm_value in _warm_pool_node_counts().items():
        cur_nodes = nodes_to_disable[warm_label]
        cur_considered_nodes = considered_nodes[warm_label]
        if cur_nodes:
            warm_value -= (len(cur_considered_nodes) - len(cur_nodes))
            for _ in range(0, warm_value):
                # Pop a random entry. Otherwise, the first node is never going to be shut down
                cur_nodes.pop(random.randrange(0, len(cur_nodes)))

    # Remove empty lists, caused by the usage of defaultdict()
    return {key: val for key, val in nodes_to_disable.items() if val}


def _determine_faulty_nodes(nodes: List[Dict[str, Any]], unconnected_instances: Dict[str, List[str]],
                            instance_uptime: Dict[str, int]) -> Dict[str, List[Any]]:
    """
    Determine all nodes that are in a faulty state and should thus be turned off
    :param unconnected_instances: Names of all nodes that are currently starting up
    :param nodes: Currently connected nodes (List of dicts)
    :param instance_uptime: Duration about how long each node has been running
    :return: (Dict[label, List(node)] containing nodes that are faulty, instances not found in jenkins)

    """
    label2faulty_nodes: DefaultDict[str, List[Any]] = defaultdict(list)
    orphaned_instances = []

    # Determine instances that failed to start up. This sometimes happens with windows slaves
    for label, instances in unconnected_instances.items():
        maximum_startup_limit = _maximum_startup_time()[label]
        for instance in instances:
            node = _find_node_by_name(nodes, instance)
            if not node:
                # Autoscaling instance not known to jenkins
                logging.error('Could not find node_data for %s, marked as orphaned instance for termination', instance)
                orphaned_instances.append(instance)
                continue

            uptime = instance_uptime[instance]
            if uptime > maximum_startup_limit:
                logging.warning('Instance %s failed to start up within %d seconds', instance, uptime)
                label2faulty_nodes[label].append(node)

    for node in nodes:
        if node['displayName'] == 'master':
            # Don't do anything for master
            continue

        label = _managed_node_label(node)

        if not label:
            logging.info('Slave %s is not managed by auto scaling. Ignoring for consideration of faulty instances',
                         node['displayName'])
        # Turn off slaves that have been marked as offline by Jenkins due to things like too low disk space
        elif node['temporarilyOffline'] and node['offlineCause'] and \
                node['offlineCause']['_class'].startswith(NODE_MONITOR_OFFLINE_CAUSE):
            logging.warning('Instance %s has been marked as offline by Jenkins monitoring due to "%s"',
                            node['displayName'], node['offlineCauseReason'])
            label2faulty_nodes[label].append(node)
        # Turn off slaves that have been marked to downscale but have not been downscaled
        elif node['offlineCauseReason'] == DOWNSCALE_REASON or node['offlineCauseReason'] \
                .startswith(DOWNSCALE_MANUAL_REASON):
            logging.warning('Instance %s has been marked to downscale but has not scaled down: "%s"',
                            node['displayName'], node['offlineCauseReason'])
            label2faulty_nodes[label].append(node)
        # Delete node slots that have been created but dont have a matching instance
        elif node['displayName'] not in instance_uptime:
            logging.warning('Slot for %s has been created but instance never started', node['displayName'])
            label2faulty_nodes[label].append(node)

    # Remove empty lists, caused by the usage of defaultdict()
    return ({key: val for key, val in label2faulty_nodes.items() if val}, orphaned_instances)


def _calculate_nb_required_nodes(dict_required_executors):
    """
    Calculate the number of required nodes based on the number of required executors for each label
    :param dict_required_executors: Dict[label, nb_required_executors]
    :return: Dict[label, nb_required_nodes]
    """
    dict_required_nodes = dict()
    for label, nb_required_executors in dict_required_executors.items():
        # Old jobs are still being triggered by some people, don't throw an error in that case
        if label in _ignored_jenkins_node_labels():
            logging.debug('Skipping ignored label %s', label)
            continue

        # Search for node with that label to extract how many executors it has
        nb_executors_per_node = _get_nb_executors_by_label(label)
        if nb_executors_per_node and nb_executors_per_node > 0:
            nb_required_nodes = math.ceil(nb_required_executors / nb_executors_per_node)
            logging.info('Need %d nodes for %d executors of type %s',
                         nb_required_nodes, nb_required_executors, label)

            if nb_required_nodes > 0:
                dict_required_nodes[label] = nb_required_nodes
        else:
            logging.error('Node label %s has %s executors per node. Has to be positive.',
                          label, nb_executors_per_node)

    return dict_required_nodes


def _unconnected_instances(nodes: list, instance_uptime: Dict[str, int], ec2_resource) \
        -> Dict[str, List[str]]:
    """
    Returns instances which are currently starting up but not connected yet
    :return: Dict, mapping label to List of slave names that are still starting up
    """
    dict_starting_nodes: Dict[str, List[str]] = defaultdict(list)
    instances_filter = ec2_resource.instances.filter(
        Filters=[
            {'Name': 'instance-state-name', 'Values': ['pending', 'running']},
            {'Name': 'tag:AutoScaledSlave', 'Values': ['True']}  # Ensure only listing instances managed by auto scaling
        ])
    for instance in instances_filter:
        tags = _ec2Instance_tag_dict(instance)
        target_node = _find_node_by_name(nodes=nodes, name=tags['Name'])
        if target_node and target_node['offline'] and (not target_node['temporarilyOffline']):
            logging.debug('Instance %s starting up but not connected yet', target_node['displayName'])
            if 'label' in tags:
                label = tags['label']
                uptime_seconds = instance_uptime[target_node['displayName']]
                logging.info('Instance %s - %s of type %s is starting up for %d seconds.',
                             instance.id, tags['Name'], label, uptime_seconds)

                dict_starting_nodes[label].append(tags['Name'])
            else:  # pragma: no cover
                logging.error("Managed slave instance %s does not have tag label", instance.id)
        elif not target_node:
            logging.error("Found orphaned / zombie instance: '%s'", instance.id)
            if 'label' in tags:
                label = tags['label']
                dict_starting_nodes[label].append(tags['Name'])
            else:  # pragma: no cover
                logging.error("Managed slave instance %s does not have tag label", instance.id)
    return dict_starting_nodes


def _label_from_queued_job(nodes, queue_item) -> Optional[str]:
    """
    Extract the node type label from a queue item. The queue item contains a reason that states why it's currently
    hanging and exposes the name of the label it's waiting for. This label is extracted by this method.
    :param queue_item: Queue item dict
    :return: Label
    """
    # Check if there are no running nodes in general. This is a special case since jenkins does not tell which
    # nodes are actually required. In that case, just assume we need a ubuntu-cpu executor.
    regex_result = re.search(RE_NO_AVAILABLE_NODES, queue_item['why'])
    if regex_result:
        logging.debug('There are no nodes on the Jenkins master, creating mxnetlinux-cpu nodes to start'
                      ' label propagation')
        label = 'mxnetlinux-cpu'
    else:
        for re_available_node in RE_NO_AVAILABLE_NODE:
            regex_result = re.search(re_available_node, queue_item['why'])
            if regex_result:
                label = regex_result.group('label')
                break
        else:
            return None

    # Clean up label of any other characters
    label = label.strip(' ‘’\'"')

    # Sometimes, Jenkins does not put the required label into the message but a node-name instead.
    # In this case, we have to extract the label from the node
    if label not in _managed_jenkins_node_labels():
        node = _find_node_by_name(nodes=nodes, name=label)
        if not node:
            logging.error("Queue reason '%s' contains unresolvable label '%s'", queue_item['why'], label)
            return None
        label = _managed_node_label(node=node)
        if not label:
            logging.error('Could not extract type label for node %s as part of queue reason "%s"',
                          node['displayName'], queue_item['why'])
            return None
    return label


def _get_nb_executors_by_label(label) -> Optional[int]:
    """
    Return the number of executors that can be run on
    :param label: Node label
    :return: Number of executors available for that label
    """
    if label in _get_nb_executors_per_label():
        return _get_nb_executors_per_label()[label]
    logging.error('Label %s is not part of NB_EXECUTORS_PER_LABEL', label)
    return None


def _find_node_by_name(nodes, name):
    """
    Loop through a list of nodes and return the one which has the matching display name
    :param nodes: List of nodes
    :param name: Target name
    :return: Matching node, None otherwise
    """
    # Nodes always have unique names, thus there's no need for duplicate check
    for node in nodes:
        if name == node['displayName']:
            return node
    return None


def _mark_nodes_offline(offline_nodes, reason):
    """
    Mark jenkins nodes as offline
    :param server: Jenkins server handle
    :param offline_nodes: List of nodes to mark as offline
    :return: None
    """
    if not offline_nodes:
        logging.info('No nodes to be marked as offline')
    else:
        logging.info('Marking %s as offline', [x.name for x in offline_nodes])
        Parallel(n_jobs=min(JENKINS_PARALLEL_REQUESTS_LIMIT, len(offline_nodes)), backend="threading")(
            delayed(node_obj.set_offline)(reason) for node_obj in offline_nodes)


def _mark_nodes_online(online_nodes):
    """
    Mark jenkins nodes as online
    :param server: Jenkins server handle
    :param offline_nodes: List of nodes to mark as online
    :return: None
    """
    if not online_nodes:
        logging.debug('No nodes to be marked as online')
    else:
        logging.info('Marking %s as online', online_nodes)
        Parallel(n_jobs=min(JENKINS_PARALLEL_REQUESTS_LIMIT, len(online_nodes)), backend="threading")(
            delayed(node_obj.set_online)() for node_obj in online_nodes)


def _convert_to_jenkins_nodes(server, instances):
    """
    Take a list of jenkins node names and convert them to API backed Node objects
    :param server: Jenkins server handle
    :param instances: Node names
    :return: Dict(displayName, node_obj)
    """
    nodes = dict()

    if not instances:
        return nodes

    # Unfortunately, the iterator of the jenkinsapi always requests the data of every single node upon calling the
    # dict (e.g. all_nodes[nodename]).
    # Since this is basically O(MN); M=len(offline_node_names); N=number of total nodes, we have to use a workaround
    # and create the objects ourselves instead of using the underlying dict - which is getting created in sequence...
    node_obj_list = Parallel(n_jobs=min(JENKINS_PARALLEL_REQUESTS_LIMIT, len(instances)), backend="threading")(
        delayed(_create_jenkins_node_obj)(server, x) for x in instances)

    for node_obj in node_obj_list:
        if node_obj:
            nodes[node_obj.name] = node_obj
    return nodes


# This has to be defined at this scope because joblib is not able to access functions defined in the local scope
def _create_jenkins_node_obj(server, node_name):
    """
    Helper function to create a jenkins node object.
    :return: Jenkins node object
    """
    try:
        node = jenkinsapi.node.Node(jenkins_obj=server, baseurl='{}/computer/{}'.format(server.baseurl, node_name),
                                    nodename=node_name, node_dict={})
        return node
    except Exception as e:
        logging.error("_create_jenkins_node_obj:")
        logging.exception(e)
        return None


def _partition_non_idle(node_objs):
    """
    Return nodes marked to be taken offline but still running a job. By design, nodes marked as offline are able to
    finish their scheduled jobs and don't get interrupted. This function filters nodes that got a job scheduled.
    :param node_objs: Jenkins nodes
    :return: 1. List of node_obj that are marked as offline and idling. 2. List of non-idle nodes
    """
    if not node_objs:
        return [], []

    # Update all objects before checking their content
    Parallel(n_jobs=min(JENKINS_PARALLEL_REQUESTS_LIMIT, len(node_objs)), backend="threading")(
        delayed(node_obj.poll)() for node_obj in node_objs)
    logging.debug("%d jenkins nodes updated", len(node_objs))

    new_node_objs = [node_obj for node_obj in node_objs if ((node_obj.is_idle()) and not node_obj.is_online())]
    non_idle_node_objs = [node_obj for node_obj in node_objs if ((not node_obj.is_idle()) or node_obj.is_online())]
    assert len(new_node_objs) + len(non_idle_node_objs) == len(node_objs)

    if non_idle_node_objs:
        logging.info('%s got a job scheduled while they are marked as offline - possible race condition',
                     ', '.join(str(o) for o in non_idle_node_objs))

    return new_node_objs, non_idle_node_objs


def _instance_uptime(ec2_resource) -> Dict[str, int]:
    """
    Return how long each instance has been running so far (uptime measured as time since launch, not OS uptime)
    :return: Dict[instance-name : uptime in seconds]
    """

    instances = list(ec2_resource.instances.filter(
        Filters=[
            {'Name': 'tag:AutoScaledSlave', 'Values': ['True']}  # Ensure only listing instances managed by auto scaling
            , {'Name': 'instance-state-name', 'Values': ['pending', 'running']}
        ]
    ))

    valid_instances = filter_ignored(instances)
    instance_uptime = {}
    if valid_instances:
        current_datetime = datetime.datetime.now(valid_instances[0].launch_time.tzinfo)
        for instance in valid_instances:
            name = _ec2Instance_tag_dict(instance)['Name']
            duration = (current_datetime - instance.launch_time).total_seconds()
            instance_uptime[name] = duration

    return instance_uptime


def _terminate_ec2_instances(instance_names, ec2_resource):
    """
    Shutdown the instances which the nodes with the passed names are running on
    :param instance_names: List of node names that should be shut down
    :param ec2_resource: EC2 resource handle
    """
    if instance_names:
        logging.info("Terminating %d instances: %s", len(instance_names), instance_names)

    # Prevent botocore.exceptions.ClientError: An error occurred (FilterLimitExceeded) when calling the
    # DescribeInstances operation: The maximum number of filter values specified on a single call is 200
    instance_names_chunked = chunks(source_list=instance_names, chunk_size=EC2_FILTER_CHUNK_SIZE)
    for instance_names in instance_names_chunked:
        ec2_resource.instances.filter(
            Filters=
            [
                {'Name': 'tag:Name', 'Values': instance_names},
                {'Name': 'tag:AutoScaledSlave', 'Values': ['True']}
                # Ensure only listing instances managed by auto scaling
            ]
        ).terminate()


def filter_ignored(ec2_instances):
    ignored = set(_ignored_jenkins_node_names())
    return list(filter(lambda x: _ec2Instance_tag_dict(x)['Name'] not in ignored, ec2_instances))


def _delete_jenkins_node_objects(node_objs):
    """
    Delete the jenkins slave node entries
    :param node_names: List of node objs
    """
    if not node_objs:
        logging.debug('No jenkins nodes to delete, exiting eagerly')
    else:
        Parallel(n_jobs=min(JENKINS_PARALLEL_REQUESTS_LIMIT, len(node_objs)), backend="threading")(
            delayed(_delete_jenkins_node_object)(node_obj) for node_obj in node_objs.values())


def _delete_jenkins_node_object(node_obj):
    """
    Delete a jenkins node object from the jenkins master
    :param node_obj:
    :return:
    """
    from requests.exceptions import HTTPError
    try:
        if node_obj.is_online():
            logging.error('Unable to delete still connected jenkins node %s', node_obj.name)
            return

        delete_url = "{}/doDelete".format(node_obj.baseurl)
        node_obj.jenkins.requester.post_and_confirm_status(url=delete_url, data={}, allow_redirects=False)
    except HTTPError as e:
        # The JenkinsAPI returns a 404 if a slave does not exist. Since we are trying to delete it in this call,
        # that's totally fine. The background is the concurrency and inconsistency of the Jenkins backend. Sometimes,
        # a slave is still being returned as existent although it already has been deleted. We can gracefully ignore
        # that exception then.
        if e.response.status_code == 404:
            logging.debug('Slave has been deleted already, no need to delete %s', node_obj.baseurl)
        else:
            raise


def _launch_ec2_instances(scale_up_slots, ec2_resource):
    """
    Launch ec2 instances, matching the appropriate labels
    :param scale_up_slots:
    :param ec2_resource:
    :return: List of started instance names. Allows to determine whether some instances were not started.
    """
    jobs = []
    launch_templates = _launch_templates()

    # Start each instance one by one as each of them require different user data
    for label, target_instance_names in scale_up_slots.items():
        if label not in launch_templates:
            logging.error('No launch template for %s defined', label)
            continue

        launch_template = launch_templates[label]
        launch_template_id = launch_template['id']
        launch_template_version = launch_template['version']

        for target_instance_name in target_instance_names:
            logging.debug('Launching instance %s of type %s', target_instance_name, label)
            user_data_command = _format_ec2_user_data_command(label=label, target_instance_name=target_instance_name)
            if user_data_command is None:  # pragma: no cover
                logging.error('No user data command defined for %s, skipping...', target_instance_name)
                continue
            else:
                # Enqueue job
                jobs.append({
                    'label': label,
                    'target_instance_name': target_instance_name,
                    'launch_template_id': launch_template_id,
                    'launch_template_version': launch_template_version,
                    'user_data_command': user_data_command
                })

    started_instance_names = Parallel(n_jobs=min(AWS_PARALLEL_REQUESTS_LIMIT, len(jobs)), backend="threading")(
        delayed(_launch_ec2_instance)(ec2_resource=ec2_resource, label=job['label'],
                                      target_instance_name=job['target_instance_name'],
                                      launch_template_id=job['launch_template_id'],
                                      launch_template_version=job['launch_template_version'],
                                      user_data_command=job['user_data_command']) for job in jobs)

    return [x for x in started_instance_names if x is not None]


def _launch_ec2_instance(ec2_resource, label, target_instance_name, launch_template_id, launch_template_version,
                         user_data_command):
    try:
        ec2_resource.meta.client.run_instances(
            DryRun=False,
            MaxCount=1,
            MinCount=1,
            LaunchTemplate={
                'LaunchTemplateId': launch_template_id,
                'Version': launch_template_version
            },
            TagSpecifications=[
                {
                    'ResourceType': 'instance',
                    'Tags': [
                        {
                            'Key': 'Name',
                            'Value': target_instance_name
                        },
                        {
                            'Key': 'AutoScaledSlave',
                            'Value': 'True'
                        },
                        {
                            'Key': 'label',
                            'Value': label
                        }
                    ]
                },
            ],
            UserData=user_data_command
        )
        return target_instance_name
    except ClientError as client_error:
        error_code = client_error.response['Error']['Code']
        if error_code == 'InsufficientInstanceCapacity':
            logging.info("Insufficient instance capacity, can't launch %s: %s",
                         target_instance_name, client_error.response['Error']['Message'])
        else:
            logging.exception('Exception occurred during instance launch')

    # Make sure to catch everything, otherwise we won't be able to clean up properly
    except Exception:  # pylint: disable=broad-except
        logging.exception('Unexpected exception during instance launch')


def _format_ec2_user_data_command(label, target_instance_name):
    """
    Format the EC2 user data command that is being passed to a started instance
    :return:
    """
    jenkins_credentials = _get_jenkins_credentials()

    def format_windows(target_instance_name):
        # Make sure this has no indentation or it will be invalid powershell code!
        return \
            """\
<script>
mkdir C:\jenkins_slave
cd C:\jenkins_slave
@echo {JENKINS_PUBLIC_URL}> jenkins_master_url.txt
@echo {JENKINS_PRIVATE_URL}> jenkins_master_private_url.txt
@echo {SLAVE_NAME}> jenkins_slave_name.txt
</script>
            """.format(
                JENKINS_PUBLIC_URL=jenkins_credentials['jenkins_url'],
                JENKINS_PRIVATE_URL=jenkins_credentials['jenkins_priv_url'],
                SLAVE_NAME=target_instance_name
            )

    def format_linux(label, target_instance_name):
        # Make sure this has no indentation or it will be invalid bash code!
        return \
            """\
#!/bin/bash
echo '{JENKINS_PUBLIC_URL}' > /home/jenkins_slave/jenkins_master_url
echo '{JENKINS_PRIVATE_URL}' > /home/jenkins_slave/jenkins_master_private_url
echo '{SLAVE_NAME}' > /home/jenkins_slave/jenkins_slave_name

            """.format(
                JENKINS_PUBLIC_URL=jenkins_credentials['jenkins_url'],
                JENKINS_PRIVATE_URL=jenkins_credentials['jenkins_priv_url'],
                SLAVE_NAME=target_instance_name
            )

    linux_types = ['restricted-ub18-c6g',
                   'mxnetlinux-cpu',
                   'restricted-mxnetlinux-cpu',
                   'mxnetlinux-gpu',
                   'restricted-mxnetlinux-gpu',
                   'mxnetlinux-gpu-g4',
                   'restricted-mxnetlinux-gpu-g4',
                   'mxnetlinux-gpu-p3-8xlarge',
                   'utility',
                   'restricted-utility']

    windows_types = ['mxnetwindows-cpu',
                     'mxnetwindows-gpu']

    if label in linux_types:
        return format_linux(label=label, target_instance_name=target_instance_name)
    if label in windows_types:
        return format_windows(target_instance_name=target_instance_name)

    logging.error('Unable to find user data handler for %s', label)
    return None


def _create_jenkins_node_slots(jenkins_server, label2num_instances):
    """
    Create a
    :param label:
    :return:
    """
    # We could use the swarm plugin to do this automatically, but we don't want to deploy credentials to our slaves.
    # Thus, we create nodes ourselves.
    jobs = []
    node_slots = defaultdict(list)
    for label, num_instances in label2num_instances.items():
        logging.info('Creating %d nodes of type %s', num_instances, label)

        if label not in _get_slave_configuration():
            logging.error('No slave configuration for %s found', label)
            continue
        configuration = _get_slave_configuration()[label]

        for _ in range(0, num_instances):
            random_part = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
            name = '{}_{}'.format(label, random_part)
            logging.debug('Creating slave slot %s of type %s', name, label)
            # Create node slot through Jenkins API. Unfortunately, we have to write our own implementation of
            # node.Node.get_node_attributes() to support all required options. This also reimplements
            # jenkins_server.nodes.create_node due to inefficiency of underlying implementation
            node_attributes_encoded = parse.urlencode(
                _custom_get_node_attributes(name=name, node_attributes=configuration))
            url = ('{}/computer/doCreateItem?{}'.format(jenkins_server.baseurl,
                                                        node_attributes_encoded))
            data = {'json': node_attributes_encoded}
            jobs.append({
                'url': url,
                'data': data
            })

            node_slots[label].append(name)

    if jobs:
        Parallel(n_jobs=min(JENKINS_PARALLEL_CREATE_REQUESTS_LIMIT, len(jobs)), backend="threading")(
            delayed(jenkins_server.requester.post_and_confirm_status)(url=job['url'], data=job['data'],
                                                                      allow_redirects=False) for job in jobs)
    else:
        logging.debug('No jenkins node slot to create')

    return node_slots


def _custom_get_node_attributes(name, node_attributes):
    """
    Custom implementation of node.Node.get_node_attributes() in order to specify more options.

    :return: Node attributes dict formatted for Jenkins API request
            to create node
    """

    launcher = {
        # http://javadoc.jenkins.io/archive/jenkins-2.73/index.html?hudson/slaves/JNLPLauncher.html
        'stapler-class': 'hudson.slaves.JNLPLauncher',
        'tunnel': node_attributes['tunnel']  # Custom option
    }

    retention = {
        'stapler-class': 'hudson.slaves.RetentionStrategy$Always',
        '$class': 'hudson.slaves.RetentionStrategy$Always'
    }

    node_props = {
        'stapler-class-bag': 'true'
    }

    if node_attributes['job_name_restriction_regex']:
        node_props['com.synopsys.arc.jenkinsci.plugins.jobrestrictions.nodes.JobRestrictionProperty'] = {
            '$plugin': 'job-restrictions@0.7',
            'jobRestriction': {
                'stapler-class':
                    'com.synopsys.arc.jenkinsci.plugins.jobrestrictions.restrictions.job.RegexNameRestriction',
                '$class': 'com.synopsys.arc.jenkinsci.plugins.jobrestrictions.restrictions.job.RegexNameRestriction',
                'regexExpression': node_attributes['job_name_restriction_regex'],
                'checkShortName': 'false'
            }
        }

    params = {
        'name': name,
        'type': 'hudson.slaves.DumbSlave$DescriptorImpl',
        'json': json.dumps({
            'name': name,
            'nodeDescription': node_attributes['node_description'],
            'numExecutors': node_attributes['num_executors'],
            'remoteFS': node_attributes['remote_fs'],
            'labelString': node_attributes['labels'],
            'mode': 'EXCLUSIVE' if node_attributes['exclusive'] else 'NORMAL',
            'retentionStrategy': retention,
            'type': 'hudson.slaves.DumbSlave',
            'nodeProperties': node_props,
            'launcher': launcher
        })
    }

    return params


def _get_idle_nodes_per_label(nodes_data: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Determine how many nodes of each label are in idle
    :param nodes_data: Jenkins nodes data
    :return: Dict[label, count]
    """
    results: DefaultDict[str, int] = defaultdict(int)
    for node_data in nodes_data:
        if node_data['offline'] or not node_data['idle']:
            # Node offline or active, ignore it
            continue

        label = _managed_node_label(node_data)
        results[label] = results.get(label, 0) + 1

    return results


def _managed_node_label(node) -> str:
    """
    Extract the node label e.g. mxnet-linux-cpu or mxnet-windows-gpu from a jenkins node item.
    Nodes have several labels: such as mxnetlinux-cpu and mxnetlinux-cpu_<random tag> we return the managed one.
    :param node: Node
    :return: string
    """
    display_name = node['displayName']
    assigned_labels = set()
    # Convert list of tuples ('name' : 'label') to set
    for labels_dict in node['assignedLabels']:
        assigned_labels.add(labels_dict['name'])

    # Check if blacklisted
    intersection_blacklist = assigned_labels.intersection(_ignored_jenkins_node_labels())
    if intersection_blacklist:
        logging.debug('Node %s matches blacklisted labels (%s)',
                      display_name, ' & '.join(intersection_blacklist))
        return next(iter(intersection_blacklist))

    intersection_match = assigned_labels.intersection(_managed_jenkins_node_labels())
    if len(intersection_match) > 1:
        logging.error('Node %s has %d matching managed labels: (%s)',
                      display_name, len(intersection_match), ' & '.join(intersection_match))
        return None

    if not intersection_match:
        logging.warning('Node %s has no matching managed labels. Assigned labels: (%s)',
                        display_name, ' & '.join(assigned_labels))
        return None

    # Found one matching label - that's the one we're looking for
    return next(iter(intersection_match))


def _apply_upscale_limit(limit, label2num_instances):
    """
    Cut-off numbers if the sum is above the limits
    :param limit: Maximum number of instances
    :param label2num_instances: Requested instances
    :return: Filtered dict of instances
    """
    # Ordering the dict ascendingly (1 -> 2 -> 5 -> 7 -> etc) allows to ensure the floating point imprecision
    # rather hits the biggest value and cuts that one off by one or two rather than cutting off the instances
    # which are less required. This is especially significant in cases where only 1 instance was requested
    # which would've resulted in the value being reduced to 0.
    ordered_label2num_instances = OrderedDict(sorted(label2num_instances.items(), key=lambda t: t[1]))
    new_scale_up_num_nodes = dict()
    total_num_requested = sum(label2num_instances.values())
    if total_num_requested <= limit:
        # No cut-off needed
        return label2num_instances

    reduction_factor = limit / total_num_requested
    num_nodes_left = limit
    for label, num_max_nodes in ordered_label2num_instances.items():
        new_value = min(num_nodes_left, int(math.ceil(num_max_nodes * reduction_factor)))
        num_nodes_left -= new_value
        new_scale_up_num_nodes[label] = new_value

    num_total_new_scale_up_nodes = sum(new_scale_up_num_nodes.values())
    assert num_total_new_scale_up_nodes == limit, 'Floating point imprecision detected. ' \
                                                  'Num Nodes: {}  Limit: {}'. \
        format(num_total_new_scale_up_nodes, limit)

    for label, num_requested_instances in label2num_instances.items():
        num_planned_instances = new_scale_up_num_nodes.get(label, 0)
        if num_planned_instances != num_requested_instances:
            logging.info('Limiting upscale of %s from %d to %d', label, num_requested_instances, num_planned_instances)

    return new_scale_up_num_nodes


def _apply_downscale_limit(limit, scale_down_nodes):
    i = 0
    shuffeled = list(scale_down_nodes.items())
    random.shuffle(shuffeled)
    new_scale_down_nodes = defaultdict(list)
    for label, nodes in shuffeled:
        for node in nodes:
            i += 1
            if i > limit:
                logging.info('Reached downscale limit')
                break
            else:
                new_scale_down_nodes[label].append(node)

        if i >= limit:
            break

    return new_scale_down_nodes


def _get_jenkins_handle() -> jenkinsapi.jenkins.Jenkins:  # pragma: no cover
    from requests.exceptions import HTTPError

    jenkins_credentials = _get_jenkins_credentials()
    try:
        server = jenkinsapi.jenkins.Jenkins(baseurl=jenkins_credentials['jenkins_url'],
                                            username=jenkins_credentials['github_username'],
                                            password=jenkins_credentials['github_token'],
                                            timeout=JENKINS_REQUEST_TIMEOUT_SECONDS)
    except HTTPError as e:
        logging.exception('Error initializing Jenkins API.')
        if e.response.status_code == 500:
            logging.error('Did you properly set up the API token? https://REDACTED/MXBLN-376')

        logging.error('HTML response - use an HTML beautifier to view it properly: %s', e.response.content)
        raise Exception('Error initializing Jenkins API', e)

    # Jenkins returns a 302 (redirect) for certain requests. That's a valid response code somehow.....
    # We do not want to follow redirects since they are very expensive and cause timeouts
    # See https://REDACTED/MXBLN-298/communication for further detailsI
    server.requester.VALID_STATUS_CODES.extend([302])
    _add_timer_to_jenkins_requester(jenkins_server=server)
    return server


def _add_timer_to_jenkins_requester(jenkins_server):
    """
    Attach a hook to the Jenkins requester functions that allow to print the duration of an HTTP request
    :param jenkins_server: Hooked jenkins server
    :return: Nothing
    """

    def timing_decorator(f):
        def wrap(*args, **kwargs):
            # These guys don't like to call their API in a consistent fashion. Thus, we have to play hide and seek
            # and search for the argument...
            url = None
            for arg in args:
                if '://' in arg:
                    url = arg
                    break

            if not url:
                url = kwargs['url']

            logging.debug('%s is starting request to %s', f.__name__, url)

            time1 = time.time()
            ret = f(*args, **kwargs)
            time2 = time.time()

            logging.debug('{:s} took {:.3f} ms to request {:s}'.format(f.__name__, (time2 - time1) * 1000.0, url))

            return ret

        return wrap

    jenkins_server.requester.get_and_confirm_status = \
        timing_decorator(jenkins_server.requester.get_and_confirm_status)
    jenkins_server.requester.post_and_confirm_status = \
        timing_decorator(jenkins_server.requester.post_and_confirm_status)
    jenkins_server.requester.get_url = \
        timing_decorator(jenkins_server.requester.get_url)
    jenkins_server.requester.post_url = \
        timing_decorator(jenkins_server.requester.post_url)


@memoize
def _get_jenkins_credentials():  # pragma: no cover
    secret_name = os.environ['SECRET_NAME']
    endpoint_url = os.environ['SECRET_ENDPOINT_URL']
    region_name = os.environ['SECRET_ENDPOINT_REGION']

    session = _get_aws_session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name,
        endpoint_url=endpoint_url
    )
    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as client_error:
        if client_error.response['Error']['Code'] == 'ResourceNotFoundException':
            logging.exception("The requested secret %s was not found", secret_name)
        elif client_error.response['Error']['Code'] == 'InvalidRequestException':
            logging.exception("The request was invalid due to:")
        elif client_error.response['Error']['Code'] == 'InvalidParameterException':
            logging.exception("The request had invalid params:")
        else:
            raise
    else:
        secret = get_secret_value_response['SecretString']
        secret_dict = json.loads(secret)
        return secret_dict


@memoize
def _warm_pool_node_counts() -> Dict[str, int]:
    """
    Leave some buffer for warm pool. This code makes sure to always leave X instances in idle while scaling down.
    For example: 5 instances running, 3 in idle, WARM_POOL_SIZE set to 2. This code will remove only 1 instance,
    leading to 4 instances running and 2 in idle.
    :return: Config dict
    """
    return json.loads(os.environ['WARM_POOL_SIZE'])


@memoize
def _minimum_queue_times_sec() -> Dict[str, int]:
    """
    Retrieves values specifying the minimum amount of time a job should remain in the Jenkins queue before being
    considered in scale_up calls. Each job type is configured dependent on the required jenkins node label.
    :return: A dictionary with values representing minimum queue time required before a job is considered in scaling,
    and a key representing the jenkins node label
    """
    return json.loads(os.environ['MINIMUM_QUEUE_TIMES_SEC'])


@memoize
def _maximum_startup_time() -> Dict[str, int]:
    """
    Retrieve the maximum time an instance is allowed to need for start up.
    :return: Dictionary mapping maximum startup time in seconds to the appropriate label
    """
    return json.loads(os.environ['MAXIMUM_STARTUP_TIME_SEC'])


@memoize
def _ignored_jenkins_node_names() -> List[str]:
    """
    Ignore nodes with these names
    :return: Config list
    """
    return json.loads(os.environ['IGNORED_JENKINS_NODE_NAMES'])


@memoize
def _ignored_jenkins_node_labels() -> List[str]:
    """
    Labels that are ignored by the auto scaling system. The system will not throw an error if they are encountered
    :return: Config list
    """
    return json.loads(os.environ['IGNORED_JENKINS_NODE_LABELS'])


@memoize
def _managed_jenkins_node_labels() -> List[str]:
    """
    Get a list of labels that are being managed by the auto scaling system
    :return: Config list
    """
    return json.loads(os.environ['MANAGED_JENKINS_NODE_LABELS'])


@memoize
def _launch_templates():
    return json.loads(os.environ['LAUNCH_TEMPLATES'])


@memoize
def _get_nb_executors_per_label():
    return json.loads(os.environ['EXECUTORS_PER_LABEL'])


@memoize
def _get_jenkins_private_tunnel_address():
    return os.environ['JENKINS_PRIV_TUNNEL']


@memoize
def _get_slave_configuration():
    return {
        'restricted-ub18-c6g': {
            'num_executors': _get_nb_executors_per_label()['restricted-ub18-c6g'],  # Number of executors
            'node_description': '[AUTOSCALING] MXNet slave running Ubuntu 18.04 on a c6g.16xlarge',
            'remote_fs': '/home/jenkins_slave',  # Remote workspace location
            'labels': 'restricted-ub18-c6g',  # Space separated labels string
            'exclusive': True,  # Only run jobs assigned to it
            'tunnel': _get_jenkins_private_tunnel_address(),
            'job_name_restriction_regex': '^restricted-(.*)'  # Only run jobs which start with restricted-
        },
        'mxnetlinux-cpu': {
            'num_executors': _get_nb_executors_per_label()['mxnetlinux-cpu'],  # Number of executors
            'node_description': '[AUTOSCALING] MXNet slave running Ubuntu 16.04 on a c5.18xlarge',
            'remote_fs': '/home/jenkins_slave',  # Remote workspace location
            'labels': 'mxnetlinux-cpu',  # Space separated labels string
            'exclusive': True,  # Only run jobs assigned to it
            'tunnel': _get_jenkins_private_tunnel_address(),
            'job_name_restriction_regex': '^(?!restricted-).+'  # Run only unrestricted jobs
        },
        'restricted-mxnetlinux-cpu': {
            'num_executors': _get_nb_executors_per_label()['mxnetlinux-cpu'],  # Number of executors
            'node_description': '[AUTOSCALING] MXNet slave running Ubuntu 16.04 on a c5.18xlarge',
            'remote_fs': '/home/jenkins_slave',  # Remote workspace location
            'labels': 'restricted-mxnetlinux-cpu',  # Space separated labels string
            'exclusive': True,  # Only run jobs assigned to it
            'tunnel': _get_jenkins_private_tunnel_address(),
            'job_name_restriction_regex': '^restricted-(.*)'  # Only run jobs which start with restricted-
        },
        'mxnetlinux-gpu': {
            'num_executors': _get_nb_executors_per_label()['mxnetlinux-gpu'],  # Number of executors
            'node_description': '[AUTOSCALING] MXNet slave running Ubuntu 16.04 on a g3.8xlarge',
            'remote_fs': '/home/jenkins_slave',  # Remote workspace location
            'labels': 'mxnetlinux-gpu',  # Space separated labels string
            'exclusive': True,  # Only run jobs assigned to it
            'tunnel': _get_jenkins_private_tunnel_address(),
            'job_name_restriction_regex': '^(?!restricted-).+'  # Run only unrestricted jobs
        },
        'restricted-mxnetlinux-gpu': {
            'num_executors': _get_nb_executors_per_label()['restricted-mxnetlinux-gpu'],  # Number of executors
            'node_description': '[AUTOSCALING] MXNet slave running Ubuntu 16.04 on a g3.8xlarge',
            'remote_fs': '/home/jenkins_slave',  # Remote workspace location
            'labels': 'restricted-mxnetlinux-gpu',  # Space separated labels string
            'exclusive': True,  # Only run jobs assigned to it
            'tunnel': _get_jenkins_private_tunnel_address(),
            'job_name_restriction_regex': '^restricted-(.*)'  # Only run jobs which start with restricted-
        },
        'mxnetlinux-gpu-g4': {
            'num_executors': _get_nb_executors_per_label()['mxnetlinux-gpu-g4'],  # Number of executors
            'node_description': '[AUTOSCALING] MXNet slave running Ubuntu 18.04 on a g4dn.4xlarge',
            'remote_fs': '/home/jenkins_slave',  # Remote workspace location
            'labels': 'mxnetlinux-gpu-g4',  # Space separated labels string
            'exclusive': True,  # Only run jobs assigned to it
            'tunnel': _get_jenkins_private_tunnel_address(),
            'job_name_restriction_regex': '^(?!restricted-).+'  # Run only unrestricted jobs
        },
        'restricted-mxnetlinux-gpu-g4': {
            'num_executors': _get_nb_executors_per_label()['restricted-mxnetlinux-gpu-g4'],  # Number of executors
            'node_description': '[AUTOSCALING] MXNet slave running Ubuntu 18.04 on a g4dn.4xlarge',
            'remote_fs': '/home/jenkins_slave',  # Remote workspace location
            'labels': 'restricted-mxnetlinux-gpu-g4',  # Space separated labels string
            'exclusive': True,  # Only run jobs assigned to it
            'tunnel': _get_jenkins_private_tunnel_address(),
            'job_name_restriction_regex': '^restricted-(.*)'  # Only run jobs which start with restricted-
        },
        'mxnetlinux-gpu-p3-8xlarge': {
            'num_executors': _get_nb_executors_per_label()['mxnetlinux-gpu-p3-8xlarge'],  # Number of executors
            'node_description': '[AUTOSCALING] MXNet slave running Ubuntu 16.04 on a p3.8xlarge',
            'remote_fs': '/home/jenkins_slave',  # Remote workspace location
            'labels': 'mxnetlinux-gpu-p3-8xlarge',  # Space separated labels string
            'exclusive': True,  # Only run jobs assigned to it
            'tunnel': _get_jenkins_private_tunnel_address(),
            'job_name_restriction_regex': '^(?!restricted-).+'  # Run only unrestricted jobs
        },
        'mxnetwindows-cpu': {
            'num_executors': _get_nb_executors_per_label()['mxnetwindows-cpu'],  # Number of executors
            'node_description': '[AUTOSCALING] MXNet slave running Windows Datacenter 2016 on a c5.18xlarge',
            'remote_fs': 'C:/jenkins_slave',  # Remote workspace location
            'labels': 'mxnetwindows-cpu',  # Space separated labels string
            'exclusive': True,  # Only run jobs assigned to it
            'tunnel': _get_jenkins_private_tunnel_address(),
            'job_name_restriction_regex': '^(?!restricted-).+'  # Run only unrestricted jobs
        },
        'mxnetwindows-gpu': {
            'num_executors': _get_nb_executors_per_label()['mxnetwindows-gpu'],  # Number of executors
            'node_description': '[AUTOSCALING] MXNet slave running Windows Datacenter 2016 on a g3.8xlarge',
            'remote_fs': 'C:/jenkins_slave',  # Remote workspace location
            'labels': 'mxnetwindows-gpu',  # Space separated labels string
            'exclusive': True,  # Only run jobs assigned to it
            'tunnel': _get_jenkins_private_tunnel_address(),
            'job_name_restriction_regex': '^(?!restricted-).+'  # Run only unrestricted jobs
        },
        'utility': {
            'num_executors': _get_nb_executors_per_label()['utility'],  # Number of executors
            'node_description': '[AUTOSCALING] Slave for utility operations',
            'remote_fs': '/home/jenkins_slave',  # Remote workspace location
            'labels': 'utility',  # Space separated labels string
            'exclusive': True,  # Only run jobs assigned to it
            'tunnel': _get_jenkins_private_tunnel_address(),
            'job_name_restriction_regex': '^(?!restricted-).+'  # Run only unrestricted jobs
        },
        'restricted-utility': {
            'num_executors': _get_nb_executors_per_label()['restricted-utility'],  # Number of executors
            'node_description': '[AUTOSCALING] Restricted slave for utility operations',
            'remote_fs': '/home/jenkins_slave',  # Remote workspace location
            'labels': 'restricted-utility',  # Space separated labels string
            'exclusive': True,  # Only run jobs assigned to it
            'tunnel': _get_jenkins_private_tunnel_address(),
            'job_name_restriction_regex': '^restricted-(.*)'  # Only run jobs which start with restricted-
        }
    }


@memoize
def _get_aws_session() -> boto3.Session:  # pragma: no cover
    """
    Get the boto3 AWS session
    :return: Session object
    """
    # For local debugging:
    # session = boto3.Session(profile_name=os.environ['AWS_PROFILE'], region_name=os.environ['AWS_REGION'])
    session = boto3.Session()
    return session


def _get_log_level(env_var_key, default_level) -> int:
    """
    Read the log level from an environment variable or set it to a default if it does not exist
    :param env_var_key:
    :param default_level:
    :return:
    """
    try:
        logging_level = os.environ[env_var_key]
    except KeyError:
        logging.warning('Unable to find %s env var. Defaulting to %s.', env_var_key, default_level)
        return default_level
    else:
        if logging_level == 'DEBUG':
            return logging.DEBUG
        elif logging_level == 'INFO':
            return logging.INFO
        elif logging_level == 'WARNING':
            return logging.WARNING
        elif logging_level == 'ERROR':
            return logging.ERROR
        else:
            raise KeyError('Unable to match logging level {} for {}'.format(logging_level, env_var_key))


def _ec2Instance_tag_dict(ec2_object):
    """Given an tagable ec2_object, return dictionary of existing tags."""
    tag_dict = {}
    if ec2_object.tags is None:
        return tag_dict

    for tag in ec2_object.tags:
        tag_dict[tag['Key']] = tag['Value']
    return tag_dict


def chunks(source_list, chunk_size):
    """return list with n chunks from l."""
    chunk_size = max(1, chunk_size)
    return (source_list[i:i + chunk_size] for i in range(0, len(source_list), chunk_size))


def _merge_dicts_nested_lists(dict1: Dict[Any, List[Any]], dict2: Dict[Any, List[Any]]) -> Dict[Any, List[Any]]:
    """
    Merge two dicts that contain lists as values.
    :param dict1: Dict1
    :param dict2: Dict2
    :return: Merged dict
    """
    result_dict: Dict[Any, List[Any]] = dict()
    # Determine key matches which require list merges
    if dict1 and dict2:
        matching_keys = set(dict1.keys()).intersection(set(dict2.keys()))
    else:
        matching_keys = set()

    for key in matching_keys:
        result_dict[key] = list(dict1[key] + dict2[key])

    # Remainders from dict1
    if dict1:
        for key in set(dict1.keys() - matching_keys):
            result_dict[key] = list(dict1[key])

    # Remainders from dict2
    if dict2:
        for key in set(dict2.keys() - matching_keys):
            result_dict[key] = list(dict2[key])

    return result_dict


def scaling():  # pragma: no cover
    """
    Main handler, used by the lambda function
    :return: None
    """
    # All underlying methods are being unit tested. This function will have to be integration tested in a live dev
    # environment.
    logging.getLogger().setLevel(_get_log_level('LOGGING_LEVEL', logging.INFO))
    logging.getLogger('botocore').setLevel(_get_log_level('LOGGING_LEVEL_BOTOCORE', logging.INFO))
    logging.getLogger('boto3').setLevel(_get_log_level('LOGGING_LEVEL_BOTO3', logging.INFO))
    logging.getLogger('urllib3').setLevel(_get_log_level('LOGGING_LEVEL_URLLIB3', logging.INFO))
    logging.getLogger('requests').setLevel(_get_log_level('LOGGING_LEVEL_REQUESTS', logging.ERROR))
    logging.getLogger('botocore.vendored.requests.packages.urllib3.connectionpool').setLevel(logging.ERROR)
    logging.getLogger('jenkinsapi.node').setLevel(logging.INFO)

    boto_config = Config(
        retries=dict(
            max_attempts=0  # Don't retry but fail fast
        )
    )
    jenkins = _get_jenkins_handle()
    aws_session = _get_aws_session()
    ec2_resource = aws_session.resource('ec2', config=boto_config)

    # list of jenkinsapi.nodes.Node
    nodes = jenkins.get_nodes()._data['computer']
    logging.info("Found %d nodes registered in Jenkins.", len(nodes))

    # Ec2 instances
    instance_uptime = _instance_uptime(ec2_resource=ec2_resource)
    logging.info("Found %d ec2 instances.", len(instance_uptime))

    if len(instance_uptime) != len(nodes):
        logging.warning("nodes and instances don't have the same length.")

    unconnected_label2instance_names = _unconnected_instances(
        nodes=nodes,
        instance_uptime=instance_uptime,
        ec2_resource=ec2_resource)

    queue_items = jenkins.get_queue()._data['items']

    label2num_instances = determine_scale_up_nodes(
        queue_items=queue_items, nodes=nodes, unconnected=unconnected_label2instance_names)

    scale_down_nodes = determine_scale_down_nodes(nodes_data=nodes,
                                                  instance_uptime=instance_uptime)

    ############################################
    # Detection of instances and slots to be cleaned up
    (label2faulty_nodes, orphaned_instances) = _determine_faulty_nodes(nodes=nodes,
                                                                       instance_uptime=instance_uptime,
                                                                       unconnected_instances=unconnected_label2instance_names)
    if label2faulty_nodes:
        faulty = []
        for faulty_nodes in label2faulty_nodes.values():
            faulty.extend([node['displayName'] for node in faulty_nodes])
        logging.warning('Found %d faulty instances: %s', len(faulty), faulty)

    if orphaned_instances:
        logging.error('Found %d orphaned instances: %s', len(orphaned_instances), orphaned_instances)
    ############################################

    label2num_instances = _apply_upscale_limit(limit=NUM_UPSCALES_PER_ROUND, label2num_instances=label2num_instances)
    scale_down_nodes = _apply_downscale_limit(limit=NUM_DOWNSCALES_PER_ROUND, scale_down_nodes=scale_down_nodes)
    scale_down_nodes = _merge_dicts_nested_lists(scale_down_nodes, label2faulty_nodes)

    execute_scale_down_logic(
        jenkins_server=jenkins,
        ec2_resource=ec2_resource,
        scale_down_nodes=scale_down_nodes,
    )
    ############
    _terminate_ec2_instances(orphaned_instances, ec2_resource)
    ############

    execute_scale_up_logic(
        jenkins_server=jenkins,
        ec2_resource=ec2_resource,
        scale_up_nb_nodes=label2num_instances)


# pylint: disable=unused-argument
def scaling_handler(event, context):  # pragma: no cover
    """
    Handler to be called by lambda
    :param event:
    :param context:
    :return:
    """
    try:
        scaling()
    except Exception:  # pylint: disable=broad-except
        logging.exception('Unexpected exception')
        logging.fatal('Unexpected exception')
        # This try-catch is important because we have to catch all exceptions. Otherwise, the exceptions bubble up to
        # lambda and the service retries executing multiple times. We only want exactly one execution per request.


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    scaling_handler(None, None)
