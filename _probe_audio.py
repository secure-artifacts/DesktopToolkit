import urllib.request, re
urls = [
 "https://www.hidden-advent.org/recital.html",
 "https://www.hidden-advent.org/readings-knowing-God.html",
 "https://www.hidden-advent.org/recital-god-word-selected-passages.html",
]
for url in urls:
  print("===", url)
  req=urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
  try:
    html=urllib.request.urlopen(req, timeout=30).read().decode("utf-8","replace")
  except Exception as e:
    print("ERR", e); continue
  print("len", len(html))
  mp3=re.findall(r"https?://[^\s\"'<>]+\.(?:mp3|m4a|ogg|wav)", html, re.I)
  print("direct audio", len(mp3), mp3[:3])
  gm=re.findall(r"grand-media/(?:audio|lrc)/[^\s\"'<>]+", html, re.I)
  print("grand-media", len(gm), gm[:5])
  shxg=re.findall(r"href=[\"']([^\"']*shxg\d+[^\"']*)[\"']", html, re.I)
  print("shxg links", len(shxg), shxg[:3])
  readings=re.findall(r"href=[\"']([^\"']*(?:reading|recital|audio)[^\"']*\.html)[\"']", html, re.I)
  print("reading links", len(set(readings)), list(set(readings))[:8])
  # gmedia player data
  for kw in ["gmedia", "wp-json", "playlist", "tracks", "audioUrl", "data-id"]:
    print(kw, html.lower().count(kw.lower()))
