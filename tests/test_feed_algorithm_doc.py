"""Adversarial gate: FEED_ALGORITHM.md must not drift from the ranker code.

The operator-facing spec documents the default weights. If someone changes a default
in feed_ranker.py (or edits the doc) without updating the other, this test fails — so
the published algorithm can never quietly diverge from what actually runs.
"""

import re
from pathlib import Path

from runtime.social.feed_ranker import FeedWeights

DOC = Path(__file__).resolve().parent.parent / "FEED_ALGORITHM.md"


def _documented_weights() -> dict[str, float]:
    """Parse the `| knob | default | meaning |` rows out of the weights table."""
    text = DOC.read_text(encoding="utf-8")
    weights: dict[str, float] = {}
    row = re.compile(r"^\|\s*`([a-z_]+)`\s*\|\s*`([-\d.]+)`\s*\|")
    for line in text.splitlines():
        m = row.match(line.strip())
        if m:
            weights[m.group(1)] = float(m.group(2))
    return weights


def test_doc_exists_and_has_a_weights_table():
    assert DOC.exists(), "FEED_ALGORITHM.md must be committed alongside the ranker"
    assert _documented_weights(), "the weights table must be parseable"


def test_documented_defaults_match_code_defaults():
    documented = _documented_weights()
    actual = FeedWeights()
    for name, value in documented.items():
        assert hasattr(actual, name), f"doc documents unknown weight '{name}'"
        assert getattr(actual, name) == value, (
            f"drift: FEED_ALGORITHM.md says {name}={value} but code default is "
            f"{getattr(actual, name)}"
        )


def test_every_code_weight_is_documented():
    documented = set(_documented_weights())
    code = set(FeedWeights.__dataclass_fields__)
    missing = code - documented
    assert not missing, f"weights in code but undocumented in FEED_ALGORITHM.md: {missing}"


def test_doc_states_no_ml_and_privacy_absolute():
    text = DOC.read_text(encoding="utf-8").lower()
    assert "no machine learning" in text
    assert "private" in text and "never" in text  # privacy guarantee is stated


def test_default_config_feed_ranker_matches_code_defaults():
    # The live feed builds weights from SocialService DEFAULT_CONFIG['feed_ranker'],
    # so THAT copy of the defaults must also match FeedWeights() — otherwise the
    # running feed could silently diverge from the dataclass and the doc.
    from runtime.blockchain.services.social.service import DEFAULT_CONFIG

    actual = FeedWeights()
    cfg = DEFAULT_CONFIG["feed_ranker"]
    for name, value in cfg.items():
        assert hasattr(actual, name), f"DEFAULT_CONFIG documents unknown weight '{name}'"
        assert getattr(actual, name) == value, (
            f"drift: DEFAULT_CONFIG says {name}={value} but code default is "
            f"{getattr(actual, name)}"
        )
    # and every knob is present in DEFAULT_CONFIG (no silent omission)
    assert set(cfg) == set(FeedWeights.__dataclass_fields__)
