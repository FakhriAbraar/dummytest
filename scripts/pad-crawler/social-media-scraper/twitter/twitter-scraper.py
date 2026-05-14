"""
Perlu install nodejs, npm, npx
Jalanin npx tweet-harvest dulu manual di terminal
Perlu extension buat liat cookies > auth_token
Kasih auth_token ke command
Baru jalan

To do:
Possible di scheduling
Selama environmentnya bisa download npm
Tinggal otomasi ngambil auth_token dari browser buat masukin ke command
"""
import subprocess

cmd = [
    "npx",
    "tweet-harvest",
    "-s", "AI Indonesia",
    "-l", "100",
    "-o", "tweets.csv"
]

result = subprocess.run(cmd, capture_output=True, text=True)

print("STDOUT:")
print(result.stdout)

print("STDERR:")
print(result.stderr)