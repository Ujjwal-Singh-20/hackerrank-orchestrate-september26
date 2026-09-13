"""Typed failure modes. Every raise in the pipeline goes through one of these;
each carries a `cause` string usable in the run manifest / usage report."""

from __future__ import annotations


class RouterError(Exception):
    """Base class for all pipeline failures."""

    def __init__(self, message: str, cause: str):
        super().__init__(message)
        self.cause = cause


class DatasetError(RouterError):
    """CSV missing, malformed, unjoinable keys, bad dates/amounts."""

    def __init__(self, message: str):
        super().__init__(message, cause="dataset")


class ExtractionError(RouterError):
    """Perception failed: unreadable image, unparseable message."""

    def __init__(self, message: str):
        super().__init__(message, cause="perception")


class ForecastError(RouterError):
    """Simulation could not run: missing exchange rate, degenerate series."""

    def __init__(self, message: str):
        super().__init__(message, cause="forecast")


class PolicyError(RouterError):
    """No plan could be produced or ranking invariants broke."""

    def __init__(self, message: str):
        super().__init__(message, cause="policy")


class OutputContractError(RouterError):
    """A produced OutputRow violates the required output contract."""

    def __init__(self, message: str):
        super().__init__(message, cause="output_contract")