import json, os, time
PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory.json")


def load():
    if not os.path.exists(PATH):
        return None
    with open(PATH) as f:
        return json.load(f)


def save(mem):
    mem["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    tmp = PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(mem, f, indent=1, sort_keys=True)
    os.replace(tmp, PATH)
