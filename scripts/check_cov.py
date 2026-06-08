import json

with open("coverage.json", encoding="utf-8") as f:
    d = json.load(f)

files = {}
for k, v in d["files"].items():
    if "test" not in k.lower():
        files[k] = v["summary"]

sorted_files = sorted(files.items(), key=lambda x: x[1]["percent_covered"])
for f, s in sorted_files:
    print(
        f"{f}: {s['percent_covered']:.2f}% ({s['covered_lines']}/{s['num_statements']})"
    )
