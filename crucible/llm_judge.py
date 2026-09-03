#!/usr/bin/env python3
"""LLM-based judge for subjective rubric criteria.

Uses a local Ollama model (via its OpenAI-compatible /v1 endpoint) or an
OpenRouter cloud model to score rubric criteria that deterministic code
cannot check objectively.

Usage:
    from crucible.llm_judge import LLMJudge
    judge = LLMJudge("ollama/qwen3:14b")
    scores = judge.judge(prompt_def, model_output, skip={"Correct answer"})
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
import urllib.error
from pathlib import Path

from crucible.constants import LMSTUDIO_BASE_URL, OLLAMA_OPENAI_API, OPENROUTER_API

MAX_OUTPUT_CHARS = 4000  # truncate model output in the judge prompt


def _parse_judge_model(model: str) -> tuple[str, str]:
    """Parse 'provider/model' into (provider, model_id)."""
    if model.startswith("ollama/"):
        return "ollama", model[len("ollama/"):]
    if model.startswith("openrouter/"):
        return "openrouter", model[len("openrouter/"):]
    if model.startswith("lmstudio/"):
        return "lmstudio", model[len("lmstudio/"):]
    raise ValueError(
        f"Unsupported judge model prefix: {model}. "
        "Use ollama/..., openrouter/..., or lmstudio/..."
    )


JUDGE_PROMPT_TEMPLATE = """\
You are an objective evaluator scoring an AI agent's response against a rubric.
Score each criterion honestly on a 0–{max} scale. Return ONLY a JSON object
mapping criterion names to numeric scores. Do not include any other text.

TASK:
{task_prompt}

RUBRIC CRITERIA (criterion: max_score — description):
{rubric_lines}

MODEL RESPONSE:
{model_output}

CRITICAL FAILURE: {critical_failure}
If the critical failure condition is triggered, cap the overall score
accordingly but still score each criterion individually.

