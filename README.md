# Savora

**Know what's in your food before you order it.**

**Project page and live dashboard:** https://karthikeya70.github.io/Savora/

Savora is a chat assistant for a restaurant menu. Instead of reading every dish
description, you just ask:

> *"Which dishes have no nuts?"*
> *"Anything vegan under ₹150?"*
> *"Does the Masala Dosa have dairy?"*

It answers using the restaurant's own ingredient list, and you can order right
there in the chat.

---

## Why I built it

There are ingredients I don't want in my food. If I know beforehand, I simply
won't order that dish. But finding out usually means reading the whole menu, or
asking a waiter who may not know.

Menus are organised the way a kitchen thinks: starters, mains, breads. People
don't think that way. They arrive with a rule like "no dairy" or "nothing over
₹150", and that rule cuts across every section. So they end up doing the
sorting themselves.

And getting it wrong isn't just a bad meal. For someone with an allergy, it can
make them ill.

---

## What it does

There are three screens, for three different people.

| Screen | Who uses it | What it's for |
| --- | --- | --- |
| **Chat** | Customers | Ask about dishes, add them to the basket, place an order |
| **Kitchen board** | Kitchen staff | See new orders arrive live and move them along: confirmed, cooking, ready |
| **Insights** | Restaurant owner | See what customers ask, where they give up, and which dishes they like |

After the food is ready, customers can tap **Liked it** or **Didn't like it**
for each dish. Once 5 real people have rated a dish, the assistant can mention
it: *"5 of 6 guests who rated this liked it."* So each person's rating helps the
next person decide.

---

## What I learned

### 1. People weren't using it the way I expected

I assumed people would mostly ask *"what's good here?"*. When I read the 833
questions typed in during testing, **nearly half (47%) were allergy and diet
checks.** People weren't browsing. They were checking whether they were allowed
to eat something.

Those questions were also answered **about 8 times slower** than any other kind.
The most important question got the worst service.

> These 833 questions came from testing by me and a few others, not from real
> customers.

### 2. The app couldn't tell whether it was helping

It saved every question and every order, but never linked them. So there was no
way to answer the most basic question: *did the assistant help anyone decide?*

I fixed that by recording each visit as one connected story: the question, the
dishes suggested, what went in the basket, the order, and the rating afterwards.

### 3. I caught the assistant making things up

After building the ratings feature, I tested it instead of assuming it worked.
I asked about a dish that **nobody had rated**. The assistant replied:

> *"The Jalebi is a bestseller, and most guests who rated it really enjoyed it!"*

That was invented. For a product whose whole promise is honest information about
food, that's a serious problem.

- **What didn't fix it:** adding a rule to the AI's instructions saying "never do
  this".
- **What did:** changing the information it's given. Every dish now carries a
  line either way. Rated dishes show real numbers. Unrated ones say *"no guest
  ratings yet — say nothing about guest opinions"*.
- **Now it replies:** *"I can't share what people think of the Jalebi, but it's
  made from fermented batter, fried into spirals and soaked in warm syrup."*

The app also checks every answer for this automatically. The count appears on
the Insights screen as **Honesty check**.

---

## Testing an idea properly (A/B test)

**The question:** if the assistant suggests fewer dishes, do people find it
easier to choose?

**How:** visitors are split into two groups. **Group A** gets normal answers,
often 4 or 5 dishes. **Group B** gets at most 3. Each person stays in the same
group for their whole visit. Then you compare how many people in each group
ordered.

**Three checks before trusting a result:**

1. **Did the change actually happen?** Group B should really see fewer dishes.
2. **Could the difference be luck?** Small gaps often are.
3. **Were there enough people?** With too few, "no difference" just means "can't
   tell yet".

This runs in the real app. It hasn't had real visitors yet, so there's no real
result to report.

---

## Answering questions with data

The `analysis` folder has 12 questions about the product, each answered with a
short piece of SQL, the language used to pull numbers out of a database. For
example:

- Of everyone who asked a question, how many went on to order?
- Which dishes do people see but never choose?
- What do people ask for that isn't on the menu?

