import litellm

from harness import litellm_caller as lc


def test_retryable_targets_transient_errors_not_auth():
    # transient provider failures are retried...
    assert litellm.RateLimitError in lc._RETRYABLE
    assert litellm.Timeout in lc._RETRYABLE
    # ...but auth/bad-request (non-retryable) are NOT, so they fail fast
    assert getattr(litellm, "AuthenticationError", None) not in lc._RETRYABLE
    assert getattr(litellm, "BadRequestError", None) not in lc._RETRYABLE
