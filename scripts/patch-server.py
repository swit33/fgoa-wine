#!/usr/bin/env python3
"""Правит два серверных инструмента установки — обе правки из
yana-arch/FGOAC-scooby-linux (ветка linux-support), перенесены дословно.

  1) Server/tools/fgo_account.py — CLI-режим печатал INFO-логи до JSON, и лончер
     показывал "bad_output: [INFO] ... {json}" на странице Account (обновить слуг,
     выдать материалы, переименовать). Теперь конфиг читается всегда, уровень
     логирования поднимается до warning, а когда профиль не изолирован, рядом
     создаётся временный fgo.yaml — иначе warning до сервлета не доходит.
  2) Server/tools/fgo_account_actions.py — для каждого слуги заново сканировались
     большие мастер-таблицы (O(N*M)): у авторов правки "Max All Servants" не влезал
     в 60-секундный таймаут GUI (81.85 с до правки, 5.04 с после). Таблицы
     индексируются один раз. На нашей машине (120 слуг, локальный диск) обе
     версии укладываются в 8 с — правка оставлена ради переносимости,
     не как обязательная.

Файлы восстановимы из архива 前端 — патч не трогает ничего, кроме этих двух мест,
и на повторном запуске просто ничего не делает.

Правки текстовые и идемпотентные: если кусок уже заменён — правило пропускается,
если исходный текст не найден — файл не трогаем и сообщаем об этом.

  python3 patch-server.py <install_root>            # план
  python3 patch-server.py <install_root> --apply    # накатить
  python3 patch-server.py <install_root> --verify   # сверить, что наложено
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

# (файл, что ищем, на что меняем, признак «уже наложено»)
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
            problems.append(f"нет файла {rel} — пропускаю правило {i}")
            continue
        data = open(path, "rb").read()
        crlf = b"\r\n" in data
        marker_b, old_b, new_b = as_bytes(marker, crlf), as_bytes(old, crlf), as_bytes(new, crlf)
        if marker_b in data:
            present += 1
            continue
        if old_b not in data:
            problems.append(f"{rel}: не нашла исходный текст правила {i} — файл другой версии?")
            continue
        if mode == "verify":
            problems.append(f"{rel}: правило {i} не наложено")
            continue
        if mode == "plan":
            applied += 1
            continue
        with open(path, "wb") as fh:
            fh.write(data.replace(old_b, new_b))
        applied += 1

    print(f"режим: {mode}")
    print(f"  серверные правки: наложено сейчас {applied}, уже было {present}, всего правил {len(RULES)}")
    if mode == "plan":
        print("  ничего не изменено; для наката добавь --apply")
    if problems:
        print(f"  проблемы ({len(problems)}):")
        for line in problems:
            print("    " + line)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
