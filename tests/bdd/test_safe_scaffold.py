"""Executable pytest-bdd bindings for safe scaffold capability reporting."""

from pytest_bdd import scenarios, then, when

from job_search_hh.capabilities import Capabilities, current_capabilities

scenarios("../features/safe_scaffold.feature")


@when("оператор запрашивает возможности HH-интеграции", target_fixture="capabilities")
def request_capabilities() -> Capabilities:
    """Read the public capability contract without network or browser side effects."""
    return current_capabilities()


@then("ответ идентифицирует компонент job-search-hh")
def response_identifies_hh(capabilities: Capabilities) -> None:
    """Prevent accidental wiring to another sibling component."""
    assert capabilities.component == "job-search-hh"


@then("внешние записи выключены")
def external_writes_are_disabled(capabilities: Capabilities) -> None:
    """Keep the primary safety invariant observable in acceptance tests."""
    assert capabilities.external_writes_enabled is False


@then("browser automation не объявлена готовой")
def browser_is_not_ready(capabilities: Capabilities) -> None:
    """Do not report Playwright readiness before its dedicated implementation slice."""
    assert capabilities.browser_automation == "not-configured"
