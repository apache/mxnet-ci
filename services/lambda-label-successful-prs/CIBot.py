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

from jenkinsapi.jenkins import Jenkins
from github import Github


class CIBot:
    def __init__(self,
                 repo=os.environ.get("repo"),
                 github_personal_access_token=None,
                 jenkins_url=os.environ.get("jenkins_url"),
                 jenkins_username=None,
                 jenkins_password=None,
                 apply_secret=True):
        """
        Initializes the CI Bot
        :param repo: GitHub repository that is being referenced
        :param github_personal_access_token: GitHub authentication token (Personal access token)
        :param jenkins_url: Jenkins URL
        :param jenkins_username: Jenkins Username for JenkinsAPI
        :param jenkins_password: Jenkins Password for JenkinsAPI
        :param apply_secret: GitHub secret credential (Secret credential that is unique to a GitHub developer)
        """
        self.repo = repo
        self.github_personal_access_token = github_personal_access_token
        self.jenkins_username = jenkins_username
        self.jenkins_password = jenkins_password
        if apply_secret:
            self._get_secret()
        self.all_jobs = None
        self.jenkins_url = jenkins_url
        self.prs_labeled = 0
        self.prs_already_labeled = 0
        self.prs_status_fail = 0
        self.prs_unknown_job = 0
        self.prs_no_build = 0

    def _get_secret(self):
        """
        This method is to get secret value from Secrets Manager
        """
        secret = json.loads(secret_manager.get_secret())
        self.github_personal_access_token = secret["github_personal_access_token"]
        self.jenkins_username = secret["jenkins_username"]
        self.jenkins_password = secret["jenkins_password"]

    def _get_github_object(self):
        """
        This method returns github object initialized with Github personal access token
        """
        github_obj = Github(self.github_personal_access_token)
        return github_obj

    def _find_all_open_prs(self, github_obj):
        """
        This method identifies all the open PRs in the given repository
        It returns a Paginated list of Pull Request objects sorted in
        descending order of created date i.e. latest PR first
        :param github_obj
        """
        repo = github_obj.get_repo(self.repo)
        pulls = repo.get_pulls(state='open', sort='created', direction='desc')
        return pulls

    def _get_jenkins_obj(self):
        """
        This method returns an object of Jenkins instantiated using username, password
        """
        return Jenkins(self.jenkins_url, username=self.jenkins_username, password=self.jenkins_password)

    def _get_checks(self):
        """
        This method finds out all the checks that are currently supported as part of CI
        """
        # for now hardcoding list of checks
        # ideally use Jenkins API to query list of checks and parse it (bit complicated)
        all_checks = ['clang', 'edge', 'centos-cpu', 'centos-gpu', 'windows-cpu', 'windows-gpu', 'miscellaneous', 'unix-cpu', 'unix-gpu', 'website', 'sanity']
        return all_checks

    def _is_successful(self, pr):
        """
        This method checks if all the pipelines corresponding to a latest build of the PR are successful
        :param pr PullRequest object
        """
        # get jenkins object
        jenkins_obj = self._get_jenkins_obj()

        # get PR number
        pr_number = pr.number

        # get a list of checks
        # Github says "status checks"
        # Jenkins refers to it as a job name
        checks = self._get_checks()

        # iterate over the checks
        for check in checks:
            # Jenkins Job name
            name = "mxnet-validation/" + check + "/PR-" + str(pr_number)

            try:
                # get Jenkins job specific object
                job = jenkins_obj[name]
            except Exception:
                logging.error(f'Unknown Job Exception')
                self.prs_unknown_job += 1
                return False
            # get status of the latest build of the job
            try:
                latest_build = job.get_last_build()
                status = latest_build.get_status()
                logging.info(f'Latest build status for PR {pr_number} is {status}')
                if(status.upper() == 'FAILURE'):
                    self.prs_status_fail += 1
                    return False
            except Exception:
                logging.error(f'No Build Exception')
                self.prs_no_build += 1
                return False
        logging.info(f'All 11 builds succeeded! Happy case!')
        return True

    def _add_label(self, pr):
        try:
            pr.add_to_labels('pr-awaiting-review')
        except Exception:
            logging.error('Unable to add label')

        # verify that label has been correctly added
        if(self._check_awaiting_review_label(pr)):
            logging.info(f'Successfully labeled {pr.number}')
            self.prs_labeled += 1
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
            self.prs_already_labeled += 1
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

        open_prs = self._find_all_open_prs(github_obj)
        logging.info(f'Number of Open PRs found : {open_prs.totalCount}')

        for pr in open_prs:
            logging.info(f'Processing PR: {pr.number}')
            self._check_status_and_label_if_successful(pr)

        summary_stats_mesg = 'Summary Statistics \n Open PRs : ' + str(open_prs.totalCount) \
            + 'PRs labeled by lambda : ' + str(self.prs_labeled) \
            + 'PRs already labeled : ' + str(self.prs_already_labeled) \
            + 'PRs with unknown jobs : ' + str(self.prs_unknown_job) \
            + 'PRs with status failed : ' + str(self.prs_status_fail) \
            + 'PRs with no build : ' + str(self.prs_no_build)
        logging.info(str(summary_stats_mesg))