It also includes a practice exercise: *"orders suddenly dropped one day — find
out why."* That's one of the most common questions in data and product
interviews. See [analysis/README.md](analysis/README.md).

---

## Try it yourself

**You'll need:** Python 3.11 or newer, and a free
[OpenRouter](https://openrouter.ai) account for the AI answers.

**1. Download the code and install what it needs**

```bash
git clone https://github.com/Karthikeya70/Savora.git
cd Savora
pip install -r requirements.txt
```

**2. Add your AI key.** Copy the example settings file:

```bash
cp .env.example .env
```

Open `.env` and replace the `OPENROUTER_API_KEY` value with your own key. You can
leave the other lines as they are. Without a key, the app still runs, but the
chat can't answer questions.

**3. Start it**

```bash
python run_local.py
```

The first start takes about a minute while it loads. Then open these in your
browser:

| Screen | Address |
| --- | --- |
| Chat | http://127.0.0.1:8000 |
| Kitchen board | http://127.0.0.1:8000/dashboard.html |
| Insights | http://127.0.0.1:8000/insights.html |

**4. Want to see the Insights screen full of data?** Create pretend customers:

```bash
python scripts/demo_data.py
```

Then switch the Insights screen to **DEMO** in the top corner. Real and pretend
data are always kept apart.

> Pretend data is invented by that script, including its patterns. It's for
> seeing how things work, not for drawing conclusions.

---

## Words used here

| Word | What it means here |
| --- | --- |
| **Visit** | One person's time in the chat, from first question to leaving. Each gets a random ID. No names are stored. |
| **Funnel** | The steps people go through: ask, see a suggestion, add to basket, order, rate. Some people stop at each step. |
| **A/B test** | Showing two versions to two groups of people, to see which works better. |
| **SQL** | A language for asking a database questions, like "how many orders were placed yesterday?" |
| **Cache** | Saved answers to common questions, so they come back instantly and cost nothing. |
| **Demo data** | Pretend customers, made up to show how the screens work. |

---

## What this project can't claim yet

- **No real customers yet.** All numbers come from my own testing or from
  pretend data.
- **The A/B test is built but hasn't run on real people.**
- **Sorting questions into topics is basic.** It matches keywords, so about a
  third of questions end up as "other".

The next step is getting real people to use it.

---

## For developers

<details>
<summary>How the code is organised</summary>

```
backend/
  app.py            the web server and all its addresses
  orchestrator.py   decides: is this a menu question, an order, or something else?
  router.py         answers menu questions: finds relevant dishes, then asks the AI
  order_agent.py    handles the basket and checkout through conversation
  cart.py           basket maths, and records every basket change
  events.py         records each step of a visit; sorts questions into topics
  popularity.py     dish ratings, and the check for invented praise
  experiment.py     the A/B test: who sees which version
  insights.py       turns the records into the numbers on the Insights screen
  cache.py          saved answers, kept separate for each A/B group
  database.py       database tables
frontend/
  index.html        chat
  dashboard.html    kitchen board
  insights.html     insights
  order-status.html order tracking and dish rating
analysis/
  questions.sql     12 product questions in SQL
  run.py            runs them and explains the A/B result
scripts/
  demo_data.py      make pretend customers
  clear_data.py     delete data (asks first before deleting anything real)
tests/
  test_tracking.py  13 tests, free to run, no AI calls
  test_chatbot.py   checks answer quality, calls the AI so costs a little
```

**Built with:** Python, FastAPI, SQLite (or PostgreSQL), plain JavaScript,
sentence-transformers for finding relevant dishes, and an AI model through
OpenRouter.

**What gets recorded:** each action in a visit, all linked by the visit's random
ID: question asked, dish suggested, basket change, order placed or cancelled,
dish rated. Names, emails and phone numbers are never needed.

**Run the tests:**

```bash
python tests/test_tracking.py
```

**Clear data before a fresh round of testing:**

```bash
python scripts/clear_data.py --demo   # pretend data only
python scripts/clear_data.py --real   # real visits, orders and baskets (asks first)
```

</details>
