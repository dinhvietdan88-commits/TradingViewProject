import subprocess
import time
import os

# Kill Chrome PID 15376
try:
    subprocess.run(["taskkill", "/F", "/PID", "15376"], capture_output=True)
except ValueError as e:
    import logging

    logging.getLogger(__name__).warning("Ignored: %s", e)

# Kill all TradingView processes
try:
    subprocess.run(["taskkill", "/F", "/IM", "TradingView.exe"], capture_output=True)
except ValueError as e:
    import logging

    logging.getLogger(__name__).warning("Ignored: %s", e)

time.sleep(2)

# Query AppxPackage for path
try:
    p = subprocess.run(
        [
            "powershell",
            "-Command",
            "(Get-AppxPackage -Name '*TradingView*').InstallLocation",
        ],
        capture_output=True,
        text=True,
    )
    install_location = p.stdout.strip()
    if install_location:
        exe_path = os.path.join(install_location, "TradingView.exe")
        print("Starting:", exe_path)
        subprocess.Popen(  # nosec
            [exe_path, "--remote-debugging-port=9223"],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        print("Started successfully!")
    else:
        print("TradingView app path not found")
except Exception as e:
    print("Error starting TradingView:", e)
