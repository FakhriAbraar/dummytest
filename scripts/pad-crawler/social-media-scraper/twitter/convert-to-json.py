import csv
import json

csv_file = "social-media-scraper/twitter/data/Prabowo_11-03-2026_00-32-58.csv"
json_file = "social-media-scraper/twitter/data/Prabowo_11-03-2026_00-32-58.json"

data = []

with open(csv_file, mode="r", encoding="utf-8") as file:
    reader = csv.DictReader(file)
    
    for row in reader:
        data.append(row)

with open(json_file, mode="w", encoding="utf-8") as file:
    json.dump(data, file, indent=4)

print("CSV berhasil dikonversi ke JSON!")