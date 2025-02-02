# Parallel filtering and smoothing for a lgssm.
# This implementation is adapted from the work of Adrien Correnflos in,
#  https://github.com/EEA-sensors/sequential-parallelization-examples/
from jax import numpy as jnp
from jax import scipy as jsc
from jax import vmap, lax

from dynamax.containers import GSSMPosterior

def make_associative_filtering_elements(params, emissions):
    """Preprocess observations to construct input for filtering assocative scan."""

    def _first_filtering_element(params, y):
        F = params.dynamics_matrix
        H = params.emission_matrix
        Q = params.dynamics_covariance
        R = params.emission_covariance
        
        S = H @ Q @ H.T + R
        CF, low = jsc.linalg.cho_factor(S)

        m1 = params.initial_mean
        P1 = params.initial_covariance
        S1 = H @ P1 @ H.T + R
        K1 = jsc.linalg.solve(S1, H @ P1, assume_a='pos').T

        A = jnp.zeros_like(F)
        b = m1 + K1 @ (y - H @ m1)
        C = P1 - K1 @ S1 @ K1.T

        eta = F.T @ H.T @ jsc.linalg.cho_solve((CF, low), y)
        J = F.T @ H.T @ jsc.linalg.cho_solve((CF, low), H @ F)
        return A, b, C, J, eta


    def _generic_filtering_element(params, y):
        F = params.dynamics_matrix
        H = params.emission_matrix
        Q = params.dynamics_covariance
        R = params.emission_covariance
        
        S = H @ Q @ H.T + R
        CF, low = jsc.linalg.cho_factor(S)  
        K = jsc.linalg.cho_solve((CF, low), H @ Q).T  
        A = F - K @ H @ F
        b = K @ y
        C = Q - K @ H @ Q

        eta = F.T @ H.T @ jsc.linalg.cho_solve((CF, low), y)
        J = F.T @ H.T @ jsc.linalg.cho_solve((CF, low), H @ F)
        return A, b, C, J, eta

    first_elems = _first_filtering_element(params, emissions[0])
    generic_elems = vmap(_generic_filtering_element, (None, 0))(params, emissions[1:])
    combined_elems = tuple(jnp.concatenate((first_elm[None,...], gen_elm))
                           for first_elm, gen_elm in zip(first_elems, generic_elems))
    return combined_elems

def lgssm_filter(params, emissions):
    """A parallel version of the lgssm filtering algorithm.

    See S. Särkkä and Á. F. García-Fernández (2021) - https://arxiv.org/abs/1905.13002.
    
    Note: This function does not yet handle `inputs` to the system.
    """
    #TODO: Add marginal loglikelihood calculation.
    #TODO: Add input handling.
    initial_elements = make_associative_filtering_elements(params, emissions)

    @vmap
    def filtering_operator(elem1, elem2):
        A1, b1, C1, J1, eta1 = elem1
        A2, b2, C2, J2, eta2 = elem2
        dim = A1.shape[0]
        I = jnp.eye(dim)  

        I_C1J2 = I + C1 @ J2
        temp = jsc.linalg.solve(I_C1J2.T, A2.T).T
        A = temp @ A1
        b = temp @ (b1 + C1 @ eta2) + b2
        C = temp @ C1 @ A2.T + C2

        I_J2C1 = I + J2 @ C1
        temp = jsc.linalg.solve(I_J2C1.T, A1).T

        eta = temp @ (eta2 - J2 @ b1) + eta1
        J = temp @ J2 @ A1 + J1

        return A, b, C, J, eta

    _, filtered_means, filtered_covs, *_ = lax.associative_scan(
                                                filtering_operator, initial_elements
                                                )
    return GSSMPosterior(filtered_means=filtered_means, filtered_covariances=filtered_covs)



def make_associative_smoothing_elements(params, filtered_means, filtered_covariances):
    """Preprocess filtering output to construct input for smoothing assocative scan."""

    def _last_smoothing_element(m, P):
        return jnp.zeros_like(P), m, P

    def _generic_smoothing_element(params, m, P):
        F = params.dynamics_matrix
        H = params.emission_matrix
        Q = params.dynamics_covariance
        R = params.emission_covariance

        Pp = F @ P @ F.T + Q

        E  = jsc.linalg.solve(Pp, F @ P, assume_a='pos').T
        g  = m - E @ F @ m
        L  = P - E @ Pp @ E.T
        return E, g, L

    last_elems = _last_smoothing_element(filtered_means[-1], filtered_covariances[-1])
    generic_elems = vmap(_generic_smoothing_element, (None, 0, 0))(
        params, filtered_means[:-1], filtered_covariances[:-1]
        )
    combined_elems = tuple(jnp.append(gen_elm, last_elm[None,:], axis=0)
                           for gen_elm, last_elm in zip(generic_elems, last_elems))
    return combined_elems


def lgssm_smoother(params, emissions):
    """A parallel version of the lgssm smoothing algorithm.

    See S. Särkkä and Á. F. García-Fernández (2021) - https://arxiv.org/abs/1905.13002.

    Note: This function does not yet handle `inputs` to the system.
    """
    filtered_posterior = lgssm_filter(params, emissions)
    filtered_means = filtered_posterior.filtered_means
    filtered_covs = filtered_posterior.filtered_covariances
    initial_elements = make_associative_smoothing_elements(params, filtered_means, filtered_covs)

    @vmap
    def smoothing_operator(elem1, elem2):
        E1, g1, L1 = elem1
        E2, g2, L2 = elem2

        E = E2 @ E1
        g = E2 @ g1 + g2
        L = E2 @ L1 @ E2.T + L2

        return E, g, L

    _, smoothed_means, smoothed_covs, *_ = lax.associative_scan(
                                                smoothing_operator, initial_elements, reverse=True
                                                )
    return GSSMPosterior(
        filtered_means=filtered_means,
        filtered_covariances=filtered_covs,
        smoothed_means=smoothed_means,
        smoothed_covariances=smoothed_covs
    )
