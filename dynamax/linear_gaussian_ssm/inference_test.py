from jax import random as jr
from jax import numpy as jnp
from jax import vmap
from functools import partial

import tensorflow_probability.substrates.jax.distributions as tfd
from dynamax.linear_gaussian_ssm.models.linear_gaussian_ssm import LinearGaussianSSM




def lgssm_dynamax_to_tfp(num_timesteps, params):
    """Create a Tensorflow Probability `LinearGaussianStateSpaceModel` object
     from an dynamax `LinearGaussianSSM`.

    Args:
        num_timesteps: int, the number of timesteps.
        lgssm: LinearGaussianSSM or LGSSMParams object.
    """
    dynamics_noise_dist = tfd.MultivariateNormalFullCovariance(covariance_matrix=params['dynamics']['cov'])
    emission_noise_dist = tfd.MultivariateNormalFullCovariance(covariance_matrix=params['emissions']['cov'])
    initial_dist = tfd.MultivariateNormalFullCovariance(params['initial']['mean'], params['initial']['cov'])

    tfp_lgssm = tfd.LinearGaussianStateSpaceModel(
        num_timesteps,
        params['dynamics']['weights'],
        dynamics_noise_dist,
        params['emissions']['weights'],
        emission_noise_dist,
        initial_dist,
    )

    return tfp_lgssm


def test_kalman_filter_smoother(num_timesteps=5, seed=0):
    key = jr.PRNGKey(seed)
    init_key, sample_key = jr.split(key)

    state_dim = 4
    emission_dim = 2
    delta = 1.0

    lgssm = LinearGaussianSSM(state_dim, emission_dim)
    params, _ = lgssm.random_initialization(init_key)
    params['initial']['mean'] = jnp.array([8.0, 10.0, 1.0, 0.0])
    params['initial']['cov'] = jnp.eye(state_dim) * 0.1
    params['dynamics']['weights'] = jnp.array([[1, 0, delta, 0],
                                               [0, 1, 0, delta],
                                               [0, 0, 1, 0],
                                               [0, 0, 0, 1]])
    params['dynamics']['cov'] = jnp.eye(state_dim) * 0.001
    params['emissions']['weights'] = jnp.array([[1.0, 0, 0, 0],
                                                [0, 1.0, 0, 0]])
    params['emissions']['cov'] = jnp.eye(emission_dim) * 1.0

    # Sample data and compute posterior
    _, emissions = lgssm.sample(params, sample_key, num_timesteps)
    ssm_posterior = lgssm.smoother(params, emissions)

    # TensorFlow Probability posteriors
    tfp_lgssm = lgssm_dynamax_to_tfp(num_timesteps, params)
    tfp_lls, tfp_filtered_means, tfp_filtered_covs, *_ = tfp_lgssm.forward_filter(emissions)
    tfp_smoothed_means, tfp_smoothed_covs = tfp_lgssm.posterior_marginals(emissions)

    assert jnp.allclose(ssm_posterior.filtered_means, tfp_filtered_means, rtol=1e-2)
    assert jnp.allclose(ssm_posterior.filtered_covariances, tfp_filtered_covs, rtol=1e-2)
    assert jnp.allclose(ssm_posterior.smoothed_means, tfp_smoothed_means, rtol=1e-2)
    assert jnp.allclose(ssm_posterior.smoothed_covariances, tfp_smoothed_covs, rtol=1e-2)
    assert jnp.allclose(ssm_posterior.marginal_loglik, tfp_lls.sum())


def test_posterior_sampler():
    state_dim = 1
    emission_dim = 1

    num_timesteps=100
    key=jr.PRNGKey(0)
    sample_size=500

    lgssm = LinearGaussianSSM(state_dim, emission_dim)
    params, _ = lgssm.random_initialization(key)
    params['initial']['mean'] = jnp.array([5.0])
    params['initial']['cov'] = jnp.eye(state_dim)
    params['dynamics']['weights'] = jnp.eye(state_dim) * 1.01
    params['dynamics']['cov'] = jnp.eye(state_dim)
    params['emissions']['weights'] = jnp.eye(emission_dim)
    params['emissions']['cov'] = jnp.eye(emission_dim) * 5.**2

    # Generate true observation
    sample_key, key = jr.split(key)
    states, emissions = lgssm.sample(params, key=sample_key, num_timesteps=num_timesteps)

    # Sample from the posterior distribution
    posterior_sample = partial(lgssm.posterior_sample, params=params, emissions=emissions)
    keys = jr.split(key, sample_size)
    samples = vmap(lambda key: posterior_sample(key=key))(keys)

    # Do the same with TFP
    tfp_lgssm = lgssm_dynamax_to_tfp(num_timesteps, params)
    tfp_samples = tfp_lgssm.posterior_sample(emissions, seed=key, sample_shape=sample_size)

    print(samples.shape) # (N,T,1)
    print(tfp_samples.shape) # (N,T,1)

    assert jnp.allclose(jnp.mean(samples), jnp.mean(tfp_samples), atol=1e-1)
    assert jnp.allclose(jnp.std(samples), jnp.std(tfp_samples), atol=1e-1)
