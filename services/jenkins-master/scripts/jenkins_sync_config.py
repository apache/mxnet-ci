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

# This script synchronizes the local config with the running configuration on a jenkins master server

import argparse
import glob
import os
import re
import shutil
from distutils.dir_util import copy_tree
from tempfile import TemporaryDirectory

from jenkins_config_templating import execute_config_templating, read_symlink_entries

BASH_SCRIPT_JENKINS_TO_TEMP = \
    'ssh-keygen -R {}; ssh -C ubuntu@{} "bash -s" <<EOS \n' \
    'sudo rm -rf /home/ubuntu/jenkins; mkdir -p /home/ubuntu/jenkins; \n' \
    'sudo cp -RP --verbose /var/lib/jenkins/* /home/ubuntu/jenkins \n' \
    'sudo chown -R ubuntu.ubuntu /home/ubuntu/jenkins; \n' \
    'find /home/ubuntu/jenkins/ -type l -delete; \n' \
    'EOS'

BASH_SCRIPT_DOWNLOAD_TEMP = 'rsync --delete -zvaP ubuntu@{}:jenkins/ {}'
BASH_SCRIPT_SYNC_LOCAL = 'rsync --delete -zvaP {}/* {}'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-jd', '--jenkinsdir',
                        help='Location of the jenkins directory',
                        type=str)

    parser.add_argument('-vf', '--varfile',
                        help='Location of the variable file',
                        type=str)

    parser.add_argument('-sf', '--symlinkfile',
                        help='Location of the symlink file',
                        type=str)

    parser.add_argument('-sd', '--secretsdir',
                        help='Location of the directory containing secrets',
                        type=str)

    parser.add_argument('-tf', '--tfvarsfile',
                        help='Location of the terraform variable file',
                        type=str)

    parser.add_argument('-m', '--mode',
                        help='"download" or "upload" config',
                        type=str)

    args = parser.parse_args()

    jenkins_sync_config(args.mode, args.jenkinsdir, args.varfile, args.symlinkfile, args.secretsdir, args.tfvarsfile)


def jenkins_sync_config(mode, jenkins_dir, var_file, symlink_file, secrets_dir, tfvars_file):
    # secret_entries = read_secret_entires(var_file) #TODO: Verify no new secrets have been downloaded
    symlink_config = read_symlink_entries(symlink_file)
    jenkins_address = 'jenkins.' + _get_tfvars_entry(tfvars_file, 'domain')

    with TemporaryDirectory() as temp_dir:
        if mode == 'download':
            # Copy config to temp dir on jenkins master to avoid permission issues due to owner being jenkins while
            # rsync is logging in as ubuntu. We're using bash scripts instead of an SSH client because all python
            # libraries for SSH usage are having trouble when we supply a custom rsa key instead ouf using id_rsa
            # TODO: Use proper SSH client
            bash_jenkins_to_temp_cmd = BASH_SCRIPT_JENKINS_TO_TEMP.format(jenkins_address, jenkins_address)
            os.system(bash_jenkins_to_temp_cmd)

            # Copy old jenkins to local temp dir to allow rsync and thus speed up the download process due to diff
            copy_tree(jenkins_dir, temp_dir)
            bash_jenkins_download_cmd = BASH_SCRIPT_DOWNLOAD_TEMP.format(jenkins_address, temp_dir)
            os.system(bash_jenkins_download_cmd)

            # Delete state files. Symlinks are already deleted before config is downloaded, but there might be new dirs
            # which were not symlinked yet.
            _delete_state_files(symlink_config, temp_dir)

            # Remove secrets according to secret config
            execute_config_templating(var_file, secrets_dir, temp_dir, 'remove', update_secrets=True)

            # TODO Optional: Verify no new secrets have been downloaded

            # Move new config to configdir
            bash_sync_local_cmd = BASH_SCRIPT_SYNC_LOCAL.format(temp_dir, jenkins_dir)
            os.system(bash_sync_local_cmd)
        else:
            raise ValueError('Mode {} not supported'.format(mode))


def _delete_state_files(symlink_config, jenkins_dir):
    for symlink_entry in symlink_config:
        result_paths = glob.glob(os.path.join(jenkins_dir, symlink_entry.filepath))
        for path in result_paths:
            if symlink_entry.is_dir:
                shutil.rmtree(path)
            else:
                os.remove(path)


def _get_tfvars_entry(tfvars_file, key):
    # This is just a hack because I don't want to spend the time to write an entire parser for the .tfvars format
    with open(tfvars_file, 'r') as fp:
        for line in fp:
            if line.startswith(key):
                result = re.search('"(.*)"', line).group(1)
                return result

        raise ValueError('Could not find {} in {}'.format(key, tfvars_file))


if __name__ == '__main__':
    main()
