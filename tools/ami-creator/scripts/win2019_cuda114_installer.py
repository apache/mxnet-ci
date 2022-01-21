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


"""Dependency installer for Windows"""

__author__ = 'Pedro Larroy, Chance Bair, Joe Evans'
__version__ = '0.4'

import argparse
import errno
import logging
import os
import psutil
import shutil
import subprocess
import urllib
import stat
import tempfile
import zipfile
from time import sleep
from urllib.error import HTTPError
import logging
from subprocess import check_output, check_call, call
import re
import sys
import urllib.request
import contextlib
import glob

import ssl

ssl._create_default_https_context = ssl._create_unverified_context

log = logging.getLogger(__name__)


DEPS = {
    'openblas': 'https://windows-post-install.s3-us-west-2.amazonaws.com/OpenBLAS-windows-v0_2_19.zip',
    'opencv': 'https://windows-post-install.s3-us-west-2.amazonaws.com/opencv-windows-4.1.2-vc14_vc15.zip',
    'cudnn8': 'https://windows-post-install.s3-us-west-2.amazonaws.com/cudnn-11.4-windows-x64-v8.2.4.15.zip',
    'perl': 'http://strawberryperl.com/download/5.30.1.1/strawberry-perl-5.30.1.1-64bit.msi',
    'clang': 'https://github.com/llvm/llvm-project/releases/download/llvmorg-9.0.1/LLVM-9.0.1-win64.exe',
}

DEFAULT_SUBPROCESS_TIMEOUT = 3600


@contextlib.contextmanager
def remember_cwd():
    '''
    Restore current directory when exiting context
    '''
    curdir = os.getcwd()
    try:
        yield
    finally:
        os.chdir(curdir)


def retry(target_exception, tries=4, delay_s=1, backoff=2):
    """Retry calling the decorated function using an exponential backoff.

    http://www.saltycrane.com/blog/2009/11/trying-out-retry-decorator-python/
    original from: http://wiki.python.org/moin/PythonDecoratorLibrary#Retry

    :param target_exception: the exception to check. may be a tuple of
        exceptions to check
    :type target_exception: Exception or tuple
    :param tries: number of times to try (not retry) before giving up
    :type tries: int
    :param delay_s: initial delay between retries in seconds
    :type delay_s: int
    :param backoff: backoff multiplier e.g. value of 2 will double the delay
        each retry
    :type backoff: int
    """
    import time
    from functools import wraps

    def decorated_retry(f):
        @wraps(f)
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay_s
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                except target_exception as e:
                    logging.warning("Exception: %s, Retrying in %d seconds...", str(e), mdelay)
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return f(*args, **kwargs)

        return f_retry  # true decorator

    return decorated_retry


@retry((ValueError, OSError, HTTPError), tries=5, delay_s=2, backoff=5)
def download(url, dest=None, progress=False) -> str:
    from urllib.request import urlopen
    from urllib.parse import (urlparse, urlunparse)
    import progressbar
    import http.client

    class ProgressCB():
        def __init__(self):
            self.pbar = None

        def __call__(self, block_num, block_size, total_size):
            if not self.pbar and total_size > 0:
                self.pbar = progressbar.bar.ProgressBar(max_value=total_size)
            downloaded = block_num * block_size
            if self.pbar:
                if downloaded < total_size:
                    self.pbar.update(downloaded)
                else:
                    self.pbar.finish()
    if dest and os.path.isdir(dest):
        local_file = os.path.split(urlparse(url).path)[1]
        local_path = os.path.normpath(os.path.join(dest, local_file))
    else:
        local_path = dest
    with urlopen(url) as c:
        content_length = c.getheader('content-length')
        length = int(content_length) if content_length and isinstance(c, http.client.HTTPResponse) else None
        if length and local_path and os.path.exists(local_path) and os.stat(local_path).st_size == length:
            log.debug(f"download('{url}'): Already downloaded.")
            return local_path
    log.debug(f"download({url}, {local_path}): downloading {length} bytes")
    if local_path:
        with tempfile.NamedTemporaryFile(delete=False) as tmpfd:
            urllib.request.urlretrieve(url, filename=tmpfd.name, reporthook=ProgressCB() if progress else None)
            shutil.move(tmpfd.name, local_path)
    else:
        (local_path, _) = urllib.request.urlretrieve(url, reporthook=ProgressCB())
    log.debug(f"download({url}, {local_path}'): done.")
    return local_path


