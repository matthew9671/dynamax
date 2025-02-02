"""
This file contains utility functions that are used to test EKF, UKF and GGF inference,
by comparing the results to the sarkka-lib codebase on some toy problems.
"""
import jax.random as jr
import jax.numpy as jnp

from dynamax.linear_gaussian_ssm.inference import LGSSMParams, lgssm_sample
from dynamax.nonlinear_gaussian_ssm.nonlinear_gaussian_ssm import NLGSSMParams
from dynamax.abstractions import SSM
from dynamax.parameters import ParameterProperties
from dynamax.utils import PSDToRealBijector

import tensorflow_probability.substrates.jax as tfp
tfd = tfp.distributions
tfb = tfp.bijectors
MVN = tfd.MultivariateNormalFullCovariance


def lgssm_to_nlgssm(params):
    """Generates NonLinearGaussianSSM params from LinearGaussianSSM params

    Args:
        params: LinearGaussianSSM object

    Returns:
        nlgssm_params: NonLinearGaussianSSM object
    """
    nlgssm_params = NLGSSMParams(
        initial_mean=params.initial_mean,
        initial_covariance=params.initial_covariance,
        dynamics_function=lambda x: params.dynamics_matrix @ x + params.dynamics_bias,
        dynamics_covariance=params.dynamics_covariance,
        emission_function=lambda x: params.emission_matrix @ x + params.emission_bias,
        emission_covariance=params.emission_covariance,
    )
    return nlgssm_params


def random_lgssm_args(key=0, num_timesteps=15, state_dim=4, emission_dim=2):
    if isinstance(key, int):
        key = jr.PRNGKey(key)
    *keys, subkey = jr.split(key, 9)

    # Generate random parameters
    initial_mean = jr.normal(keys[0], (state_dim,))
    initial_covariance = jnp.eye(state_dim) * jr.uniform(keys[1])
    dynamics_covariance = jnp.eye(state_dim) * jr.uniform(keys[2])
    emission_covariance = jnp.eye(emission_dim) * jr.uniform(keys[3])

    params = LGSSMParams(
        initial_mean=initial_mean,
        initial_covariance=initial_covariance,
        dynamics_matrix=jr.normal(keys[4], (state_dim, state_dim)),
        dynamics_input_weights=jnp.zeros((state_dim, 0)),
        dynamics_covariance=dynamics_covariance,
        dynamics_bias=jr.normal(keys[5], (state_dim,)),
        emission_matrix=jr.normal(keys[6], (emission_dim, state_dim)),
        emission_input_weights=jnp.zeros((emission_dim, 0)),
        emission_covariance=emission_covariance,
        emission_bias=jr.normal(keys[7], (emission_dim,)),
    )

    # Generate random samples
    key, subkey = jr.split(subkey, 2)
    states, emissions = lgssm_sample(key, params, num_timesteps)
    return params, states, emissions


def to_poly(state, degree):
    return jnp.concatenate([state**d for d in jnp.arange(degree+1)])


class SimpleNonlinearSSM(SSM):
    def __init__(self, state_dim, emission_dim, dynamics_degree=1, emission_degree=1):
        self.state_dim = state_dim
        self.emission_dim = emission_dim
        self.dynamics_degree = dynamics_degree
        self.emission_degree = emission_degree

    @property
    def emission_shape(self):
        return (self.emission_dim,)

    def initial_distribution(self, params, covariates=None):
        return MVN(params["initial"]["mean"], params["initial"]["cov"])

    def transition_distribution(self, params, state, covariates=None):
        x = to_poly(state, self.dynamics_degree)
        mean = jnp.sin(params["dynamics"]["weights"] @ x)
        return MVN(mean, params["dynamics"]["cov"])

    def emission_distribution(self, params, state, covariates=None):
        x = to_poly(state, self.emission_degree)
        mean = jnp.cos(params["emissions"]["weights"] @ x)
        return MVN(mean, params["emissions"]["cov"])

    def random_initialization(self, key):
        key1, key2 = jr.split(key)
        params = dict(
            initial=dict(mean=0.2 * jnp.ones(self.state_dim), cov=jnp.eye(self.state_dim)),
            dynamics=dict(weights=jr.normal(key1, (self.state_dim, self.state_dim * (self.dynamics_degree+1))),
                          cov=jnp.eye(self.state_dim)),
            emissions=dict(weights=jr.normal(key2, (self.emission_dim, self.state_dim * (self.emission_degree+1))),
                          cov=jnp.eye(self.emission_dim)),
        )

        param_props = dict(
            initial=dict(mean=ParameterProperties(),
                         cov=ParameterProperties(constrainer=tfb.Invert(PSDToRealBijector))),
            dynamics=dict(weights=ParameterProperties(),
                          cov=ParameterProperties(constrainer=tfb.Invert(PSDToRealBijector))),
            emissions=dict(weights=ParameterProperties(),
                           cov=ParameterProperties(constrainer=tfb.Invert(PSDToRealBijector))),
        )
        return params, param_props

    def _make_inference_args(self, params):
        f = lambda state: jnp.sin(params["dynamics"]["weights"] @ to_poly(state, self.dynamics_degree))
        h = lambda state: jnp.cos(params["emissions"]["weights"] @ to_poly(state, self.emission_degree))
        return NLGSSMParams(
            initial_mean=params["initial"]["mean"],
            initial_covariance=params["initial"]["cov"],
            dynamics_function=f,
            dynamics_covariance=params["dynamics"]["cov"],
            emission_function=h,
            emission_covariance=params["emissions"]["cov"])


def random_nlgssm_args(key=0, num_timesteps=15, state_dim=4, emission_dim=2):
    if isinstance(key, int):
        key = jr.PRNGKey(key)

    init_key, sample_key = jr.split(key, 2)
    model = SimpleNonlinearSSM(state_dim, emission_dim)
    params, _ = model.random_initialization(init_key)
    states, emissions = model.sample(params, sample_key, num_timesteps)
    args = model._make_inference_args(params)
    return args, states, emissions
