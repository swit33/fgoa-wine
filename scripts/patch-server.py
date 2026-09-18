#!/usr/bin/env python3
"""Patches two server tools of the install - both fixes come from
yana-arch/FGOAC-scooby-linux (branch linux-support) and were carried over verbatim.

  1) Server/tools/fgo_account.py - the CLI printed INFO logs before its JSON, so the launcher
     showed "bad_output: [INFO] ... {json}" on the Account page (upgrading Servants, granting
     materials, renaming). Now the config is always read, the log level is raised to warning,
     and when the profile is not isolated a temporary fgo.yaml is created next to it -
     otherwise the warning never reaches the servlet.
  2) Server/tools/fgo_account_actions.py - the big master tables were rescanned for every
     Servant (O(N*M)): "Max All Servants" did not fit the GUI's 60-second timeout for the
     authors (81.85 s before, 5.04 s after). The tables are indexed once now. On this machine
     (120 Servants, local disk) both versions finish in about 8 s, so the fix is carried
     for portability rather than need,
     for portability rather than need, and not because it was required.

The files are recoverable from the 前端 archive - the patch touches nothing but those two
places and does nothing at all on a re-run.

The edits are textual and idempotent: an already replaced block is skipped, and when the
original text is not found the file is left alone and reported.

  python3 patch-server.py <install_root>            # plan
  python3 patch-server.py <install_root> --apply    # apply
  python3 patch-server.py <install_root> --verify   # check what is applied
"""
import os
import sys

ACCOUNT = "Server/tools/fgo_account.py"
ACTIONS = "Server/tools/fgo_account_actions.py"

ACCOUNT_READ_YAML = """    config_dir = ARTEMIS_DIR / "config"
    with open(config_dir / "fgo.yaml", "r", encoding="utf-8") as config_file:
        isolated_config = yaml.safe_load(config_file) or {}
    isolated_server = isolated_config.setdefault("server", {})
    isolated_server["loglevel"] = "warning"

    if isolated_profile_path is not None:
        isolated_path = Path(isolated_profile_path).resolve()
        isolated_path.parent.mkdir(parents=True, exist_ok=True)
        isolated_server["profile_path"] = str(isolated_path)"""

ACCOUNT_TEMP_YAML = """        config_dir = isolated_path.parent
    else:
        temp_dir = ARTEMIS_DIR / "config" / "_account_tool_temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        with open(
            temp_dir / "fgo.yaml", "w", encoding="utf-8"
        ) as config_file:
            yaml.safe_dump(isolated_config, config_file, sort_keys=False)
        config_dir = temp_dir

"""

ACTIONS_INDEXES = """        np_rows = rows('np', 'svt_noble_phantasm') if action == 'levels' else []

        limits_by_sid = defaultdict(list)
        for r in limits:
            if 0 <= int(r['limit_count']) <= 4:
                limits_by_sid[int(r['svt_id'])].append(int(r['limit_count']))

        skills_by_sid_num = defaultdict(lambda: defaultdict(list))
        for r in skill_rows:
            skills_by_sid_num[int(r['svt_id'])][int(r['num'])].append(int(r['priority']))

        support_by_sid_num = defaultdict(lambda: defaultdict(list))
        for r in support_rows:
            support_by_sid_num[int(r['svt_id'])][int(r['num'])].append(int(r['priority']))

        np_by_sid = defaultdict(list)
        for r in np_rows:
            np_by_sid[int(r['svt_id'])].append(int(r['priority']))

"""

