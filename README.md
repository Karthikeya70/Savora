# Savora

**Know what's in your food before you order it.**

A chat assistant for a restaurant menu. You ask in plain language ("which dishes
are nut-free?", "anything vegan under ₹150?"), it answers from the restaurant's
own ingredient data, and you can order without leaving the chat.

## The product story

**The problem.** Menus are organised the way a kitchen thinks: starters, mains,
breads. Customers arrive with restrictions that cut across all of those: no
nuts, no dairy, under ₹150. So they read every description themselves, and a
wrong guess can mean an allergic reaction, not just a bad meal.

**What the data showed.** I read 833 questions typed into the app during
testing. Nearly half (47%) were allergy and diet checks, not "what's good
here?". Those were also answered about 8× slower than anything else. The most
important question got the worst service.

**What I built because of that.**

- **Journey tracking.** Every visit records question, suggestion, cart, order
  and rating, joined by one visit id. Before this, the app couldn't tell
  whether it helped anyone decide.
- **Post-meal ratings**, one tap per dish, fed back into answers
  ("5 of 6 guests who rated this liked it") once 5 real people have rated it.
- **An insights page** for the restaurant: drop-off funnel, topics, dish
  scorecard, and questions the menu couldn't answer.
- **An A/B test** of fewer suggestions (3) against the usual 4–5.
- **12 SQL queries** answering product questions, including a root-cause drill.
  See [analysis/README.md](analysis/README.md).

**What I caught.** Testing the ratings feature, I found the assistant inventing
praise ("most guests loved it") for a dish nobody had rated. A rule in the
prompt didn't stop it. Changing the data it was shown did. The app now checks
every answer for this automatically and reports it as an **Honesty check**.

**What it can't claim yet.** The 833 questions came from testing, not real
customers, and the practice data in `scripts/demo_data.py` is invented. The next
step is real people.

## Running it

```bash
pip install -r requirements.txt
python run_local.py
```

Then open:

| Page | Address | Who it's for |
| --- | --- | --- |
| Chat | http://127.0.0.1:8000 | customers |
| Kitchen board | http://127.0.0.1:8000/dashboard.html | staff, live orders |
| Insights | http://127.0.0.1:8000/insights.html | owner, what the data says |

If `DASHBOARD_SECRET` is set in `.env`, the last two pages need
`?secret=YOUR_SECRET` on the end of the address.

`run_local.py` stores data in a local file, `savora_local.db`, instead of the
Supabase database in `.env`. Use it while Supabase is paused or when testing.
`.env` is never modified, so switching back needs no changes.

## What gets recorded

Every step of a visit is written to one `events` table, all tagged with the same
session id so the steps can be joined up afterwards:

| Event | When |
| --- | --- |
| `question_asked` | someone types a question (with its topic and how long the answer took) |
| `dish_suggested` | the assistant names a dish in its answer |
| `cart_added` / `cart_removed` | the cart changes, noting whether the dish had been suggested first |
| `order_placed` / `order_cancelled` | checkout, or a cancellation |
| `dish_rated` | the customer says they liked a dish, after the food is ready |

No names, emails or phone numbers are needed for any of this. Session ids are
random. Keep it that way.

## Reading the insights page

- **The big picture** — four numbers: how many people used it, how many ordered,
  how many of those orders contained a dish the assistant suggested, and how many
  people liked their food.
- **Where people drop off** — of everyone who asked something, how many reached
  each next step. The biggest fall is the thing worth fixing.
- **What people ask about** — questions sorted by topic, with how many of those
  people went on to order, and how long they waited.
- **Dish scorecard** — for each dish: how many people were shown it, how many
  ordered it after being shown it, and what share liked it. A dish shown often
  but rarely picked is usually described badly or priced wrong.
- **Does the assistant actually help?** — whether people liked suggested dishes
  more than dishes they picked themselves.
- **Questions the menu couldn't answer** — repeats here are free menu research.

A "%" built on very few ratings is marked `few`. Treat those as hints, not facts.

## Guest feedback, fed back into the answers

Once **5 real people** have rated a dish, the assistant may mention it:
"5 of 6 guests who rated this liked it". That closes the loop the app was
missing — someone asks, the assistant suggests, they order, they rate it, and
the next person sees the result.

Two safety rules, both enforced in code, not just asked for in the prompt:

- **Only real ratings count.** Demo ratings never reach a customer.
- **Below 5 ratings the assistant is told "no guest ratings yet" and must say
  nothing about guest opinions.** This matters: when unrated dishes simply had
  no feedback line, the assistant filled the silence and claimed guests had
  loved a dish nobody had rated. Every answer is now checked for that
  automatically, and the count appears on the insights page under
  **Honesty check**.

Thresholds live at the top of `backend/popularity.py`.

## Real data vs demo data

The insights page has a **REAL / DEMO** switch, and the two never mix.

- **REAL** is what actual people did in the app.
- **DEMO** is pretend customers created by `scripts/demo_data.py`, so you can see
  the page working before anyone has used it.

Demo patterns were put there by that script. They are **not findings** and must
never be presented as results.

```bash
python scripts/demo_data.py                 # 300 pretend customers
python scripts/demo_data.py --customers 800
python scripts/demo_data.py --clear         # remove them again
```

To start a clean round of testing:

```bash
python scripts/clear_data.py --demo   # pretend data only
python scripts/clear_data.py --real   # real activity, orders and carts (asks first)
```

## Collecting real data

Ask people to use it on their own phone, then watch where they hesitate. Tell
them what's being recorded first. A nickname at checkout is plenty; real names
add risk and tell you nothing extra.

## The A/B test

Visitors are split into two groups by their visit id. Group B's answers name at
most 3 dishes; group A's are unchanged. Each group has its own answer cache so
the versions never mix. Turn it off with `RUNNING = False` in
`backend/experiment.py`. Read the result with `python analysis/run.py --only 9`.

## Tests

```bash
python tests/test_tracking.py   # 13 tests: tracking, ratings, A/B split, SQL vs dashboard — free
python tests/test_chatbot.py    # answer quality — calls the AI, costs a little
```

## How it's put together

```
backend/
  app.py            web API and page routes
  orchestrator.py   decides: menu question, order, or support
  router.py         menu answers: cache, then find relevant dishes, then ask the AI
  order_agent.py    cart and checkout, by conversation
  cart.py           cart maths, and records every cart change
  events.py         writes the diary; sorts questions into topics
  popularity.py     guest feedback per dish, and the invented-praise check
  experiment.py     the A/B test: who sees which version
  insights.py       turns the diary into the numbers on the insights page
  database.py       tables: sessions, orders, order_items, events
frontend/
  index.html        customer chat
  dashboard.html    kitchen board
  insights.html     insights
  order-status.html order tracking and dish rating
scripts/
  demo_data.py      make pretend customers
  clear_data.py     delete data
analysis/
  questions.sql     12 product questions in SQL
  run.py            runs them, and reads the A/B result
```
