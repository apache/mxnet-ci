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

# This script serves the purpose to replace sensitive parts in the jenkins configuration with placeholders in order
# to allow the configuration to be published to a public repository

import argparse
import filecmp
import glob
import json
import logging
import os
import pathlib
import shutil
from collections import namedtuple

from lxml import etree

SECRET_ENTRY_KEYS = ['filepath', 'xpath', 'secret', 'placeholder']
SecretEntry = namedtuple('SecretEntry', SECRET_ENTRY_KEYS)

SYMLINK_ENTRY_KEYS = ['filepath', 'is_dir']
SymlinkEntry = namedtuple('SymlinkEntry', SYMLINK_ENTRY_KEYS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-vf', '--varfile',
                        help='Location of the variable file',
                        type=str)

    parser.add_argument('-sf', '--symlinkfile',
                        help='Location of the symlink file',
                        type=str)

    parser.add_argument('-sd', '--secretsdir',
                        help='Location of the directory containing secrets',
                        type=str)

    parser.add_argument('-jd', '--jenkinsdir',
                        help='Location of the jenkins directory',
                        type=str)

    parser.add_argument('-m', '--mode',
                        help='"remove" or "insert" credentials',
                        default='insert',
                        type=str)

    args = parser.parse_args()

    execute_config_templating(args.varfile, args.secretsdir, args.jenkinsdir, args.mode, update_secrets=False)
    # TODO: Add symlink list creation


def execute_config_templating(varfile, secretsdir, jenkinsdir, mode, update_secrets):
    """
    Execute config templating that inserts or removes secrets from a jenkins configuration directory
    :param varfile: File containing the actual variables that should be used during replacement
    :param secretsdir: Directory containing all files that should be just copied or removed as secrets
    :param jenkinsdir: Jenkins configuration directory
    :param mode: 'insert' replaces placeholders with actual values. 'remove' removes these values and
        inserts placeholders
    :param update_secrets: Update secrets if mode == 'remove' and actual secrets differ from the stored ones
    :return:
    """
    secret_entries = read_secret_entires(varfile)
    logging.debug('Found {} secret entries to be replaced'.format(len(secret_entries)))

    # Prepare by finding all unique identifiers. This is required because XML parsers do not allow in-place
    # replacements. Instead, we're reading a unique identifier under the specified xpath and then try to
    # replace it in-place by using search-and-replace. This method will be aborted if the current value
    # has been found multiple times within the same file.
    for root, dirs, files in os.walk(secretsdir, topdown=False):
        for name in files:
            original_path = os.path.join(root, name)
            rel_path = os.path.relpath(original_path, secretsdir)
            temp_path = os.path.join(jenkinsdir, rel_path)

            if mode == 'insert':
                pathlib.Path(os.path.dirname(temp_path)).mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original_path, temp_path)
            elif mode == 'remove':
                # Check if secret does not exist anymore
                if not os.path.isfile(temp_path):
                    if update_secrets:
                        logging.info('Deleting secret {} because it has been removed on target'.format(rel_path))
                        os.remove(original_path)
                    else:
                        raise ValueError('Secret {} has been deleted'.format(rel_path))

                # Check if secrets are the same or have to be updated
                if not filecmp.cmp(temp_path, original_path):
                    if update_secrets:
                        logging.info('Replacing secret {} due to changed content'.format(rel_path))
                        shutil.copyfile(temp_path, original_path)
                    else:
                        raise ValueError('Secret {} contains changed content'.format(rel_path))

                os.remove(temp_path)
            else:
                raise ValueError('Mode {} unknown'.format(mode))  # TODO check this previously

    # Check if any files in the secrets-dir are left that didn't exist in the previous config. Unfortunately,
    # we can't verify if secrets outside the secrets-dir have been added.
    if mode == 'remove':
        temp_secrets_dir = os.path.join(jenkinsdir, 'secrets')
        for root, dirs, files in os.walk(temp_secrets_dir, topdown=False):
            for name in files:
                temp_path = os.path.join(root, name)
                rel_path = os.path.relpath(temp_path, jenkinsdir)
                original_path = os.path.join(secretsdir, rel_path)

                if update_secrets:
                    logging.info('Adding new secret at {}'.format(rel_path))
                    shutil.copyfile(temp_path, original_path)
                else:
                    raise ValueError('New secret at {}'.format(rel_path))
        shutil.rmtree(temp_secrets_dir)

    for secret_entry in secret_entries:
        temp_file_path = os.path.join(jenkinsdir, secret_entry.filepath)
        if os.path.isfile(temp_file_path):
            element = etree.parse(temp_file_path).xpath(secret_entry.xpath)

            # Check if xpath delivers multiple results. The xpath should only match once
            if len(element) == 1:
                current_value = element[0].text
                if not current_value.strip():
                    raise ValueError('Element {} at {}:{} is not a text field'.
                                     format(current_value, temp_file_path, secret_entry.xpath))

                if mode == 'insert':
                    expected_value = secret_entry.placeholder
                    target_value = secret_entry.secret
                elif mode == 'remove':
                    expected_value = secret_entry.secret
                    target_value = secret_entry.placeholder
                else:
                    raise ValueError('Mode {} unknown'.format(mode))

                if current_value == expected_value:
                    logging.debug(
                        'Replacing {} with {} at {}:{}'.format(current_value, target_value, secret_entry.xpath,
                                                               temp_file_path))
                    _replace_values(current_value, target_value, temp_file_path)

                elif current_value == target_value:
                    logging.info('Target value {} already present. Skipping {}:{}'.
                                 format(target_value, secret_entry.xpath, temp_file_path))
                    continue
                else:
                    raise ValueError('Current value "{}" does not match expected value "{}" in {}:{}'.format(
                        current_value, expected_value, secret_entry.xpath))
            elif len(element) == 0:
                raise ValueError('Element at {}:{} not found'.format(temp_file_path, secret_entry.xpath))
            else:
                raise ValueError('1 Element expected, {} found at {}:{}'.
                                 format(len(element), temp_file_path, secret_entry.xpath))
        else:
            raise FileNotFoundError('Could not find file {}'.format(temp_file_path))


