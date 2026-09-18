"""
Run every query in analysis/questions.sql and show the answers.

    python analysis/run.py                 # practice data (demo)
    python analysis/run.py --source live   # real people
    python analysis/run.py --only 9        # just one query, by number

Results are printed and also saved to analysis/results_<source>.md, so you can
read them later or show them to someone.

For the A/B test it also answers the question every interviewer asks next:
"is that difference real, or could it be luck?"
"""
import argparse
import math
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SQL_FILE = HERE / "questions.sql"


# ── reading the .sql file ─────────────────────────────────────────────────────

def load_queries() -> list[dict]:
    """Split questions.sql into blocks that start with '-- @name:'."""
    text = SQL_FILE.read_text(encoding="utf-8")
    blocks = re.split(r"^-- @name:\s*", text, flags=re.M)[1:]
    queries = []
    for block in blocks:
        name, _, rest = block.partition("\n")
        m = re.search(r"^-- @question:\s*(.+)$", rest, flags=re.M)
        # Drop comments first (they may contain semicolons), then the SQL
        # itself ends at the first semicolon.
        code = "\n".join(line.split("--")[0] for line in rest.splitlines())
        sql = code.split(";")[0].strip()
        queries.append({
            "number":   int(name.split(".")[0]),
            "name":     name.strip(),
            "question": m.group(1).strip() if m else "",
            "sql":      sql,
        })
    return queries


# ── showing results ───────────────────────────────────────────────────────────

def as_table(columns: list[str], rows: list[tuple]) -> str:
    """Rows as a markdown table: readable in a terminal and on GitHub."""
    if not rows:
        return "_no rows — there's no data for this yet_"
    cells = [[("" if v is None else str(v)) for v in row] for row in rows]
    widths = [max(len(c), *(len(r[i]) for r in cells)) for i, c in enumerate(columns)]
    line = lambda vals: "| " + " | ".join(v.ljust(w) for v, w in zip(vals, widths)) + " |"
    return "\n".join([line(columns), line(["-" * w for w in widths]), *map(line, cells)])


# ── is the A/B difference real? ───────────────────────────────────────────────

def _normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def ab_verdict(columns: list[str], rows: list[tuple]) -> str:
    """
    Plain-English reading of the A/B result.

    Uses a two-proportion z-test: it asks how likely a gap this size would be
    if the two versions were actually identical. That likelihood is the p-value.
    Below 0.05 (a 5% chance of luck) is the usual bar for "probably real".
    """
    data = {r[columns.index("ab_group")]: r for r in rows}
    if not {"A", "B"} <= set(data):
        return "Not enough data yet: need visitors in both group A and group B."

    col = columns.index
    n_a, o_a = data["A"][col("people")], data["A"][col("ordered")]
    n_b, o_b = data["B"][col("people")], data["B"][col("ordered")]
    p_a, p_b = o_a / n_a, o_b / n_b
    pooled   = (o_a + o_b) / (n_a + n_b)
    se       = math.sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b)) or 1e-9
    z        = (p_b - p_a) / se
    p_value  = 2 * (1 - _normal_cdf(abs(z)))
    gap      = (p_b - p_a) * 100

    # How many people per group you'd need to reliably spot a 5-point change.
    # The 1.96 and 0.84 are the standard numbers for "5% chance of a false alarm,
    # 80% chance of catching a real effect".
    target = min(p_a + 0.05, 0.99)
    needed = math.ceil((1.96 + 0.84) ** 2 * (p_a * (1 - p_a) + target * (1 - target)) / 0.05 ** 2)

    named_a = data["A"][col("avg_dishes_named")]
    named_b = data["B"][col("avg_dishes_named")]
    change_happened = named_b is not None and named_a is not None and named_b < named_a

    lines = [
        f"Group B ordered {abs(gap):.1f} points {'more' if gap >= 0 else 'less'} than group A "
        f"({p_b:.1%} against {p_a:.1%}).",
        f"Chance of a gap this size by pure luck: {p_value:.0%} (p-value {p_value:.3f}).",
    ]
    if not change_happened:
        lines.append("WARNING: group B did not name fewer dishes, so the change may not have "
                     "been applied. Fix that before trusting anything else here.")
    if p_value < 0.05:
        lines.append("Verdict: the difference is probably real.")
    else:
        lines.append("Verdict: can't tell. This gap is small enough to be luck, "
                     "so treat the two versions as equal for now.")
    lines.append(f"To reliably spot a 5-point change you'd need about {needed:,} people "
                 f"per group. You have {min(n_a, n_b):,}.")
    return "\n".join(lines)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["demo", "live"], default="demo")
    ap.add_argument("--db", default=str(ROOT / "savora_local.db"))
    ap.add_argument("--only", type=int, help="run only this query number")
    args = ap.parse_args()

    if not Path(args.db).exists():
        sys.exit(f"No database at {args.db}. Start the app once with: python run_local.py")

    con = sqlite3.connect(args.db)
    out = [
        f"# Savora analysis — {args.source} data",
        "",
        ("> **Practice data.** Made by scripts/demo_data.py. The patterns were put "
         "there by that script; these are not findings about real people."
         if args.source == "demo" else
         "> **Real data** from people using the app."),
        "",
    ]

    for q in load_queries():
        if args.only and q["number"] != args.only:
            continue
        cur = con.execute(q["sql"], {"source": args.source})
        columns = [d[0] for d in cur.description]
        rows = cur.fetchall()

        block = [f"## {q['name']}", "", f"*{q['question']}*", "", as_table(columns, rows), ""]
        if q["number"] == 9:
            block += ["**Reading it:**", "", *[f"- {l}" for l in ab_verdict(columns, rows).split("\n")], ""]
        print("\n".join(block))
        out += block

    con.close()
    if not args.only:
        path = HERE / f"results_{args.source}.md"
        path.write_text("\n".join(out), encoding="utf-8")
        print(f"Saved to {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
