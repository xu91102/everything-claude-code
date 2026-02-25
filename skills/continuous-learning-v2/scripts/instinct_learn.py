"""
instinct_learn - Analyze observations and extract instinct candidates.

Detects patterns from observations.jsonl:
  - User corrections: same tool used consecutively, later overwriting earlier
  - Repeated workflows: identical tool sequences appearing 3+ times
  - Error fixes: Bash failure followed by an edit
"""

import json
import re
from collections import defaultdict, Counter
from datetime import datetime
from pathlib import Path
from typing import Optional


def _load_observations(obs_path: Path) -> list[dict]:
    """Load observations from JSONL file."""
    if not obs_path.exists():
        return []
    observations = []
    for line in obs_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            observations.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return observations


def _group_by_session(observations: list[dict]) -> dict[str, list[dict]]:
    """Group observations by session ID."""
    sessions = defaultdict(list)
    for obs in observations:
        sid = obs.get('session', obs.get('session_id', 'unknown'))
        sessions[sid].append(obs)
    return dict(sessions)


def _detect_user_corrections(session_obs: list[dict]) -> list[dict]:
    """Detect user corrections: same tool used consecutively, rewriting."""
    candidates = []
    for i in range(1, len(session_obs)):
        prev = session_obs[i - 1]
        curr = session_obs[i]
        if prev.get('tool') != curr.get('tool'):
            continue
        if prev.get('tool') not in ('Edit', 'Write'):
            continue
        # Same tool, consecutive -> likely a correction
        candidates.append({
            'id': f"correction-{prev.get('tool', 'unknown').lower()}-pattern",
            'trigger': f"when using {prev.get('tool', 'unknown')}",
            'domain': 'workflow',
            'pattern_type': 'user_correction',
            'evidence': f"Consecutive {prev.get('tool')} calls detected",
        })
    return candidates


def _detect_repeated_workflows(
    sessions: dict[str, list[dict]],
    min_occurrences: int = 3,
) -> list[dict]:
    """Detect repeated tool sequences across sessions."""
    # Build tool sequences per session (use sliding windows of 3-5 tools)
    seq_counter = Counter()
    for session_obs in sessions.values():
        tools = [o.get('tool', '') for o in session_obs
                 if o.get('event') == 'tool_start']
        for window_size in range(3, min(6, len(tools) + 1)):
            for i in range(len(tools) - window_size + 1):
                seq = tuple(tools[i:i + window_size])
                seq_counter[seq] += 1

    candidates = []
    for seq, count in seq_counter.items():
        if count < min_occurrences:
            continue
        seq_str = " -> ".join(seq)
        seq_id = re.sub(
            r'[^a-z0-9]+', '-',
            "-".join(s.lower() for s in seq),
        ).strip('-')[:40]
        candidates.append({
            'id': f"workflow-{seq_id}",
            'trigger': f"when following {seq_str} workflow",
            'domain': 'workflow',
            'pattern_type': 'repeated_workflow',
            'evidence': f"Sequence appeared {count} times",
            'occurrences': count,
        })
    return candidates


def _detect_error_fixes(session_obs: list[dict]) -> list[dict]:
    """Detect error-fix patterns: Bash failure followed by Edit."""
    candidates = []
    for i in range(len(session_obs) - 1):
        curr = session_obs[i]
        nxt = session_obs[i + 1]
        # Bash complete with error indicator
        if curr.get('tool') != 'Bash' or curr.get('event') != 'tool_complete':
            continue
        output = str(curr.get('output', ''))
        has_error = any(kw in output.lower()
                        for kw in ['error', 'failed', 'traceback',
                                   'exception', 'exit code'])
        if not has_error:
            continue
        if nxt.get('tool') in ('Edit', 'Write'):
            candidates.append({
                'id': 'error-then-fix-pattern',
                'trigger': 'when a command fails',
                'domain': 'debugging',
                'pattern_type': 'error_fix',
                'evidence': f"Bash error followed by {nxt.get('tool')}",
            })
    return candidates


