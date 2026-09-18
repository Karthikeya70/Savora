# Analysis

Twelve SQL queries, each answering one product question about Savora.

```bash
python analysis/run.py                 # practice data
python analysis/run.py --source live   # real people
python analysis/run.py --only 9        # one query
```

Results print to the screen and save to `results_demo.md` or `results_live.md`.

Everything reads one table, `events`: one row per thing a customer did, all
tied together by `session_id`. That single design choice is what makes every
question below answerable.

| # | Question | SQL used |
| --- | --- | --- |
| 1 | How many people, questions, orders? | `COUNT`, `SUM` of a condition |
| 2 | Where do people drop off? | one row per visit, then `MAX` as a 1/0 flag |
| 3 | What do people ask, and do they order? | `LEFT JOIN`, `COUNT DISTINCT` |
| 4 | How many orders did the assistant help with? | `json_each` to unpack a list |
| 5 | Which dishes are seen but not chosen? | three `WITH` blocks joined, `HAVING` |
| 6 | Do suggested dishes get liked more? | `CASE WHEN` grouping |
| 7 | What do people want that isn't on the menu? | filter on JSON fields |
| 8 | How many questions before ordering? | join on a time condition |
| 9 | A/B test: do fewer choices help? | per-group rates, plus a luck check |
| 10–12 | Why did orders drop one day? | `DATE()`, `ROW_NUMBER()`, conditional averages |

A note on practice data: `scripts/demo_data.py` invents it, and its patterns
were put there on purpose. Use it to learn the method. Never quote its numbers
as findings.

---

## The A/B test, in plain words

**What changed.** Half the visitors (group B) get answers that name at most 3
dishes. The other half (group A) get the normal answers, which often name 4 or 5.

**The bet.** Too many options make people freeze. If that's true, group B
should order more often.

**How people are split.** By their visit id, so each person sees one version for
their whole visit and the split comes out about 50/50. Each group also has its
own answer cache, otherwise a B answer could leak to an A visitor.

**How to read the result** (query 9):

1. **Check the change actually happened first.** Group B's average dishes
   named should be lower. If it isn't, nothing else in the result means
   anything.
2. **Look at the gap** in order rate between the groups.
3. **Ask if it could be luck.** The runner works out the chance of seeing a
   gap that size if both versions were really identical. Under 5% is the usual
   bar for "probably real".
4. **Check you had enough people.** The runner says how many you'd need per
   group to spot a 5-point change. With too few, "no difference" just means
   "couldn't tell".

**What the practice data shows.** B named fewer dishes (2.3 against 3.1), so the
change happened. B ordered 2.5 points less, but there's a 54% chance that's
luck. Around 1,560 people per group would be needed and there are about 300.
Verdict: can't tell yet.

**Why that's the honest answer.** Most real tests end this way. It also means
15 friends can never settle an A/B test. With a group that small, watching them
use it teaches you far more.

---

## Root-cause drill: "orders dropped. Why?"

This is the question analyst interviews ask most. The practice data contains one
real problem, planted on one day. Try to find it yourself before reading the
answer at the bottom.

**Step 1: when?** Run query 10. Find the days where the order rate is clearly
lower than usual.

> Two days look bad: one around 30% and one around 24%. The normal range is
> roughly 40–55%. Don't assume both are the same problem.

**Step 2: who?** Run query 11. It splits each day by what people asked about
first. A real problem usually hits one group hard. Noise spreads thinly across
everyone.

> On one of the bad days, every group dipped a little. That's an ordinary slow
> day. On the other, one group fell to zero while the rest looked normal. That's
> the real problem.

**Step 3: why?** Run query 12. You now know which day and which group. Look
for what was different about that group's experience on that day.

**Step 4: say it in one sentence**, with the evidence and what you'd do next.
That sentence is what an interviewer is listening for.

**What people usually miss:** checking whether the data itself broke. Did
tracking stop, or did far fewer people show up? Query 10's `people_asking`
column answers that. It's a little low on one bad day but nowhere near the
collapse you'd see if tracking had broken, so the drop is real behaviour, not
missing data.

<details>
<summary><b>Answer</b> (open after you've tried)</summary>

The problem is planted four days before the practice data is generated. In the
copy made on 18 September, that's the 14th.

That day, answers to allergy and diet questions took about 10 seconds instead
of the usual 2. Nobody who started with an allergy question ordered, against
roughly 35–60% on other days. Every other kind of question was answered at
normal speed and ordered at normal rates.

One sentence: *"Orders dropped on the 14th because allergy answers slowed to
10 seconds and those customers gave up. Everyone else was unaffected. I'd check
what changed in the allergy lookup that day, and add an alert if allergy
answers go over 5 seconds."*

The other low day (the 6th in that copy) was just a slow day: every group
dipped a little and answer speeds were normal.

</details>
