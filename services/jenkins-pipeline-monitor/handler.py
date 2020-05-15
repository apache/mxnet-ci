import os
import boto3
import json
import logging
import secret_manager

from jenkinsapi.jenkins import Jenkins

logging.getLogger().setLevel(logging.INFO)
logging.getLogger('boto3').setLevel(logging.CRITICAL)
logging.getLogger('botocore').setLevel(logging.CRITICAL)


def get_jenkins_obj(secret):
    """
    This method returns an object of Jenkins instantiated using username, password
    """
    jenkins_url, jenkins_username, jenkins_password = os.environ["JENKINS_URL"], secret["jenkins_username"], secret["jenkins_password"]
    return Jenkins(jenkins_url, username=jenkins_username, password=jenkins_password)


def get_secret():
    """
    This method is to get secret value from Secrets Manager
    """
    secret = json.loads(secret_manager.get_secret())
    return secret


def get_pipeline_job(jenkinsObj):
    job = jenkinsObj["restricted-mxnet-cd/mxnet-cd-release-job"]
    return job


def get_latest_build_number(job):
    return job.get_last_build().get_number()


def get_build_from_build_number(job, build_number):
    return job.get_build(build_number)


def get_build_timestamp(build):
    return build.get_timestamp()


def get_build_date(timestamp):
    return timestamp.date()


def is_latest_day_build(current_build, latest_build):
    current_build_timestamp = get_build_timestamp(current_build)
    latest_build_timestamp = get_build_timestamp(latest_build)
    # if 2 builds are on the same day
    current_build_date = get_build_date(current_build_timestamp)
    latest_build_date = get_build_date(latest_build_timestamp)
    if(current_build_date == latest_build_date):
        return True
    else:
        return False


def get_latest_day_builds(job, latest_build_number):
    latest_build = get_build_from_build_number(job, latest_build_number)
    builds = [latest_build]
    current_build_number = latest_build_number-1
    while True:
        current_build = get_build_from_build_number(job, current_build_number)
        if is_latest_day_build(current_build, latest_build):
            builds.append(current_build)
            current_build_number -= 1
        else:
            break
    return builds


def get_release_job_type(build):
    return build.get_params()['RELEASE_JOB_TYPE']


def filter_by_desired_release_job_type(latest_day_builds, desired_release_job_type):
    filtered_builds = []
    for build in latest_day_builds:
        if get_release_job_type(build) in desired_release_job_type:
            filtered_builds.append(build)
    return filtered_builds


def status_check(builds):
    for build in builds:
        if build.get_status() == 'SUCCESS':
            logging.info(f'Successful build {get_release_job_type(build)} {build.get_number()}')
        else:
            logging.info(f'Failure build {get_release_job_type(build)} {build.get_number()}')


def get_cause(build):
    return build.get_causes()[0]['_class']


def filter_by_upstream_cause(builds, desired_cause):
    filtered_builds = []
    for build in builds:
        if get_cause(build) == desired_cause:
            filtered_builds.append(build)
    return filtered_builds


def jenkins_pipeline_monitor():
    # retrieve secret from secert manager
    secret = get_secret()
    logging.info(f'Secrets retrieved')
    # get jenkins object
    jenkinsObj = get_jenkins_obj(secret)
    logging.info(f'Jenkins obj created')
    # get relevant pipeline job
    job = get_pipeline_job(jenkinsObj)
    logging.info(f'Job fetch {job}')
    # get the latest build on the pipeline
    latest_build_number = get_latest_build_number(job)

    # get builds scheduled for the latest day
    latest_day_builds = get_latest_day_builds(job, latest_build_number)
    logging.info(f'latest builds {latest_day_builds}')
    # filter latest day builds by desired build type a.k.a release job type
    desired_release_job_type = ['mxnet_lib/static', 'python/pypi']

    filtered_builds = filter_by_desired_release_job_type(latest_day_builds, desired_release_job_type)
    logging.info(f'Builds filtered by desired release job type : {filtered_builds}')

    desired_cause = 'hudson.model.Cause$UpstreamCause'
    filtered_builds = filter_by_upstream_cause(filtered_builds, desired_cause)

    logging.info(f'Filtered builds by {desired_cause} : {filtered_builds}')
    status_check(filtered_builds)


def lambda_handler(event, context):
    try:
        logging.info(f'Lambda handler invoked')
        jenkins_pipeline_monitor()
    except Exception as e:
        logging.error("Lambda raised an exception! %s", exc_info=e)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    lambda_handler(None, None)