def _deduplicate(
    candidates: list[dict],
    existing_instincts: list[dict],
    confidence_boost: float = 0.05,
) -> tuple[list[dict], list[dict]]:
    """Deduplicate candidates against existing instincts.

    Returns:
        (new_candidates, boosted_existing)
    """
    existing_ids = {i.get('id') for i in existing_instincts}
    new_candidates = []
    boosted = []

    seen_ids = set()
    for cand in candidates:
        cid = cand.get('id', '')
        if cid in seen_ids:
            continue
        seen_ids.add(cid)

        if cid in existing_ids:
            # Boost existing instinct confidence
            existing = next(
                (e for e in existing_instincts if e.get('id') == cid), None,
            )
            if existing:
                old_conf = existing.get('confidence', 0.5)
                new_conf = min(old_conf + confidence_boost, 1.0)
                boosted.append({
                    'instinct': existing,
                    'old_confidence': old_conf,
                    'new_confidence': new_conf,
                })
        else:
            new_candidates.append(cand)

    return new_candidates, boosted


def run_learn(
    observations_path: Path,
    existing_instincts: list[dict],
    personal_dir: Path,
    execute: bool = False,
    initial_confidence: float = 0.5,
) -> int:
    """Main learn logic.

    Args:
        observations_path: Path to observations.jsonl
        existing_instincts: Already loaded instincts
        personal_dir: Directory to write new instinct files
        execute: Whether to actually write files
        initial_confidence: Default confidence for new instincts

    Returns:
        Exit code
    """
    observations = _load_observations(observations_path)
    if not observations:
        print("No observations found. Run some sessions first.")
        return 0

    sessions = _group_by_session(observations)
    print(f"Analyzing {len(observations)} observations "
          f"across {len(sessions)} sessions...")

    # Detect patterns
    all_candidates = []
    for sid, session_obs in sessions.items():
        all_candidates.extend(_detect_user_corrections(session_obs))
        all_candidates.extend(_detect_error_fixes(session_obs))
    all_candidates.extend(_detect_repeated_workflows(sessions))

    if not all_candidates:
        print("No patterns detected.")
        return 0

    # Deduplicate
    new_candidates, boosted = _deduplicate(
        all_candidates, existing_instincts,
    )

    # Print results
    if new_candidates:
        print(f"\nNEW CANDIDATES ({len(new_candidates)}):")
        for cand in new_candidates:
            print(f"  + {cand['id']}")
            print(f"    trigger: {cand.get('trigger', 'N/A')}")
            print(f"    evidence: {cand.get('evidence', 'N/A')}")
            print()

    if boosted:
        print(f"BOOSTED ({len(boosted)}):")
        for item in boosted:
            iid = item['instinct'].get('id', 'unnamed')
            print(f"  ~ {iid}: "
                  f"{item['old_confidence']:.2f} -> "
                  f"{item['new_confidence']:.2f}")

    if not execute:
        print("\n[PREVIEW] Use --execute to write instinct files.")
        return 0

    # Write new instinct files
    now = datetime.now().isoformat()
    written = 0
    for cand in new_candidates:
        cid = cand['id']
        filename = re.sub(r'[^a-z0-9-]', '', cid) + '.yaml'
        filepath = personal_dir / filename

        if filepath.exists():
            continue

        content = "---\n"
        content += f"id: {cid}\n"
        content += f'trigger: "{cand.get("trigger", "unknown")}"\n'
        content += f"confidence: {initial_confidence}\n"
        content += f"domain: {cand.get('domain', 'general')}\n"
        content += f"source: auto-learned\n"
        content += f"last_observed: {now}\n"
        content += f"observed_count: 1\n"
        content += "---\n\n"
        content += f"## Action\n\n"
        content += f"Pattern: {cand.get('pattern_type', 'unknown')}\n\n"
        content += f"## Evidence\n\n{cand.get('evidence', 'N/A')}\n"

        filepath.write_text(content)
        written += 1

    print(f"\nWrote {written} new instinct files to {personal_dir}")
    return 0
