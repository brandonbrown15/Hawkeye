# Hermes overnight coding autopilot (skill text)

Outcome: Keep Jetson Hermes working the Build Queue automatically while staying cheap and safe.

Instructions:
1. Read Ready + Local-safe items from the Build Queue.
2. Work only inside the stated acceptance criteria.
3. Use local model first. Do not call paid models unless the task is marked for cloud or local failed twice.
4. Create a feature branch `hermes/<task-id>-short-slug`, implement, run available checks, open a PR.
5. Log every session in Agent Runs.
6. On failure, write Escalation Log with why + context, then stop.
7. Never merge main. Never invent secrets. Prefer small PRs.
8. Send a short morning digest: what shipped, what failed, what needs human review.
