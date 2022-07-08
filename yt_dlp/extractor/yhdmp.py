
import re
import time

from .common import InfoExtractor


class YhdmpIE(InfoExtractor):
    _VALID_URL = r'(?x)https?://(?:www\.yhdmp\.cc/vp/)(?P<id>[\d]+-[12]-0)\.html'

    _TESTS = [{
        'url': 'https://www.yhdmp.cc/vp/22296-1-0.html',
        'only_matching': True,
    }]

    def _real_extract(self, url):
        video_id = self._match_id(url)

        params = self._downloader.params
        webpage_try_num = params.get('yhdmp_webpage_retry_num', 0) + 1

        for idx in range(webpage_try_num):
            try:
                webpage = self._download_webpage(url, video_id)
                break
            except Exception as e:
                print(e)
                print(f'download_webpage failed retry ({idx+1}/{webpage_try_num})...')
                time.sleep(3)
                if idx == webpage_try_num - 1:
                    raise

        title = self._search_regex(r'<title>(?P<t>[^<]+)</title>', webpage, 'title', group='t')

        title_mobj = re.match(r'(?P<t>.*?)\—在线播放\—樱花动漫\(P\)', title)
        if title_mobj.group('t'):
            title = title_mobj.group('t')

        return {
            'id': video_id,
            'title': title,
            'formats': [{'url': url, 'protocol': 'yhdmp', 'ext': 'mp4'}],
            '_type': 'video',
        }

