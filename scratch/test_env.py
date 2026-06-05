import os
import subprocess

print("Python env proxy vars:")
for k, v in os.environ.items():
    if "proxy" in k.lower():
        print(f"  {k} = {v}")

print("Running test_fetch.js via subprocess...")
res = subprocess.run(
    ["node", "scratch/test_fetch.js"], capture_output=True, text=True, env=os.environ
)
print("STDOUT:")
print(res.stdout)
print("STDERR:")
print(res.stderr)
