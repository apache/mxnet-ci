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
import unittest
import ast
from LabelBot import LabelBot

# some version issue
try:
    from unittest.mock import patch
except ImportError:
    from mock import patch


class TestLabelBot(unittest.TestCase):
    """
    Unittest of LabelBot.py
    """
    def setUp(self):
        self.lb = LabelBot(repo="harshp8l/mxnet-infrastructure",  apply_secret=True)

    # Tests for basic functionality
    def test_add_labels(self):
        with patch('LabelBot.requests.post') as mocked_post:
            mocked_post.return_value.status_code = 200
            self.lb.all_labels = ['sample_label', 'another_label', 'all_labels']
            self.assertTrue(self.lb.add_labels(issue_num=0, labels=['sample_label']))

    def test_remove_labels(self):
        with patch('LabelBot.requests.delete') as mocked_delete:
            mocked_delete.return_value.status_code = 200
            self.lb.all_labels = ['sample_label', 'another_label', 'all_labels']
            self.assertTrue(self.lb.remove_labels(issue_num=0, labels=['sample_label']))

    def test_update_labels(self):
        with patch('LabelBot.requests.put') as mocked_put:
            mocked_put.return_value.status_code = 200
            self.lb.all_labels = ['sample_label', 'another_label', 'all_labels']
            self.assertTrue(self.lb.update_labels(issue_num=0, labels=['sample_label']))

    # Tests for different kinds of user input
    # Tests for spaces
    def test_tokenize_frontSpace(self):
        user_label = LabelBot._tokenize(LabelBot.__class__, "[   Sample Label]")
        self.assertEqual(user_label, ['sample label'])

    def test_tokenize_endSpace(self):
        user_label = LabelBot._tokenize(LabelBot.__class__, "[ Sample Label      ]")
        self.assertEqual(user_label, ['sample label'])

    def test_tokenize_midSpace(self):
        user_label = LabelBot._tokenize(LabelBot.__class__, "[Sample        Label]")
        self.assertEqual(user_label, ['sample label'])

    def test_tokenize_manyWordsSpace(self):
        user_label = LabelBot._tokenize(LabelBot.__class__, "[This    is    a     sample    label]")
        self.assertEqual(user_label, ['this is a sample label'])

    # Tests for case-insensitive
    def test_tokenize_upperCase(self):
        user_label = LabelBot._tokenize(LabelBot.__class__, "[SAMPLE LABEL, ANOTHER LABEL, FINAL]")
        self.assertEqual(user_label, ['sample label', 'another label', 'final'])

    def test_tokenize_mixCase(self):
        user_label = LabelBot._tokenize(LabelBot.__class__, "[sAmPlE LaBeL, AnOtHeR lAbEl, fInAl]")
        self.assertEqual(user_label, ['sample label', 'another label', 'final'])

    def test_tokenize_lowerCase(self):
        user_label = LabelBot._tokenize(LabelBot.__class__, "[sample label, another label, final]")
        self.assertEqual(user_label, ['sample label', 'another label', 'final'])

    # Tests for parsing data from github comments
    # Referencing @mxnet-label-bot from different places in the comment body
    def test_parse_webhook_data_referencedAtEnd(self):
        with open("testInputFiles/testAtEnd.json", "r") as fh:
            token = ast.literal_eval(fh.read())
            with patch.object(LabelBot, '_secure_webhook', return_value=True):
                with patch.object(LabelBot, 'add_labels', return_value=True):
                    self.lb.parse_webhook_data(token)

    def test_parse_webhook_data_referencedAtStart(self):
        with open("testInputFiles/testAtStart.json", "r") as fh:
            token = ast.literal_eval(fh.read())
            with patch.object(LabelBot, '_secure_webhook', return_value=True):
                with patch.object(LabelBot, 'add_labels', return_value=True):
                    self.lb.parse_webhook_data(token)

    def test_parse_webhook_data_referencedAtMid(self):
        with open("testInputFiles/testAtMid.json", "r") as fh:
            token = ast.literal_eval(fh.read())
            with patch.object(LabelBot, '_secure_webhook', return_value=True):
                with patch.object(LabelBot, 'add_labels', return_value=True):
                    print(self.lb.parse_webhook_data(token))

    # Test if actions are triggered with different user inputs ( i.e. add[label] )
    def test_parse_webhook_data_actionNoSpace(self):
        with open("testInputFiles/testNoSpace.json", "r") as fh:
            token = ast.literal_eval(fh.read())
            with patch.object(LabelBot, '_secure_webhook', return_value=True):
                with patch.object(LabelBot, 'add_labels', return_value=True):
                    print(self.lb.parse_webhook_data(token))


if __name__ == "__main__":
    unittest.main()
