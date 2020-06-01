import os
import boto3
import json
import logging
import secret_manager

from datetime import datetime, timezone
from jenkinsapi.jenkins import Jenkins

logging.getLogger().setLevel(logging.INFO)
logging.getLogger('boto3').setLevel(logging.CRITICAL)
logging.getLogger('botocore').setLevel(logging.CRITICAL)

release_job_type = ['mxnet_lib/static', 'python/pypi']

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


def is_latest_day_build(current_build):
    current_build_timestamp = get_build_timestamp(current_build)
    current_time_stamp = datetime.now().replace(tzinfo=timezone.utc)
    # if current build is within 24 hours of the current time
    seconds_difference = (current_time_stamp-current_build_timestamp).total_seconds()
    hour_difference = divmod(seconds_difference, 3600)[0]
    if(hour_difference < 24):
        return True
    else:
        return False


def get_latest_day_builds(job, latest_build_number):
    """
    Get all the builds that were triggered in the past 24 hours from the current time
    i.e. the time when the Lambda function is triggered
    :param job: Jenkins Job object
    :param latest_build_number: latest build number from which to start checking
    :result: List[builds]
    """
    builds = []
    current_build_number = latest_build_number
    while True:
        current_build = get_build_from_build_number(job, current_build_number)
        if is_latest_day_build(current_build):
            builds.append(current_build)
            current_build_number -= 1
        else:
            break
    return builds


def get_release_job_type(build):
    return build.get_params()['RELEASE_JOB_TYPE']


def filter_by_release_job_type(latest_day_builds):
    filtered_builds = []
    for build in latest_day_builds:
        if get_release_job_type(build) in release_job_type:
            filtered_builds.append(build)
    return filtered_builds


def status_check(builds):
    """
    Check the status of the filtered builds
    i.e. Check if all the required release job types are present in the pipeline
    If there is not a single build from the list of desired release job types, log the failures
    else check the status via Jenkins API and report accordingly
    :param builds
    """
    # dictionary of the type release_job_type: count
    # e.g. {'mxnet_lib/static':0, 'python/pypi':0}
    global release_job_type
    success_count = 0
    release_job_type_dict = {el : 0 for el in release_job_type}

    # iterate over the builds to count number of the desirect release job types
    for build in builds:
        build_release_job_type = get_release_job_type(build)
        if build_release_job_type in release_job_type_dict:
            if build.get_status() == 'SUCCESS':
                logging.info(f'Successful build {build_release_job_type} {build.get_number()}')
            else:
                logging.info(f'Failure build {build_release_job_type} {build.get_number()}')
            release_job_type_dict[build_release_job_type] += 1

    # iterate over the map of release_job_type: count
    # if 'mxnet_lib/static':1 indicates static jobtype job ran in the pipeline
    # else 'mxnet_lib/static':0 indicates static jobtype never ran -> log as failed
    for release_job_type_name, release_job_type_count in release_job_type_dict.items():
        if release_job_type_count == 0:
            logging.info(f'Failure build {release_job_type_name}')
        elif release_job_type_count == 1:
            success_count += 1
        else:
            logging.info(f'{release_job_type} ran {release_job_type_count} times')
    # if success_count = 2 [i.e. len of release_job_type], it means both static & pypi jobs have run
    if success_count == len(release_job_type):
        logging.info(f'All the required jobs ran')
    else:
        logging.info(f'1/more of the required jobs did not run')


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
    filtered_builds = filter_by_release_job_type(latest_day_builds)
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
