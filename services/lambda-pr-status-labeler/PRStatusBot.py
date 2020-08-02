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
import ast
import json
import hmac
import hashlib
import os
import logging
import secret_manager

from github import Github


class PRStatusBot:
    def __init__(self,
                 repo=os.environ.get("repo"),
                 github_personal_access_token=None,
                 apply_secret=True):
        """
        Initializes the PR Status Bot
        :param repo: GitHub repository that is being referenced
        :param github_personal_access_token: GitHub authentication token (Personal access token)
        :param apply_secret: GitHub secret credential (Secret credential that is unique to a GitHub developer)
        """
        self.repo = repo
        self.github_personal_access_token = github_personal_access_token
        if apply_secret:
            self._get_secret()

    def _get_secret(self):
        """
        This method is to get secret value from Secrets Manager
        """
        secret = json.loads(secret_manager.get_secret())
        self.github_personal_access_token = secret["github_personal_access_token"]
        self.webhook_secret = secret["webhook_secret"]

    def _secure_webhook(self, event):
        """
        This method will validate the security of the webhook, it confirms that the secret
        of the webhook is matched and that each github event is signed appropriately
        :param event: The github event we want to validate
        :return Response denoting success or failure of security
        """

        # Validating github event is signed
        try:
            git_signed = ast.literal_eval(event["Records"][0]['body'])['headers']["X-Hub-Signature"]
        except KeyError:
            raise Exception("WebHook from GitHub is not signed")
        git_signed = git_signed.replace('sha1=', '')

        # Signing our event with the same secret as what we assigned to github event
        secret = self.webhook_secret
        body = ast.literal_eval(event["Records"][0]['body'])['body']
        secret_sign = hmac.new(key=secret.encode('utf-8'), msg=body.encode('utf-8'), digestmod=hashlib.sha1).hexdigest()

        # Validating signatures match
        return hmac.compare_digest(git_signed, secret_sign)

    def _get_github_object(self):
        """
        This method returns github object initialized with Github personal access token
        """
        github_obj = Github(self.github_personal_access_token)
        return github_obj

    def _get_pull_request_object(self, github_obj, pr_number):
        """
        This method returns a PullRequest object based on the PR number
        :param github_obj
        :param pr_number
        """
        repo = github_obj.get_repo(self.repo)
        pr_obj = repo.get_pull(pr_number)
        return pr_obj

    def _add_label(self, pr):
        try:
            pr.add_to_labels('pr-awaiting-review')
        except Exception:
            logging.error('Unable to add label')

        # verify that label has been correctly added
        if(self._check_awaiting_review_label(pr)):
            logging.info(f'Successfully labeled {pr.number}')
        return

    def _check_awaiting_review_label(self, pr):
        """
        This method returns True if pr-awaiting-review label found in PR labels
        """
        labels = pr.get_labels()
        for label in labels:
            if 'pr-awaiting-review' == label.name:
                return True
        return False

    def _label_pr_based_on_status(self, pr):
        """
        This method checks the CI status of each PR
        and it labels the PR accordingly
        """
        # pseudo-code
        # if WIP in title or PR is draft or CI failed:
        #   pr-work-in-progress
        # elif CI has not started yet or CI is in progress:
        #   pr-awaiting-testing
        # else: # CI passed checks
        #   if pr has at least one approval and no request changes:
        #       pr-awaiting-merge
        #   elif pr has no review or all reviews have been dismissed/re-requested:
        #       pr-awaiting-review
        #   else: # pr has a review that hasn't been dismissed yet no approval
        #       pr-awaiting-response
        # # check if the open PR already has a pr-awaiting-review label
        # if(self._check_awaiting_review_label(pr)):
        #     logging.info(f'PR {pr.number} already contains the label pr-awaiting-review')
        #     return

        # # check the status of the PR and add label if successful
        # if(self._is_successful(pr)):
        #     self._add_label(pr)
        logging.info(f'Labeling PR {pr.number} based on the status')
        return

    def parse_webhook_data(self, event):
        """
        This method handles the processing for each PR depending on the appropriate Github event
        information provided by the Github Webhook.
        """
        try:
            github_event = ast.literal_eval(event["Records"][0]['body'])['headers']["X-GitHub-Event"]
            logging.info(f"github event {github_event}")
        except KeyError:
            raise Exception("Not a GitHub Event")

        if not self._secure_webhook(event):
            raise Exception("Failed to validate WebHook security")

        try:
            payload = json.loads(ast.literal_eval(event["Records"][0]['body'])['body'])
        except ValueError:
            raise Exception("Decoding JSON for payload failed")
        context = payload['context']
        state = payload['state']
        logging.info(f'PR Context {context}')
        logging.info(f'PR State {state}')
        # pr_number = payload['number']
        # github_obj = self._get_github_object()
        # pr_obj = self._get_pull_request_object(github_obj, pr_number)
        # self._label_pr_based_on_status(pr_obj)
