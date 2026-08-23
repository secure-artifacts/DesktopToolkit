import urllib.request, re
js_url="https://static.kingdomsalvation.org/cdn/v3/common/page-recitals-list/page-recitals-list.min.js?v=260819"
js=urllib.request.urlopen(urllib.request.Request(js_url, headers={"User-Agent":"Mozilla/5.0"}), timeout=30).read().decode("utf-8","replace")
print("js len", len(js))
# find urls
urls=set(re.findall(r"https?://[^\"'\s]+", js))
print("http urls", list(urls)[:30])
# api paths
paths=set(re.findall(r"[\"'](/[^\"']+)[\"']", js))
interesting=[p for p in paths if any(k in p.lower() for k in ["api","audio","recital","read","list","json","media","wp-"])]
print("paths", interesting[:40])
# keywords around fetch/ajax
for kw in ["fetch(","axios","ajax","playlist","mp3","m4a","grand-media","getJSON","/api/"]:
  i=js.lower().find(kw.lower())
  print(kw, i)
  if i>=0:
    print(js[max(0,i-80):i+200])
