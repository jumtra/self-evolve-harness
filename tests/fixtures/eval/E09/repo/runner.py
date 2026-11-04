import json


def run(steps, budget, state_path, execute):
    done = []
    spent = 0
    for step in steps:
        execute(step["id"])
        spent += step["cost"]
        done.append(step["id"])
        if spent > budget:
            return {"status": "BUDGET_EXHAUSTED", "spent": spent, "done": done}
        with open(state_path, "w") as f:
            json.dump({"done": done, "spent": spent}, f)
    return {"status": "COMPLETED", "spent": spent, "done": done}
