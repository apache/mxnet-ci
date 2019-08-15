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

import platform
import logging
import jenkins
import functools
import argparse
import os
import urllib.request
import pprint
import subprocess
import sys
import shutil
import boto3
import time
import re
import random

AGENT_SLAVE_JAR_PATH = 'jnlpJars/slave.jar'
LOCAL_SLAVE_JAR_PATH = 'slave.jar'
SLAVE_CONNECTION_URL_FORMAT = "{master_private}/computer/{label}/slave-agent.jnlp"
SLAVE_START_COMMAND = 'java -jar {slave_path} -jnlpUrl {connection_url} -workDir "{work_dir}" -failIfWorkDirIsMissing'
REGION_REGEX = r'"region" : "([a-z0-9\-]+)"'
INSTANCE_ID_REGEX = r'"instanceId" : "([a-z0-9\-]+)"'
RETRY_COUNTER_RESET_TIME_SECONDS = 600
RETRY_LIMIT = 5
RETRY_SLEEP_MIN_SECONDS = 5
RETRY_SLEEP_MAX_SECONDS = 30
CLOUD_INIT_MAX_WAIT_SECONDS = 120


"""
In order to use this script, it has to be placed in auto start of your instance. Put the following into the user-data
part of the launch command in order to get the parameters initialized:

#!/bin/bash
echo 'http://jenkins.mxnet-ci-dev.amazon-ml.com/' > /home/jenkins_slave/jenkins_master_url
echo 'http://jenkins-priv.mxnet-ci-dev.amazon-ml.com/' > /home/jenkins_slave/jenkins_master_private_url
echo 'mxnet-linux-cpu10' > /home/jenkins_slave/jenkins_slave_name
"""


def connect_to_master(node_name, master_private_url, work_dir):
    # We have to rename this instance before it is able to connect because we're not getting back the control
    # if the launch was successful
    rename_instance(node_name)

    # Try to connect to this node. If it fails, there's probably already a node connected to that slot
    slave_connection_url = SLAVE_CONNECTION_URL_FORMAT.format(master_private=master_private_url, label=node_name)
    slave_start_command = SLAVE_START_COMMAND.format(connection_url=slave_connection_url, work_dir=work_dir,
                                                     slave_path=LOCAL_SLAVE_JAR_PATH)
    logging.info('slave start command: {}'.format(slave_start_command))
    return_code = subprocess.call(slave_start_command, shell=True)
    # TODO: Wait if this line appears: 'is already connected to this master. Rejecting this connection.'
    return return_code


def download(url: str, file: str):
    logging.debug('Downloading {} to {}'.format(url, file))
    urllib.request.urlretrieve(url, file)


def is_offline_node_matches_prefix(prefix: str, node) -> bool:
    return node['name'].startswith(prefix) and node['offline']


def generate_node_label():
    system = platform.system()
    labelPlatform = "mxnet-"

    # Determine platform type
    if system == "Windows":
        labelPlatform += "windows-"
    elif system == "Linux":
        labelPlatform += "linux-"
    else:
        raise RuntimeError("system {} is not supported yet".format(system))

    # Determine whether CPU or GPU system
    if is_gpu_present():
        labelPlatform += "gpu"
    else:
        labelPlatform += "cpu"

    return labelPlatform

def rename_instance(name: str):
    logging.info('Renaming instance to {}'.format(name))
    response = urllib.request.urlopen("http://169.254.169.254/latest/dynamic/instance-identity/document")
    instance_info = response.read().decode('utf-8')
    logging.debug('Instance info: {}'.format(instance_info))

    region_match = re.search(REGION_REGEX, instance_info)
    instance_id_match = re.search(INSTANCE_ID_REGEX, instance_info)

    if not region_match or not instance_id_match:
        raise RuntimeError("Unable to determine instance id or region. Instance info: {}".format(instance_info))

    region = region_match.group(1)
    instance_id = instance_id_match.group(1)

    logging.debug('Instance region: {}   Instance id: {}'.format(region, instance_id))

    ec2 = boto3.resource('ec2', region_name=region)
    ec2.create_tags(
        DryRun=False,
        Resources=[
            instance_id
        ],
        Tags=[
            {
                'Key': 'Name',
                'Value': name
            },
        ]
    )


def is_gpu_present() -> bool:
    num_gpus = get_num_gpus()
    logging.debug('Number GPUs present: {}'.format(num_gpus))
    return num_gpus > 0


def get_num_gpus() -> int:
    """
    Gets the number of GPUs available on the host (depends on nvidia-smi).
    :return: The number of GPUs on the system.
    """
    #if shutil.which("nvidia-smi") is None:
    nvidia_smi_path = get_nvidia_smi_path()
    if nvidia_smi_path is None or shutil.which(nvidia_smi_path) is None:
        logging.warning("Couldn't find nvidia-smi, therefore we assume no GPUs are available.")
        return 0
    #sp = subprocess.Popen(['nvidia-smi', '-L'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    sp = subprocess.Popen([get_nvidia_smi_path(), '-L'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    out_str = sp.communicate()[0].decode("utf-8")

    # Ensure we're counting the lines with GPU as CPU-instances have nvidia-smi present as well
    num_gpus = 0
    for line in out_str.split("\n"):
        logging.debug('Nvidia-SMI: {}'.format(line))
        if 'GPU' in line:
            num_gpus += 1

    return num_gpus


def get_nvidia_smi_path() -> str:
    if shutil.which("nvidia-smi") is not None:
        return 'nvidia-smi'

    if shutil.which("C:\\Program Files\\NVIDIA Corporation\\NVSMI\\nvidia-smi.exe") is not None:
        return 'C:\\Program Files\\NVIDIA Corporation\\NVSMI\\nvidia-smi.exe'

    return None


