import numpy as np
import theano as th
import theano.tensor as tt
from hidden import HiddenLayer
from weights import borrow, is_shared_var

float_x = th.config.floatX
############################### Output Layer  ##################################


class OutputLayer(object):
    def neg_log_likli(self, y):
        return -tt.mean(self.logprob[tt.arange(y.shape[0]), y])

    def features_and_predictions(self):
        return self.features, self.y_preds

    def sym_and_oth_err_rate(self, y):
        sym_err_rate = tt.mean(tt.neq(self.y_preds, y))

        if self.kind == 'LOGIT':
            # Bit error rate
            second_stat = tt.mean(self.bitprob[tt.arange(y.shape[0]), y] < .5)

        else:
            # Likelihood of MLE
            second_stat = tt.mean(self.probs[tt.arange(y.shape[0]), y])

        return sym_err_rate, second_stat


class SoftmaxLayer(HiddenLayer, OutputLayer):
    def __init__(self, inpt, wts, rand_gen=None, n_in=None, n_out=None):
        HiddenLayer.__init__(self, inpt, wts, rand_gen, n_in, n_out,
                             actvn='Softmax',
                             pdrop=0)
        self.y_preds = tt.argmax(self.output, axis=1)
        self.probs = self.output
        self.logprob = tt.log(self.probs)
        self.features = self.logprob
        self.kind = 'SOFTMAX'
        self.representation = 'Softmax In:{:3d} Out:{:3d}'.format(self.n_in,
                                                                  self.n_out)

    def TestVersion(self, inpt):
        return SoftmaxLayer(inpt, (self.w, self.b))


activs = {'LOGIT': 'sigmoid', 'RBF': 'scaled_tanh'}


class CenteredOutLayer(HiddenLayer, OutputLayer):
    def __init__(self, inpt, wts, centers, rand_gen=None,
                 n_in=None, n_features=None, n_classes=None,
                 kind='LOGIT', learn_centers=False, junk_dist=np.inf):
        # wts (n_in x n_features)
        # centers (n_classesx n_features)

        assert kind in activs
        assert n_in or wts
        assert n_features or wts or centers
        assert n_classes or centers
        assert kind == 'RBF' or not learn_centers

        HiddenLayer.__init__(self, inpt, wts, rand_gen, n_in, n_out=n_features,
                             actvn=activs[kind], pdrop=0)

        # Initialize centers
        if centers is None:
            if kind == 'LOGIT':
                centers_vals = rand_gen.binomial(n=1, p=.5,
                                                 size=(n_classes, n_features))
            elif kind == 'RBF':
                centers_vals = rand_gen.uniform(low=0, high=1,
                                                size=(n_classes, n_features))
            centers = np.asarray(centers_vals, dtype=float_x)

        if is_shared_var(centers):
            self.centers = centers
        else:
            self.centers = th.shared(centers, name='centers', borrow=True)

        if learn_centers:
            self.params.append(self.centers)

        # Populate various n's based on weights
        if not n_in or not n_features:
            n_in, n_features = borrow(self.w).shape
        if not n_features or not n_classes:
            n_classes, n_features = borrow(self.centers).shape

        # c = centers; v = output of hidden layer = calculated features
        self.features = self.output  # Refers to the output of HiddenLayer
        c = self.centers.dimshuffle('x', 0, 1)
        v = self.features.dimshuffle(0, 'x', 1)
        self.kind = kind
        self.junk_dist = junk_dist

        if kind == 'LOGIT':
            # BATCH_SZ x nClasses x nFeatures >> BATCH_SZ x nClasses >> BATCH_SZ
            epsilon = .001
            v = v * (1 - 2 * epsilon) + epsilon
            self.bitprob = c * v + (1 - c) * (1 - v)
            self.logprob = tt.sum(tt.log(self.bitprob), axis=2)
            # if imp == None \
            # else T.tensordot(T.log(self.bitprob), imp, axes=([2, 0]))
            self.y_preds = tt.argmax(self.logprob, axis=1)
        elif kind == 'RBF':
            dists = tt.sum((v - c) ** 2, axis=2)  # BATCH_SZ x nClasses
            junk_col = junk_dist + tt.zeros_like(dists[:, 1]).dimshuffle(0, 'x')
            self.dists = tt.concatenate([dists, junk_col], axis=1)
            self.probs = tt.nnet.softmax(-self.dists)  # BATCH_SZ x nClasses+1
            self.logprob = tt.log(self.probs)
            self.y_preds = tt.argmax(self.probs, axis=1)

        self.representation = ('CenteredOut Kind:{} In:{:3d} Hidden:{:3d} '
                               'Out:{:3d} learn_centers:{} junk_dist:{}'.format(
            kind, n_in, n_features, n_classes, learn_centers, junk_dist))

    def TestVersion(self, inpt):
        return CenteredOutLayer(inpt, (self.w, self.b), self.centers,
                                kind=self.kind, junk_dist=self.junk_dist)