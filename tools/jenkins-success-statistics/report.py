#!/usr/bin/env python3

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

# -*- coding: utf-8 -*-3
"""Description"""

__author__ = 'Pedro Larroy'
__version__ = '0.1'

import os
import sys
import json
import dateutil.parser
import datetime


def usage():
    sys.stderr.write('usage: {0}\n'.format(sys.argv[0]))


def main():
    with open("runs", "r") as f:
        runs = json.load(f)
        res = [{"result": x['result'], "endTime": dateutil.parser.parse(x['endTime'], ignoretz=True)} for x in runs if x['endTime']]
        a_week_ago = datetime.datetime.now()-datetime.timedelta(days=7)
        last_week_runs = filter(lambda x: x["endTime"] > a_week_ago, res)
        fails = 0
        success = 0
        for x in last_week_runs:
            if x['result'].lower() == 'success':
                success += 1
            else:
                fails += 1
        success_rate = float(success)*100 / (success + fails)
        print("MXNet master CI pass rate {:.0f}%".format(success_rate))


    return 1

if __name__ == '__main__':
    sys.exit(main())

