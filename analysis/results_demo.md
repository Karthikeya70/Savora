# Savora analysis — demo data

> **Practice data.** Made by scripts/demo_data.py. The patterns were put there by that script; these are not findings about real people.

## 1. The headline numbers

*How many people used it, how many questions, how many orders?*

| people | questions | orders | ratings |
| ------ | --------- | ------ | ------- |
| 600    | 1253      | 272    | 258     |

## 2. The funnel

*Of the people who asked a question, how many made it to each next step?*

| asked | got_a_suggestion | added_to_cart | ordered | rated | order_rate_pct |
| ----- | ---------------- | ------------- | ------- | ----- | -------------- |
| 600   | 543              | 358           | 272     | 151   | 45.3           |

## 3. What people ask about

*Which topics come up most, and do those people go on to order?*

| topic           | questions | share_pct | people | went_on_to_order_pct |
| --------------- | --------- | --------- | ------ | -------------------- |
| allergy_or_diet | 371       | 29.6      | 254    | 44.1                 |
| recommendation  | 267       | 21.3      | 185    | 51.4                 |
| ingredients     | 193       | 15.4      | 152    | 40.8                 |
| budget          | 175       | 14.0      | 124    | 60.5                 |
| spice           | 137       | 10.9      | 96     | 47.9                 |
| other           | 110       | 8.8       | 89     | 37.1                 |

## 4. Orders the assistant helped with

*What share of orders had at least one dish the assistant suggested first?*

| orders | helped_orders | helped_pct |
| ------ | ------------- | ---------- |
| 272    | 242           | 89.0       |

## 5. Dishes people see but don't choose

*Which dishes get suggested a lot but rarely picked? (Worst first.)*

| dish_name             | people_shown | picked_when_shown_pct | ratings | liked_pct |
| --------------------- | ------------ | --------------------- | ------- | --------- |
| Samosa Chaat          | 40           | 0.0                   |         |           |
| Schezwan Fried Rice   | 44           | 0.0                   |         |           |
| Garlic Naan           | 73           | 2.7                   | 2       | 100.0     |
| Crispy Chicken Burger | 33           | 3.0                   | 1       | 0.0       |
| Paneer Tikka Pizza    | 20           | 5.0                   | 1       | 0.0       |
| Chicken Biryani       | 75           | 5.3                   | 1       | 100.0     |
| Mixed Veg Pakora      | 92           | 5.4                   | 4       | 100.0     |
| Paneer Momos          | 64           | 6.3                   | 3       | 66.7      |

## 6. Do suggested dishes get liked more?

*Do people enjoy the food more when the assistant suggested it?*

| how_chosen             | ratings | liked_pct |
| ---------------------- | ------- | --------- |
| picked themselves      | 50      | 58.0      |
| suggested by assistant | 208     | 86.1      |

## 7. What people want that the menu doesn't have

*Which questions got an answer with no dish in it at all?*

| question                          | times_asked |
| --------------------------------- | ----------- |
| Do you have cheesecake?           | 49          |
| Do you have sushi?                | 41          |
| Do you serve sugar free desserts? | 36          |
| Is there a kids menu?             | 35          |

## 8. How long people take to decide

*How many questions do people ask before they order?*

| questions_before_ordering | people |
| ------------------------- | ------ |
| 1                         | 75     |
| 2                         | 106    |
| 3                         | 51     |
| 4                         | 40     |

## 9. A/B test: fewer choices

*Did group B (at most 3 dishes per answer) order more often than group A?*

| ab_group | people | avg_dishes_named | ordered | order_rate_pct |
| -------- | ------ | ---------------- | ------- | -------------- |
| A        | 316    | 3.07             | 147     | 46.5           |
| B        | 284    | 2.3              | 125     | 44.0           |

**Reading it:**

