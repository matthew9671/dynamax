import chex
import jax.numpy as jnp
from jax import lax
from jax import vmap
from jax import value_and_grad

from dynamax.hmm.inference import HMMPosterior

@chex.dataclass
class Message:
    A: chex.Array
    log_b: chex.Array


def _condition_on(A, ll, axis=-1):
    ll_max = ll.max(axis=axis)
    A_cond = A * jnp.exp(ll - ll_max)
    norm = A_cond.sum(axis=axis)
    A_cond /= jnp.expand_dims(norm, axis=axis)
    return A_cond, jnp.log(norm) + ll_max


def hmm_filter(initial_probs, transition_matrix, log_likelihoods):
    T, K = log_likelihoods.shape

    @vmap
    def marginalize(m_ij, m_jk):
        A_ij_cond, lognorm = _condition_on(m_ij.A, m_jk.log_b)
        A_ik = A_ij_cond @ m_jk.A
        log_b_ik = m_ij.log_b + lognorm
        return Message(A=A_ik, log_b=log_b_ik)


    # Initialize the messages
    A0, log_b0 = _condition_on(initial_probs, log_likelihoods[0])
    A0 *= jnp.ones((K, K))
    log_b0 *= jnp.ones(K)
    A1T, log_b1T = vmap(_condition_on, in_axes=(None, 0))(transition_matrix, log_likelihoods[1:])
    initial_messages = Message(
        A=jnp.concatenate([A0[None, :, :], A1T]),
        log_b=jnp.vstack([log_b0, log_b1T])
    )

    # Run the associative scan
    partial_messages = lax.associative_scan(marginalize, initial_messages)

    # Extract the marginal log likelihood and filtered probabilities
    marginal_loglik = partial_messages.log_b[-1,0]
    filtered_probs = partial_messages.A[:, 0, :]

    # Compute the predicted probabilities
    predicted_probs = jnp.vstack([initial_probs, filtered_probs[:-1] @ transition_matrix])

    # Package into a posterior object
    return HMMPosterior(marginal_loglik=marginal_loglik,
                        filtered_probs=filtered_probs,
                        predicted_probs=predicted_probs)


def hmm_smoother(initial_probs, transition_matrix, log_likelihoods):
    """A parallel implementation of `hmm_smoother`.
    NOTE: This implementation uses the gradient of the HMM log normalizer
    rather than an explicit implementation of the backward message passing.

    Args:
        initial_probs (_type_): _description_
        transition_matrix (_type_): _description_
        log_likelihoods (_type_): _description_
    """
    def log_normalizer(log_initial_probs, log_transition_matrix, log_likelihoods):
        post = hmm_filter(jnp.exp(log_initial_probs),
                                   jnp.exp(log_transition_matrix),
                                   log_likelihoods)
        return post.marginal_loglik, post

    f = value_and_grad(log_normalizer, has_aux=True, argnums=(1, 2))
    (marginal_loglik, fwd_post), (trans_probs, smoothed_probs) = \
        f(jnp.log(initial_probs), jnp.log(transition_matrix), log_likelihoods)

    return HMMPosterior(
        marginal_loglik=marginal_loglik,
        filtered_probs=fwd_post.filtered_probs,
        predicted_probs=fwd_post.predicted_probs,
        initial_probs=smoothed_probs[0],
        smoothed_probs=smoothed_probs,
        trans_probs=trans_probs
    )