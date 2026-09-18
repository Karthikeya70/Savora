-- ═══════════════════════════════════════════════════════════════════════════
-- Savora product questions, answered in SQL
--
-- Every query below answers ONE question a product analyst would be asked.
-- They all read a single table, `events`, which has one row per thing a
-- customer did:
--
--   session_id   one visit (random id, no names)
--   event_type   question_asked, dish_suggested, cart_added, cart_removed,
--                order_placed, order_cancelled, dish_rated
--   dish_name    the dish involved, if any
--   properties   extra details stored as JSON, read with json_extract()
--   source       'live' = real people, 'demo' = practice data
--   created_at   when it happened
--
-- :source is filled in by analysis/run.py ('demo' or 'live').
-- Written for SQLite, the database run_local.py uses.
--
-- Run them all:   python analysis/run.py
-- ═══════════════════════════════════════════════════════════════════════════


-- @name: 1. The headline numbers
-- @question: How many people used it, how many questions, how many orders?
SELECT
  COUNT(DISTINCT session_id)          AS people,
  SUM(event_type = 'question_asked')  AS questions,
  SUM(event_type = 'order_placed')    AS orders,
  SUM(event_type = 'dish_rated')      AS ratings
FROM events
WHERE source = :source;


-- @name: 2. The funnel
-- @question: Of the people who asked a question, how many made it to each next step?
-- One row per visit, with a 1/0 flag for each step it reached.
WITH visits AS (
  SELECT
    session_id,
    MAX(event_type = 'question_asked') AS asked,
    MAX(event_type = 'dish_suggested') AS suggested,
    MAX(event_type = 'cart_added')     AS added,
    MAX(event_type = 'order_placed')   AS ordered,
    MAX(event_type = 'dish_rated')     AS rated
  FROM events
  WHERE source = :source
  GROUP BY session_id
)
SELECT
  SUM(asked)                                            AS asked,
  SUM(asked AND suggested)                              AS got_a_suggestion,
  SUM(asked AND added)                                  AS added_to_cart,
  SUM(asked AND ordered)                                AS ordered,
  SUM(asked AND rated)                                  AS rated,
  ROUND(100.0 * SUM(asked AND ordered) / SUM(asked), 1) AS order_rate_pct
FROM visits;


-- @name: 3. What people ask about
-- @question: Which topics come up most, and do those people go on to order?
WITH questions AS (
  SELECT session_id, json_extract(properties, '$.topic') AS topic
  FROM events
  WHERE source = :source AND event_type = 'question_asked'
),
orderers AS (
  SELECT DISTINCT session_id
  FROM events
  WHERE source = :source AND event_type = 'order_placed'
)
SELECT
  q.topic,
  COUNT(*)                                                     AS questions,
  ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM questions), 1) AS share_pct,
  COUNT(DISTINCT q.session_id)                                 AS people,
  ROUND(100.0 * COUNT(DISTINCT o.session_id)
        / COUNT(DISTINCT q.session_id), 1)                     AS went_on_to_order_pct
FROM questions q
LEFT JOIN orderers o ON o.session_id = q.session_id
GROUP BY q.topic
ORDER BY questions DESC;


-- @name: 4. Orders the assistant helped with
-- @question: What share of orders had at least one dish the assistant suggested first?
-- Each order stores its dishes as a JSON list; json_each() turns that list into rows.
WITH orders AS (
  SELECT
    e.id,
    MAX(json_extract(item.value, '$.was_suggested')) AS used_a_suggestion
  FROM events e, json_each(e.properties, '$.items') AS item
  WHERE e.source = :source AND e.event_type = 'order_placed'
  GROUP BY e.id
)
SELECT
  COUNT(*)                                             AS orders,
  SUM(used_a_suggestion)                               AS helped_orders,
  ROUND(100.0 * SUM(used_a_suggestion) / COUNT(*), 1)  AS helped_pct
FROM orders;


