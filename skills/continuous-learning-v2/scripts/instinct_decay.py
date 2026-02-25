"""
instinct_decay - Apply confidence decay to stale instincts.

Instincts without recent observations lose confidence over time.
Those falling below the minimum threshold are archived.
"""

import json
import sys
from datetime import datetime
from pathlib import Path


def _load_config() -> dict:
    """Load config.json from the skill directory."""
    config_path = Path(__file__).resolve().parent.parent / "config.json"
    try:
        return json.loads(config_path.read_text())
    except Exception:
        return {}


def write_instinct_file(filepath: Path, instinct: dict) -> None:
    """Write a single instinct dict back to its YAML-like file."""
    output = "---\n"
    for key in ['id', 'trigger', 'confidence', 'domain', 'source',
                'last_observed', 'observed_count', 'source_repo',
                'imported_from']:
        if key in instinct:
            value = instinct[key]
            if key == 'trigger':
                output += f'{key}: "{value}"\n'
            elif key == 'confidence':
                output += f'{key}: {value:.2f}\n'
            else:
                output += f'{key}: {value}\n'
    output += "---\n\n"
    output += instinct.get('content', '') + "\n"
    filepath.write_text(output)


def run_decay(
    personal_dir: Path,
    archived_dir: Path,
    parse_fn,
    dry_run: bool = False,
) -> int:
    """Apply confidence decay to personal instincts.

    Args:
        personal_dir: Path to personal instincts directory
        archived_dir: Path to archived instincts directory
        parse_fn: Function to parse instinct file content
        dry_run: If True, preview changes without applying

    Returns:
        Exit code
    """
    config = _load_config()
    instincts_cfg = config.get('instincts', {})
    decay_rate = instincts_cfg.get('confidence_decay_rate', 0.02)
    min_confidence = instincts_cfg.get('min_confidence', 0.3)
    now = datetime.now()

    if not personal_dir.exists():
        print("No personal instincts directory found.")
        return 0

    files = sorted(
        set(personal_dir.glob("*.yaml"))
        | set(personal_dir.glob("*.yml"))
        | set(personal_dir.glob("*.md"))
    )
    if not files:
        print("No personal instinct files found.")
        return 0

    decayed = []
    archived = []

    for filepath in files:
        try:
            content = filepath.read_text()
            parsed_list = parse_fn(content)
        except Exception as e:
            print(f"Warning: Failed to parse {filepath}: {e}",
                  file=sys.stderr)
            continue

        for inst in parsed_list:
            last_obs_str = inst.get('last_observed')
            if not last_obs_str:
                continue

            try:
                last_obs = datetime.fromisoformat(last_obs_str)
            except ValueError:
                continue

            weeks_since = (now - last_obs).days / 7.0
            if weeks_since <= 0:
                continue

            old_conf = inst.get('confidence', 0.5)
            new_conf = round(old_conf - (weeks_since * decay_rate), 4)
            new_conf = max(new_conf, 0.0)

            if new_conf == old_conf:
                continue

            if new_conf < min_confidence:
                archived.append({
                    'file': filepath,
                    'instinct': inst,
                    'old': old_conf,
                    'new': new_conf,
                })
            else:
                decayed.append({
                    'file': filepath,
                    'instinct': inst,
                    'old': old_conf,
                    'new': new_conf,
                })

    if not decayed and not archived:
        print("No instincts need decay.")
        return 0

    if decayed:
        print(f"\nDECAYED ({len(decayed)}):")
        for item in decayed:
            iid = item['instinct'].get('id', 'unnamed')
            print(f"  {iid}: {item['old']:.2f} -> {item['new']:.2f}")

    if archived:
        print(f"\nARCHIVED (below {min_confidence}) ({len(archived)}):")
        for item in archived:
            iid = item['instinct'].get('id', 'unnamed')
            print(f"  {iid}: {item['old']:.2f} -> {item['new']:.2f}")

    if dry_run:
        print("\n[DRY RUN] No changes made.")
        return 0

    for item in decayed:
        inst = item['instinct']
        inst['confidence'] = item['new']
        write_instinct_file(item['file'], inst)

    for item in archived:
        src = item['file']
        dest = archived_dir / src.name
        inst = item['instinct']
        inst['confidence'] = item['new']
        write_instinct_file(dest, inst)
        src.unlink()

    print(f"\nDone: {len(decayed)} decayed, {len(archived)} archived.")
    return 0
