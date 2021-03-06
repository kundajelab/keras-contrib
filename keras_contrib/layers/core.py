# -*- coding: utf-8 -*-
from __future__ import absolute_import
from __future__ import division

from .. import backend as K
from .. import activations
from .. import initializers
from .. import regularizers
from .. import constraints
from keras.engine import InputSpec
from keras.engine import Layer
from keras.utils.generic_utils import get_custom_objects


class SeparableFC(Layer):
    """A separable fully-connected NN layer
    Separable Fully Connected Layers Improve Deep Learning Models For Genomics
    https://doi.org/10.1101/146431

    # Example
        Expected usage is after a stack of convolutional layers and before
        densely connected layers
        A gist illustrating model setup is at: goo.gl/gYooaa

    # Arguments
        output_dim: the number of output neurons
        symmetric: if weights are to be symmetric along length, set to True
        smoothness_regularizer: regularization to be applied on adjacent
            weights in the length dimension of positional weights matrix
        positional_constraint: constraint to be enforced on adjacent
            weights in the length dimension of positional weights matrix

    # Input shape
        3D tensor with shape: `(samples, steps, features)`.

    # Output shape
        2D tensor with shape: `(samples, output_features)`.
    """
    def __init__(self, output_dim, symmetric=False,
                 smoothness_regularizer=None,
                 positional_constraint=None, **kwargs):
        super(SeparableFC, self).__init__(**kwargs)
        self.output_dim = output_dim
        self.symmetric = symmetric
        self.smoothness_regularizer = smoothness_regularizer
        self.positional_constraint = positional_constraint

    def build(self, input_shape):
        import numpy as np
        self.original_length = input_shape[1]
        if self.symmetric is False:
            self.length = input_shape[1]
        else:
            self.odd_input_length = input_shape[1] % 2.0 == 1
            self.length = int(input_shape[1] / 2.0 + 0.5)
        self.num_channels = input_shape[2]
        limit = np.sqrt(np.sqrt(
            2.0 / (self.length * self.num_channels + self.output_dim)))
        self.W_pos = self.add_weight(
            shape=(self.output_dim, self.length),
            name='{}_W_pos'.format(self.name),
            initializer=initializers.uniform(-1 * limit, limit),
            constraint=self.positional_constraint,
            regularizer=self.smoothness_regularizer,
            trainable=True)
        self.W_chan = self.add_weight(
            shape=(self.output_dim, self.num_channels),
            name='{}_W_chan'.format(self.name),
            initializer=initializers.uniform(-1 * limit, limit),
            trainable=True)
        self.built = True

    def compute_output_shape(self, input_shape):
        return (input_shape[0], self.output_dim)

    def call(self, x, mask=None):
        if self.symmetric is False:
            W_pos = self.W_pos
        else:
            W_pos = K.concatenate(
                tensors=[self.W_pos,
                         self.W_pos[:, ::-1][:, (1 if self.odd_input_length else 0):]],
                axis=1)
        W_output = K.expand_dims(W_pos, 2) * K.expand_dims(self.W_chan, 1)
        W_output = K.reshape(W_output,
                             (self.output_dim, self.original_length * self.num_channels))
        x = K.reshape(x,
                      (-1, self.original_length * self.num_channels))
        output = K.dot(x, K.transpose(W_output))
        return output

    def get_config(self):
        config = {'output_dim': self.output_dim,
                  'symmetric': self.symmetric,
                  'smoothness_regularizer': self.smoothness_regularizer,
                  'positional_constraint': self.positional_constraint}
        base_config = super(SeparableFC, self).get_config()
        return dict(list(base_config.items()) + list(config.items()))


get_custom_objects().update({'SeparableFC': SeparableFC})


