import json

html_path = r"H:\NEXEN\ui\mission_control.html"
json_path = r"H:\NEXEN\knowledge\master_100_prompts.json"

with open(html_path, "r", encoding="utf-8") as f:
    html = f.read()

with open(json_path, "r", encoding="utf-8") as f:
    prompts_data = json.load(f)["categories"]

# Replace ugcPrompts
start_tag = "ugcPrompts: ["
end_tag = "        productPrompts: ["
idx1 = html.find(start_tag)
idx2 = html.find(end_tag)
if idx1 != -1 and idx2 != -1:
    ugc_js = "ugcPrompts: " + json.dumps(prompts_data["ugc_personas"], indent=8) + ",\n"
    html = html[:idx1] + ugc_js + html[idx2:]

# Replace productPrompts
start_tag = "productPrompts: ["
end_tag = "        facelessNiches: ["
idx1 = html.find(start_tag)
idx2 = html.find(end_tag)
if idx1 != -1 and idx2 != -1:
    prod_js = "productPrompts: " + json.dumps(prompts_data["ecommerce_products"], indent=8) + ",\n"
    html = html[:idx1] + prod_js + html[idx2:]

# Replace facelessNiches
start_tag = "facelessNiches: ["
end_tag = "        kidsPrompts: ["
idx1 = html.find(start_tag)
idx2 = html.find(end_tag)
if idx1 != -1 and idx2 != -1:
    yt_js = "facelessNiches: " + json.dumps(prompts_data["faceless_youtube"], indent=8) + ",\n"
    html = html[:idx1] + yt_js + html[idx2:]

# Replace kidsPrompts
start_tag = "kidsPrompts: ["
end_tag = "        passionHomecare: ["
idx1 = html.find(start_tag)
idx2 = html.find(end_tag)
if idx1 != -1 and idx2 != -1:
    kids_js = "kidsPrompts: " + json.dumps(prompts_data["kids_animations"], indent=8) + ",\n"
    html = html[:idx1] + kids_js + html[idx2:]

# Replace passionHomecare
start_tag = "passionHomecare: ["
end_tag = "        scheduleCalendar: ["
idx1 = html.find(start_tag)
idx2 = html.find(end_tag)
if idx1 != -1 and idx2 != -1:
    phc_js = "passionHomecare: " + json.dumps(prompts_data["passion_homecare"], indent=8) + ",\n"
    html = html[:idx1] + phc_js + html[idx2:]

with open(html_path, "w", encoding="utf-8") as f:
    f.write(html)

print("Successfully injected all 100 master prompts into mission_control.html! Total length:", len(html))
