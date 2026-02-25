"""Tests for instinct_learn - observation analysis and pattern extraction."""

import importlib.util
import json
import os
import tempfile
from pathlib import Path

# Load instinct_learn module
_learn_spec = importlib.util.spec_from_file_location(
    "instinct_learn",
    os.path.join(os.path.dirname(__file__), "instinct_learn.py"),
)
_learn_mod = importlib.util.module_from_spec(_learn_spec)
_learn_spec.loader.exec_module(_learn_mod)

_load_observations = _learn_mod._load_observations
_detect_repeated_workflows = _learn_mod._detect_repeated_workflows
_detect_user_corrections = _learn_mod._detect_user_corrections
_detect_error_fixes = _learn_mod._detect_error_fixes
_deduplicate = _learn_mod._deduplicate
_group_by_session = _learn_mod._group_by_session
run_learn = _learn_mod.run_learn


def _write_observations(path, observations):
    """Write observation dicts as JSONL file."""
    with open(path, 'w') as f:
        for obs in observations:
            f.write(json.dumps(obs) + '\n')


class TestDetectRepeatedWorkflows:
    """Test repeated workflow detection."""

    def test_detects_3_plus_occurrences(self):
        sessions = {
            's1': [
                {'tool': 'Grep', 'event': 'tool_start'},
                {'tool': 'Read', 'event': 'tool_start'},
                {'tool': 'Edit', 'event': 'tool_start'},
            ],
            's2': [
                {'tool': 'Grep', 'event': 'tool_start'},
                {'tool': 'Read', 'event': 'tool_start'},
                {'tool': 'Edit', 'event': 'tool_start'},
            ],
            's3': [
                {'tool': 'Grep', 'event': 'tool_start'},
                {'tool': 'Read', 'event': 'tool_start'},
                {'tool': 'Edit', 'event': 'tool_start'},
            ],
        }
        result = _detect_repeated_workflows(sessions, min_occurrences=3)
        assert len(result) >= 1
        assert any('grep' in c['id'] for c in result)

    def test_ignores_below_threshold(self):
        sessions = {
            's1': [
                {'tool': 'Grep', 'event': 'tool_start'},
                {'tool': 'Read', 'event': 'tool_start'},
                {'tool': 'Edit', 'event': 'tool_start'},
            ],
        }
        result = _detect_repeated_workflows(sessions, min_occurrences=3)
        assert len(result) == 0


class TestDeduplication:
    """Test deduplication against existing instincts."""

    def test_existing_gets_boosted(self):
        candidates = [{'id': 'existing-pattern'}]
        existing = [{'id': 'existing-pattern', 'confidence': 0.6}]

        new, boosted = _deduplicate(candidates, existing)
        assert len(new) == 0
        assert len(boosted) == 1
        assert boosted[0]['new_confidence'] == 0.65

    def test_new_candidate_passes_through(self):
        candidates = [{'id': 'brand-new-pattern'}]
        existing = [{'id': 'other-pattern', 'confidence': 0.6}]

        new, boosted = _deduplicate(candidates, existing)
        assert len(new) == 1
        assert len(boosted) == 0


class TestRunLearnEmpty:
    """Test learn with empty observations."""

    def test_empty_file_exits_clean(self, tmp_path):
        obs_path = tmp_path / "observations.jsonl"
        obs_path.write_text("")
        personal = tmp_path / "personal"
        personal.mkdir()

        result = run_learn(obs_path, [], personal)
        assert result == 0


class TestRunLearnWithData:
    """Test learn with sample observation data."""

    def test_detects_patterns_from_observations(self, tmp_path):
        obs_path = tmp_path / "observations.jsonl"
        personal = tmp_path / "personal"
        personal.mkdir()

        # Create observations that form a repeated workflow
        observations = []
        for session_num in range(4):
            sid = f"session-{session_num}"
            for tool in ['Grep', 'Read', 'Edit']:
                observations.append({
                    'session': sid,
                    'event': 'tool_start',
                    'tool': tool,
                    'timestamp': '2025-01-22T10:00:00Z',
                })

        _write_observations(obs_path, observations)

        result = run_learn(obs_path, [], personal, execute=False)
        assert result == 0
