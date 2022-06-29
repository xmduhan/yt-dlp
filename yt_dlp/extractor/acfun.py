import re

from .common import InfoExtractor
from ..utils import (
    parse_duration,
    parse_iso8601,
    try_get, traverse_obj, int_or_none, float_or_none,
)


class AcFunVideoIE(InfoExtractor):
    IE_NAME = 'AcFunVideoIE'
    _VALID_URL = r'''(?x)
                    https?://
                        (?:
                            www\.acfun\.cn/v/
                        )
                        ac(?P<id>\d+)
                    '''

    _TESTS = [{
        'url': 'https://www.acfun.cn/v/ac35457073',
        'info_dict': {
            'id': '35283657',
            'title': '【十五周年庆】文章区UP主祝AcFun生日快乐！',
            'duration': 455.21,
            'timestamp': 1655289827,
        },
        'params': {
            # m3u8 download
            'skip_download': True,
        },
    }, {
        'url': 'https://www.acfun.cn/v/ac35457073',
        'only_matching': True,
    }]

    def _real_extract(self, url):
        mobj = self._match_valid_url(url)

        video_id = mobj.group('id')

        webpage = self._download_webpage(url, video_id)

        json_all = self._search_json(r'window.videoInfo\s*=\s*', webpage, 'videoInfo', video_id)

        playjson = self._parse_json(traverse_obj(json_all, ('currentVideoInfo', 'ksPlayJson')), video_id)
        video_list_info = json_all['videoList']

        format_jsons = traverse_obj(playjson, ('adaptationSet', 0, 'representation'))

        formats = []
        for idx, video in enumerate(format_jsons):
            vcodec = None
            acodec = None

            codec_str = video.get('codecs') or ''
            m = re.match('(?P<vc>[^,]+),(?P<ac>[^,]+)', codec_str)
            if m:
                vcodec = m.group("vc")
                acodec = m.group("ac")

            fmt = {
                'url': video.get('url'),
                'fps': int_or_none(video.get('frameRate')),
                'width': int_or_none(video.get('width')),
                'height': int_or_none(video.get('height')),
                'vcodec': vcodec,
                'acodec': acodec,
                'tbr': float_or_none(video.get('avgBitrate'))
            }
            if 'm3u8Slice' in video:
                fmt['ext'] = 'ts'
            formats.append(fmt)

        video_info = video_list_info[0]
        info = {
            'id': video_id,
            'title': json_all['title'],
            'duration': float_or_none(video_info.get('durationMillis'), 1000),
            'timestamp': int_or_none(video_info.get('uploadTime'), 1000),
            'formats': formats,
            'http_headers': {
                'Referer': url,
            },
        }

        return info


class AcFunBangumiIE(InfoExtractor):
    IE_NAME = 'AcFunBangumiIE'
    _VALID_URL = r'''(?x)
                    https?://
                        (?:
                            www\.acfun\.cn/bangumi/
                        )
                        (?P<id>aa\d+)
                    '''

    _TESTS = [{
        'url': 'https://www.acfun.cn/bangumi/aa6002917',
        'info_dict': {
            'id': 'aa6002917',
            'title': '租借女友 第1话 租借女友',
            'duration': 1467,
            'timestamp': 1594432800,
        },
        'params': {
            # m3u8 download
            'skip_download': True,
        },
    }, {
        'url': 'https://www.acfun.cn/bangumi/aa6002917',
        'only_matching': True,
    }]

    def _real_extract(self, url):
        mobj = self._match_valid_url(url)

        video_id = mobj.group('id')

        webpage = self._download_webpage(url, video_id)

        json_all = self._search_json(r'window.bangumiData\s*=\s*', webpage, 'bangumiData', video_id)

        playjson = self._parse_json(traverse_obj(json_all, ('currentVideoInfo', 'ksPlayJson')), video_id)

        format_jsons = traverse_obj(playjson, ('adaptationSet', 0, 'representation'))

        formats = []
        for idx, video in enumerate(format_jsons):
            vcodec = None
            acodec = None

            codec_str = video.get('codecs') or ''
            m = re.match('(?P<vc>[^,]+),(?P<ac>[^,]+)', codec_str)
            if m:
                vcodec = m.group("vc")
                acodec = m.group("ac")

            fmt = {
                'url': video.get('url'),
                'fps': int_or_none(video.get('frameRate')),
                'width': int_or_none(video.get('width')),
                'height': int_or_none(video.get('height')),
                'vcodec': vcodec,
                'acodec': acodec,
                'tbr': float_or_none(video.get('avgBitrate'))
            }
            if 'm3u8Slice' in video:
                fmt['ext'] = 'ts'
            formats.append(fmt)

        info = {
            'id': video_id,
            'title': json_all['showTitle'],
            'duration': int_or_none(traverse_obj(json_all, ('currentVideoInfo', 'durationMillis')), 1000),
            'timestamp': parse_iso8601(json_all.get('updateTime'), delimiter=' '),
            'formats': formats,
            'http_headers': {
                'Referer': url,
            },
        }

        return info
