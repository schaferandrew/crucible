"""Turn --provider / --model CLI arguments into one 'provider/model' string."""
from __future__ import annotations

import sys

from crucible import providers
from crucible.model_picker import pick_model
from crucible.selector import select_from_list


def _choose(options: list[str], title: str, none_found: str) -> str:
    """The single option, or an interactive pick; exits when there is nothing to pick."""
    if not options:
        print(none_found)
        sys.exit(1)
    if len(options) == 1:
        return options[0]
    selected = select_from_list(options, title)
    if selected is None:
        print("Cancelled.")
        sys.exit(0)
    return selected


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _picked(model: str | None) -> str:
    if model is None:
        print("Cancelled.")
        sys.exit(0)
    return model


def resolve_model(provider: str | None, model: str | None) -> str | None:
    """Resolve the final provider/model string; None means the agent's default.

    - provider + model: join them (without doubling an existing prefix)
    - model with a '/': used as-is
    - bare model: looked up across providers
    - provider only: pick from that provider's models
    """
    if provider and model:
        return model if model.startswith(f"{provider}/") else f"{provider}/{model}"
    if model and "/" in model:
        return model
    if model and _interactive():
        # One exact hit needs no question; otherwise browse every provider, filtered by the name
        found = providers.find_model_matches(model)
        return found[0] if len(found) == 1 else _picked(pick_model(initial=model))
    if model:
        return _choose(providers.find_model_matches(model),
                       f"Model '{model}' found on multiple providers:",
                       none_found=f"Model '{model}' not found on any provider.")
    if provider:
        if provider not in providers.PROVIDERS:
            print(f"Unknown provider: {provider}")
            sys.exit(1)
        if _interactive():
            return _picked(pick_model(f"Select {provider} model:", provider_names=[provider]))
        entry = providers.PROVIDERS[provider]
        return _choose([f"{provider}/{m}" for m in entry.list_models()],
                       f"Select {provider} model:", none_found=entry.empty_hint)
    return None
