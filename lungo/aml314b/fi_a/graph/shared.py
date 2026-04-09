from typing import Optional

from agntcy_app_sdk.factory import AgntcyFactory

_factory: Optional[AgntcyFactory] = None


def set_factory(factory: AgntcyFactory) -> None:
    global _factory
    _factory = factory


def get_factory() -> AgntcyFactory:
    if _factory is None:
        return AgntcyFactory("lungo.aml314b.fi_a", enable_tracing=True)
    return _factory
