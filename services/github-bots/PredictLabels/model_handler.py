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

# custom service file

# model_handler.py

"""
ModelHandler defines a base model handler.
"""
import logging
import data_transformer
import keras
import sys
import numpy as np
import defs
import mxnet as mx


class ModelHandler(object):
    """
    A base Model handler implementation.
    """

    def __init__(self):
        self.error = None
        self._context = None
        self._batch_size = 0
        self.initialized = False
        self.mod = None

    def initialize(self, context):
        """
        Initialize model. This will be called during model loading time
        :param context: Initial context contains model server system properties.
        :return:
        """
        self._context = context
        self._batch_size = context.system_properties["batch_size"]
        self.initialized = True

        sym, arg_params, aux_params = mx.model.load_checkpoint(prefix='./prog', epoch=0)
        self.mod = mx.mod.Module(symbol=sym,
                            data_names=['/dropout_1_input1'],
                            context=mx.cpu(),
                            label_names=None)
        self.mod.bind(for_training=False,
                 data_shapes=[('/dropout_1_input1', (1, 2048, 70), 'float32', 'NTC')],
                 label_shapes=self.mod._label_shapes)

        self.mod.set_params(arg_params, aux_params)

    def preprocess(self, batch):
        """
        Transform raw input into model input data.
        :param batch: list of raw requests, should match batch size
        :return: list of preprocessed model input data
        """
        assert self._batch_size == len(batch), "Invalid input batch size: {}".format(len(batch))
        #with open('tmp_file','wb') as f:
        #     f.write(batch[0].get('body'))
        #return mx.nd.array(data_transformer.file_to_vec('tmp_file', file_vector_size=defs.file_chars_trunc_limit))
        return mx.nd.array(data_transformer.file_to_vec(batch[0].get('body'), file_vector_size=defs.file_chars_trunc_limit))

    def inference(self, model_input):
        """
        Internal inference methods
        :param model_input: transformed model input data
        :return: list of inference output in NDArray
        """
        return self.mod.predict(model_input)

    def postprocess(self, inference_output):
        """
        Return predict result in batch.
        :param inference_output: list of inference output
        :return: list of predict results
        """
        y = inference_output
        results = []
        for i in range(0, len(defs.langs)):
            results.append("{} - {}:     {}%".format(' ' if (y[0][i] < 0.5) else '*', defs.langs[i],
                                                     (100 * y[0][i])).strip('<NDArray 1 @cpu(0)>%'))
        return [results]

    def handle(self, data, context):
        """
        Custom service entry point function.
        :param data: list of objects, raw input from request
        :param context: model server context
        :return: list of outputs to be send back to client
        """

        try:
            data = self.preprocess(data)
            data = self.inference(data)
            data = self.postprocess(data)
            print("after", data)
            return data
        except Exception as e:
            logging.error(e, exc_info=True)
            request_processor = context.request_processor
            request_processor.report_status(500, "Unknown inference error")
            return [str(e)] * self._batch_size