-- @name: 5. Dishes people see but don't choose
-- @question: Which dishes get suggested a lot but rarely picked? (Worst first.)
-- A dish shown often and picked rarely is usually described badly, priced
-- wrong, or suggested to the wrong people.
WITH shown AS (
  SELECT DISTINCT session_id, dish_name
  FROM events
  WHERE source = :source AND event_type = 'dish_suggested'
),
ordered AS (
  SELECT DISTINCT e.session_id, json_extract(item.value, '$.dish_name') AS dish_name
  FROM events e, json_each(e.properties, '$.items') AS item
  WHERE e.source = :source AND e.event_type = 'order_placed'
),
ratings AS (
  SELECT dish_name,
         COUNT(*)                                  AS n,
         SUM(json_extract(properties, '$.liked'))  AS likes
  FROM events
  WHERE source = :source AND event_type = 'dish_rated'
  GROUP BY dish_name
)
SELECT
  s.dish_name,
  COUNT(*)                                          AS people_shown,
  ROUND(100.0 * COUNT(o.session_id) / COUNT(*), 1)  AS picked_when_shown_pct,
  r.n                                               AS ratings,
  ROUND(100.0 * r.likes / r.n, 1)                   AS liked_pct
FROM shown s
LEFT JOIN ordered o ON o.session_id = s.session_id AND o.dish_name = s.dish_name
LEFT JOIN ratings r ON r.dish_name  = s.dish_name
GROUP BY s.dish_name
HAVING COUNT(*) >= 20              -- ignore dishes shown too rarely to judge
ORDER BY picked_when_shown_pct ASC
LIMIT 8;


-- @name: 6. Do suggested dishes get liked more?
-- @question: Do people enjoy the food more when the assistant suggested it?
SELECT
  CASE WHEN json_extract(properties, '$.was_suggested')
       THEN 'suggested by assistant' ELSE 'picked themselves' END  AS how_chosen,
  COUNT(*)                                                          AS ratings,
  ROUND(100.0 * SUM(json_extract(properties, '$.liked')) / COUNT(*), 1) AS liked_pct
FROM events
WHERE source = :source AND event_type = 'dish_rated'
GROUP BY how_chosen;


-- @name: 7. What people want that the menu doesn't have
-- @question: Which questions got an answer with no dish in it at all?
SELECT
  json_extract(properties, '$.question') AS question,
  COUNT(*)                               AS times_asked
FROM events
WHERE source = :source
  AND event_type = 'question_asked'
  AND json_extract(properties, '$.handled_by')   = 'menu'
  AND json_extract(properties, '$.dishes_named') = 0
GROUP BY question
ORDER BY times_asked DESC
LIMIT 10;


-- @name: 8. How long people take to decide
-- @question: How many questions do people ask before they order?
WITH first_order AS (
  SELECT session_id, MIN(created_at) AS ordered_at
  FROM events
  WHERE source = :source AND event_type = 'order_placed'
  GROUP BY session_id
),
per_person AS (
  SELECT f.session_id, COUNT(q.id) AS questions_before_ordering
  FROM first_order f
  JOIN events q
    ON  q.session_id = f.session_id
    AND q.event_type = 'question_asked'
    AND q.created_at <= f.ordered_at
  GROUP BY f.session_id
)
SELECT questions_before_ordering, COUNT(*) AS people
FROM per_person
GROUP BY questions_before_ordering
ORDER BY questions_before_ordering;


-- @name: 9. A/B test: fewer choices
-- @question: Did group B (at most 3 dishes per answer) order more often than group A?
-- First column to check is avg_dishes_named: if B isn't lower, the change
-- didn't actually happen and the rest of the result means nothing.
WITH people AS (
  SELECT
    session_id,
    MAX(json_extract(properties, '$.ab_group'))     AS ab_group,
    AVG(json_extract(properties, '$.dishes_named')) AS dishes_named
  FROM events
  WHERE source = :source
    AND event_type = 'question_asked'
    AND json_extract(properties, '$.ab_group') IS NOT NULL
  GROUP BY session_id
),
orderers AS (
  SELECT DISTINCT session_id
  FROM events
  WHERE source = :source AND event_type = 'order_placed'
)
SELECT
  p.ab_group,
  COUNT(*)                                          AS people,
  ROUND(AVG(p.dishes_named), 2)                     AS avg_dishes_named,
  COUNT(o.session_id)                               AS ordered,
  ROUND(100.0 * COUNT(o.session_id) / COUNT(*), 1)  AS order_rate_pct
