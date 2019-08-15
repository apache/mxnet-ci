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
import os
import re
from botocore.vendored import requests
import logging
import secret_manager
import hmac
import hashlib


class LabelBot:
    LABEL_PAGE_PARSE = 30  # Limit for total labels per page to parse

    def __init__(self,
                 repo=os.environ.get("repo"),
                 github_user=None,
                 github_oauth_token=None,
                 bot_user=None,
                 bot_oauth_token=None,
                 prediction_url=None,
                 apply_secret=True):
        """
        Initializes the Label Bot
        :param repo: GitHub repository that is being referenced
        :param github_user: GitHub username
        :param github_oauth_token: GitHub authentication token (Personal access token)
        :param apply_secret: GitHub secret credential (Secret credential that is unique to a GitHub developer)
        """
        self.repo = repo
        self.github_user = github_user
        self.github_oauth_token = github_oauth_token
        self.bot_user = bot_user
        self.bot_oauth_token = bot_oauth_token
        self.prediction_url = prediction_url
        if apply_secret:
            self._get_secret()
        self.auth = (self.github_user, self.github_oauth_token)
        self.bot_auth = (self.bot_user, self.bot_oauth_token)
        self.all_labels = None

    def _get_rate_limit(self):
        """
        This method gets the remaining rate limit that is left from the GitHub API
        :return Remaining API requests left that GitHub will allow
        """
        res = requests.get('https://api.github.com/rate_limit',
                           auth=self.auth)
        res.raise_for_status()
        data = res.json()['rate']
        return data['remaining']

    def _get_secret(self):
        """
        This method is to get secret value from Secrets Manager
        """
        secret = json.loads(secret_manager.get_secret())
        self.github_user = secret["github_user"]
        self.github_oauth_token = secret["github_oauth_token"]
        self.webhook_secret = secret["webhook_secret"]
        self.bot_user = secret["bot_user"]
        self.bot_oauth_token = secret["bot_oauth_token"]
        self.prediction_url = secret["prediction_url"]

    def _tokenize(self, string):
        """
        This method is to extract labels from comments
        :param string: String parsed from a GitHub comment
        :return Set of Labels which have been extracted
        """
        substring = string[string.find('[') + 1: string.rfind(']')]
        labels = [' '.join(label.split()).lower() for label in substring.split(',')]
        return labels

    def _ascii_only(self, raw_string, sub_string):
        """
        This method is to convert all non-alphanumeric characters from raw_string to sub_string
        :param raw_string The original string messy string
        :param sub_string The string we want to convert to
        :return Fully converted string
        """
        converted_string = re.sub("[^0-9a-zA-Z]", sub_string, raw_string)
        return converted_string.lower()

    def _find_all_labels(self):
        """
        This method finds all existing labels in the repo
        :return A set of all labels which have been extracted from the repo
        """
        url = f'https://api.github.com/repos/{self.repo}/labels'
        response = requests.get(url, auth=self.auth)
        response.raise_for_status()

        # Getting total pages of labels present
        if "link" not in response.headers:
            pages = 1
        else:
            pages = int(self._ascii_only(response.headers['link'], " ").split()[-3])

        all_labels = []
        for page in range(1, pages + 1):
            url = 'https://api.github.com/repos/' + self.repo + '/labels?page=' + str(page) \
                  + '&per_page=%s' % self.LABEL_PAGE_PARSE
            response = requests.get(url, auth=self.auth)
            for item in response.json():
                all_labels.append(item['name'].lower())
        self.all_labels = set(all_labels)
        return set(all_labels)

    def _format_labels(self, labels):
        """
        This method formats labels that a user specifies for a specific issue. This is meant
        to provide functionality for the operations on labels
        :param labels: The messy labels inputted by the user which we want to format
        :return: Formatted labels to send for CRUD operations
        """
        assert self.all_labels, "Find all labels first"
        # clean labels, remove duplicated spaces. ex: "hello  world" -> "hello world"
        labels = [" ".join(label.split()) for label in labels]
        labels = [label for label in labels if label.lower() in self.all_labels]
        return labels

    def add_labels(self, issue_num, labels):
        """
        This method is to add a list of labels to one issue.
        It checks whether labels exist in the repo, and adds existing labels to the issue
        :param issue_num: The specific issue number we want to label
        :param labels: The labels which we want to add
        :return Response denoting success or failure for logging purposes
        """
        labels = self._format_labels(labels)
        issue_labels_url = f'https://api.github.com/repos/{self.repo}/issues/{issue_num}/labels'
        response = requests.post(issue_labels_url, json.dumps(labels), auth=self.auth)
        if response.status_code == 200:
            logging.info(f'Successfully added labels to {issue_num}: {labels}.')
            return True
        else:
            logging.error(f'Could not add the labels to {issue_num}: {labels}. '
                          f'\nResponse: {json.dumps(response.json())}')
            return False

    def remove_labels(self, issue_num, labels):
        """
        This method is to remove a list of labels to one issue.
        It checks whether labels exist in the repo, and removes existing labels to the issue
        :param issue_num: The specific issue number we want to label
        :param labels: The labels which we want to remove
        :return Response denoting success or failure for logging purposes
        """
        labels = self._format_labels(labels)
        issue_labels_url = f'https://api.github.com/repos/{self.repo}/issues/{issue_num}/labels/'

        for label in labels:
            delete_label_url = issue_labels_url + label
            response = requests.delete(delete_label_url, auth=self.auth)
            if response.status_code == 200:
                logging.info(f'Successfully removed label to {issue_num}: {label}.')
            else:
                logging.error(f'Could not remove the label to {issue_num}: {label}. '
                              f'\nResponse: {json.dumps(response.json())}')
                return False
        return True

    def update_labels(self, issue_num, labels):
        """
        This method is to update a list of labels to one issue.
        It checks whether labels exist in the repo, and updates existing labels to the issue
        :param issue_num: The specific issue number we want to label
        :param labels: The labels which we want to remove
        :return Response denoting success or failure for logging purposes
        """
        labels = self._format_labels(labels)
        issue_labels_url = f'https://api.github.com/repos/{self.repo}/issues/{issue_num}/labels'

        response = requests.put(issue_labels_url, data=json.dumps(labels), auth=self.auth)
        if response.status_code == 200:
            logging.info(f'Successfully updated labels to {issue_num}: {labels}.')
            return True
        else:
            logging.error(f'Could not update the labels to {issue_num}: {labels}. '
                          f'\nResponse: {json.dumps(response.json())}')
            return False

    def replace_label(self, issue_num, labels):
        """
        This method is to change a label to another in an issue
        :param issue_num: The specific issue number we want to label
        :param labels: The labels which we want to change from and to
        :return: Response denoting success or failure for logging purposes
        """
        labels = self._format_labels(labels)
        if len(labels) != 2:
            logging.error('Must only specify 2 labels when wanting to change labels')
            return False
        logging.info('Label on {} to change from: {} to {}'.format(str(issue_num), str(labels[0]), str(labels[1])))
        if self.remove_labels(issue_num, [labels[0]]) and self.add_labels(issue_num, [labels[1]]):
            return True
        else:
            return False

    def predict_label(self, issue_num):

        predict_issue = {"issues": [issue_num]}
        header = {"Content-Type": 'application/json'}
        response = requests.post(self.prediction_url, data=json.dumps(predict_issue), headers=header)
        predicted_labels = response.json()[0]["predictions"]

        if response.status_code == 200:
            logging.info(f'Successfully predicted labels to {issue_num}: {predicted_labels}')
        else:
            logging.error("Unable to predict labels")
            return False

        if 'Question' in predicted_labels:
            message = "Hey, this is the MXNet Label Bot and I think you have raised a question. \n" \
                      "For questions, you can also submit on MXNet discussion forum (https://discuss.mxnet.io), " \
                      "where it will get a wider audience and allow others to learn as well. Thanks! \n "
            self.add_github_labels(issue_num, ['question'])

        else:
            message = "Hey, this is the MXNet Label Bot. \n Thank you for submitting the issue! I will try and " \
                      "suggest some labels so that the appropriate MXNet community members can help " \
                      "resolve it. \n "
        if predicted_labels:
            message += 'Here are my recommended label(s): {}'.format(', '.join(predicted_labels))
        
        self.create_comment(issue_num, message)
        return True

    def create_comment(self, issue_num, message):
        """
        This method will trigger a comment to an issue by the label bot
        :param issue_num: The issue we want to comment
        :param message: The comment message we want to send
        :return Response denoting success or failure for logging purposes
        """
        send_msg = {"body": message}
        issue_comments_url = f'https://api.github.com/repos/{self.repo}/issues/{issue_num}/comments'

        response = requests.post(issue_comments_url, data=json.dumps(send_msg), auth=self.bot_auth)
        if response.status_code == 201:
            logging.info(f'Successfully commented {send_msg} to: {issue_num}')
            return True
        else:
            logging.error(f'Could not comment \n {json.dumps(response.json())}')
            return False

    def label_action(self, actions):
        """
        This method will perform an actions for the labels that are provided. This function delegates
        the appropriate action to the correct methods.
        :param actions: The action we want to take on the label
        :return Response denoting success or failure for logging purposes
        """
        if "add" in actions:
            return self.add_labels(actions["add"][0], actions["add"][1])
        elif "remove" in actions:
            return self.remove_labels(actions["remove"][0], actions["remove"][1])
        elif "update" in actions:
            return self.update_labels(actions["update"][0], actions["update"][1])
        elif "replace" in actions:
            return self.replace_label(actions["replace"][0], actions["replace"][1])
        else:
            return False

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

    def parse_webhook_data(self, event):
        """
        This method triggers the label bot when the appropriate
        GitHub event is recognized by use of a webhook
        :param event: The event data that is received whenever a github issue, issue comment, etc. is made
        :return: Log statements which we can track in lambda
        """
        try:
            github_event = ast.literal_eval(event["Records"][0]['body'])['headers']["X-GitHub-Event"]
        except KeyError:
            raise Exception("Not a GitHub Event")

        if not self._secure_webhook(event):
            raise Exception("Failed to validate WebHook security")

        try:
            payload = json.loads(ast.literal_eval(event["Records"][0]['body'])['body'])
        except ValueError:
            raise Exception("Decoding JSON for payload failed")

        # Grabs actual payload data of the appropriate GitHub event needed for labelling
        if github_event == "issue_comment":

            # Acquiring labels specific to this repo
            labels = []
            actions = {}

            # Looks for and reads phrase referencing @mxnet-label-bot, and trims extra whitespace to single space
            if "@mxnet-label-bot" in payload["comment"]["body"]:
                phrase = payload["comment"]["body"][payload["comment"]["body"].find("@mxnet-label-bot"):payload["comment"]["body"].find("]")+1]
                phrase = ' '.join(phrase.split())

                labels += self._tokenize(phrase)
                if not labels:
                    logging.error(f'Message typed by user: {phrase}')
                    raise Exception("Unable to gather labels from issue comments")

                self._find_all_labels()
                if not self.all_labels:
                    raise Exception("Unable to gather labels from the repo")

                if not set(labels).intersection(set(self.all_labels)):
                    logging.error(f'Labels entered by user: {set(labels)}')
                    logging.error(f'Repo labels: {set(self.all_labels)}')
                    raise Exception("Provided labels don't match labels from the repo")

                # Case so that ( add[label1] ) and ( add [label1] ) are treated the same way
                if phrase.split(" ")[1].find('[') != -1:
                    action = phrase.split(" ")[1][:phrase.split(" ")[1].find('[')].lower()
                else:
                    action = phrase.split(" ")[1].lower()

                issue_num = payload["issue"]["number"]
                actions[action] = issue_num, labels
                if not self.label_action(actions):
                    logging.error(f'Unsupported actions: {actions}')
                    raise Exception("Unrecognized/Infeasible label action for the mxnet-label-bot")

        # On creation of a new issue, automatically trigger the bot to recommend labels
        if github_event == "issues" and payload["action"] == "opened":
            self._find_all_labels()
            return self.predict_label(payload["issue"]["number"])

        else:
            logging.info(f'GitHub Event unsupported by Label Bot: {github_event} {payload["action"]}')