# (file, what we look for, what we replace it with, the "already applied" marker)
RULES = [
    (ACCOUNT,
     """    config_dir = ARTEMIS_DIR / "config"
    if isolated_profile_path is not None:
        isolated_path = Path(isolated_profile_path).resolve()
        isolated_path.parent.mkdir(parents=True, exist_ok=True)
        with open(
            config_dir / "fgo.yaml", "r", encoding="utf-8"
        ) as config_file:
            isolated_config = yaml.safe_load(config_file) or {}
        isolated_server = isolated_config.setdefault("server", {})
        isolated_server["profile_path"] = str(isolated_path)""",
     ACCOUNT_READ_YAML,
     'isolated_server["loglevel"] = "warning"'),

    (ACCOUNT,
     """        config_dir = isolated_path.parent
    return FgoServlet(cfg, str(config_dir))""",
     ACCOUNT_TEMP_YAML + "    return FgoServlet(cfg, str(config_dir))",
     "_account_tool_temp"),

    (ACTIONS,
     '''"""Explicit, finite account upgrades using the installed game's master data."""
from copy import deepcopy''',
     '''"""Explicit, finite account upgrades using the installed game's master data."""
from collections import defaultdict
from copy import deepcopy''',
     "from collections import defaultdict"),

    (ACTIONS,
     "        np_rows = rows('np', 'svt_noble_phantasm') if action == 'levels' else []\n        for row in inventory:",
     ACTIONS_INDEXES + "        for row in inventory:",
     "limits_by_sid = defaultdict(list)"),

    (ACTIONS,
     "                stages = [int(r['limit_count']) for r in limits if int(r['svt_id']) == sid and 0 <= int(r['limit_count']) <= 4]",
     "                stages = limits_by_sid.get(sid, [])",
     "stages = limits_by_sid.get(sid, [])"),

    (ACTIONS,
     "                row['skl_stp'] = [max((int(r['priority']) for r in skill_rows if int(r['svt_id']) == sid and int(r['num']) == slot), default=1) for slot in (1, 2, 3)]\n"
     "                row['sprt_skl_stp'] = [max((int(r['priority']) for r in support_rows if int(r['svt_id']) == sid and int(r['num']) == slot), default=1) for slot in (1, 2, 3)]\n"
     "                row['np_stp'] = max((int(r['priority']) for r in np_rows if int(r['svt_id']) == sid), default=row.get('np_stp', 0))",
     "                row['skl_stp'] = [max(skills_by_sid_num[sid].get(slot, []), default=1) for slot in (1, 2, 3)]\n"
     "                row['sprt_skl_stp'] = [max(support_by_sid_num[sid].get(slot, []), default=1) for slot in (1, 2, 3)]\n"
     "                row['np_stp'] = max(np_by_sid.get(sid, []), default=row.get('np_stp', 0))",
     "skills_by_sid_num[sid].get(slot, [])"),
]


def as_bytes(text, crlf):
    return (text.replace("\n", "\r\n") if crlf else text).encode("utf-8")


def main():
    root = os.path.abspath(sys.argv[1])
    mode = "verify" if "--verify" in sys.argv else ("apply" if "--apply" in sys.argv else "plan")
    applied = present = 0
    problems = []
    for i, (rel, old, new, marker) in enumerate(RULES, 1):
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            problems.append(f"no such file {rel} - skipping rule {i}")
            continue
        data = open(path, "rb").read()
        crlf = b"\r\n" in data
        marker_b, old_b, new_b = as_bytes(marker, crlf), as_bytes(old, crlf), as_bytes(new, crlf)
        if marker_b in data:
            present += 1
            continue
        if old_b not in data:
            problems.append(f"{rel}: the original text of rule {i} was not found - another version?")
            continue
        if mode == "verify":
            problems.append(f"{rel}: rule {i} is not applied")
            continue
        if mode == "plan":
            applied += 1
            continue
        with open(path, "wb") as fh:
            fh.write(data.replace(old_b, new_b))
        applied += 1

    print(f"mode: {mode}")
    print(f"  server-side fixes: applied now {applied}, already present {present}, rules {len(RULES)}")
    if mode == "plan":
        print("  nothing was changed; add --apply to apply")
    if problems:
        print(f"  problems ({len(problems)}):")
        for line in problems:
            print("    " + line)
    return 1 if problems else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: patch-server.py <install_root> [--apply | --verify]")
        raise SystemExit(2)
    sys.exit(main())
