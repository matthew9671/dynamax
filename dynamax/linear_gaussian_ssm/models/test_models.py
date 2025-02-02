import pytest
from datetime import datetime
import jax.numpy as jnp
import jax.random as jr
import dynamax.linear_gaussian_ssm.models as models
from dynamax.utils import ensure_array_has_batch_dim, monotonically_increasing

NUM_TIMESTEPS = 100

CONFIGS = [
    (models.LinearGaussianSSM, dict(state_dim=2, emission_dim=10), None),
    (models.LinearGaussianConjugateSSM, dict(state_dim=2, emission_dim=10), None),
]

@pytest.mark.parametrize(["cls", "kwargs", "covariates"], CONFIGS)
def test_sample_and_fit(cls, kwargs, covariates):
    model = cls(**kwargs)
    #key1, key2 = jr.split(jr.PRNGKey(int(datetime.now().timestamp())))
    key1, key2 = jr.split(jr.PRNGKey(0))
    params, param_props = model.random_initialization(key1)
    states, emissions = model.sample(params, key2, num_timesteps=NUM_TIMESTEPS, covariates=covariates)
    fitted_params, lps = model.fit_em(params, param_props, emissions, covariates=covariates, num_iters=10)
    assert monotonically_increasing(lps)
    fitted_params, lps = model.fit_sgd(params, param_props, emissions, covariates=covariates, num_epochs=10)
