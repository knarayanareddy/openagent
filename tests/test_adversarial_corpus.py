import json
from pathlib import Path

from openagent.security import RegexThreatScanner


def test_adversarial_corpus_seed():
    scanner = RegexThreatScanner()
    corpus = Path(__file__).parent / "adversarial_corpus" / "prompt_injection.jsonl"
    for line in corpus.read_text().splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        verdict = scanner.scan(case["text"])
        if case["expect_blocked"]:
            assert not verdict.ok, case
        else:
            assert verdict.ok, case
