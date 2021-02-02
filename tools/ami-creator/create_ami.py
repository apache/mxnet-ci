#!/usr/bin/env python3

import boto3
import sys, os, subprocess
import time, datetime
import logging
from optparse import OptionParser
import base64, binascii, getpass, optparse, sys
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP, PKCS1_v1_5

ec2Client = boto3.resource('ec2')

def read_userdata(file):
    logging.info("Reading userdata from file %s", file)
    with open(file, "r") as fh:
        return fh.read()

def create_instance(instance_type, disk_size, userdata_file, ami, security_group, ssh_key):
    logging.info("Creating instance type %s for image creation", instance_type)
    instances = ec2Client.create_instances(
        BlockDeviceMappings=[
            {
                'DeviceName': '/dev/sda1',
                'Ebs': {
                    'DeleteOnTermination': True,
                    'VolumeSize': disk_size,
                    'VolumeType': 'gp2',
                    'Encrypted': False
                }
            }
        ],
        ImageId=ami,
        InstanceType=instance_type,
        KeyName=ssh_key,
        MaxCount=1,
        MinCount=1,
        SecurityGroupIds=[
            security_group
        ],
        UserData=read_userdata(userdata_file),
        InstanceInitiatedShutdownBehavior='stop',
        TagSpecifications=[
            {
                'ResourceType': 'instance',
                'Tags': [
                    { 'Key': 'Name', 'Value': 'ami-builder-tmp-instance' },
                    { 'Key': 'mxnet', 'Value': 'ami-builder' }
                ]
            }
        ]
    )
    logging.info("Created instance %s", instances[0].id)
    logging.info("Public IP: %s", instances[0].public_ip_address)
    logging.info("Platform: %s", instances[0].platform)
    return instances[0]

def decrypt_windows_password(encrypted_password, keyfile):
    with open(keyfile, "r") as fh_key:
        key = RSA.importKey(fh_key.read())
    cipher = PKCS1_v1_5.new(key)
    sentinel = "password decryption failed!!!"
    password = cipher.decrypt(encrypted_password, sentinel)
    #password = password[2:-1]
    return password.decode("utf-8")


def wait_for_instance(instance, private_key):
    instance_id = instance.id
    current_state = instance.state
    logging.info("Waiting for instance to install software and shut down. Current state: %s", instance.state['Name'])
    windows_password = None
    last_log_size = 0
    last_install_log_size = 0
    while (current_state['Code'] != 80):
        time.sleep(20)
        i = ec2Client.Instance(instance_id)
        if current_state['Code'] != i.state['Code']:
            current_state = i.state
            logging.info("Instance state changed to: %s", current_state['Name'])
        if current_state['Name'] == "running" and i.public_ip_address != "none":
            if i.platform == "windows":
                if windows_password == None:
                    logging.debug("Attempting to get password info for instance")
                    try:
                        pwdata = i.password_data()
                        if pwdata['PasswordData'] != '':
                            logging.debug("Got password data, decrypting [%s]", pwdata['PasswordData'])
                            password = decrypt_windows_password(base64.b64decode(pwdata['PasswordData']), private_key)
                            logging.info("Public IP Address: %s", i.public_ip_address)
                            logging.info("Decrypted password: %s", password)
                            windows_password = password
                    except:
                        logging.exception("Unable to get password data for windows instance")
                # attempt to save the latest userdata execute log
                logfile = "log/userdata-{}.log".format(instance_id)
                ret = subprocess.run(["scp","-q","-o","StrictHostKeyChecking=no","-o","ConnectTimeout=10","-i",private_key,"administrator@{}:\"C:\\ProgramData\Amazon\\EC2-Windows\\Launch\\Log\\UserdataExecution.log\"".format(i.public_ip_address),logfile])
                if ret.returncode == 0:
                    if os.stat(logfile).st_size != last_log_size:
                        last_log_size = os.stat(logfile).st_size
                        logging.info("Updated userdata execution log to %s (size=%d)", logfile, last_log_size)
                else:
                    logging.debug("Unable to retrieve userdata log via ssh, does this windows system have sshd installed and running?")
                    continue
                install_logfile = "log/install-{}.log".format(instance_id)
                ret = subprocess.run(["scp","-q","-o","StrictHostKeyChecking=no","-i",private_key,"administrator@{}:\"C:\\install.log\"".format(i.public_ip_address),install_logfile])
                if ret.returncode == 0:
                    if os.stat(install_logfile).st_size != last_install_log_size:
                        last_install_log_size = os.stat(install_logfile).st_size
                        logging.info("Updated install log to %s (size=%d)", install_logfile, last_install_log_size)
            else:
                logging.info("Attempting to get cloud-init output log.")
                os.system("ssh -o StrictHostKeyChecking=no -i {} ubuntu@{} tail -n +0 -f /var/log/cloud-init-output.log 2>/dev/null".format(private_key, i.public_ip_address))
    logging.info("Instance stopped")


