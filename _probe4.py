import urllib.request, re, json
js_url="https://static.kingdomsalvation.org/cdn/v3/common/page-recitals-list/page-recitals-list.min.js?v=260819"
js=urllib.request.urlopen(urllib.request.Request(js_url, headers={"User-Agent":"Mozilla/5.0"}), timeout=30).read().decode("utf-8","replace")
# extract around ajax calls
for m in re.finditer(r"ajax\s*\(\s*\{", js):
  i=m.start()
  print("---", js[i:i+500])
  print()
# also page-player js?
html=urllib.request.urlopen(urllib.request.Request("https://www.hidden-advent.org/readings-knowing-God.html", headers={"User-Agent":"Mozilla/5.0"}), timeout=30).read().decode("utf-8","replace")
# gospelAjax
for m in re.finditer(r"gospelAjax\s*=\s*(\{.*?\})", html, re.S):
  print("gospelAjax", m.group(1)[:500])
print("admin-ajax", "admin-ajax" in html)
print("ajaxurl", re.findall(r"ajaxurl[\"']?\s*[:=]\s*[\"']([^\"']+)", html)[:5])
# find category slug on page
print("category", re.findall(r"category[_-]?slug[\"']?\s*[:=]\s*[\"']([^\"']+)", html, re.I)[:5])
print("data-slug", re.findall(r"data-slug=[\"']([^\"']+)", html)[:10])
print("body class", re.findall(r"<body[^>]+class=[\"']([^\"']+)", html)[:2])