def assemble_symlink_list(symlink_file, jenkinsdir):
    """
    Assemble a list of files that should be symlinked during startup, providing support for state files on EBS
    :param symlink_file: File containing path expressions to describe the symlinked files and dirs
    :param jenkinsdir: Jenkins configuration directory
    :return: Array of SymlinkEntry
    """
    symlink_config = read_symlink_entries(symlink_file)
    logging.debug('Found {} symlink entries'.format(len(symlink_config)))

    symlinks = []

    for symlink_entry in symlink_config:
        input_path_expression = os.path.join(jenkinsdir, symlink_entry.filepath)
        result_paths = []

        if '*' in symlink_entry.filepath:
            # If path contains a wildcard, search for all results
            wildcard_path_split = input_path_expression.split('*')
            if len(wildcard_path_split) == 1:
                result_paths = glob.glob(input_path_expression)
            elif len(wildcard_path_split) == 2:
                # If wildcard is in the middle and target directories don't exist, result would be empty.
                # Instead, iterate manually
                for partial_path in glob.glob(os.path.join(wildcard_path_split[0], '*')):
                    result_paths.append(os.path.join(partial_path, wildcard_path_split[1].lstrip('/')))
            else:
                raise ValueError('Symlink expression may only contain one wildcard')
            logging.debug('Resolving {} to {}'.format(symlink_entry.filepath, result_paths))
        else:
            result_paths = [input_path_expression]

        for abs_path in result_paths:
            rel_path = os.path.relpath(abs_path, jenkinsdir)
            symlinks.append(SymlinkEntry(rel_path, symlink_entry.is_dir))

    return symlinks


def read_secret_entires(varfile):
    """
    Read SecretEntry from varfile
    :param varfile: File containing SecretEntries as JSON
    :return: Array of SecretEntry
    """
    with open(varfile, 'r') as fp:
        secret_dict_raw = json.load(fp)
        secrets = []
        for secret_entry_dict in secret_dict_raw:
            # Import values in the same order as expected in SecretEntry. Reason being that the values are expected
            # to be inserted in the same order as defined previously.
            secrets.append(SecretEntry(*[secret_entry_dict[k] for k in SECRET_ENTRY_KEYS]))
        return secrets


def read_symlink_entries(varfile):
    """
    Read SymlinkEntry from varfile
    :param varfile: File containing SymlinkEntries as JSON
    :return: Array of SymlinkEntries
    """
    with open(varfile, 'r') as fp:
        symlink_dict_raw = json.load(fp)
        symlinks = []
        for symlink_entry_dict in symlink_dict_raw:
            # Import values in the same order as expected in SecretEntry. Reason being that the values are expected
            # to be inserted in the same order as defined previously.
            symlinks.append(SymlinkEntry(*[symlink_entry_dict[k] for k in SYMLINK_ENTRY_KEYS]))
        return symlinks


def _replace_values(current_value, target_value, temp_file_path):
    # Only execute changes on the temp file
    with open(temp_file_path, 'r+') as temp_fh:
        temp_file_content = temp_fh.read()

        # Check if current value is unique within the temp file to prevent injection attacks
        nb_occurrences_temp = temp_file_content.count(current_value)
        if nb_occurrences_temp != 1:
            raise ValueError(
                '1 occurrence of current value {} in file {} expected, {} found'.format(
                    current_value,
                    temp_file_path,
                    nb_occurrences_temp))

        temp_file_content_replaced = temp_file_content.replace(current_value, target_value)

        # Write replaced content back to the temp file
        temp_fh.seek(0)
        temp_fh.write(temp_file_content_replaced)
        temp_fh.truncate()


if __name__ == '__main__':
    main()