def read_master_urls(args) -> (str,str):
    try:
        if args.master is not None:
            master = args.master
        else:
            if args.master_file is not None:
                master = read_file_content(file_path=args.master_file,
                                           timeout_seconds=CLOUD_INIT_MAX_WAIT_SECONDS)
                if not master:
                    raise ValueError('{} is empty'.format(args.master_file))
            else:
                raise ValueError('--master_file not specified')

        if args.master_private is not None:
            master_private = args.master_private
        else:
            if args.master_private_file is not None:
                master_private = read_file_content(file_path=args.master_private_file,
                                                   timeout_seconds=CLOUD_INIT_MAX_WAIT_SECONDS)
                if not master_private:
                    raise ValueError('{} is empty'.format(args.master_private_file))
            else:
                raise ValueError('--master_private_file not specified')

        logging.debug('Master: {}    Private: {}'.format(master, master_private))
        return master, master_private
    except:
        logging.exception('Error during reading master URLs')
        rename_instance('read-master-config-error')
        raise


def read_name_from_path(name_path):
    if name_path is None:
        return None

    return read_file_content(file_path=name_path, timeout_seconds=120)


def read_file_content(file_path, timeout_seconds):
    """
    Read file content
    :param path: Filepath
    :param timeout_seconds: Time to wait until file exists
    :return: File content
    """
    end_time = time.time() + timeout_seconds
    while end_time > time.time() and not os.path.exists(file_path):
        time.sleep(1)

    if end_time <= time.time():
        raise FileNotFoundError('Timeout waiting for file {} to exist'.format(file_path))

    with open(file_path, "r") as file_handle:
        content = file_handle.readline().strip()
        if not content:
            raise ValueError('{} is empty'.format(file_path))

        return content


def main():
    try:
        logging.getLogger().setLevel(logging.DEBUG)
        parser = argparse.ArgumentParser()
        parser.add_argument('-m', '--master',
            help='URL of jenkins master',
            # default='http://jenkins.mxnet-ci.amazon-ml.com',
            type=str)

        parser.add_argument('-mf', '--master-file',
            help='File containing URL of jenkins master',
            # default='/home/jenkins_slave/jenkins_master_url',
            type=str)

        parser.add_argument('-mp', '--master-private',
            help='Private URL of jenkins master',
            # default='http://jenkins-priv.mxnet-ci.amazon-ml.com',
            type=str)

        parser.add_argument('-mpf', '--master-private-file',
            help='File containing private URL of jenkins master',
            # default='/home/jenkins_slave/jenkins_master_private_url',
            type=str)

        parser.add_argument('-snf', '--slave-name-file',
            help='File containing name of the slave slot',
            type=str)

        args = parser.parse_args()

        master_url, master_private_url = read_master_urls(args)
        slave_name = read_name_from_path(args.slave_name_file)

        # Replace \ by / on URL due to windows using \ as default separator
        jenkins_slave_jar_url = os.path.join(master_url, AGENT_SLAVE_JAR_PATH).replace('\\', '/')

        # Download jenkins slave jar
        download(jenkins_slave_jar_url, LOCAL_SLAVE_JAR_PATH)

        work_dir = os.path.join(os.getcwd(), 'workspace')
        logging.info('Work dir: {}'.format(work_dir))

        # Create work dir if it doesnt exist
        os.makedirs(work_dir, exist_ok=True)
        os.makedirs(os.path.join(work_dir, 'remoting'), exist_ok=True)

        server = jenkins.Jenkins(master_url)

        i = 0
        while i < RETRY_LIMIT:
            i += 1
            if slave_name:
                logging.info('Entering manual connect mode to slave slot {}'.format(slave_name))
                offline_nodes = [slave_name]
            else:
                logging.info('Entering auto connect mode')
                label = generate_node_label()
                logging.info('Local node prefix: {}'.format(label))
                nodes = server.get_nodes()

                offline_nodes = [node['name'] for node in
                                 list(filter(functools.partial(is_offline_node_matches_prefix, label), nodes))]
                logging.debug('Offline nodes: {}', offline_nodes)
                # Shuffle to provide random order to reduce race conditions if multiple instances
                # are started at the same time and thus try to connect to the same slot, possibly
                # resulting in a hang
                random.shuffle(offline_nodes)

                if len(offline_nodes) == 0:
                    rename_instance('error-no-free-slot')
                    logging.fatal('Could connect to master - no free slots')
                    return 1

            reset = False
            # Loop through nodes and try to connect
            for node_name in offline_nodes:
                start_time = time.time()
                connect_to_master(node_name=node_name, master_private_url=master_private_url, work_dir=work_dir)
                total_runtime_seconds = time.time() - start_time

                if total_runtime_seconds > RETRY_COUNTER_RESET_TIME_SECONDS:
                    logging.info('Instance ran for {} seconds, resetting retry counter'.format(total_runtime_seconds))
                    reset = True
                else:
                    logging.info('Unable to connect as node {}'.format(node_name))

                    # Rename this instance to show it was unable to connect
                    rename_instance('{}-unable-to-connect'.format(node_name))

            time.sleep(random.randint(RETRY_SLEEP_MIN_SECONDS, RETRY_SLEEP_MAX_SECONDS))
            if reset:
                logging.info('Resetting repetition counter')
                i = 0

        rename_instance('error-too-many-attempts')
        logging.fatal('Could connect to master - too many attempts')
        return 1
    except Exception as e:
        logging.exception('Fatal exception')
        logging.fatal('Fatal exception, aborting execution')
        return 1


if __name__ == '__main__':
    sys.exit(main())
