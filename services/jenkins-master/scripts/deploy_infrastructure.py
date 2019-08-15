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

# This script automates the Jenkins master deployment process.

import argparse
import logging
import os
import re
import shutil
import subprocess
import tarfile
from shutil import copytree
from tempfile import TemporaryDirectory

from jenkins_config_templating import execute_config_templating, assemble_symlink_list

JENKINS_DIR_NAME = 'jenkins'
SECRET_DIR_NAME = 'secrets'
VARFILE_FILE_NAME = 'jenkins_config.varfile'
SYMLINKFILE_FILE_NAME = 'jenkins_config.symlinkfile'

TERRAFORM_DEPLOY_TEMP_DIR = 'temp'
TERRAFORM_SCRIPT_NAME = 'infrastructure.tf'
TERRAFORM_VARFILE_NAME = 'infrastructure.tfvars'
TERRAFORM_BACKEND_VARFILE_NAME = 'infrastructure_backend.tfvars'

JENKINS_PLUGINS_DIR_NAME = 'plugins'
JENKINS_CONFIG_TAR_NAME = 'jenkins.tar.bz2'
JENKINS_PLUGINS_TAR_NAME = 'jenkins_plugins.tar.bz2'
JENKINS_SYMLINK_FILE_NAME = 'jenkins_symlinks.sh'

STATE_TOUCH_FILE_TEMPLATE = 'touch /ebs_jenkins_state/{} \n'
STATE_CREATE_DIR_TEMPLATE = 'mkdir -p /ebs_jenkins_state/{} \n'
STATE_SYMLINK_TEMPLATE = 'mkdir -p /var/lib/jenkins/{} && sudo ln -s /ebs_jenkins_state/{} /var/lib/jenkins/{} \n'


