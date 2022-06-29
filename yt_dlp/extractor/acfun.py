import re
from pathlib import Path

from .common import InfoExtractor
from ..utils import (
    traverse_obj, int_or_none, float_or_none,
)


class AcFunVideoIE(InfoExtractor):
    IE_NAME = 'AcFunVideoIE'
    _VALID_URL = r'''(?x)
                    https?://
                        (?:
                            www\.acfun\.cn/v/
                        )
                        ac(?P<id>[_\d]+)
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
        'skip': 'Geo-restricted to China',
    }, {
        'url': 'https://www.acfun.cn/v/ac35457073',
        'only_matching': True,
    }]

    def _real_extract(self, url):
        mobj = self._match_valid_url(url)

        video_id = mobj.group('id')

        webpage = self._download_webpage(url, video_id)

        json_all = self._search_json(r'window.videoInfo\s*=\s*', webpage, 'videoInfo', video_id)

        video_info = json_all['currentVideoInfo']
        playjson = self._parse_json(video_info['ksPlayJson'], video_id)
        video_inner_id = traverse_obj(json_all, ('currentVideoInfo', 'id'))

        format_jsons = traverse_obj(playjson, ('adaptationSet', 0, 'representation'))

        try:
            ext = Path(video_info['fileName']).suffix[1:]
        except Exception:
            self.report_warning('Parse ext failed, use mp4')
            ext = 'mp4'

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
                'tbr': float_or_none(video.get('avgBitrate')),
                'ext': ext
            }
            formats.append(fmt)

        self._sort_formats(formats)

        video_list = json_all['videoList']
        p_idx, video_info = [(idx, v) for (idx, v) in enumerate(video_list)
                             if v['id'] == video_inner_id
                             ][0]

        title = json_all['title']
        if len(video_list) > 1:
            title = f"{title} P{p_idx:02d} {video_info['title']}"
        info = {
            'id': video_id,
            'title': title,
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
                        (?P<id>aa[_\d]+)
                        (?:\?ac=(?P<ac_idx>\d+))?
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
        'skip': 'Geo-restricted to China',
    }, {
        'url': 'https://www.acfun.cn/bangumi/aa6002917',
        'only_matching': True,
    }, {
        'url': 'https://www.acfun.cn/bangumi/aa6002917_36188_1745457?ac=2',
        'only_matching': True,
    }]

    def _real_extract(self, url):
        mobj = self._match_valid_url(url)

        video_id = mobj.group('id')

        webpage = self._download_webpage(url, video_id)

        json_bangumi_data = self._search_json(r'window.bangumiData\s*=\s*', webpage, 'bangumiData', video_id)

        if not mobj.group('ac_idx'):
            video_info = json_bangumi_data['currentVideoInfo']
            playjson = self._parse_json(video_info['ksPlayJson'], video_id)
            title = json_bangumi_data['showTitle']
        else:
            # if has ac_idx, this url is a proxy to other video which is at https://www.acfun.cn/v/ac
            # the normal video_id is not in json
            ac_idx = mobj.group('ac_idx')
            video_id = f"{video_id}_ac={ac_idx}"
            video_info = json_bangumi_data['hlVideoInfo']
            playjson = self._parse_json(video_info['ksPlayJson'], video_id)
            title = video_info['title']

        try:
            ext = Path(video_info['fileName']).suffix[1:]
        except Exception:
            self.report_warning('Parse ext failed, use mp4')
            ext = 'mp4'

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
                'tbr': float_or_none(video.get('avgBitrate')),
                'ext': ext
            }
            formats.append(fmt)

        self._sort_formats(formats)

        info = {
            'id': video_id,
            'title': title,
            'duration': int_or_none(video_info['durationMillis'], 1000),
            'timestamp': int_or_none(video_info.get('uploadTime'), 1000),
            'formats': formats,
            'http_headers': {
                'Referer': url,
            },
        }

        return info
