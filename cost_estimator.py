import json
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup


URL = "https://platform.claude.com/docs/en/about-claude/pricing"
OUTPUT_FILE = "claude_pricing.json"

response = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
response.raise_for_status()

soup = BeautifulSoup(response.text, "html.parser")

claude_pricing = {"Model pricing":{}, "Batch processing":{}}
for table in soup.find_all("table"):
    headers = [re.sub(r"\s+", " ", th.get_text()).strip()
               for th in table.find_all("th")]
    if "model" in " ".join(headers).lower():
        if "base input tokens" in " ".join(headers).lower():
            for tr in table.find_all("tr")[1:]:
                cells = tr.find_all(["td", "th"])
                claude_pricing["Model pricing"][cells[0].get_text()] = {}
                for header, cell in zip(table.find_all("th")[1:],cells[1:]):
                    claude_pricing["Model pricing"][cells[0].get_text()][header.get_text()] = cell.get_text().split(" / ")[0].replace("$","")
                    claude_pricing["Model pricing"][cells[0].get_text()]["unit"] = re.sub(r"\d+(\.\d+)?", "", cell.get_text())
        elif "batch input" in " ".join(headers).lower():
            for tr in table.find_all("tr")[1:]:
                cells = tr.find_all(["td", "th"])
                claude_pricing["Batch processing"][cells[0].get_text()] = {}
                for header, cell in zip(table.find_all("th")[1:],cells[1:]):
                    claude_pricing["Batch processing"][cells[0].get_text()][header.get_text()] = cell.get_text().split(" / ")[0].replace("$","")
                    claude_pricing["Model pricing"][cells[0].get_text()]["unit"] = re.sub(r"\d+(\.\d+)?", "", cell.get_text())
with open("claude_pricing.json", "w", encoding="utf-8") as f:
    json.dump(claude_pricing, f, indent=2, ensure_ascii=False)

print("Claude prcing JSON file saved.")

