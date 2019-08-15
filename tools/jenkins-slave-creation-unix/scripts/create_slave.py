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

# This script serves the purpose to automatize the creation process of a jenkins slave

import logging
import argparse
import os
import re
import time
import tarfile
import pprint
import shutil
from python_terraform import *
from tempfile import TemporaryDirectory
from shutil import copytree



TERRAFORM_SCRIPT_NAME = 'infrastructure.tf'
TERRAFORM_VARFILE_NAME = 'infrastructure.tfvars'
TERRAFORM_BACKEND_VARFILE_NAME = 'infrastructure_backend.tfvars'


DEPLOYED_SCRIPTS_DIR_NAME = 'scripts/deploy'


def main():
    logging.getLogger().setLevel(logging.DEBUG)

    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--configdir',
                        help='Deployment configuration directory',
                        default='conf-ubuntu-cpu',
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
        temp_archive_path = os.path.join(temp_dir, "config.tar.bz2")

        with tarfile.open(temp_archive_path, "w:bz2") as tar:
            scripts_dir = os.path.join(args.terraformdir, DEPLOYED_SCRIPTS_DIR_NAME)
            for file in os.listdir(scripts_dir):
                logging.debug('Archiving {}'.format(file))
                tar.add(os.path.join(scripts_dir, file), arcname=os.path.basename(file))

        # Trigger terraform
        logging.info('Running terraform...')

        logging.debug('Switching current work dir to {}'.format(terraform_dir_abs))
        os.chdir(terraform_dir_abs)

        # Setting up the terraform S3 backend requires to have AWS credentials in the env vars - it's not able
        # to access the variables file due interpolation in terraform being enabled after initialization of
        # the s3 backend
        env_vars = os.environ.copy()

        subprocess.check_call('~/bin/terraform init -backend-config={}'.format(os.path.join(args.configdir, TERRAFORM_BACKEND_VARFILE_NAME)), cwd=terraform_dir_abs, env=env_vars, shell=True)
        command = input("Terraform apply or plan? [apply]: ") or "apply"
        subprocess.check_call('~/bin/terraform {} -var-file="{}" -var "slave_config_tar_path={}"'.format(command, os.path.join(args.configdir, TERRAFORM_VARFILE_NAME), temp_archive_path), cwd=terraform_dir_abs, env=env_vars, shell=True)
        logging.debug('Deployment finished')


def get_tfvars_entry(tfvars_file, key):
    # This is just a hack because I don't want to spend the time to write an entire parser for the .tfvars format
    with open(tfvars_file, 'r') as fp:
        for line in fp:
            if line.startswith(key):
                result = re.search('"(.*)"', line).group(1)
                return result

        raise ValueError('Could not find {} in {}'.format(key, tfvars_file))

if __name__ == '__main__':
    main()