- Group B ordered 2.5 points less than group A (44.0% against 46.5%).
- Chance of a gap this size by pure luck: 54% (p-value 0.538).
- Verdict: can't tell. This gap is small enough to be luck, so treat the two versions as equal for now.
- To reliably spot a 5-point change you'd need about 1,564 people per group. You have 284.

## 10. Root cause, step 1: when did it happen?

*What was the order rate on each day?*

| day        | people_asking | people_ordering | order_rate_pct |
| ---------- | ------------- | --------------- | -------------- |
| 2026-09-05 | 38            | 19              | 50.0           |
| 2026-09-06 | 46            | 14              | 30.4           |
| 2026-09-07 | 45            | 17              | 37.8           |
| 2026-09-08 | 44            | 20              | 45.5           |
| 2026-09-09 | 46            | 30              | 65.2           |
| 2026-09-10 | 43            | 21              | 48.8           |
| 2026-09-11 | 45            | 18              | 40.0           |
| 2026-09-12 | 40            | 22              | 55.0           |
| 2026-09-13 | 56            | 25              | 44.6           |
| 2026-09-14 | 33            | 8               | 24.2           |
| 2026-09-15 | 44            | 23              | 52.3           |
| 2026-09-16 | 44            | 20              | 45.5           |
| 2026-09-17 | 67            | 31              | 46.3           |
| 2026-09-18 | 9             | 4               | 44.4           |

## 11. Root cause, step 2: who was affected?

*Split each day's order rate by what the person asked about first.*

| day        | allergy_diet_pct | help_me_choose_pct | price_pct | everything_else_pct |
| ---------- | ---------------- | ------------------ | --------- | ------------------- |
| 2026-09-05 | 50.0             | 67.0               | 75.0      | 27.0                |
| 2026-09-06 | 38.0             | 27.0               | 33.0      | 23.0                |
| 2026-09-07 | 40.0             | 44.0               | 40.0      | 27.0                |
| 2026-09-08 | 53.0             | 44.0               | 75.0      | 25.0                |
| 2026-09-09 | 55.0             | 67.0               | 67.0      | 73.0                |
| 2026-09-10 | 53.0             | 44.0               | 60.0      | 42.0                |
| 2026-09-11 | 33.0             | 50.0               | 86.0      | 19.0                |
| 2026-09-12 | 62.0             | 50.0               | 57.0      | 50.0                |
| 2026-09-13 | 44.0             | 63.0               | 25.0      | 45.0                |
| 2026-09-14 | 0.0              | 40.0               | 67.0      | 44.0                |
| 2026-09-15 | 57.0             | 50.0               | 67.0      | 44.0                |
| 2026-09-16 | 55.0             | 33.0               | 64.0      | 29.0                |
| 2026-09-17 | 38.0             | 78.0               | 40.0      | 30.0                |
| 2026-09-18 | 40.0             | 50.0               | 100.0     | 0.0                 |

## 12. Root cause, step 3: what went wrong?

*How long did answers take each day, allergy questions against the rest?*

| day        | allergy_answer_secs | other_answer_secs |
| ---------- | ------------------- | ----------------- |
| 2026-09-05 | 1.8                 | 0.7               |
| 2026-09-06 | 2.3                 | 0.7               |
| 2026-09-07 | 2.1                 | 0.8               |
| 2026-09-08 | 2.8                 | 0.7               |
| 2026-09-09 | 2.7                 | 0.8               |
| 2026-09-10 | 3.0                 | 0.8               |
| 2026-09-11 | 2.1                 | 0.8               |
| 2026-09-12 | 1.8                 | 0.8               |
| 2026-09-13 | 2.4                 | 0.7               |
| 2026-09-14 | 10.0                | 0.8               |
| 2026-09-15 | 2.0                 | 0.8               |
| 2026-09-16 | 2.2                 | 0.6               |
| 2026-09-17 | 2.4                 | 0.8               |
| 2026-09-18 | 2.4                 | 0.5               |
