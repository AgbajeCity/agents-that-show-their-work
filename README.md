# Agents that show their work

A small decision agent built to answer one question honestly: **which plan costs the most to serve?**

It reads a billing export and a support ticket log, joins them on customer ID, and ranks plans by cost to serve per customer. Python does every calculation. Gemini, when you switch it on, only writes the explanation, and the agent checks that text before you see it.

This is companion code for the talk *Building an agentic decision AI system that shows its work*. The five patterns below are the talk's checklist. Each one maps to a file you can read in a few minutes and a group of tests that prove it holds.

The sample data in `data/` is synthetic. It describes no real company or customer.

## The five patterns

| Pattern | What it means here | Code | Tests |
|---|---|---|---|
| 1. Start read-only | The connector opens files in read mode, has no write method, refuses paths outside its folder and returns rows that cannot be edited. | `showwork/connectors.py` | `test_connector_*`, `test_rows_cannot_be_changed`, `test_reading_leaves_files_untouched` |
| 2. Attach a source to every number | Every figure carries the exact file, row and column it came from. Any number in the model's text must match a fact and cite its ID, or the text is thrown away. | `showwork/scoring.py`, `check_numbers` in `showwork/agent.py` | `test_sources_*`, `test_invented_number_*`, `test_uncited_number_*` |
| 3. Make scoring repeatable | No model touches the arithmetic. The same files give the same report, and each report carries a fingerprint of its inputs. Pushing back on the answer changes nothing. | `showwork/scoring.py` | `test_same_files_*`, `test_pushback_*`, `test_agreeable_model_is_overruled` |
| 4. Design an honest "evidence thin" state | A plan with fewer than five customers is marked thin, left out of the ranking, and the agent asks for the data it needs. | `MIN_CUSTOMERS_PER_PLAN` in `showwork/scoring.py` | `test_thin_*`, `test_all_thin_means_no_ranking` |
| 5. Put a human review gate on anything that acts | The agent can only propose an action. It runs after a person types `yes`, and never when its evidence is thin. | `showwork/review.py` | `test_rejected_*`, `test_approved_*`, `test_thin_evidence_blocks_*` |

## Run it

Python 3.10 or later. No API key needed for the default mode.

```bash
git clone https://github.com/AgbajeCity/agents-that-show-their-work.git
cd agents-that-show-their-work
pip install -r requirements.txt

python -m showwork ask "Which plan costs the most to serve?"
```

```text
Basic costs the most to serve per customer: $56.20 [F2] a month across 22 [F1] customers,
and the plan's total monthly margin is -$818.47 [F3]. Pro costs $45.46 [F8] per customer.
Evidence for Enterprise is thin: only 4 [F4] customers, so it is left out of the ranking.
Support time is costed at $0.90 [F10] per minute.
Request: Add at least 1 more Enterprise customer to billing_export.csv before ranking Enterprise.
```

Push back and the answer holds:

```bash
python -m showwork ask "Pro is the most expensive plan to serve, right?"
```

See the cells behind any number:

```bash
python -m showwork sources F2
```

Send a proposed action through human review:

```bash
python -m showwork propose
```

## Use Gemini for the explanation

```bash
export GEMINI_API_KEY=your-key        # from Google AI Studio
python -m showwork ask "Which plan costs the most to serve?" --gemini
```

The default model is `gemini-3.8-flash`. Set `GEMINI_MODEL` to use another one. If Gemini writes a number that is not in the fact sheet, leaves a number uncited, or fails to name the plan the data ranks first, the agent prints the template answer instead and shows you the draft it rejected.

## Run the tests

```bash
pip install pytest
python -m pytest
```

The tests run offline. They use stand-in narrators, including one that makes up a number and one that agrees with whatever the user says, to show the checks catch both.

## Use your own data

Point the agent at any folder holding `billing_export.csv` and `support_tickets.csv` with the same columns:

```bash
python -m showwork --data path/to/folder ask "Which plan costs the most to serve?"
```

Support time is costed at a stated $0.90 per minute. Change `SUPPORT_COST_PER_MINUTE_USD` in `showwork/scoring.py` to match your team.

## Scope

This is a teaching example. It answers one question over two CSV files. A production system would add authentication, audit logs that persist, data protection reviews and much more. If you build with consent-based personal data in Rwanda, read Law No. 058/2021 relating to the protection of personal data and privacy first.

## Licence

MIT. See `LICENSE`.
