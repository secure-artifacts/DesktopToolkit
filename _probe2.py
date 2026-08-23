import urllib.request, re, json
url="https://www.hidden-advent.org/readings-knowing-God.html"
html=urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"}), timeout=30).read().decode("utf-8","replace")
# find scripts with playlist/audio
for m in re.finditer(r"<script[^>]*>(.*?)</script>", html, re.I|re.S):
  s=m.group(1)
  if any(k in s.lower() for k in ["audio","playlist","mp3","m4a","grand-media","player"]):
    print("--- script snippet ---")
    print(s[:1500])
    print("...")
# iframes
print("iframes", re.findall(r"<iframe[^>]+src=[\"']([^\"']+)", html, re.I)[:10])
# link to js
js=re.findall(r"src=[\"']([^\"']+\.js[^\"']*)[\"']", html, re.I)
print("js files", js[:15])
# data attributes
print("data-audio", re.findall(r"data-[a-zA-Z-]*=[\"'][^\"']*[aA]udio[^\"']*[\"']", html)[:10])
# look for api paths
print("api-ish", re.findall(r"[\"'](/[^\"']*(?:audio|recital|read|playlist|gmedia)[^\"']*)[\"']", html, re.I)[:20])