# Takes arguments and runs command on host.  Shell is disabled by default.
# TODO: Move timeout to args
def run_command(*args, shell=False, timeout=DEFAULT_SUBPROCESS_TIMEOUT, **kwargs):
    try:
        logging.info("Issuing command: {}".format(args))
        res = subprocess.check_output(*args, shell=shell, timeout=timeout).decode("utf-8").replace("\r\n", "\n")
        logging.info("Output: {}".format(res))
    except subprocess.CalledProcessError as e:
        raise RuntimeError("command '{}' return with error (code {}): {}".format(e.cmd, e.returncode, e.output))
    return res


# Copies source directory recursively to destination.
def copy(src, dest):
    try:
        shutil.copytree(src, dest)
        logging.info("Moved {} to {}".format(src, dest))
    except OSError as e:
        # If the error was caused because the source wasn't a directory
        if e.errno == errno.ENOTDIR:
            shutil.copy(src, dest)
            logging.info("Moved {} to {}".format(src, dest))
        else:
            raise RuntimeError("copy return with error: {}".format(e))


# Workaround for windows readonly attribute error
def on_rm_error(func, path, exc_info):
    # path contains the path of the file that couldn't be removed
    # let's just assume that it's read-only and unlink it.
    os.chmod(path, stat.S_IWRITE)
    os.unlink(path)


def reboot_system():
    logging.info("Rebooting system now...")
    run_command("shutdown -r -t 5")
    exit(0)


def shutdown_system():
    logging.info("Shutting down system now...")
    # wait 20 sec so we can capture the install logs
    run_command("shutdown -s -t 20")
    exit(0)

def install_vs():
    if os.path.exists("C:\\Program Files (x86)\\Microsoft Visual Studio\\2019"):
        logging.info("MSVS already installed, skipping.")
        return False
    # Visual Studio 2019
    # Components: https://docs.microsoft.com/en-us/visualstudio/install/workload-component-id-vs-community?view=vs-2019#visual-studio-core-editor-included-with-visual-studio-community-2019
    logging.info("Installing Visual Studio 2019...")
    vs_file_path = download('https://windows-post-install.s3-us-west-2.amazonaws.com/vs_community__1246179388.1585201415.exe')
    run_command("PowerShell Rename-Item -Path {} -NewName \"{}.exe\"".format(vs_file_path,
                                                                             vs_file_path.split('\\')[-1]), shell=True)
    vs_file_path = vs_file_path + '.exe'
    logging.info("Installing VisualStudio 2019.....")
    ret = call(vs_file_path +
               ' --add Microsoft.VisualStudio.Workload.ManagedDesktop'
               ' --add Microsoft.VisualStudio.Workload.NetCoreTools'
               ' --add Microsoft.VisualStudio.Workload.NetWeb'
               ' --add Microsoft.VisualStudio.Workload.Node'
               ' --add Microsoft.VisualStudio.Workload.Office'
               ' --add Microsoft.VisualStudio.Component.TypeScript.2.0'
               ' --add Microsoft.VisualStudio.Component.TestTools.WebLoadTest'
               ' --add Component.GitHub.VisualStudio'
               ' --add Microsoft.VisualStudio.ComponentGroup.NativeDesktop.Core'
               ' --add Microsoft.VisualStudio.Component.Static.Analysis.Tools'
               ' --add Microsoft.VisualStudio.Component.VC.CMake.Project'
               ' --add Microsoft.VisualStudio.Component.VC.140'
               ' --add Microsoft.VisualStudio.Component.VC.14.28.x86.x64'
               ' --add Microsoft.VisualStudio.Component.Windows10SDK.18362.Desktop'
               ' --add Microsoft.VisualStudio.Component.Windows10SDK.18362.UWP'
               ' --add Microsoft.VisualStudio.Component.Windows10SDK.18362.UWP.Native'
               ' --add Microsoft.VisualStudio.ComponentGroup.Windows10SDK.18362'
               ' --add Microsoft.VisualStudio.Component.Windows10SDK.16299'
               ' --wait'
               ' --passive'
               ' --norestart'
               )

    if ret == 3010 or ret == 0:
        # 3010 is restart required
        logging.info("VS install successful.")
    else:
        raise RuntimeError("VS failed to install, exit status {}".format(ret))

    # Workaround for --wait sometimes ignoring the subprocesses doing component installs
    def vs_still_installing():
        return {'vs_installer.exe', 'vs_installershell.exe', 'vs_setup_bootstrapper.exe'} & set(map(lambda process: process.name(), psutil.process_iter()))
    timer = 0
    while vs_still_installing() and timer < DEFAULT_SUBPROCESS_TIMEOUT:
        logging.warning("VS installers still running for %d s", timer)
        if timer % 60 == 0:
            logging.info("Waiting for Visual Studio to install for the last {} seconds".format(str(timer)))
        sleep(1)
        timer += 1
    if vs_still_installing():
        logging.warning("VS install still running after timeout (%d)", DEFAULT_SUBPROCESS_TIMEOUT)
    else:
        logging.info("Visual studio install complete.")
    return True


