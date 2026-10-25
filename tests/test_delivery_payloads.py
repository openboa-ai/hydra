"""P14-T09: final provider payloads preserve post-merge completion responsibility."""
import copy
import unittest

from hydra_sdlc.github import GitHub, GitHubError
from test_github import HEAD, IDENTITY, MERGE, REPO, REPOSITORY, owned_pr


class DeliveryPayloadTests(unittest.TestCase):
    def client(self, *, title='Implement the accepted outcome', extra=''):
        requests = []
        pr = {**owned_pr(), 'title': title, 'body': owned_pr()['body'] + extra}
        def transport(method, path, payload):
            if path == '/user':
                return IDENTITY
            if path == f'/repos/{REPO}':
                return REPOSITORY
            if method == 'PUT':
                requests.append(copy.deepcopy(payload))
                return {'merged': True, 'sha': MERGE}
            self.assertEqual(path, f'/repos/{REPO}/pulls/7')
            return {**copy.deepcopy(pr), **({'state': 'closed', 'merged': True,
                'merge_commit_sha': MERGE} if requests else {})}
        return GitHub(transport=transport), requests

    def test_valid_owned_squash_is_still_read_back(self):
        client, requests = self.client()
        result = client.merge(REPO, 7, HEAD,
            commit_message='Hydra-Squash-v1: ' + 'e' * 64, issue_number=4)
        self.assertEqual(result['merge_commit_sha'], MERGE)
        self.assertEqual(len(requests), 1)

    def test_closing_pr_payload_is_rejected_before_put(self):
        phrases = ['Fixes: #4', 'CLOSES example/product#4',
                   'Resolved https://github.com/example/product/issues/4']
        for phrase in phrases:
            for field in ('title', 'body'):
                with self.subTest(phrase=phrase, field=field):
                    client, requests = self.client(
                        title=phrase if field == 'title' else 'Valid title',
                        extra='\n' + phrase if field == 'body' else '')
                    with self.assertRaises(GitHubError):
                        client.merge(REPO, 7, HEAD,
                            commit_message='Hydra-Squash-v1: ' + 'e' * 64, issue_number=4)
                    self.assertEqual(requests, [])

    def test_squash_title_does_not_depend_on_mutable_pr_title(self):
        client, requests = self.client(title='A mutable but harmless PR title')
        client.merge(REPO, 7, HEAD,
            commit_message='Hydra-Squash-v1: ' + 'e' * 64, issue_number=4)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].get('commit_title'), 'Deliver Issue 4 (#7)')
        self.assertEqual(requests[0]['commit_message'], 'Hydra-Squash-v1: ' + 'e' * 64)
