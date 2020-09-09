import os
import json
from PRStatusBot import PRStatusBot, GithubObj

def load_and_test(data):
    payload_json = json.loads(data)
    os.environ["AWS_PROFILE"] = "mxnet-ci"
    # set secret_name [commented since it is to be redacted]
    # os.environ["secret_name"] = REDACTED
    os.environ["region_name"] = "us-west-2"
    github_obj = GithubObj(apply_secret=True)
    pr_status_bot = PRStatusBot(repo="apache/incubator-mxnet", github_obj=github_obj.github_object, apply_secret=True)
    pr_status_bot.parse_payload(payload_json)


def prepare_input(pr_num, context, state, sha):
    data = {
        "target_url": "PR-" + str(pr_num),
        "context": "ci/jenkins/mxnet-validation/" + context,
        "state": state,
        "commit": {
            "sha": sha
        }
    }
    # return serialized data dictionary
    return json.dumps(data)


def check_ci_failure():
    data = prepare_input(18984, "website", "failed", "6fbfa3c020e566c0d54825cbfb67abca1d70b4fa")
    load_and_test(data)


def check_ci_pending():
    data = prepare_input(18921, "sanity", "pending", "19fa075dc0cc76678750b6c691208aa7aa1f45ff")
    load_and_test(data)


def check_ci_success():
    data = prepare_input(18983, "unix-gpu", "success", "26fb1921b6e09226146b4b90d2d995b7a018347d")
    load_and_test(data)


def check_pr_awaiting_merge():
    # https://github.com/apache/incubator-mxnet/pull/17468
    # PR satisfies all criterion for pr-awaiting-merge label
    # - passed all CI tests;
    # - PR contains atleast 1 Committers' approvers; no requested changes
    # It does have a merge conflict though
    data = prepare_input(17468, "unix-gpu", "success", "68c19d7b08d04df1d4ac9dd3fca7ad58f925ec51")
    load_and_test(data)


def check_commit_with_non_committer_review():
    # https://github.com/apache/incubator-mxnet/pull/16025
    # PR passes CI but has 1 non-MX Committer review
    data = prepare_input(16025, "unix-gpu", "success", "fb343b55ec4721c9cce4422224c246eb3a188bb2")
    load_and_test(data)


def check_commit_with_no_review():
    # https://github.com/apache/incubator-mxnet/pull/18983
    # PR has no review but CI passes
    data = prepare_input(18983, "unix-gpu", "success", "26fb1921b6e09226146b4b90d2d995b7a018347d")
    load_and_test(data)


def check_wip_title_pr():
    data = prepare_input(18715, "unix-gpu", "success", "d638d3c51c176208e2909134306fb62d1df99b6c")
    load_and_test(data)


def check_draft_pr():
    data = prepare_input(18835, "unix-gpu", "success", "12dd397f6886a4014ef5f81c1cbcae4ca68e3f5b")
    load_and_test(data)


def check_pr_with_requested_changes():
    data = prepare_input(13735, "unix-gpu", "success", "32a3b6eb2b53f27a5bddbfd130ac2e357877475d")
    load_and_test(data)


check_ci_failure()
check_ci_success()
check_ci_pending()
check_pr_awaiting_merge()
check_commit_with_non_committer_review()
check_commit_with_no_review()
check_wip_title_pr()
check_draft_pr()
check_pr_with_requested_changes()
# check_pr_awaiting_response()
