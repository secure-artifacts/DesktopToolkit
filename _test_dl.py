from lyrics_engine import scan_page_for_songs, download_media
from pathlib import Path
import tempfile
urls = scan_page_for_songs("https://www.hidden-advent.org/recital.html")
print("catalog expand", len(urls), urls[:5])
urls2 = scan_page_for_songs("https://www.hidden-advent.org/readings-knowing-God.html")
print("category audios", len(urls2), urls2[:3])
# download one
if urls2:
  d=Path(tempfile.mkdtemp())
  a,l=download_media(urls2[0], d)
  print("dl", a, a.stat().st_size if a else None)