def create_ami(name, instance):
    ami_name = "{}-{}".format(name, datetime.datetime.now().strftime("%Y%m%d%H%M"))
    logging.info("Creating AMI from instance, name: %s", ami_name)
    image = instance.create_image(
        Description = "Image auto-created",
        Name = ami_name
    )
    logging.info("Created image %s", image.id)
    return image

def wait_for_ami(image):
    ami_id = image.id
    current_state = image.state
    logging.info("Waiting for AMI to become available")
    while (current_state != 'available'):
        time.sleep(5)
        i = ec2Client.Image(ami_id)
        if current_state != i.state:
            current_state = i.state
            logging.info("Image state changed to %s", current_state)
    logging.info("AMI %s is now available", ami_id)

def terminate_instance(instance):
    logging.info("Terminating instance %s", instance.id)
    instance.terminate()


def main():
    parser = OptionParser()
    parser.add_option("-i", "--instance-type", dest="instance_type",
        help="Instance type to create")
    parser.add_option("-a", "--ami", dest="ami",
        help="AMI to start with")
    parser.add_option("-n", "--name", dest="name",
        help="Prefix to use for AMI name (timestamp will be appended)")
    parser.add_option("-d", "--disk-size", dest="disk_size", type="int",
        default=10, help="Size of disk to use for image creation (in GB)")
    parser.add_option("-s", "--security-group", dest="security_group",
        help="Security group ID for instance")
    parser.add_option("-k", "--key-name", dest="ssh_key",
        help="SSH key pair name to use")
    parser.add_option("-p", "--private-key", dest="private_key",
        help="Private key used to SSH into instance or decrypt windows password")
    parser.add_option("-u", "--userdata", dest="userdata",
        help="UserData file to use")
    parser.add_option("-q", "--quiet",
        action="store_false", dest="verbose", default=True,
        help="don't print status messages to stdout")

    (options, args) = parser.parse_args()

    # ensure required parameters are passed
    if options.instance_type is None:
        logging.error("You must pass --instance-type option")
        sys.exit(-1)
    if options.name is None:
        logging.error("You must pass --name option")
        sys.exit(-1)
    if options.security_group is None:
        logging.error("You must pass --security-group option")
        sys.exit(-1)
    if options.userdata is None:
        logging.error("You must pass --userdata option")
        sys.exit(-1)
    if options.private_key is None:
        logging.error("You must pass --private-key option")
        sys.exit(-1)

    loglev = logging.WARNING
    if options.verbose:
        loglev = logging.INFO
    logging.basicConfig(
        level = loglev,
        format = '%(asctime)s %(levelname)s %(message)s'
    )
    if options.userdata:
        userdata = options.userdata
    else:
        userdata = 'userdata/{}.txt'.format(options.name)



    instance = create_instance(
        instance_type=options.instance_type,
        disk_size=options.disk_size,
        userdata_file=userdata,
        ami=options.ami,
        security_group=options.security_group,
        ssh_key=options.ssh_key
    )
    wait_for_instance(instance, options.private_key)
    image = create_ami(options.name, instance)
    wait_for_ami(image)
    terminate_instance(instance)


main()

