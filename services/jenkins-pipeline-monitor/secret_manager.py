import boto3
from botocore.exceptions import ClientError
import os
import logging
logging.basicConfig(level=logging.INFO)


def get_secret():
    """
    This method is to fetch secret values
    Please configure corresponding secret_name and region_name in environment.yml
    """
    secret_name = os.environ.get("secret_name")
    region_name = os.environ.get("region_name")
    endpoint_url = "https://secretsmanager.{}.amazonaws.com".format(region_name)
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name,
        endpoint_url=endpoint_url
    )

    try:
        # Decrypted secret using the associated KMS CMK
        # Depending on whether the secret was a string or binary, one of these fields will be populated
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
        if 'SecretString' in get_secret_value_response:
            secret = get_secret_value_response['SecretString']
            return secret
        else:
            binary_secret_data = get_secret_value_response['SecretBinary']
            return binary_secret_data
    except ClientError as e:
        logging.exception(e.response['Error']['Code'])