def install_perl():
    if os.path.exists("C:\\Strawberry\\perl\\bin\\perl.exe"):
        logging.info("Perl already installed, skipping.")
        return False
    logging.info("Installing Perl")
    with tempfile.TemporaryDirectory() as tmpdir:
        perl_file_path = download(DEPS['perl'], tmpdir)
        check_call(['msiexec ', '/n', '/passive', '/i', perl_file_path])
    logging.info("Perl install complete")
    return True


def install_clang():
    if os.path.exists("C:\\Program Files\\LLVM"):
        logging.info("Clang already installed, skipping.")
        return False
    logging.info("Installing Clang")
    with tempfile.TemporaryDirectory() as tmpdir:
        clang_file_path = download(DEPS['clang'], tmpdir)
        run_command(clang_file_path + " /S /D=C:\\Program Files\\LLVM")
    logging.info("Clang install complete")
    return True


def install_openblas():
    if os.path.exists("C:\\Program Files\\OpenBLAS-windows-v0_2_19"):
        logging.info("OpenBLAS already installed, skipping.")
        return False
    logging.info("Installing OpenBLAS")
    local_file = download(DEPS['openblas'])
    with zipfile.ZipFile(local_file, 'r') as zip:
        zip.extractall("C:\\Program Files")
    run_command("PowerShell Set-ItemProperty -path 'hklm:\\system\\currentcontrolset\\control\\session manager\\environment' -Name OpenBLAS_HOME -Value 'C:\\Program Files\\OpenBLAS-windows-v0_2_19'")
    logging.info("Openblas Install complete")
    return True


def install_mkl():
    if os.path.exists("C:\\Program Files (x86)\\IntelSWTools"):
        logging.info("Intel MKL already installed, skipping.")
        return False
    logging.info("Installing MKL 2019.3.203...")
    file_path = download("http://registrationcenter-download.intel.com/akdlm/irc_nas/tec/15247/w_mkl_2019.3.203.exe")
    run_command("{} --silent --remove-extracted-files yes --a install -output=C:\mkl-install-log.txt -eula=accept".format(file_path))
    logging.info("MKL Install complete")
    return True


def install_opencv():
    if os.path.exists("C:\\Program Files\\opencv"):
        logging.info("OpenCV already installed, skipping.")
        return False
    logging.info("Installing OpenCV")
    with tempfile.TemporaryDirectory() as tmpdir:
        local_file = download(DEPS['opencv'])
        with zipfile.ZipFile(local_file, 'r') as zip:
            zip.extractall(tmpdir)
        copy(f'{tmpdir}\\opencv\\build', r'c:\Program Files\opencv')

    run_command("PowerShell Set-ItemProperty -path 'hklm:\\system\\currentcontrolset\\control\\session manager\\environment' -Name OpenCV_DIR -Value 'C:\\Program Files\\opencv'")
    logging.info("OpenCV install complete")
    return True

