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

# This script is served to train Machine Learning models
from DataFetcher import DataFetcher
from SentenceParser import SentenceParser
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import SVC
from sklearn.preprocessing import LabelEncoder
import tempfile
import pickle
import logging
import os


class Trainer:
    # target labels that we are interested in
    labels = ["Performance", "Test", "Question",
               "Feature request", "Call for contribution",
               "Feature", "Example", "Doc",
               "Installation", "Build", "Bug"]

    def __init__(self, 
                 tv=TfidfVectorizer(min_df=0.00009, ngram_range=(1, 3), max_features=10000), 
                 clf=SVC(gamma=0.5, C=100, probability=True),
                 tmp_dir = tempfile.TemporaryDirectory()
                 ):
        """
        Trainer is to train issues using Machine Learning methods.
        self.labels(list): a list of target labels
        self.tv: TFIDF model (trigram, max_features = 10000)
        self.clf: Classifier (SVC, kenerl = 'rbf')
        self.tmp_tv_file: tempfile to store Vectorizer
        self.tmp_clf_file: tempfile to store Classifier
        self.tmp_labels_file: tempfile to store Labels
        """
        self.tv = tv
        self.clf = clf
        self.tmp_dir = tmp_dir

    def train(self):
        """
        This method is to train and save models.
        It has 5 steps:
        1. Fetch issues
        2. Clean data
        3. Word embedding
        4. Train models
        5. Save models
        """
        logging.info("Start training issues of general labels")
        # Step1: Fetch issues with general labels
        logging.info("Fetching Data..")
        DF = DataFetcher()
        filename = DF.data2json('all', self.labels, False)
        # Step2: Clean data
        logging.info("Cleaning Data..")
        SP = SentenceParser()
        SP.read_file(filename, 'json')
        SP.clean_body('body', True, True)
        SP.merge_column(['title', 'title', 'title', 'body'], 'train')
        text = SP.process_text('train', True, False, True)
        df = SP.data
        # Step3: Word Embedding
        logging.info("Word Embedding..")
        # tv = TfidfVectorizer(min_df=0.00009, ngram_range=(1, 3), max_features=10000)
        tv = self.tv
        X = tv.fit_transform(text).toarray()
        # Labels
        labels = SP.data['labels']
        le = LabelEncoder()
        Y = le.fit_transform(labels)
        # Step4: Train Classifier
        # SVC, kernel = 'rbf'
        logging.info("Training Data..")
        # clf = SVC(gamma=0.5, C=100, probability=True)
        clf = self.clf
        clf.fit(X, Y)
        # Step5: save models
        logging.info("Saving Models..")
        with open(os.path.join(self.tmp_dir.name,'Vectorizer.p'), 'wb') as tv_file:
            pickle.dump(tv, tv_file)
        with open(os.path.join(self.tmp_dir.name,'Classifier.p'), 'wb') as clf_file:
            pickle.dump(clf, clf_file)
        with open(os.path.join(self.tmp_dir.name,'Labels.p'), 'wb') as labels_file:
            pickle.dump(labels, labels_file)
        logging.info("Completed!")
        return self.tmp_dir
