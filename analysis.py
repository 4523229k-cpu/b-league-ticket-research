import pandas as pd

# CSVの読み込み
df = pd.read_csv(
    "data/b_league_2026-11-10_to_17_combined.csv"
)

# ホーム・アウェーを仮判定
teams = df["試合名"].str.split(
    r"\s+vs\s+", n=1, expand=True
)

df["ホームチーム"] = teams[0]
df["アウェーチーム"] = teams[1]

# 確認
print(df[["試合名", "ホームチーム", "アウェーチーム"]].head(10))
