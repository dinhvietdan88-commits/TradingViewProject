import pandas as pd

base_ts = 1774569600000
prices = [
    (100.0, 1000.0, 50.0, 500.0),
    (500.0, 10000.0, 400.0, 8000.0),
    (8000.0, 1000000.0, 7000.0, 50000.0),
    (50000.0, 60000.0, 0.0001, 10.0),
    (10.0, 100.0, 5.0, 90.0),
    (90.0, 150.0, 80.0, 120.0),
]

candles_5m = []
for i in range(6):
    ts = base_ts + i * 300000
    open_p, high_p, low_p, close_p = prices[i]
    candles_5m.append([ts, open_p, high_p, low_p, close_p, 15.0])

df = pd.DataFrame(
    candles_5m, columns=["timestamp", "open", "high", "low", "close", "volume"]
)
is_ms = True
if is_ms:
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
else:
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
df.set_index("datetime", inplace=True)

print("Original DF:")
print(df)

rule = "30min"
resampled = (
    df.resample(rule, closed="left", label="left")
    .agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    .dropna()
)

print("\nResampled DF:")
print(resampled)
