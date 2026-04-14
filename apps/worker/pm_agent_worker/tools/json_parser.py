import json
from typing import Any


def parse_first_json_object(text: str) -> Any:
    text = text.strip()
    if not text:
        raise ValueError("empty response")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = min([index for index in [text.find("{"), text.find("[")] if index != -1], default=-1)
    if start == -1:
        raise ValueError("no json object found")

    for end in range(len(text), start, -1):
        snippet = text[start:end]
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            continue
    raise ValueError("unable to parse json payload")

