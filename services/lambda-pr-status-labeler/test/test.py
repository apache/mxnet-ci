import json

from github import Github

from base import PyGithubTestCase


class TestUser(PyGithubTestCase):
    def test_username(self):
        g = Github('fake-token')
        user = g.get_user()

        with open('user.json', 'rb') as f:
            expected_body = json.load(f)
        self.assertEqual(user.login, expected_body['login'])  # True


TestUser().test_username()
