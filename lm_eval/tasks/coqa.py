# REMINDER: this code needs to be rewritten for the new framework. Remove this comment when the code is fully converted.

import json
import random
import numpy as np
from lm_eval.base import Task, rf, mean
from ..utils import sh
from itertools import zip_longest
import transformers.data.metrics.squad_metrics as squad_metrics

class CoQA(Task):
    def download(self):
        pass
        # -N only overwrites if the remote file has changed
        sh ("""
            mkdir -p data/coqa 
            wget -N http://downloads.cs.stanford.edu/nlp/data/coqa/coqa-train-v1.0.json -O data/coqa/coqa-train-v1.0.json
            wget -N http://downloads.cs.stanford.edu/nlp/data/coqa/coqa-dev-v1.0.json -O data/coqa/coqa-dev-v1.0.json
            """)

    def has_training_docs(self):
        return True

    def has_validation_docs(self):
        return True

    def has_test_docs(self):
        return False

    def training_docs(self):
        return json.load(open('data/coqa/coqa-train-v1.0.json'))['data']

    def validation_docs(self):
        return json.load(open('data/coqa/coqa-dev-v1.0.json'))['data']  

    def test_docs(self):
        pass
    
    def fewshot_description(self):
        return "Given a passage and a conversation so far, answer the next question in the conversation."
    
    def doc_to_text(self, doc):
        # Each "doc" is a story and conversation (Q and A pairs).
        doc_text = doc["story"] + '\n\n'
        for (q, a) in zip_longest(doc["questions"], doc["answers"][:-1]):   # omit target answer
            question = f"Q: {q['input_text']}" + '\n\n'
            answer = f"A: {a['input_text']}" + '\n\n' if a is not None else "A: "
            doc_text += question + answer
            print(doc_text)
        return doc_text

    @classmethod
    def get_answers(cls, doc, turn_id):
        # This function returns an answer and valid alternatives.
        answers = []
        answer_forturn = doc["answers"][turn_id - 1]["input_text"]
        answers.append(answer_forturn)
        
        additionals = doc.get("additional_answers")
        if additionals:
            for key in additionals:
                additional_answer_for_turn = additionals[key][turn_id - 1]["input_text"]
                if additional_answer_for_turn.upper() not in map(str.upper, answers):
                    answers.append(additional_answer_for_turn)
        return answers
    
    def doc_to_target(self, doc, turnid=None):
        # Default to predict last turn.
        if turnid is None:
            turnid = len(doc["questions"])
        all_answers = self.get_answers(doc, turnid)
        return all_answers[0]   # ignore alternative answers for now

    @staticmethod
    def compute_scores(gold_list, pred):
        f1_sum = 0.0
        em_sum = 0.0
        if len(gold_list) > 1:
            for i in range(len(gold_list)):
                gold_answers = gold_list[0:i] + gold_list[i + 1:]
                em_sum += max(squad_metrics.compute_exact(a, pred) for a in gold_answers)
                f1_sum += max(squad_metrics.compute_f1(a, pred) for a in gold_answers)
        else:
            em_sum += max(squad_metrics.compute_exact(a, pred) for a in gold_list)
            f1_sum += max(squad_metrics.compute_f1(a, pred) for a in gold_list)

        return {'em': em_sum / max(1, len(gold_list)), 'f1': f1_sum / max(1, len(gold_list))}

    def construct_requests(self, doc, ctx):
        """ Uses RequestFactory to construct Requests and returns an iterable of 
        Requests which will be sent to the LM.

        :param doc:
            The document as returned from training_docs, validation_docs, or test_docs.
        :param ctx: str
            The context string, generated by fewshot_context. This includes the natural 
            language description, as well as the few shot examples, and the question
            part of the document for `doc`. 
        """
        requests = []
        for answers in self.get_answers(doc, len(doc["questions"])):
            for a in answers:
                requests.append(rf.loglikelihood(ctx, " " + a)) 
        return requests
    
    def process_results(self, doc, results):
        """Take a single document and the LM results and evaluates, returning a 
        dict where keys are the names of submetrics and values are the values of 
        the metric for that one document

        :param doc:
            The document as returned from training_docs, validation_docs, or test_docs.
        :param results:
            The results of the requests created in construct_requests.
        """

        turn_id = len(doc["questions"])
        gold_list = self.get_answers(doc, turn_id)
        pred = np.argmax(results)

        (em, f1) = self.compute_scores(gold_list, pred)

        return {
            "f1": f1,
            "em": em,
        }

    def higher_is_better(self):
        return {
            "f1": True,
            "em": True,
        }

    def aggregation(self):
        return {
            "f1": mean,
            "em": mean,
        }