FROM people p
LEFT JOIN orderers o ON o.session_id = p.session_id
GROUP BY p.ab_group
ORDER BY p.ab_group;


-- ─── Root-cause practice: "orders dropped one day — why?" ────────────────────
-- Run these three in order. Each one narrows the problem down.


-- @name: 10. Root cause, step 1: when did it happen?
-- @question: What was the order rate on each day?
WITH daily AS (
  SELECT
    DATE(created_at)                  AS day,
    session_id,
    MAX(event_type = 'question_asked') AS asked,
    MAX(event_type = 'order_placed')   AS ordered
  FROM events
  WHERE source = :source
  GROUP BY day, session_id
)
SELECT
  day,
  SUM(asked)                                               AS people_asking,
  SUM(asked AND ordered)                                   AS people_ordering,
  ROUND(100.0 * SUM(asked AND ordered) / NULLIF(SUM(asked), 0), 1) AS order_rate_pct
FROM daily
GROUP BY day
ORDER BY day;


-- @name: 11. Root cause, step 2: who was affected?
-- @question: Split each day's order rate by what the person asked about first.
-- ROW_NUMBER() finds each visitor's first question.
WITH ranked AS (
  SELECT
    session_id,
    DATE(created_at)                        AS day,
    json_extract(properties, '$.topic')     AS topic,
    ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY created_at) AS nth
  FROM events
  WHERE source = :source AND event_type = 'question_asked'
),
first_q AS (
  SELECT session_id, day, topic FROM ranked WHERE nth = 1
),
orderers AS (
  SELECT DISTINCT session_id
  FROM events
  WHERE source = :source AND event_type = 'order_placed'
)
SELECT
  f.day,
  ROUND(100.0 * SUM(f.topic = 'allergy_or_diet' AND o.session_id IS NOT NULL)
        / NULLIF(SUM(f.topic = 'allergy_or_diet'), 0), 0)                  AS allergy_diet_pct,
  ROUND(100.0 * SUM(f.topic = 'recommendation' AND o.session_id IS NOT NULL)
        / NULLIF(SUM(f.topic = 'recommendation'), 0), 0)                   AS help_me_choose_pct,
  ROUND(100.0 * SUM(f.topic = 'budget' AND o.session_id IS NOT NULL)
        / NULLIF(SUM(f.topic = 'budget'), 0), 0)                           AS price_pct,
  ROUND(100.0 * SUM(f.topic NOT IN ('allergy_or_diet', 'recommendation', 'budget')
                    AND o.session_id IS NOT NULL)
        / NULLIF(SUM(f.topic NOT IN ('allergy_or_diet', 'recommendation', 'budget')), 0), 0)
                                                                           AS everything_else_pct
FROM first_q f
LEFT JOIN orderers o ON o.session_id = f.session_id
GROUP BY f.day
ORDER BY f.day;


-- @name: 12. Root cause, step 3: what went wrong?
-- @question: How long did answers take each day, allergy questions against the rest?
SELECT
  DATE(created_at) AS day,
  ROUND(AVG(CASE WHEN json_extract(properties, '$.topic') = 'allergy_or_diet'
                 THEN json_extract(properties, '$.response_ms') END) / 1000.0, 1) AS allergy_answer_secs,
  ROUND(AVG(CASE WHEN json_extract(properties, '$.topic') <> 'allergy_or_diet'
                 THEN json_extract(properties, '$.response_ms') END) / 1000.0, 1) AS other_answer_secs
FROM events
WHERE source = :source
  AND event_type = 'question_asked'
  AND NOT COALESCE(json_extract(properties, '$.from_cache'), 0)
GROUP BY day
ORDER BY day;
