from unittest import TestCase

import httpretty


class JsonContent:
    """Descriptor that sets a new class attribute based on the JSON file of the same name"""

    def __init__(self, name):
        self.name = name

    def __get__(self, instance, owner):
        if instance is None:
            return owner

        with open(f'{self.name}.json') as file:
            setattr(instance, self.name, file.read())

        return getattr(instance, self.name)


class MockGithubResponse:

    user = JsonContent('user')
    # add any Github object you need here


class PyGithubTestCase(TestCase):

    def setUp(self):
        httpretty.enable()
        httpretty.reset()

        base_url = 'https://api.github.com'
        headers = {
            'content-type': 'application/json',
            'X-OAuth-Scopes': 'admin:org, admin:repo_hook, repo, user',
            'X-Accepted-OAuth-Scopes': 'repo'
        }
        
        fake = MockGithubResponse()
        response_mapping = {
            '/user(/(\w+))?': fake.user,
            # Add API url RegEx, with its corresponding response here...
        }

        for url, response in response_mapping.items():
            # Note: Here, I only bind `GET` methods, but you can bind any method you want
            httpretty.register_uri(
                httpretty.GET, 
                re.compile(base_url + url),
                response,
                adding_headers=headers  # You need this!
            )

    def tearDown(self):
        httpretty.disable()
