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
import json
import os
from PRStatusBot import PRStatusBot, GithubObj, FAILURE_STATE, PENDING_STATE, SUCCESS_STATE, PR_WORK_IN_PROGRESS_LABEL, PR_AWAITING_TESTING_LABEL, PR_AWAITING_REVIEW_LABEL, PR_AWAITING_RESPONSE_LABEL, PR_AWAITING_MERGE_LABEL, WORK_IN_PROGRESS_TITLE_SUBSTRING
import handler


def test_if_payload_is_non_PR(mocker):
    payload = {'target_url': 'master'}
    prsb = PRStatusBot(None, None, False)
    actual = prsb.parse_payload(payload)
    expected = 1
    assert actual == expected


def test_if_pr_closed(mocker):
    payload = {'target_url': 'PR-1'}
    prsb = PRStatusBot(None, None, False)
    mocker.patch.object(PRStatusBot, '_get_pull_request_object', return_value=MockPR(state='closed'))
    actual = prsb.parse_payload(payload)
    expected = 2
    assert actual == expected


def test_if_pr_wip_title(mocker):
    mockpr = MockPR(title=WORK_IN_PROGRESS_TITLE_SUBSTRING)
    prsb = PRStatusBot(None, None, False)
    mocker.patch.object(PRStatusBot, '_add_label')
    prsb._label_pr_based_on_status(FAILURE_STATE, mockpr)
    PRStatusBot._add_label.assert_called_with(mockpr, PR_WORK_IN_PROGRESS_LABEL)


def test_if_pr_draft(mocker):
    mockpr = MockPR(draft=True)
    prsb = PRStatusBot(None, None, False)
    mocker.patch.object(PRStatusBot, '_add_label')
    prsb._label_pr_based_on_status(SUCCESS_STATE, mockpr)
    PRStatusBot._add_label.assert_called_with(mockpr, PR_WORK_IN_PROGRESS_LABEL)


def test_if_ci_status_failure(mocker):
    mockpr = MockPR()
    prsb = PRStatusBot(None, None, False)
    mocker.patch.object(PRStatusBot, '_add_label')
    prsb._label_pr_based_on_status(FAILURE_STATE, mockpr)
    PRStatusBot._add_label.assert_called_with(mockpr, PR_WORK_IN_PROGRESS_LABEL)


def test_if_ci_status_pending(mocker):
    mockpr = MockPR()
    prsb = PRStatusBot(None, None, False)
    mocker.patch.object(PRStatusBot, '_add_label')
    prsb._label_pr_based_on_status(PENDING_STATE, mockpr)
    PRStatusBot._add_label.assert_called_with(mockpr, PR_AWAITING_TESTING_LABEL)


def test_if_pr_no_reviews(mocker):
    def mock_no_review_counts(self, pr):
        # approves, request_changes, comments
        return 0, 0, 0
    mockpr = MockPR()
    prsb = PRStatusBot(None, None, False)
    mocker.patch.object(PRStatusBot, '_add_label')
    mocker.patch.object(PRStatusBot, '_parse_reviews', mock_no_review_counts)
    prsb._label_pr_based_on_status(SUCCESS_STATE, mockpr)
    PRStatusBot._add_label.assert_called_with(mockpr, PR_AWAITING_REVIEW_LABEL)


def test_if_pr_reviews_requested_changes(mocker):
    def mock_no_review_counts(self, pr):
        # approves, request_changes, comments
        return 0, 1, 0
    mockpr = MockPR()
    prsb = PRStatusBot(None, None, False)
    mocker.patch.object(PRStatusBot, '_add_label')
    mocker.patch.object(PRStatusBot, '_parse_reviews', mock_no_review_counts)
    prsb._label_pr_based_on_status(SUCCESS_STATE, mockpr)
    PRStatusBot._add_label.assert_called_with(mockpr, PR_AWAITING_RESPONSE_LABEL)


class MockRepo:
    def __init__(self, name=None):
        self.name = name

    def get_commit(self, commit_sha):
        return 'abc'

    def get_pull(self, pr_number):
        return MockPR(pr_number)


class MockGithub:
    def __init__(self):
        pass

    def get_repo(self, name=None):
        return MockRepo(name)


class MockLabel:
    def __init__(self, name=None):
        self.name = name


class MockPR:
    def __init__(self, pr_number=1, state='open', title='abc', draft=False):
        self.number = pr_number
        self.state = state
        self.title = title
        self.draft = draft

    def get_labels(self):
        return [MockLabel('lab1'), MockLabel('lab2')]
