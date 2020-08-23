import json
import os
from PRStatusBot import PRStatusBot

json_file = 'pr_awaiting.json'
file_obj = open(json_file, "r")
payload_json = json.loads(file_obj.read())
os.environ["AWS_PROFILE"] = "mxnet-ci"
os.environ["secret_name"] = "prod/pr-status_labeler_bot_credentials"
os.environ["region_name"] = "us-west-2"
pr_status_bot = PRStatusBot("apache/incubator-mxnet", apply_secret=True)
pr_status_bot.parse_payload(payload_json)
