#!/usr/bin/env python3
"""스킬 트리거 테스트 러너.

각 쿼리를 판정자(claude -p)에게 보내 "이 스킬이 켜져야 하는가"를 묻고,
기대값과 비교해 통과율을 낸다.

판정자는 레포 밖 임시 디렉터리에서 돌린다. 레포 안에서 돌리면 이 레포의
스킬들이 판정자 컨텍스트에 딸려 들어가 판정이 오염되기 때문이다.

사용:
    python3 scripts/trigger_test.py evals/dev-kickoff/triggers.json \
        --skill-file .claude/skills/dev-kickoff/SKILL.md
"""
import argparse
import concurrent.futures
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

JUDGE = """You are testing whether a Claude Code skill would be invoked.

SKILL NAME: {name}
SKILL DESCRIPTION: {desc}

A user types the message below. Based only on the skill description above,
would Claude invoke this skill to handle it?

USER MESSAGE:
{query}

Answer with exactly one word: TRIGGER or NO_TRIGGER."""


def read_frontmatter(skill_file):
    text = Path(skill_file).read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise SystemExit(f"{skill_file}: YAML frontmatter를 찾지 못했다")
    block = m.group(1)
    name = re.search(r"^name:\s*(.+)$", block, re.M).group(1).strip()
    desc = re.search(r"^description:\s*(.+)$", block, re.M | re.S).group(1).strip()
    return name, desc.strip("\"'")


def ask_once(prompt, workdir, timeout):
    """판정자를 한 번 호출한다. (판정, 원문) 을 돌려주며 판정이 None이면 실패."""
    try:
        out = subprocess.run(
            ["claude", "-p", prompt],
            cwd=workdir,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
        ).stdout
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT"
    raw = out.strip()
    upper = raw.upper()
    # API 오류는 판정이 아니다. 이걸 오답으로 세면 스킬 품질과 인프라 장애가
    # 한 숫자에 섞여서, 통과율이 무엇을 뜻하는지 알 수 없게 된다.
    if raw.startswith("API Error") or "Unable to connect" in raw:
        return None, raw
    if "NO_TRIGGER" in upper:
        return False, raw
    if "TRIGGER" in upper:
        return True, raw
    return None, raw


def judge(item, name, desc, workdir, timeout, retries=2):
    """판정이 나올 때까지 최대 retries회 재시도한다.

    재시도 상한은 conductor의 규칙과 같은 2회다. 같은 방식으로 세 번 실패하면
    접근이 틀린 것이므로 오류로 남기고 넘어간다."""
    prompt = JUDGE.format(name=name, desc=desc, query=item["query"])
    raw = ""
    for attempt in range(retries + 1):
        actual, raw = ask_once(prompt, workdir, timeout)
        if actual is not None:
            return {**item, "actual": actual, "attempts": attempt + 1,
                    "passed": actual == item["should_trigger"], "raw": raw[:200]}
    return {**item, "actual": None, "attempts": retries + 1,
            "passed": False, "error": True, "raw": raw[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query_file")
    ap.add_argument("--skill-file", required=True)
    ap.add_argument("--workers", type=int, default=5,
                    help="동시 판정 수. conductor의 동시 실행 상한(3~5)과 맞춰 기본 5")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--threshold", type=float, default=0.8,
                    help="이 통과율 미만이면 종료 코드 1")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    data = json.loads(Path(args.query_file).read_text(encoding="utf-8"))
    items = data["queries"]
    name, desc = read_frontmatter(args.skill_file)
    out_dir = Path(args.out_dir or Path(args.query_file).parent)

    with tempfile.TemporaryDirectory() as workdir:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(
                lambda it: judge(it, name, desc, workdir, args.timeout), items))

    results.sort(key=lambda r: r["id"])
    errors = [r for r in results if r.get("error")]
    judged = [r for r in results if not r.get("error")]
    passed = sum(r["passed"] for r in judged)
    total = len(judged)
    rate = passed / total if total else 0.0

    pos = [r for r in judged if r["should_trigger"]]
    neg = [r for r in judged if not r["should_trigger"]]
    summary = {
        "skill": name,
        "judged": total,
        "errors": len(errors),
        "passed": passed,
        "pass_rate": round(rate, 3),
        "recall_should_trigger": round(sum(r["passed"] for r in pos) / len(pos), 3) if pos else None,
        "precision_should_not_trigger": round(sum(r["passed"] for r in neg) / len(neg), 3) if neg else None,
        "failures": [{"id": r["id"], "query": r["query"],
                      "expected": r["should_trigger"], "actual": r["actual"]}
                     for r in judged if not r["passed"]],
        "error_ids": [r["id"] for r in errors],
    }

    (out_dir / "results.json").write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    lines = [f"# 트리거 테스트 결과 — {name}", "",
             f"- 통과: **{passed}/{total}** ({rate:.0%})",
             f"- 판정 실패(API 오류 등, 통과율에서 제외): {len(errors)}건" if errors else "",
             f"- 켜져야 할 때 켜진 비율: {summary['recall_should_trigger']:.0%}" if pos else "",
             f"- 켜지면 안 될 때 안 켜진 비율: {summary['precision_should_not_trigger']:.0%}" if neg else "",
             "", "| # | 기대 | 실제 | 결과 | 쿼리 |", "|---|---|---|---|---|"]
    for r in results:
        exp = "켜짐" if r["should_trigger"] else "안켜짐"
        act = {True: "켜짐", False: "안켜짐", None: "판정불가"}[r["actual"]]
        verdict = "ERROR" if r.get("error") else ("PASS" if r["passed"] else "FAIL")
        lines.append(f"| {r['id']} | {exp} | {act} | {verdict} "
                     f"| {r['query'][:60]} |")
    (out_dir / "results.md").write_text("\n".join(l for l in lines if l != "") + "\n",
                                        encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if rate >= args.threshold else 1


if __name__ == "__main__":
    sys.exit(main())
