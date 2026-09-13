"""Validated per-verifier request limits; not a monetary or token-cost guarantee."""

import os

from pydantic import Field

from services.analysis.domain import Contract


class VerificationLimits(Contract):
    max_requests: int = Field(default=10, ge=1, le=50)
    elapsed_seconds: int = Field(default=45, ge=1, le=300)
    output_tokens: int = Field(default=1500, ge=100, le=3000)

    @classmethod
    def configured(cls):
        keys = {
            "max_requests": "SPECGUARD_VERIFIER_MAX_REQUESTS",
            "elapsed_seconds": "SPECGUARD_VERIFIER_SECONDS",
            "output_tokens": "SPECGUARD_VERIFIER_OUTPUT_TOKENS",
        }
        try:
            return cls.model_validate(
                {field: os.environ[key] for field, key in keys.items() if key in os.environ}
            )
        except ValueError as error:
            raise ValueError("Invalid verifier limit configuration") from error

    def identity(self) -> str:
        return f"requests-{self.max_requests}/seconds-{self.elapsed_seconds}/output-{self.output_tokens}"