class CosineDense(Layer):
    """A cosine normalized densely-connected NN layer
    Cosine Normalization: Using Cosine Similarity Instead of Dot Product in Neural Networks
    https://arxiv.org/pdf/1702.05870.pdf

    # Example

    ```python
        # as first layer in a sequential model:
        model = Sequential()
        model.add(CosineDense(32, input_dim=16))
        # now the model will take as input arrays of shape (*, 16)
        # and output arrays of shape (*, 32)

        # this is equivalent to the above:
        model = Sequential()
        model.add(CosineDense(32, input_shape=(16,)))

        # after the first layer, you don't need to specify
        # the size of the input anymore:
        model.add(CosineDense(32))

        **Note that a regular Dense layer may work better as the final layer
    ```

    # Arguments
        units: Positive integer, dimensionality of the output space.
        init: name of initialization function for the weights of the layer
            (see [initializers](../initializers.md)),
            or alternatively, Theano function to use for weights
            initialization. This parameter is only relevant
            if you don't pass a `weights` argument.
        activation: name of activation function to use
            (see [activations](../activations.md)),
            or alternatively, elementwise Theano function.
            If you don't specify anything, no activation is applied
            (ie. "linear" activation: a(x) = x).
        weights: list of Numpy arrays to set as initial weights.
            The list should have 2 elements, of shape `(input_dim, units)`
            and (units,) for weights and biases respectively.
        kernel_regularizer: instance of [WeightRegularizer](../regularizers.md)
            (eg. L1 or L2 regularization), applied to the main weights matrix.
        bias_regularizer: instance of [WeightRegularizer](../regularizers.md),
            applied to the bias.
        activity_regularizer: instance of [ActivityRegularizer](../regularizers.md),
            applied to the network output.
        kernel_constraint: instance of the [constraints](../constraints.md) module
            (eg. maxnorm, nonneg), applied to the main weights matrix.
        bias_constraint: instance of the [constraints](../constraints.md) module,
            applied to the bias.
        use_bias: whether to include a bias
            (i.e. make the layer affine rather than linear).
        input_dim: dimensionality of the input (integer). This argument
            (or alternatively, the keyword argument `input_shape`)
            is required when using this layer as the first layer in a model.

    # Input shape
        nD tensor with shape: `(nb_samples, ..., input_dim)`.
        The most common situation would be
        a 2D input with shape `(nb_samples, input_dim)`.

    # Output shape
        nD tensor with shape: `(nb_samples, ..., units)`.
        For instance, for a 2D input with shape `(nb_samples, input_dim)`,
        the output would have shape `(nb_samples, units)`.
    """

    def __init__(self, units, kernel_initializer='glorot_uniform',
                 activation=None, weights=None,
                 kernel_regularizer=None, bias_regularizer=None, activity_regularizer=None,
                 kernel_constraint=None, bias_constraint=None,
                 use_bias=True, input_dim=None, **kwargs):
        self.kernel_initializer = initializers.get(kernel_initializer)
        self.activation = activations.get(activation)
        self.units = units
        self.input_dim = input_dim

        self.kernel_regularizer = regularizers.get(kernel_regularizer)
        self.bias_regularizer = regularizers.get(bias_regularizer)
        self.activity_regularizer = regularizers.get(activity_regularizer)

        self.kernel_constraint = constraints.get(kernel_constraint)
        self.bias_constraint = constraints.get(bias_constraint)

        self.use_bias = use_bias
        self.initial_weights = weights

        if self.input_dim:
            kwargs['input_shape'] = (self.input_dim,)
        super(CosineDense, self).__init__(**kwargs)

    def build(self, input_shape):
        ndim = len(input_shape)
        assert ndim >= 2
        input_dim = input_shape[-1]
        self.input_dim = input_dim
        self.input_spec = [InputSpec(dtype=K.floatx(),
                                     ndim=ndim)]

        self.kernel = self.add_weight((input_dim, self.units),
                                      initializer=self.kernel_initializer,
                                      name='{}_W'.format(self.name),
                                      regularizer=self.kernel_regularizer,
                                      constraint=self.kernel_constraint)
        if self.use_bias:
            self.bias = self.add_weight((self.units,),
                                        initializer='zero',
                                        name='{}_b'.format(self.name),
                                        regularizer=self.bias_regularizer,
                                        constraint=self.bias_constraint)
        else:
            self.bias = None

        if self.initial_weights is not None:
            self.set_weights(self.initial_weights)
            del self.initial_weights
        self.built = True

    def call(self, x, mask=None):
        if self.use_bias:
            b, xb = self.bias, 1.
        else:
            b, xb = 0., 0.

        xnorm = K.sqrt(K.sum(K.square(x), axis=-1, keepdims=True) + xb + K.epsilon())
        Wnorm = K.sqrt(K.sum(K.square(self.kernel), axis=0) + K.square(b) + K.epsilon())

        xWnorm = (xnorm * Wnorm)

        output = K.dot(x, self.kernel) / xWnorm
        if self.use_bias:
            output += (self.bias / xWnorm)
        return self.activation(output)

    def compute_output_shape(self, input_shape):
        assert input_shape and len(input_shape) >= 2
        assert input_shape[-1] and input_shape[-1] == self.input_dim
        output_shape = list(input_shape)
        output_shape[-1] = self.units
        return tuple(output_shape)

    def get_config(self):
        config = {'units': self.units,
                  'kernel_initializer': initializers.serialize(self.kernel_initializer),
                  'activation': activations.serialize(self.activation),
                  'kernel_regularizer': regularizers.serialize(self.kernel_regularizer),
                  'bias_regularizer': regularizers.serialize(self.bias_regularizer),
                  'activity_regularizer': regularizers.serialize(self.activity_regularizer),
                  'kernel_constraint': constraints.serialize(self.kernel_constraint),
                  'bias_constraint': constraints.serialize(self.bias_constraint),
                  'use_bias': self.use_bias,
                  'input_dim': self.input_dim}
        base_config = super(CosineDense, self).get_config()
        return dict(list(base_config.items()) + list(config.items()))


get_custom_objects().update({'CosineDense': CosineDense})
