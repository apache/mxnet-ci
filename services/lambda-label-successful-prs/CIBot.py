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
import json
import os
import logging
import secret_manager

from github import Github


class CIBot:
    def __init__(self,
                 repo=os.environ.get("repo"),
                 github_personal_access_token=None,
                 apply_secret=True):
        """
        Initializes the CI Bot
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

    def _get_github_object(self):
        """
        This method returns github object initialized with Github personal access token
        """
        github_obj = Github(self.github_personal_access_token)
        return github_obj

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

    def _check_status_and_label_if_successful(self, pr):
        """
        This method checks the CI status of each PR
        and it labels if the status is successful
        """
        # check if the open PR already has a pr-awaiting-review label
        if(self._check_awaiting_review_label(pr)):
            logging.info(f'PR {pr.number} already contains the label pr-awaiting-review')
            return

        # check the status of the PR and add label if successful
        if(self._is_successful(pr)):
            self._add_label(pr)
        return

    def process_prs(self):
        """
        This method handles the processing for each open PR
        """
        github_obj = self._get_github_object()
        self._check_status_and_label_if_successful(pr)