def install_cudnn8():
    cuda_root_path = "C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v11.4"
    if os.path.exists(cuda_root_path + "\\bin\\cudnn64_8.dll"):
        logging.info("cuDNN8 already installed, skipping.")
        return False
    # cuDNN
    logging.info("Installing cuDNN8")
    with tempfile.TemporaryDirectory() as tmpdir:
        local_file = download(DEPS['cudnn8'])
        logging.info("Extracting cuDNN archive.")
        with zipfile.ZipFile(local_file, 'r') as zip:
            zip.extractall(tmpdir)
        logging.info("Copying cuDNN distribution files.")
        for f in glob.glob(tmpdir+"\\cuda\\bin\\*"):
            copy(f, cuda_root_path + "\\bin")
        for f in glob.glob(tmpdir+"\\cuda\\include\\*.h"):
            copy(f, cuda_root_path + "\\include")
        for f in glob.glob(tmpdir+"\\cuda\\lib\\x64\\*"):
            copy(f, cuda_root_path + "\\lib\\x64")
    logging.info("cuDNN8 install complete")
    return True

def instance_family():
    return urllib.request.urlopen('http://instance-data/latest/meta-data/instance-type').read().decode().split('.')[0]

def install_cuda114():
    if os.path.exists("C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v11.4\\bin"):
        logging.info("CUDA 11.4 already installed, skipping.")
        return False
    logging.info("Downloadinng CUDA 11.4...")
    cuda_file_path = download(
        'https://windows-post-install.s3-us-west-2.amazonaws.com/cuda_11.4.2_win10_network.exe')
    try:
        check_call("PowerShell Rename-Item -Path {} -NewName \"{}.exe\"".format(cuda_file_path,
                                                                            cuda_file_path.split('\\')[-1]), shell=True)
    except subprocess.CalledProcessError as e:
        logging.exception("Rename file failed")
    cuda_file_path = cuda_file_path + '.exe'
    logging.info("Installing CUDA 11.4...")
    check_call(cuda_file_path + ' -s')
    logging.info("Done installing CUDA 11.4.")
    return True

def schedule_aws_userdata():
    logging.info("Scheduling AWS init so userdata will run on next boot...")
    run_command("PowerShell C:\\ProgramData\\Amazon\\EC2-Windows\\Launch\\Scripts\\InitializeInstance.ps1 -Schedule")

def add_paths():
    # TODO: Add python paths (python -> C:\\Python37\\python.exe, python2 -> C:\\Python27\\python.exe)
    logging.info("Adding Windows Kits to PATH...")
    current_path = run_command(
        "PowerShell (Get-Itemproperty -path 'hklm:\\system\\currentcontrolset\\control\\session manager\\environment' -Name Path).Path")
    current_path = current_path.rstrip()
    logging.debug("current_path: {}".format(current_path))
    new_path = current_path + \
        ";C:\\Program Files (x86)\\Windows Kits\\10\\bin\\10.0.16299.0\\x86;C:\\Program Files\\OpenBLAS-windows-v0_2_19\\bin;C:\\Program Files\\LLVM\\bin;C:\\Program Files\\opencv\\bin;C:\\Program Files\\opencv\\x64\\vc15\\bin"
    logging.debug("new_path: {}".format(new_path))
    run_command("PowerShell Set-ItemProperty -path 'hklm:\\system\\currentcontrolset\\control\\session manager\\environment' -Name Path -Value '" + new_path + "'")


def script_name() -> str:
    """:returns: script name with leading paths removed"""
    return os.path.split(sys.argv[0])[1]

def remove_install_task():
    logging.info("Removing stage2 startup task...")
    run_command("PowerShell Unregister-ScheduledTask -TaskName 'Stage2Install' -Confirm:$false")


def main():
    logging.getLogger().setLevel(os.environ.get('LOGLEVEL', logging.DEBUG))
    logging.basicConfig(filename="C:\\install.log", format='{}: %(asctime)sZ %(levelname)s %(message)s'.format(script_name()))

    # install all necessary software and reboot after some components

    # for CUDA, the last version you install will be the default, based on PATH variable
    if install_cuda114():
        reboot_system()
    install_cudnn8()
    if install_vs():
        reboot_system()
    install_openblas()
    install_mkl()
    install_opencv()
    install_perl()
    install_clang()
    add_paths()
    remove_install_task()
    schedule_aws_userdata()
    shutdown_system()


if __name__ == "__main__":
    exit(main())