def main():
    logging.getLogger().setLevel(logging.DEBUG)

    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--configdir',
                        help='Jenkins deployment configuration directory',
                        default='test',
                        type=str)

    parser.add_argument('-tf', '--terraformdir',
                        help='Directory containing the terraform scripts',
                        default='.',
                        type=str)

    args = parser.parse_args()

    terraform_dir_abs = os.path.abspath(args.terraformdir)

    if not os.path.isfile(os.path.join(terraform_dir_abs, TERRAFORM_SCRIPT_NAME)):
        raise FileNotFoundError('Unable to find terraform script. Did you specify "--terraformdir"? {}'.
                                format(os.path.join(terraform_dir_abs, TERRAFORM_SCRIPT_NAME)))

    # Copy configuration to temp dir
    with TemporaryDirectory() as temp_dir:
        terraform_deploy_dir = os.path.join(terraform_dir_abs, TERRAFORM_DEPLOY_TEMP_DIR)
        # Create deployment temp dir
        if not os.path.exists(terraform_deploy_dir):
            os.makedirs(terraform_deploy_dir)

        jenkins_dir = os.path.join(args.configdir, JENKINS_DIR_NAME)
        temp_jenkins_dir = os.path.join(temp_dir, JENKINS_DIR_NAME)
        logging.debug('Copying jenkins dir from {} to {}'.format(jenkins_dir, temp_jenkins_dir))
        copytree(jenkins_dir, temp_jenkins_dir, True)

        # Replace placeholders with actual secrets
        execute_config_templating(os.path.join(args.configdir, VARFILE_FILE_NAME),
                                  os.path.join(args.configdir, SECRET_DIR_NAME), temp_jenkins_dir, 'insert',
                                  update_secrets=False)
        logging.debug('Config replaced. Result can be found at {}'.format(temp_jenkins_dir))

        # Assemble list of symlinks to be created
        symlinks = assemble_symlink_list(os.path.join(args.configdir, SYMLINKFILE_FILE_NAME), temp_jenkins_dir)

        # Create shell script to symlink during startup
        _create_symlink_shellscript(symlinks, os.path.join(terraform_deploy_dir, JENKINS_SYMLINK_FILE_NAME))

        # Sanity: Ensure no state is part of config
        _validate_config_contain_no_state(symlinks, temp_jenkins_dir)

        # Optional: Create backup of EBS
        # TODO

        # Compress jenkins dir to allow upload to S3
        temp_jenkins_compressed_file = os.path.join(temp_dir, 'jenkins_config.tar.bz2')
        temp_jenkins_compressed_plugins_file = os.path.join(temp_dir, 'jenkins_plugins.tar.bz2')
        with tarfile.open(temp_jenkins_compressed_file, "w:bz2") as tar:
            with tarfile.open(temp_jenkins_compressed_plugins_file, "w:bz2") as tar_plugin:
                for file in os.listdir(temp_jenkins_dir):
                    logging.debug('Archiving {}'.format(file))
                    # Since jenkins plugins are a few hundreds of megabytes, store them in a second compressed archive
                    # in order to prevent uploading (~15mins) them every single time the actual configuration is changed
                    if file != JENKINS_PLUGINS_DIR_NAME:
                        tar.add(os.path.join(temp_jenkins_dir, file), arcname=os.path.basename(file))
                    else:
                        tar_plugin.add(os.path.join(temp_jenkins_dir, file), arcname=os.path.basename(file))

        logging.info('Copying archives to {}'.format(terraform_dir_abs))
        # Copy generated archives to original dir
        shutil.copy2(temp_jenkins_compressed_file, os.path.join(terraform_deploy_dir, JENKINS_CONFIG_TAR_NAME))
        shutil.copy2(temp_jenkins_compressed_plugins_file, os.path.join(terraform_deploy_dir, JENKINS_PLUGINS_TAR_NAME))

    # Trigger terraform
    logging.info('Running terraform...')
    logging.debug('Switching current work dir to {}'.format(terraform_dir_abs))
    os.chdir(terraform_dir_abs)

    # Setting up the terraform S3 backend requires to have AWS credentials in the env vars - it's not able
    # to access the variables file due interpolation in terraform being enabled after initialization of
    # the s3 backend
    env_vars = os.environ.copy()
    env_vars['AWS_ACCESS_KEY_ID'] = _get_tfvars_entry(os.path.join(args.configdir, TERRAFORM_VARFILE_NAME),
                                                      'aws_access_key')
    env_vars['AWS_SECRET_ACCESS_KEY'] = _get_tfvars_entry(os.path.join(args.configdir, TERRAFORM_VARFILE_NAME),
                                                          'aws_secret_key')

    p1 = subprocess.Popen('~/bin/terraform init -backend-config={}'.
                          format(os.path.join(args.configdir, TERRAFORM_BACKEND_VARFILE_NAME)), cwd=terraform_dir_abs,
                          env=env_vars, shell=True)
    p1.wait()
    p2 = subprocess.Popen('~/bin/terraform apply -var-file="{}"'.
                          format(os.path.join(args.configdir, TERRAFORM_VARFILE_NAME)), cwd=terraform_dir_abs,
                          env=env_vars, shell=True)
    p2.wait()
    logging.info('Deployment finished')


def _get_tfvars_entry(tfvars_file, key):
    # This is just a hack because I don't want to spend the time to write an entire parser for the .tfvars format
    with open(tfvars_file, 'r') as fp:
        for line in fp:
            if line.startswith(key):
                result = re.search('"(.*)"', line).group(1)
                return result

        raise ValueError('Could not find {} in {}'.format(key, tfvars_file))


def _create_symlink_shellscript(symlinks, target_file):
    with open(target_file, 'w') as fp:
        for symlink_entry in symlinks:
            # Ensure dirs and files exist on EBS before creating symlink
            if symlink_entry.is_dir:
                fp.write(STATE_CREATE_DIR_TEMPLATE.format(symlink_entry.filepath))
            else:
                fp.write(STATE_TOUCH_FILE_TEMPLATE.format(symlink_entry.filepath))

            # Create symlink
            fp.write(STATE_SYMLINK_TEMPLATE.
                     format(os.path.dirname(symlink_entry.filepath), symlink_entry.filepath, symlink_entry.filepath))


def _validate_config_contain_no_state(symlinks, jenkins_config_dir):
    for symlink_entry in symlinks:
        path = os.path.join(jenkins_config_dir, symlink_entry.filepath)
        if os.path.isfile(path) or os.path.isdir(path):
            raise FileExistsError(
                '{} is defined as state, but included in config. Remove before continuing.'.format(path))


if __name__ == '__main__':
    main()