Return JSON: {{"criterion name": score, ...}}"""


class LLMJudge:
    """Judge rubric criteria using an LLM (Ollama, OpenRouter, or LM Studio)."""

    def __init__(self, model: str):
        self.provider, self.model_id = _parse_judge_model(model)

    def _build_prompt(self, prompt_def: dict, model_output: str,
                     skip: set[str] | None = None) -> list[dict]:
        """Build the chat message list for the judge call."""
        rubric = prompt_def.get("rubric", [])
        rubric_lines = "\n".join(
            f'  "{item["criterion"]}" (0-{item["max_score"]}): {item.get("description", "")}'
            for item in rubric
        )

        task_prompt = prompt_def.get("prompt", "")
        critical = prompt_def.get("critical_failure") or "None"

        # Truncate model output if very long
        output = model_output
        if len(output) > MAX_OUTPUT_CHARS:
            output = output[-MAX_OUTPUT_CHARS:] + "\n...[truncated]"

        # Determine max score for the template
        max_score = max((item["max_score"] for item in rubric), default=10)

        judge_text = JUDGE_PROMPT_TEMPLATE.format(
            max=max_score,
            task_prompt=task_prompt,
            rubric_lines=rubric_lines,
            model_output=output,
            critical_failure=critical,
        )

        return [{"role": "user", "content": judge_text}]

    def _chat_complete(self, messages: list[dict]) -> str:
        """Send chat completion request and return the response text."""
        body = json.dumps({
            "model": self.model_id,
            "messages": messages,
            "temperature": 0.2,
            "stream": False,
        }).encode()

        if self.provider == "ollama":
            url = f"{OLLAMA_OPENAI_API}/chat/completions"
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        elif self.provider == "lmstudio":
            url = f"{LMSTUDIO_BASE_URL}/chat/completions"
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        elif self.provider == "openrouter":
            api_key = os.environ.get("OPENROUTER_API_KEY")
            if not api_key:
                raise RuntimeError("OPENROUTER_API_KEY env var required for openrouter judge")
            url = f"{OPENROUTER_API}/chat/completions"
            req = urllib.request.Request(
                url, data=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/schaferandrew/crucible",
                    "X-Title": "Crucible LLM Judge",
                },
                method="POST",
            )
        else:
            raise ValueError(f"Unknown judge provider: {self.provider}")

        try:
            resp = urllib.request.urlopen(req, timeout=120)
            data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            try:
                err = e.read().decode("utf-8", errors="replace")
            except (AttributeError, OSError):
                err = str(e)
            raise RuntimeError(f"Judge API error ({e.code}): {err}") from e
        except URLError as e:
            raise RuntimeError(f"Judge connection failed: {e.reason}") from e
        except Exception as e:
            raise RuntimeError(f"Judge API call failed: {e}") from e

        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError(f"No choices in judge response: {data}")
        message = choices[0].get("message", {})
        if isinstance(message.get("content"), list):
            return "".join(p.get("text", "") for p in message["content"] if isinstance(p, dict))
        return message.get("content", "")

    def judge(self, prompt_def: dict, model_output: str,
              skip: set[str] | None = None) -> dict[str, float]:
        """Judge rubric criteria, skipping those already scored.

        Args:
            prompt_def: The loaded prompt YAML as a dict.
            model_output: The model's output text.
            skip: Set of criterion names already scored by deterministic grader.

        Returns:
            dict mapping criterion name -> score (float).
        """
        skip = skip or set()
        messages = self._build_prompt(prompt_def, model_output, skip)
        response = self._chat_complete(messages)
        return _parse_scores(response, prompt_def.get("rubric", []), skip)

    def judge_text(self, prompt_text: str, rubric: list[dict],
                   model_output: str,
                   critical_failure: str | None = None,
                   skip: set[str] | None = None) -> dict[str, float]:
        """Judge using raw prompt text + rubric instead of a loaded prompt_def."""
        prompt_def = {
            "prompt": prompt_text,
            "rubric": rubric,
            "critical_failure": critical_failure,
        }
        return self.judge(prompt_def, model_output, skip)


def _parse_scores(response: str, rubric: list[dict],
                   skip: set[str] | None = None) -> dict[str, float]:
    """Parse JSON scores from the LLM response, mapping to rubric criteria."""
    skip = skip or set()
    max_by_criterion = {item["criterion"]: item["max_score"] for item in rubric}

    # Try direct JSON parse first
    scores: dict[str, float] = {}
    try:
        raw = json.loads(response.strip())
    except json.JSONDecodeError:
        # Try to find a JSON object in the response
        decoder = json.JSONDecoder()
        try:
            raw, _ = decoder.raw_decode(response.strip())
        except json.JSONDecodeError:
            # Fallback: regex extraction of "criterion": score patterns
            raw = {}
            for match in re.finditer(r'"([^"]+)"\s*:\s*([\d.]+)', response):
                raw[match.group(1)] = float(match.group(2))

    if isinstance(raw, dict):
        for key, val in raw.items():
            if key in skip:
                continue
            if key in max_by_criterion:
                try:
                    score = float(val)
                    max_s = max_by_criterion[key]
                    score = max(0.0, min(max_s, score))
                    scores[key] = score
                except (ValueError, TypeError):
                    pass
    elif isinstance(raw, list):
        # Some models return a list of {"criterion": ..., "score": ...}
        for entry in raw:
            if isinstance(entry, dict):
                crit = entry.get("criterion") or entry.get("name")
                score = entry.get("score") or entry.get("value")
                if crit and crit in max_by_criterion and crit not in skip:
                    try:
                        score = max(0.0, min(max_by_criterion[crit], float(score)))
                        scores[crit] = score
                    except (ValueError, TypeError):
                        pass

    # For any rubric criteria not in the response, assign 0 (unscored by judge)
    if not scores:
        # If we got nothing, return partial zeros for non-skipped criteria
        return scores

    return scores
