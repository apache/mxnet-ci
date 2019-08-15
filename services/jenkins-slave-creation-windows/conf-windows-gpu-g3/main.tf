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

variable "document_name" {}

variable "source_ami_id" {}

variable "iam_instance_profile_name" {}

variable "automation_assume_role" {}

variable "target_ami_name" {}

variable "instance_type" {}

variable "ebs_volume_size" {}

variable "post_update_script_s3" {}

variable "post_update_script_key" {}

variable "post_update_script_path" {}

variable "slave_autoconnect_python_s3" {}

variable "slave_autoconnect_python_path" {}

variable "slave_autoconnect_python_key" {}

variable "slave_autoconnect_bat_s3" {}

variable "slave_autoconnect_bat_path" {}

variable "slave_autoconnect_bat_key" {}

variable "cudnn_install_s3" {}

variable "cudnn_install_key" {}

variable "cudnn_install_path" {}

resource "aws_ssm_document" "UpdateWindowsAMIGPU" {
  name          = "${var.document_name}"
  document_type = "Automation"

  content = <<DOC
{
  "schemaVersion": "0.3",
  "description": "Updates the Microsoft Windows AMI. By default it will install all Windows updates, Amazon software, and Amazon drivers. It will then sysprep and create a new AMI. Supports Windows Server 2008 R2 and greater.",
  "assumeRole": "{{ AutomationAssumeRole }}",
  "parameters": {
    "SourceAmiId": {
      "type": "String",
      "description": "(Required) The source Amazon Machine Image ID.",
      "default": "${var.source_ami_id}"
    },
    "IamInstanceProfileName": {
      "type": "String",
      "description": "(Required) The name of the role that enables Systems Manager to manage the instance.",
      "default": "${var.iam_instance_profile_name}"
    },
    "AutomationAssumeRole": {
      "type": "String",
      "description": "(Required) The ARN of the role that allows Automation to perform the actions on your behalf.",
      "default": "${var.automation_assume_role}"
    },
    "TargetAmiName": {
      "type": "String",
      "description": "(Optional) The name of the new AMI that will be created. Default is a system-generated string including the source AMI id and the creation time and date.",
      "default": "${var.target_ami_name}"
    },
    "InstanceType": {
      "type": "String",
      "description": "(Optional) Type of instance to launch as the workspace host. Instance types vary by region. Default is t2.medium.",
      "default": "${var.instance_type}"
    },
    "EBSVolumeSize": {
      "type": "String",
      "description": "(Optional) Size of EBS volume.",
      "default": "${var.ebs_volume_size}"
    },
    "PostUpdateScriptS3": {
      "type": "String",
      "description": "(Required) Location of the S3 script for MXNet dependency installs.",
      "default": "${var.post_update_script_s3}"
    },
    "PostUpdateScriptKey": {
      "type": "String",
      "description": "(Required) Name of the S3 script for MXNet dependency install.",
      "default": "${var.post_update_script_key}"
    },
    "PostUpdateScriptPath": {
      "type": "String",
      "description": "(Required) Destination path of the S3 script for MXNet dependency install.",
      "default": "${var.post_update_script_path}"
    },
    "SlaveAutoconnectPythonS3": {
      "type": "String",
      "description": "(Required) Location of the S3 script for Jenkins Autoconnect.",
      "default": "${var.slave_autoconnect_python_s3}"
    },
    "SlaveAutoconnectPythonKey": {
      "type": "String",
      "description": "(Required) Name of the S3 Bat script to trigger the Jenkins Autoconnect script.",
      "default": "${var.slave_autoconnect_python_key}"
    },
    "SlaveAutoconnectPythonPath": {
      "type": "String",
      "description": "(Required) Destination path of the S3 script for Jenkins Autoconnect.",
      "default": "${var.slave_autoconnect_python_path}"
    },
    "SlaveAutoconnectBatS3": {
      "type": "String",
      "description": "(Required) Location of the S3 Bat script to trigger the Jenkins Autoconnect script.",
      "default": "${var.slave_autoconnect_bat_s3}"
    },
    "SlaveAutoconnectBatPath": {
      "type": "String",
      "description": "(Required) Destination path of the S3 Bat script to trigger the Jenkins Autoconnect script.",
      "default": "${var.slave_autoconnect_bat_path}"
    },
    "SlaveAutoconnectBatKey": {
      "type": "String",
      "description": "(Required) Name of the S3 Bat script to trigger the Jenkins Autoconnect script.",
      "default": "${var.slave_autoconnect_bat_key}"
    },
    "CudnnInstallZipS3": {
      "type": "String",
      "description": "(Required) Location of the cuDNN install zip.",
      "default": "${var.cudnn_install_s3}"
    },
    "CudnnInstallZipPath": {
      "type": "String",
      "description": "(Required) Destination path of the cuDNN install zip.",
      "default": "${var.cudnn_install_path}"
    },
    "CudnnInstallZipKey": {
      "type": "String",
      "description": "(Required) Name of the cuDNN install zip.",
      "default": "${var.cudnn_install_key}"
    },
    "SubnetId": {
      "type": "String",
      "description": "(Optional) Specify the SubnetId if you want to launch into a specific subnet.",
      "default": ""
    },
    "IncludeKbs": {
      "type": "String",
      "description": "(Optional) Specify one or more Microsoft Knowledge Base (KB) article IDs to include. You can install multiple IDs using comma-separated values. Valid formats: KB9876543 or 9876543.",
      "default": ""
    },
    "ExcludeKbs": {
      "type": "String",
      "description": "(Optional) Specify one or more Microsoft Knowledge Base (KB) article IDs to exclude. You can exclude multiple IDs using comma-separated values. Valid formats: KB9876543 or 9876543.",
      "default": ""
    },
    "Categories": {
      "type": "String",
      "description": "(Optional) Specify one or more update categories. You can filter categories using comma-separated values. Options: Application, Connectors, CriticalUpdates, DefinitionUpdates, DeveloperKits, Drivers, FeaturePacks, Guidance, Microsoft, SecurityUpdates, ServicePacks, Tools, UpdateRollups, Updates. Valid formats include a single entry, for example: CriticalUpdates. Or you can specify a comma separated list: CriticalUpdates,SecurityUpdates. NOTE: There cannot be any spaces around the commas.",
      "default": ""
    },
    "SeverityLevels": {
      "type": "String",
      "description": "(Optional) Specify one or more MSRC severity levels associated with an update. You can filter severity levels using comma-separated values. By default patches for all security levels are selected. If value supplied, the update list is filtered by those values. Options: Critical, Important, Low, Moderate or Unspecified. Valid formats include a single entry, for example: Critical. Or, you can specify a comma separated list: Critical,Important,Low.",
      "default": ""
    },
    "PublishedDaysOld": {
      "type": "String",
      "default": "",
      "description": "(Optional) Specify the amount of days old the updates must be from the published date.  For example, if 10 is specified, any updates that were found during the Windows Update search that have been published 10 or more days ago will be returned."
    },
    "PublishedDateAfter": {
      "type": "String",
      "default": "",
      "description": "(Optional) Specify the date that the updates should be published after.  For example, if 01/01/2017 is specified, any updates that were found during the Windows Update search that have been published on or after 01/01/2017 will be returned."
    },
    "PublishedDateBefore": {
      "type": "String",
      "default": "",
      "description": "(Optional) Specify the date that the updates should be published before.  For example, if 01/01/2017 is specified, any updates that were found during the Windows Update search that have been published on or before 01/01/2017 will be returned."
    },
    "PreUpdateScript": {
      "type": "String",
      "description": "(Optional) A script provided as a string. It will execute prior to installing OS updates.",
      "default": ""
    }
  },
  "mainSteps": [
    {
      "name": "LaunchInstance",
      "action": "aws:runInstances",
      "timeoutSeconds": 1800,
      "maxAttempts": 3,
      "onFailure": "Abort",
      "inputs": {
        "ImageId": "{{ SourceAmiId  }}",
        "InstanceType": "{{ InstanceType }}",
        "MinInstanceCount": 1,
        "MaxInstanceCount": 1,
        "IamInstanceProfileName": "{{ IamInstanceProfileName }}",
        "SubnetId": "{{ SubnetId }}",
        "BlockDeviceMappings": [{
          "DeviceName": "/dev/sda1",
          "Ebs": {
            "VolumeSize": "{{ EBSVolumeSize }}"
          }
        }],
        "SecurityGroupIds": ["sg-REDACTED","sg-REDACTED"],
        "KeyName": "REDACTED"
      }
    },
    {
      "name": "OSCompatibilityCheck",
      "action": "aws:runCommand",
      "maxAttempts": 3,
      "onFailure": "Abort",
      "timeoutSeconds": 7200,
      "inputs": {
        "DocumentName": "AWS-RunPowerShellScript",
        "InstanceIds": [
          "{{LaunchInstance.InstanceIds}}"
        ],
        "Parameters": {
          "executionTimeout": "7200",
          "commands": [
            "[System.Version]$osversion = [System.Environment]::OSVersion.Version",
            "if(($osversion.Major -eq 6 -and $osversion.Minor -ge 1) -or ($osversion.Major -ge 10)) {",
            "  Write-Host 'This OS is supported for use with this automation document.'",
            "} else {",
            "  Write-Host 'This OS is not supported for use with this automation document.'",
            "  exit -1",
            "}"
          ]
        }
      }
    },
    {
      "name": "RunPreUpdateScript",
      "action": "aws:runCommand",
      "maxAttempts": 3,
      "onFailure": "Abort",
      "timeoutSeconds": 1800,
      "inputs": {
        "DocumentName": "AWS-RunPowerShellScript",
        "InstanceIds": [
          "{{ LaunchInstance.InstanceIds }}"
        ],
        "Parameters": {
          "commands": "{{ PreUpdateScript }}"
        }
      }
    },
    {
      "name": "UpdateEC2Config",
      "action": "aws:runCommand",
      "maxAttempts": 3,
      "onFailure": "Abort",
      "timeoutSeconds": 7200,
      "inputs": {
        "DocumentName": "AWS-RunPowerShellScript",
        "InstanceIds": [
          "{{ LaunchInstance.InstanceIds }}"
        ],
        "Parameters": {
          "commands": [
            "$zipFilename = 'AWSUpdateWindowsInstance_1_4_3_1.zip'",
            "$zipFileHash = '9FC935717FFC2CB5476B06DFAC07B6133F483AE5402CAE8035F39A2D74FBB1BF'",
            "$moduleName = 'AWSUpdateWindowsInstance'",
            "$tempPath = $env:TEMP",
            "$moduleDirectory = Join-Path $tempPath -ChildPath $moduleName",
            "$moduleZipFilePath = Join-Path $tempPath -ChildPath $zipFilename",
            "$moduleManifestPath = Join-Path $moduleDirectory -ChildPath ('{0}.psd1' -f $moduleName)",
            "[string[]] $includeList = ('{{ IncludeKbs }}').Split(',',[System.StringSplitOptions]::RemoveEmptyEntries)",
            "[string[]] $excludeList = ('{{ ExcludeKbs }}').Split(',',[System.StringSplitOptions]::RemoveEmptyEntries)",
            "[string[]] $categoryList = ('{{ Categories }}').Split(',',[System.StringSplitOptions]::RemoveEmptyEntries)",
            "[string[]] $severityLevelList = ('{{ SeverityLevels }}').Split(',',[System.StringSplitOptions]::RemoveEmptyEntries)",
            "[string]$publishedDateAfter = '{{ PublishedDateAfter }}'",
            "[string]$publishedDateBefore = '{{ PublishedDateBefore }}'",
            "[string]$publishedDaysOld = '{{ PublishedDaysOld }}'",
            "",
            "$ssmAgentService = Get-ItemProperty 'HKLM:SYSTEM\\CurrentControlSet\\Services\\AmazonSSMAgent\\' -ErrorAction SilentlyContinue",
            "if($ssmAgentService -and $ssmAgentService.Version -ge '2.0.533.0') {",
            "  $region = $env:AWS_SSM_REGION_NAME",
            "}",
            "",
            "if(-not $region) {",
            "  try {",
            "    $identityDocumentUrl = 'http://169.254.169.254/latest/dynamic/instance-identity/document'",
            "    $region = ((Invoke-WebRequest -UseBasicParsing -uri $identityDocumentUrl).Content | ConvertFrom-Json).region",
            "  } catch {",
            "    $region = 'us-east-1'",
            "  }",
            "}",
            "",
            "function Main {",
            "  Test-PreCondition",
            "  Clear-WindowsUpdateModule",
            "  Get-WindowsUpdateModule",
            "  Expand-WindowsUpdateModule",
            "  if ([Environment]::OSVersion.Version.Major -ge 10) {",
            "    Invoke-UpdateEC2Launch",
            "  } else {",
            "    Invoke-UpdateEC2Config",
            "  }",
            "}",
            "",
            "function Test-PreCondition {",
            "  try {",
            "    $osversion = [Environment]::OSVersion.Version",
            "    if ($osversion.Major -le 5) {",
            "      Write-Host 'This document is not supported on Windows Server 2003 or earlier.'",
            "      Exit -1",
            "    }",
            "",
            "    if ($osversion.Version -ge '10.0') {",
            "      $sku = (Get-CimInstance -ClassName Win32_OperatingSystem).OperatingSystemSKU",
            "      if ($sku -eq 143 -or $sku -eq 144) {",
            "        Write-Host 'This document is not supported on Windows 2016 Nano Server.'",
            "        Exit -1",
            "      }",
            "    }",
            "  } catch {",
            "    Write-Host 'Executing Test-PreCondition resulted in error: $($_)'",
            "    Exit -1",
            "  }",
            "}",
            "",
            "function Clear-WindowsUpdateModule {",
            "  try {",
            "    if (Test-Path $moduleDirectory) {",
            "      Remove-Item $moduleDirectory -Force -Recurse",
            "    }",
            "    if (Test-Path $moduleZipFilePath) {",
            "      Remove-Item $moduleZipFilePath -Force",
            "    }",
            "  } catch {",
            "    Write-Host \"Cleaning Windows update module resulted in error: $($_)\"",
            "  }",
            "}",
            "",
            "function Get-WindowsUpdateModule {",
            "  try {",
            "    if ($region.StartsWith('cn-')) {",
            "      $s3Location = 'https://s3.{0}.amazonaws.com.cn/aws-windows-downloads-{0}/PSModules/AWSUpdateWindowsInstance/{1}'",
            "    } elseif($region.StartsWith('us-gov-')) {",
            "      $s3Location = 'https://s3-fips-{0}.amazonaws.com/aws-windows-downloads-{0}/PSModules/AWSUpdateWindowsInstance/{1}'",
            "    } elseif($region -eq 'us-east-1') {",
            "      $s3Location = 'https://s3.amazonaws.com/aws-windows-downloads-{0}/PSModules/AWSUpdateWindowsInstance/{1}'",
            "    } else {",
            "      $s3Location = 'https://aws-windows-downloads-{0}.s3.amazonaws.com/PSModules/AWSUpdateWindowsInstance/{1}'",
            "    }",
            "",
            "    $source = $s3Location -f $region, $zipFilename",
            "    $moduleLocalPath = Join-Path $tempPath -ChildPath $zipFilename",
            "    Start-BitsTransfer -Source $source -Destination $moduleLocalPath",
            "",
            "    $fileStream = New-Object System.IO.FileStream($moduleLocalPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read)",
            "    $sha256 = [System.Security.Cryptography.HashAlgorithm]::Create('System.Security.Cryptography.SHA256CryptoServiceProvider')",
            "    $currentHash = [System.BitConverter]::ToString($sha256.ComputeHash($fileStream), 0).Replace('-', '').ToLowerInvariant()",
            "    $sha256.Dispose()",
            "    $fileStream.Dispose()",
            "",
            "    if ($currentHash -ne $zipFileHash) {",
            "      Write-Host 'The SHA hash of the module does not match the expected value.'",
            "      Exit -1",
            "    }",
            "  } catch {",
            "    Write-Host ('Error encountered while getting the module: {0}.' -f $_.Exception.Message)",
            "    Exit -1",
            "  }",
            "}",
            "",
            "function Expand-WindowsUpdateModule {",
            "  try {",
            "    [System.Reflection.Assembly]::LoadWithPartialName('System.IO.Compression.FileSystem') | Out-Null",
            "    $zip = [System.IO.Compression.ZipFile]::OpenRead($moduleZipFilePath)",
            "    foreach ($item in $zip.Entries) {",
            "      $extractPath = Join-Path $tempPath -ChildPath $item.FullName",
            "      if ($item.Length -eq 0) {",
            "        if (-not (Test-Path $extractPath)) {",
            "          New-Item $extractPath -ItemType Directory | Out-Null",
            "        }",
            "      } else {",
            "        $parentPath = Split-Path $extractPath",
            "        if (-not (Test-Path $parentPath)) {",
            "          New-Item $parentPath -ItemType Directory | Out-Null",
            "        }",
            "        [System.IO.Compression.ZipFileExtensions]::ExtractToFile($item, $extractPath, $true)",
            "      }",
            "    }",
            "  } catch {",
            "    Write-Host ('Error encountered when extracting module file: {0}.' -f $_.Exception.Message)",
            "    Exit -1",
            "  } finally {",
            "    $zip.Dispose()",
            "  }",
            "}",
            "",
            "function Invoke-UpdateEC2Config {",
            "  try {",
            "    Import-Module $moduleManifestPath",
            "    $command = \"Install-AwsUwiEC2Config -Region $region\"",
            "    if($id) { $command += \" -Id $($id)\"}",
            "    Invoke-Expression $command",
            "  } catch {",
            "    Write-Host 'Executing Invoke-AwsUwiEC2Config resulted in error: $($_)'",
            "    Exit -1",
            "  }",
            "}",
            "",
            "function Invoke-UpdateEC2Launch {",
            "  try {",
            "    Import-Module $moduleManifestPath",
            "    $command = 'Install-AwsUwiEC2Launch'",
            "    if($id) { $command += \" -Id $($id)\" }",
            "    Invoke-Expression $command",
            "  } catch {",
            "    Write-Host 'Executing Invoke-AwsUwiEC2Launch resulted in error: $($_)'",
            "    Exit -1",
            "  }",
            "}",
            "",
            "Main"
          ]
        }
      }
    },
    {
      "name": "UpdateSSMAgent",
      "action": "aws:runCommand",
      "maxAttempts": 3,
      "onFailure": "Abort",
      "timeoutSeconds": 600,
      "inputs": {
        "DocumentName": "AWS-UpdateSSMAgent",
        "InstanceIds": [
          "{{ LaunchInstance.InstanceIds }}"
        ],
        "Parameters": {
          "allowDowngrade": "false"
        }
      }
    },
    {
      "name": "UpdateAWSPVDriver",
      "action": "aws:runCommand",
      "maxAttempts": 3,
      "onFailure": "Abort",
      "timeoutSeconds": 600,
      "inputs": {
        "DocumentName": "AWS-ConfigureAWSPackage",
        "InstanceIds": [
          "{{LaunchInstance.InstanceIds}}"
        ],
        "Parameters": {
          "name": "AWSPVDriver",
          "action": "Install"
        }
      }
    },
    {
      "name": "UpdateAWSEnaNetworkDriver",
      "action": "aws:runCommand",
      "maxAttempts": 3,
      "onFailure": "Abort",
      "timeoutSeconds": 600,
      "inputs": {
        "DocumentName": "AWS-ConfigureAWSPackage",
        "InstanceIds": [
          "{{LaunchInstance.InstanceIds}}"
        ],
        "Parameters": {
          "name": "AwsEnaNetworkDriver",
          "action": "Install"
        }
      }
    },
    {
      "name": "UpdateAWSNVMe",
      "action": "aws:runCommand",
      "maxAttempts": 3,
      "onFailure": "Abort",
      "timeoutSeconds": 600,
      "inputs": {
        "DocumentName": "AWS-ConfigureAWSPackage",
        "InstanceIds": [
          "{{LaunchInstance.InstanceIds}}"
        ],
        "Parameters": {
          "name": "AWSNVMe",
          "action": "Install"
        }
      }
    },
    {
      "name": "InstallWindowsUpdates",
      "action": "aws:runCommand",
      "maxAttempts": 3,
      "onFailure": "Abort",
      "timeoutSeconds": 14400,
      "inputs": {
        "DocumentName": "AWS-InstallWindowsUpdates",
        "InstanceIds": [
          "{{ LaunchInstance.InstanceIds }}"
        ],
        "Parameters": {
          "Action": "Install",
          "IncludeKbs": "{{ IncludeKbs }}",
          "ExcludeKbs": "{{ ExcludeKbs }}",
          "Categories": "{{ Categories }}",
          "SeverityLevels": "{{ SeverityLevels }}",
          "PublishedDaysOld": "{{ PublishedDaysOld }}",
          "PublishedDateAfter": "{{ PublishedDateAfter }}",
          "PublishedDateBefore": "{{ PublishedDateBefore }}"
        }
      }
    },
    {
      "name": "DisableESC",
      "action": "aws:runCommand",
      "maxAttempts": 3,
      "onFailure": "Abort",
      "timeoutSeconds": 600,
      "inputs": {
        "DocumentName": "AWS-RunPowerShellScript",
        "InstanceIds": [
          "{{ LaunchInstance.InstanceIds }}"
        ],
        "Parameters": {
          "commands": [
            "$AdminKey = 'HKLM:\\SOFTWARE\\Microsoft\\Active Setup\\Installed Components\\{A509B1A7-37EF-4b3f-8CFC-4F3A74704073}'",
            "$UserKey = 'HKLM:\\SOFTWARE\\Microsoft\\Active Setup\\Installed Components\\{A509B1A8-37EF-4b3f-8CFC-4F3A74704073}'",
            "Set-ItemProperty -Path $AdminKey -Name 'IsInstalled' -Value 0",
            "Set-ItemProperty -Path $UserKey -Name 'IsInstalled' -Value 0",
            "Write-Host 'IE Enhanced Security Configuration (ESC) has been disabled.' -ForegroundColor Green"
          ]
        }
      }
    },
    {
      "name": "InstallChocolatey",
      "action": "aws:runCommand",
      "maxAttempts": 3,
      "onFailure": "Abort",
      "timeoutSeconds": 600,
      "inputs": {
        "DocumentName": "AWS-RunPowerShellScript",
        "InstanceIds": [
          "{{ LaunchInstance.InstanceIds }}"
        ],
        "Parameters": {
          "commands": [
            "Set-ExecutionPolicy Bypass -Scope Process -Force; iex ((New-Object System.Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))"
          ]
        }
      }
    },
    {
      "name": "FirstStopInstance",
      "action": "aws:changeInstanceState",
      "maxAttempts": 3,
      "timeoutSeconds": 7200,
      "onFailure": "Abort",
      "inputs": {
        "InstanceIds": [
          "{{ LaunchInstance.InstanceIds }}"
        ],
        "CheckStateOnly": false,
        "DesiredState": "stopped"
      }
    },
    {
      "name": "StartInstance",
      "action": "aws:changeInstanceState",
      "maxAttempts": 3,
      "timeoutSeconds": 7200,
      "onFailure": "Abort",
      "inputs": {
        "InstanceIds": [
          "{{ LaunchInstance.InstanceIds }}"
        ],
        "CheckStateOnly": false,
        "DesiredState": "running"
      }
    },
    {
      "name": "InstallPython",
      "action": "aws:runCommand",
      "maxAttempts": 3,
      "onFailure": "Abort",
      "timeoutSeconds": 7200,
      "inputs": {
        "DocumentName": "AWS-RunPowerShellScript",
        "InstanceIds": [
          "{{ LaunchInstance.InstanceIds }}"
        ],
        "Parameters": {
          "commands": [
            "Function Command-Wrapper($FilePath, $InstallOptions) {",
            "  $pinfo = New-Object System.Diagnostics.ProcessStartInfo",
            "  $pinfo.CreateNoWindow = $true",
            "  $pinfo.RedirectStandardError = $true",
            "  $pinfo.RedirectStandardOutput = $true",
            "  $pinfo.UseShellExecute = $false",
            "  $pinfo.FileName = $FilePath",
            "  $pinfo.Arguments = $InstallOptions",
            "  $p = New-Object System.Diagnostics.Process",
            "  $p.StartInfo = $pinfo",
            "  $p.Start() | Out-Null",
            "  $stdout = $p.StandardOutput.ReadToEnd()",
            "  $stderr = $p.StandardError.ReadToEnd()",
            "  $p.WaitForExit()",
            "  Write-Host 'stdout: $stdout'",
            "  Write-Host 'stderr: $stderr'",
            "  Write-Host 'exit code: ' $p.ExitCode",
            "  if (!$p.ExitCode -eq 0)",
            "  {",
            "      exit $p.ExitCode",
            "  }",
            "}",
            "Command-Wrapper -FilePath 'C:\\ProgramData\\chocolatey\\choco' -InstallOptions 'install python3 -y'",
            "Command-Wrapper -FilePath 'C:\\ProgramData\\chocolatey\\choco' -InstallOptions 'install python2 -y'",
            "Command-Wrapper -FilePath 'C:\\Python37\\python' -InstallOptions '-m pip install --upgrade pip'",
            "Command-Wrapper -FilePath 'C:\\Python37\\python' -InstallOptions '-m pip install --upgrade requests'",
            "Command-Wrapper -FilePath 'C:\\Python37\\python' -InstallOptions '-m pip install --upgrade psutil'",
            "Command-Wrapper -FilePath 'C:\\Python37\\python' -InstallOptions '-m pip install --upgrade python-jenkins'",
            "Command-Wrapper -FilePath 'C:\\Python37\\python' -InstallOptions '-m pip install --upgrade boto3'",
            "Command-Wrapper -FilePath 'C:\\Python27\\python' -InstallOptions '-m pip install --upgrade pip'",
            "Command-Wrapper -FilePath 'C:\\Python27\\python' -InstallOptions '-m pip install --upgrade requests'"
          ]
        }
      }
    },
    {
      "name":"DownloadMXNetDependencyScript",
      "action":"aws:runCommand",
      "inputs":{
        "DocumentName":"AWS-RunRemoteScript",
        "InstanceIds": [
          "{{ LaunchInstance.InstanceIds }}"
        ],
        "Parameters":{
          "sourceType":[
            "S3"
          ],
          "sourceInfo":[
            "{\"path\": \"{{ PostUpdateScriptS3 }}\"}"
            ],
          "commandLine":[
            "Move-Item -Path .\\{{ PostUpdateScriptKey }} -Destination {{ PostUpdateScriptPath }}"
            ]
        }
      }
    },
    {
      "name":"DownloadCudnnInstallZip",
      "action":"aws:runCommand",
      "inputs":{
        "DocumentName":"AWS-RunRemoteScript",
        "InstanceIds": [
          "{{ LaunchInstance.InstanceIds }}"
        ],
        "Parameters":{
          "sourceType":[
            "S3"
          ],
          "sourceInfo":[
            "{\"path\": \"{{ CudnnInstallZipS3 }}\"}"
            ],
          "commandLine":[
            "Move-Item -Path .\\{{ CudnnInstallZipKey }} -Destination {{ CudnnInstallZipPath }}"
            ]
        }
      }
    },
    {
      "name": "RunMXNetDependencyScript",
      "action": "aws:runCommand",
      "maxAttempts": 3,
      "onFailure": "Abort",
      "timeoutSeconds": 3600,
      "inputs": {
        "DocumentName": "AWS-RunPowerShellScript",
        "InstanceIds": [
          "{{ LaunchInstance.InstanceIds }}"
        ],
        "Parameters": {
          "commands": [
            "C:\\Python37\\python {{ PostUpdateScriptPath }}"
          ]
        }
      }
    },
    {
      "name": "MXNetDependencyChocolateyInstalls",
      "action": "aws:runCommand",
      "maxAttempts": 3,
      "onFailure": "Abort",
      "timeoutSeconds": 7200,
      "inputs": {
        "DocumentName": "AWS-RunPowerShellScript",
        "InstanceIds": [
          "{{ LaunchInstance.InstanceIds }}"
        ],
        "Parameters": {
          "commands": [
            "Function Command-Wrapper($FilePath, $InstallOptions) {",
            "  $pinfo = New-Object System.Diagnostics.ProcessStartInfo",
            "  $pinfo.CreateNoWindow = $true",
            "  $pinfo.RedirectStandardError = $true",
            "  $pinfo.RedirectStandardOutput = $true",
            "  $pinfo.UseShellExecute = $false",
            "  $pinfo.FileName = $FilePath",
            "  $pinfo.Arguments = $InstallOptions",
            "  $p = New-Object System.Diagnostics.Process",
            "  $p.StartInfo = $pinfo",
            "  $p.Start() | Out-Null",
            "  $stdout = $p.StandardOutput.ReadToEnd()",
            "  $stderr = $p.StandardError.ReadToEnd()",
            "  $p.WaitForExit()",
            "  Write-Host 'stdout: $stdout'",
            "  Write-Host 'stderr: $stderr'",
            "  Write-Host 'exit code: ' $p.ExitCode",
            "  if (!$p.ExitCode -eq 0)",
            "  {",
            "      exit $p.ExitCode",
            "  }",
            "}",
            "Command-Wrapper -FilePath 'C:\\ProgramData\\chocolatey\\choco' -InstallOptions 'install jom -y'",
            "Command-Wrapper -FilePath 'C:\\ProgramData\\chocolatey\\choco' -InstallOptions 'install 7zip -y'",
            "Command-Wrapper -FilePath 'C:\\ProgramData\\chocolatey\\choco' -InstallOptions 'install mingw -y'",
            "Command-Wrapper -FilePath 'C:\\ProgramData\\chocolatey\\choco' -InstallOptions 'install javaruntime -y'"
          ]
        }
      }
    },
    {
      "name":"DownloadJenkinsSlaveAutoconnectPython",
      "action":"aws:runCommand",
      "inputs":{
        "DocumentName":"AWS-RunRemoteScript",
        "InstanceIds": [
          "{{ LaunchInstance.InstanceIds }}"
        ],
        "Parameters":{
          "sourceType":[
            "S3"
          ],
          "sourceInfo":[
            "{\"path\": \"{{ SlaveAutoconnectPythonS3 }}\"}"
            ],
          "commandLine":[
            "Move-Item -Path .\\{{ SlaveAutoconnectPythonKey }} -Destination {{ SlaveAutoconnectPythonPath }}"
            ]
        }
      }
    },
    {
      "name":"DownloadJenkinsSlaveAutoconnectBat",
      "action":"aws:runCommand",
      "inputs":{
        "DocumentName":"AWS-RunRemoteScript",
        "InstanceIds": [
          "{{ LaunchInstance.InstanceIds }}"
        ],
        "Parameters":{
          "sourceType":[
            "S3"
          ],
          "sourceInfo":[
            "{\"path\": \"{{ SlaveAutoconnectBatS3 }}\"}"
            ],
          "commandLine":[
            "Move-Item -Path .\\{{ SlaveAutoconnectBatKey }} -Destination {{ SlaveAutoconnectBatPath }}"
            ]
        }
      }
    },
    {
      "name": "CreateAutoconnectJob",
      "action": "aws:runCommand",
      "maxAttempts": 3,
      "onFailure": "Abort",
      "timeoutSeconds": 7200,
      "inputs": {
        "DocumentName": "AWS-RunPowerShellScript",
        "InstanceIds": [
          "{{ LaunchInstance.InstanceIds }}"
        ],
        "Parameters": {
          "commands": [
            "$trigger = New-ScheduledTaskTrigger -AtStartup -RandomDelay 00:00:30",
            "$action = New-ScheduledTaskAction -Execute \"{{ SlaveAutoconnectBatPath }}\"",
            "$principal = New-ScheduledTaskPrincipal -UserID \"NT AUTHORITY\\SYSTEM\" -LogonType ServiceAccount -RunLevel Highest",
            "Register-ScheduledTask \"JenkinsAutoConnect\" -Description \"Connect to Jenkins at startup\" -Action $action -Trigger $trigger -Principal $principal"
          ]
        }
      }
    },
    {
      "name": "RunSysprepGeneralize",
      "action": "aws:runCommand",
      "maxAttempts": 3,
      "onFailure": "Abort",
      "timeoutSeconds": 600,
      "inputs": {
        "DocumentName": "AWSEC2-RunSysprep",
        "InstanceIds": [
          "{{LaunchInstance.InstanceIds}}"
        ],
        "Parameters": {
          "Id": "{{automation:EXECUTION_ID}}"
        }
      }
    },
    {
      "name": "SecondStopInstance",
      "action": "aws:changeInstanceState",
      "maxAttempts": 3,
      "timeoutSeconds": 7200,
      "onFailure": "Abort",
      "inputs": {
        "InstanceIds": [
          "{{ LaunchInstance.InstanceIds }}"
        ],
        "CheckStateOnly": false,
        "DesiredState": "stopped"
      }
    },
    {
      "name": "CreateImage",
      "action": "aws:createImage",
      "maxAttempts": 3,
      "onFailure": "Abort",
      "inputs": {
        "InstanceId": "{{ LaunchInstance.InstanceIds }}",
        "ImageName": "{{ TargetAmiName }}",
        "NoReboot": true,
        "ImageDescription": "Test CreateImage Description"
      }
    },
    {
      "name": "TerminateInstance",
      "action": "aws:changeInstanceState",
      "maxAttempts": 3,
      "onFailure": "Abort",
      "inputs": {
        "InstanceIds": [
          "{{ LaunchInstance.InstanceIds }}"
        ],
        "DesiredState": "terminated"
      }
    }
  ]
}
DOC
}
