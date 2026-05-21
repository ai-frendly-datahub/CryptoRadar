from __future__ import annotations

from cryptoradar.resilience import SourceCircuitBreakerManager, get_circuit_breaker_manager


def test_circuit_breaker_manager_reuses_breakers_per_source() -> None:
    manager = SourceCircuitBreakerManager()

    first = manager.get_breaker("SourceA")
    second = manager.get_breaker("SourceA")
    other = manager.get_breaker("SourceB")

    assert first is second
    assert first is not other
    assert manager.get_status() == {"SourceA": "closed", "SourceB": "closed"}


def test_circuit_breaker_manager_reset_methods_keep_registry() -> None:
    manager = SourceCircuitBreakerManager()
    breaker = manager.get_breaker("SourceA")

    manager.reset_breaker("SourceA")
    manager.reset_breaker("MissingSource")
    manager.reset_all()

    assert manager.get_breaker("SourceA") is breaker
    assert manager.get_status()["SourceA"] == "closed"


def test_global_circuit_breaker_manager_is_singleton() -> None:
    assert get_circuit_breaker_manager() is get_circuit_breaker_manager()
