import urllib.request, urllib.parse, re, json
page="https://www.hidden-advent.org/recital.html"
html=urllib.request.urlopen(urllib.request.Request(page, headers={"User-Agent":"Mozilla/5.0"}), timeout=30).read().decode("utf-8","replace")
ajaxurl=re.search(r'"ajaxurl":"([^"]+)"', html).group(1).replace("\\/","/")
security=re.search(r'"security":"([^"]+)"', html).group(1)
# try get category list
for method, extra in [
 ("get_list_category", {}),
 ("get_category_list", {}),
 ("get_list_category_data", {"category_slug":"all"}),
]:
  data={
    "action":"gp_home_ajax",
    "page_name":"page-recitals",
    "taxonomy":"category",
    "page_method":method,
    "tab_slug":"all",
    "page_no":"-1",
    "security":security,
    **extra,
  }
  try:
    body=urllib.parse.urlencode(data).encode()
    req=urllib.request.Request(ajaxurl, data=body, headers={"User-Agent":"Mozilla/5.0","Referer":page})
    resp=urllib.request.urlopen(req, timeout=20).read().decode("utf-8","replace")
    print(method, resp[:300])
  except Exception as e:
    print(method, "ERR", e)
# extract category slugs from links on recital.html
links=re.findall(r'href=["\']([^"\']+(?:readings|recital|audio|reading)[^"\']*\.html)["\']', html, re.I)
print("unique category pages", len(set(links)))
for u in sorted(set(links))[:15]:
  print(" ", u)
