"""Tests for instinct_decay.run_decay() - confidence decay and archiving."""

import importlib.util
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

# Load instinct-cli.py (hyphenated filename requires importlib)
_spec = importlib.util.spec_from_file_location(
    "instinct_cli",
    os.path.join(os.path.dirname(__file__), "instinct-cli.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
parse_instinct_file = _mod.parse_instinct_file

# Load instinct_decay module
_decay_spec = importlib.util.spec_from_file_location(
    "instinct_decay",
    os.path.join(os.path.dirname(__file__), "instinct_decay.py"),
)
_decay_mod = importlib.util.module_from_spec(_decay_spec)
_decay_spec.loader.exec_module(_decay_mod)
run_decay = _decay_mod.run_decay


def _make_instinct_file(directory, filename, instinct_id, confidence,
                        last_observed=None, observed_count=1):
    """Create a sample instinct YAML file in the given directory."""
    content = "---\n"
    content += f"id: {instinct_id}\n"
    content += f'trigger: "when testing"\n'
    content += f"confidence: {confidence}\n"
    content += f"domain: testing\n"
    if last_observed:
        content += f"last_observed: {last_observed}\n"
    if observed_count:
        content += f"observed_count: {observed_count}\n"
    content += "---\n\n## Action\nDo something useful.\n"
    filepath = directory / filename
    filepath.write_text(content)
    return filepath


class TestDecayNormal:
    """Test normal confidence decay after 1 week."""

    def test_7_days_decays_by_0_02(self, tmp_path):
        personal = tmp_path / "personal"
        personal.mkdir()
        archived = tmp_path / "archived"
        archived.mkdir()

        last_obs = (datetime.now() - timedelta(days=7)).isoformat()
        _make_instinct_file(personal, "test.yaml", "test-inst", 0.8,
                            last_observed=last_obs)

        with patch.object(_decay_mod, '_load_config', return_value={
            'instincts': {
                'confidence_decay_rate': 0.02,
                'min_confidence': 0.3,
            }
        }):
            run_decay(personal, archived, parse_instinct_file)

        content = (personal / "test.yaml").read_text()
        parsed = parse_instinct_file(content)
        assert len(parsed) == 1
        # 0.8 - (1 week * 0.02) = 0.78
        assert abs(parsed[0]['confidence'] - 0.78) < 0.01


class TestDecayMultiWeek:
    """Test 4-week decay."""

    def test_28_days_decays_by_0_08(self, tmp_path):
        personal = tmp_path / "personal"
        personal.mkdir()
        archived = tmp_path / "archived"
        archived.mkdir()

        last_obs = (datetime.now() - timedelta(days=28)).isoformat()
        _make_instinct_file(personal, "test.yaml", "test-inst", 0.9,
                            last_observed=last_obs)

        with patch.object(_decay_mod, '_load_config', return_value={
            'instincts': {
                'confidence_decay_rate': 0.02,
                'min_confidence': 0.3,
            }
        }):
            run_decay(personal, archived, parse_instinct_file)

        content = (personal / "test.yaml").read_text()
        parsed = parse_instinct_file(content)
        assert len(parsed) == 1
        # 0.9 - (4 weeks * 0.02) = 0.82
        assert abs(parsed[0]['confidence'] - 0.82) < 0.01


class TestDecayArchive:
    """Test archiving when confidence drops below threshold."""

    def test_below_threshold_moves_to_archived(self, tmp_path):
        personal = tmp_path / "personal"
        personal.mkdir()
        archived = tmp_path / "archived"
        archived.mkdir()

        # confidence 0.35. After 4 weeks: 0.35 - 0.08 = 0.27 < 0.3
        last_obs = (datetime.now() - timedelta(days=28)).isoformat()
        _make_instinct_file(personal, "low.yaml", "low-inst", 0.35,
                            last_observed=last_obs)

        with patch.object(_decay_mod, '_load_config', return_value={
            'instincts': {
                'confidence_decay_rate': 0.02,
                'min_confidence': 0.3,
            }
        }):
            run_decay(personal, archived, parse_instinct_file)

        # Source file should be removed
        assert not (personal / "low.yaml").exists()
        # Archived file should exist
        assert (archived / "low.yaml").exists()


class TestDecayDryRun:
    """Test dry-run mode does not modify files."""

    def test_dry_run_no_changes(self, tmp_path):
        personal = tmp_path / "personal"
        personal.mkdir()
        archived = tmp_path / "archived"
        archived.mkdir()

        last_obs = (datetime.now() - timedelta(days=14)).isoformat()
        _make_instinct_file(personal, "test.yaml", "test-inst", 0.8,
                            last_observed=last_obs)

        original_content = (personal / "test.yaml").read_text()

        with patch.object(_decay_mod, '_load_config', return_value={
            'instincts': {
                'confidence_decay_rate': 0.02,
                'min_confidence': 0.3,
            }
        }):
            run_decay(personal, archived, parse_instinct_file,
                      dry_run=True)

        # File content should be unchanged
        assert (personal / "test.yaml").read_text() == original_content


class TestDecayNoLastObserved:
    """Test instinct without last_observed is skipped."""

    def test_no_last_observed_skips(self, tmp_path):
        personal = tmp_path / "personal"
        personal.mkdir()
        archived = tmp_path / "archived"
        archived.mkdir()

        # No last_observed field
        _make_instinct_file(personal, "test.yaml", "test-inst", 0.8)

        original_content = (personal / "test.yaml").read_text()

        with patch.object(_decay_mod, '_load_config', return_value={
            'instincts': {
                'confidence_decay_rate': 0.02,
                'min_confidence': 0.3,
            }
        }):
            run_decay(personal, archived, parse_instinct_file)

        # File should remain unchanged
        assert (personal / "test.yaml").read_text() == original_content
