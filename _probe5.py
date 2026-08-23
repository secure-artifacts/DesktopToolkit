import urllib.request, urllib.parse, json, re

def get_gospel_ajax(page_url):
  html=urllib.request.urlopen(urllib.request.Request(page_url, headers={"User-Agent":"Mozilla/5.0"}), timeout=30).read().decode("utf-8","replace")
  m=re.search(r"gospelAjax\s*=\s*(\{.*?\})", html, re.S)
  cfg=json.loads(m.group(1).encode().decode("unicode_escape") if False else m.group(1).replace("\\/","/"))
  # safer parse
  cfg=json.loads(bytes(m.group(1), "utf-8").decode("unicode_escape")) if "\\/" in m.group(1) else json.loads(m.group(1))
  # try simple
  ajaxurl = re.search(r'"ajaxurl":"([^"]+)"', m.group(1)).group(1).replace("\\/","/")
  security = re.search(r'"security":"([^"]+)"', m.group(1)).group(1)
  # category slug from page
  slug = None
  for pat in [r'category_slug["\']?\s*[:=]\s*["\']([^"\']+)', r'data-category[_-]slug=["\']([^"\']+)', r'page-recitals[^"]*slug["\']:\s*["\']([^"\']+)']:
    mm=re.search(pat, html, re.I)
    if mm:
      slug=mm.group(1); break
  # from url path
  if not slug:
    slug=page_url.rstrip("/").split("/")[-1].replace(".html","")
  return ajaxurl, security, slug, html

page="https://www.hidden-advent.org/readings-knowing-God.html"
ajaxurl, security, slug, html = get_gospel_ajax(page)
print("ajax", ajaxurl)
print("sec", security)
print("slug", slug)

data=urllib.parse.urlencode({
  "action":"gp_home_ajax",
  "page_name":"page-recitals",
  "taxonomy":"category",
  "page_method":"get_list_category_data",
  "category_slug":slug,
  "tab_slug":"all",
  "page_no":"-1",
  "security":security,
}).encode()
req=urllib.request.Request(ajaxurl, data=data, headers={"User-Agent":"Mozilla/5.0","Referer":page})
resp=urllib.request.urlopen(req, timeout=30).read().decode("utf-8","replace")
print("resp len", len(resp))
print(resp[:800])
try:
  j=json.loads(resp)
  print("keys", j.keys() if isinstance(j,dict) else type(j))
  # dig for download_link
  s=json.dumps(j)[:2000]
  print(s[:2000])
except Exception as e:
  print("json err", e)
