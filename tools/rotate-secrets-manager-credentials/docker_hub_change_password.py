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
Script to update Docker Hub Credentials


"""

import requests
import logging
import sys
import time
import argparse
import boto3
import os
import json

def dockerhub_get_session(secret_dict):
    """Gets a session to the DockerHub User API from a secret dictionary

    This helper function tries to connect to the DockerHub User API by grabbing login info
    from the secret dictionary. If successful, it returns the http session, else None

    Args:
        secret_dict (dict): The Secret Dictionary

    Returns:
        Session: The requests.Session object if successful. None otherwise

    Raises:
        KeyError: If the secret json does not contain the expected keys

    """
    # Log in
    session = requests.Session()
    logging.info('Logging in with provided credentials...')
    url = "https://id.docker.com/api/id/v1/user/login"
    json = {"password": secret_dict['password'], "username": secret_dict['username']}
    r = session.post(url, json=json)

    if r.status_code != 200:
        logging.error("Login Failed. Error: {}".format(r.status_code))
        return None

    # Get CSRF Token
    logging.info('Getting CSRF Token...')
    url = "https://cloud.docker.com/sso/start"
    r = session.get(url)

    if r.status_code != 200 or not session.cookies['csrftoken']:
        logging.error('CSRFToken acquisition failed')
        return None

    logging.info('Successfully logged in to DockerHub')

    return session

def dockerhub_set_password(session, username, old_password, new_password):
    """Update a DockerHub password

    This method asks the DockerHub API to change the password to the requested one.

    Args:
        session (requests.Session): Logged in session

        username (string): DockerHub username

        old_password (string): Current password

        new_password (string): Password to be set

    Raises:
        Exception: If changing the password failed
    """
    # Update Password
    logging.info('Changing password...')
    url = 'https://cloud.docker.com/v2/user/change_password/'
    json = {"username": username, "old_password": old_password, "new_password": new_password}
    headers = {'X-CSRFToken': session.cookies['csrftoken']}
    r = session.put(url, json=json, headers=headers)

    if r.status_code != 204:
        logging.error('Password update failed')
        raise Exception('Password update failed: ' + r.status_code)

    logging.info('Password changed successfully!')


def create_secret(service_client, arn, token):
    """Generate a new secret

    This method first checks for the existence of a secret for the passed in token. If one does not exist, it will generate a
    new secret and put it with the passed in token.

    Args:
        service_client (client): The secrets manager service client

        arn (string): The secret ARN or other identifier

        token (string): The ClientRequestToken associated with the secret version

    Raises:
        ValueError: If the current secret is not valid JSON

        KeyError: If the secret json does not contain the expected keys

    """
    # Make sure the current secret exists
    current_dict = get_secret_dict(service_client, arn, "AWSCURRENT")

    # Now try to get the secret version, if that fails, put a new secret
    try:
        get_secret_dict(service_client, arn, "AWSPENDING", token)
        logging.info("createSecret: Successfully retrieved secret for %s." % arn)
    except service_client.exceptions.ResourceNotFoundException:
        # Generate a random password
        passwd = service_client.get_random_password(ExcludeCharacters='/@"\'\\')
        current_dict['password'] = passwd['RandomPassword']

        # Put the secret
        service_client.put_secret_value(SecretId=arn, ClientRequestToken=token, SecretString=json.dumps(current_dict), VersionStages=['AWSPENDING'])
        logging.info("createSecret: Successfully put secret for ARN %s and version %s." % (arn, token))


def set_secret(service_client, arn, token):
    """Set the pending secret in the database

    This method tries to login to the database with the AWSPENDING secret and returns on success. If that fails, it
    tries to login with the AWSCURRENT and AWSPREVIOUS secrets. If either one succeeds, it sets the AWSPENDING password
    as the user password in the database. Else, it throws a ValueError.

    Args:
        service_client (client): The secrets manager service client

        arn (string): The secret ARN or other identifier

        token (string): The ClientRequestToken associated with the secret version

    Raises:
        ResourceNotFoundException: If the secret with the specified arn and stage does not exist

        ValueError: If the secret is not valid JSON or valid credentials are found to login to the database

        KeyError: If the secret json does not contain the expected keys

    """
    # First try to login with the pending secret, if it succeeds, return
    pending_dict = get_secret_dict(service_client, arn, "AWSPENDING", token)
    session = dockerhub_get_session(pending_dict)
    if session:
        logging.info("setSecret: AWSPENDING secret is already set as password in DockerHub for secret arn %s." % arn)
        return

    # Now try the current password
    current_dict = get_secret_dict(service_client, arn, "AWSCURRENT")
    session = dockerhub_get_session(current_dict)
    if not session:
        # If both current and pending do not work, try previous
        try:
            previous_dict = get_secret_dict(service_client, arn, "AWSPREVIOUS")
            session = dockerhub_get_session(previous_dict)

            # The current password is actually the previous one, correct that fact
            current_dict = previous_dict
        except service_client.exceptions.ResourceNotFoundException:
            session = None

    # If we still don't have a session, raise a ValueError
    if not session:
        logging.error("setSecret: Unable to log into DockerHub with previous, current, or pending secret of secret arn %s" % arn)
        raise ValueError("Unable to log into DockerHub with previous, current, or pending secret of secret arn %s" % arn)

    # Now set the password to the pending password
    dockerhub_set_password(session, pending_dict['username'], current_dict['password'], pending_dict['password'])


def test_secret(service_client, arn, token):
    """Test the pending secret against the DockerHub API

    This method tries to log into the DockerHub API

    Args:
        service_client (client): The secrets manager service client

        arn (string): The secret ARN or other identifier

        token (string): The ClientRequestToken associated with the secret version

    Raises:
        ResourceNotFoundException: If the secret with the specified arn and stage does not exist

        ValueError: If the secret is not valid JSON or valid credentials are found to login to the DockerHub API

        KeyError: If the secret json does not contain the expected keys

    """
    # Try to login with the pending secret, if it succeeds, return
    session = dockerhub_get_session(get_secret_dict(service_client, arn, "AWSPENDING", token))
    if session:
        # This is where the lambda will validate the user's permissions. Uncomment/modify the below lines to
        # tailor these validations to your needs
        logging.info("testSecret: Successfully signed into DockerHub API with AWSPENDING secret in %s." % arn)
        return
    else:
        logging.error("testSecret: Unable to log into DockerHub API with pending secret of secret ARN %s" % arn)
        raise ValueError("Unable to log into DockerHub API with pending secret of secret ARN %s" % arn)



def finish_secret(service_client, arn, token):
    """Finish the rotation by marking the pending secret as current

    This method finishes the secret rotation by staging the secret staged AWSPENDING with the AWSCURRENT stage.

    Args:
        service_client (client): The secrets manager service client

        arn (string): The secret ARN or other identifier

        token (string): The ClientRequestToken associated with the secret version

    """
    # First describe the secret to get the current version
    metadata = service_client.describe_secret(SecretId=arn)
    current_version = None
    for version in metadata["VersionIdsToStages"]:
        if "AWSCURRENT" in metadata["VersionIdsToStages"][version]:
            if version == token:
                # The correct version is already marked as current, return
                logging.info("finishSecret: Version %s already marked as AWSCURRENT for %s" % (version, arn))
                return
            current_version = version
            break

    # Finalize by staging the secret version current
    service_client.update_secret_version_stage(SecretId=arn, VersionStage="AWSCURRENT", MoveToVersionId=token, RemoveFromVersionId=current_version)
    logging.info("finishSecret: Successfully set AWSCURRENT stage to version %s for secret %s." % (version, arn))


def get_secret_dict(service_client, arn, stage, token=None):
    """Gets the secret dictionary corresponding for the secret arn, stage, and token

    This helper function gets credentials for the arn and stage passed in and returns the dictionary by parsing the JSON string

    Args:
        service_client (client): The secrets manager service client

        arn (string): The secret ARN or other identifier

        token (string): The ClientRequestToken associated with the secret version, or None if no validation is desired

        stage (string): The stage identifying the secret version

    Returns:
        SecretDictionary: Secret dictionary

    Raises:
        ResourceNotFoundException: If the secret with the specified arn and stage does not exist

        ValueError: If the secret is not valid JSON

    """
    required_fields = ['username', 'password']

    # Only do VersionId validation against the stage if a token is passed in
    if token:
        secret = service_client.get_secret_value(SecretId=arn, VersionId=token, VersionStage=stage)
    else:
        secret = service_client.get_secret_value(SecretId=arn, VersionStage=stage)
    plaintext = secret['SecretString']
    secret_dict = json.loads(plaintext)

    # Run validations against the secret
    for field in required_fields:
        if field not in secret_dict:
            raise KeyError("%s key is missing from secret JSON" % field)

    # Parse and return the secret JSON string
    return secret_dict

def lambda_handler(event, context):
    """
    Main lambda handler
    """
    logging.basicConfig(level=logging.INFO)
    logging.getLogger().setLevel(logging.INFO)
    arn = event['SecretId']
    token = event['ClientRequestToken']
    step = event['Step']
    logging.info('Step: ' + step)

    # Setup the client
    service_client = boto3.client('secretsmanager', endpoint_url=os.environ['SECRET_ENDPOINT_URL'])

    # Make sure the version is staged correctly
    metadata = service_client.describe_secret(SecretId=arn)
    if "RotationEnabled" in metadata and not metadata['RotationEnabled']:
        logging.error("Secret %s is not enabled for rotation" % arn)
        raise ValueError("Secret %s is not enabled for rotation" % arn)
    versions = metadata['VersionIdsToStages']
    if token not in versions:
        logging.error("Secret version %s has no stage for rotation of secret %s." % (token, arn))
        raise ValueError("Secret version %s has no stage for rotation of secret %s." % (token, arn))
    if "AWSCURRENT" in versions[token]:
        logging.info("Secret version %s already set as AWSCURRENT for secret %s." % (token, arn))
        return
    elif "AWSPENDING" not in versions[token]:
        logging.error("Secret version %s not set as AWSPENDING for rotation of secret %s." % (token, arn))
        raise ValueError("Secret version %s not set as AWSPENDING for rotation of secret %s." % (token, arn))


    if step == 'createSecret':
        return create_secret(service_client, arn, token)
    elif step == 'setSecret':
        return set_secret(service_client, arn, token)
    elif step == 'testSecret':
        return test_secret(service_client, arn, token)
    elif step == 'finishSecret':
        return finish_secret(service_client, arn, token)

    raise Exception('Unknown Step: ' + step)

if __name__ == '__main__':
    sys.exit(main())
