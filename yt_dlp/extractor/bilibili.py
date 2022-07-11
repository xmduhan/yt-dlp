import base64
import collections
import itertools
import functools
import math

from .common import InfoExtractor, SearchInfoExtractor
from ..compat import (
    compat_urllib_parse_urlparse
)
from ..utils import (
    bug_reports_message,
    ExtractorError,
    filter_dict,
    int_or_none,
    float_or_none,
    format_field,
    mimetype2ext,
    qualities,
    traverse_obj,
    parse_count,
    srt_subtitles_timecode,
    str_or_none,
    urlencode_postdata,
    url_or_none,
    OnDemandPagedList
)


class BiliBiliIE(InfoExtractor):
    _VALID_URL = r'''(?x)
                    https?://
                        www\.
                        bilibili\.(?:tv|com)/
                        (?:
                            (?:
                                video/[aA][vV]|
                                (?P<bangumi>bangumi/play/)
                            )(?P<id>(?:ss|ep)?\d+)|
                            (s/)?video/[bB][vV](?P<id_bv>[^/?#&]+)
                        )
                        (?:/?\?p=(?P<page>\d+))?
                    '''

    _TESTS = [{
        'url': 'http://www.bilibili.com/video/av1074402/',
        'info_dict': {
            'thumbnail': 're:^https?://.*\.(jpg|jpeg)$',
            'uploader': '菊子桑',
            'uploader_id': '156160',
            'id': '1074402',
            'title': '【金坷垃】金泡沫',
            'duration': 308.36,
            'upload_date': '20140420',
            'like_count': int,
            'description': 'md5:ce18c2a2d2193f0df2917d270f2e5923',
            'comment_count': int,
            'timestamp': 1397983878,
            'view_count': int,
            'tags': ['金坷垃', '邓紫棋', '顶上去报复社会', '该来的总会来的', '金克拉是检验歌曲的唯一标准', '坷垃教主', '治愈系坷垃'],
        },
        'params': {
            'skip_download': True,
            'ignore_no_formats_error': True,
        },
    }, {
        'url': 'https://www.bilibili.com/bangumi/play/ep508406',
        'only_matching': True,
    }, {
        # bilibili.tv
        'url': 'http://www.bilibili.tv/video/av1074402/',
        'only_matching': True,
    }, {
        'url': 'https://www.bilibili.com/bangumi/play/ss897',
        'info_dict': {
            'series': '神的记事本',
            'season': '神的记事本',
            'season_id': 897,
            'season_number': 1,
            'episode': '你与旅行包',
            'episode_number': 2,
            'id': 'ss897',
            'title': '神的记事本：第2话 你与旅行包',
            'duration': 1428.487,
            'timestamp': 1310809380,
            'upload_date': '20110716',
            'thumbnail': r're:^https?://.*\.(jpg|jpeg|png)$',
        },
        'params': {
            'skip_download': True,
            'ignore_no_formats_error': True,
        },
    }, {
        'url': 'http://www.bilibili.com/video/av8903802/',
        'info_dict': {
            'id': '8903802',
            'title': '阿滴英文｜英文歌分享#6 "Closer',
            'description': '滴妹今天唱Closer給你聽! 有史以来，被推最多次也是最久的歌曲，其实歌词跟我原本想像差蛮多的，不过还是好听！ 微博@阿滴英文',
            'uploader_id': '65880958',
            'uploader': '阿滴英文',
            'thumbnail': r're:^https?://.*\.(jpg|jpeg|png)$',
            'duration': 554.117,
            'tags': ['英语', '公开课', '人文', '文化', '阿滴英文'],
            'comment_count': int,
            'upload_date': '20170301',
            'timestamp': 1488353834,
            'like_count': int,
            'view_count': int,
        },
        'params': {
            'skip_download': True,
            'ignore_no_formats_error': True,
        },
    }, {
        # Anthology
        'url': 'https://www.bilibili.com/video/BV1bK411W797',
        'info_dict': {
            'id': 'BV1bK411W797',
            'title': '物语中的人物是如何吐槽自己的OP的'
        },
        'playlist_count': 18,
    }, {
        # Correct matching of single and double quotes in title
        'url': 'https://www.bilibili.com/video/BV1NY411E7Rx/',
        'info_dict': {
            'id': '1NY411E7Rx',
            'title': 'Vid"eo" Te\'st',
            'thumbnail': r're:^https?://.*\.(jpg|jpeg|png)$',
            'uploader_id': '1630758804',
            'duration': 60.394,
            'uploader': 'bili_31244483705',
            'comment_count': int,
            'description': '',
            'tags': ['VLOG'],
            'view_count': int,
            'like_count': int,
            'upload_date': '20220408',
            'timestamp': 1649407752,
        },
        'params': {
            'skip_download': True,
            'ignore_no_formats_error': True,
        },
    }, {
        # old flv frags format example
        'url': 'https://www.bilibili.com/video/BV1Xx411P7Ks?p=1',
        'only_matching': True,
    }]

    def json2srt(self, json_data):
        srt_data = ''
        for idx, line in enumerate(json_data.get('body', [])):
            srt_data += f'{idx + 1}\n'
            srt_data += f'{srt_subtitles_timecode(line["from"])} --> {srt_subtitles_timecode(line["to"])}\n'
            srt_data += f'{line["content"]}\n\n'
        return srt_data

    def _real_extract(self, url):
        mobj = self._match_valid_url(url)
        video_id = mobj.group('id_bv') or mobj.group('id')

        webpage = self._download_webpage(url, video_id)

        if '开通大会员观看' in webpage and '__playinfo__' not in webpage:
            raise ExtractorError(f'VIP is required for {url}', expected=True)

        initial_state = self._search_json(r'window.__INITIAL_STATE__\s*=\s*', webpage, 'initial state', video_id)

        is_bangumi = mobj.group('bangumi') is not None
        video_data = traverse_obj(initial_state, 'epInfo', 'videoData') or {}
        bv_id = video_data['bvid']

        page_list_json = traverse_obj(
            self._download_json(
                'https://api.bilibili.com/x/player/pagelist', video_id,
                fatal=False, query={'bvid': bv_id, 'jsonp': 'jsonp'},
                note='Extracting videos in anthology'),
            'data', expected_type=list) or []
        has_multi_p = len(page_list_json or []) > 1

        page_id = int_or_none(mobj.group('page'))

        title = self._html_search_regex((
            r'<h1[^>]+title=(["])(?P<content>[^"]+)',
            r'<h1[^>]+title=([\'])(?P<content>[^\']+)',
            r'(?s)<h1[^>]*>(?P<content>.+?)</h1>',
            self._meta_regex('title')
        ), webpage, 'title', group='content', fatal=False)

        if not is_bangumi and has_multi_p and page_id is None:
            # Bilibili anthologies are similar to playlists but all videos share the same video ID as the anthology itself.
            # If the video has no page argument and it's an anthology, download as a playlist
            if not self.get_param('noplaylist'):
                ret = self.playlist_from_matches(page_list_json, bv_id, title, ie=BiliBiliIE.ie_key(),
                                                 getter=lambda entry: f'https://www.bilibili.com/video/{bv_id}?p={entry["page"]}')
                if ret is not None:
                    self.to_screen('Downloading anthology %s - add --no-playlist to just download video' % video_id)
                    return ret
            else:
                self.to_screen('Downloading just video %s because of --no-playlist' % video_id)

        http_headers = {
            'Referer': url,
            **self.geo_verification_headers()
        }

        # Get part title for anthologies
        if page_id is not None and has_multi_p:
            title = f'{title} p{page_id:02d} {traverse_obj(page_list_json, (page_id - 1, "part")) or ""}'

        id_str = f'{video_id}{format_field(page_id, template= f"_p%02d", default="")}'

        play_info = self._search_json(r'window.__playinfo__\s*=\s*', webpage, 'play info', video_id)['data']

        format_desc_dict = {
            r['quality']: traverse_obj(r, 'new_description', 'display_desc')
            for r in traverse_obj(play_info, 'support_formats', expected_type=list) or []
            if 'quality' in r
        }

        info = {'formats': []}
        audios = traverse_obj(play_info, ('dash', 'audio')) or []

        for idx, video in enumerate(traverse_obj(play_info, ('dash', 'video')) or []):
            info['formats'].append({
                'url': video.get('baseUrl') or video.get('base_url') or video.get('url'),
                'ext': mimetype2ext(video.get('mimeType') or video.get('mime_type')),
                'fps': self.fix_fps(video.get('frameRate') or video.get('frame_rate')),
                'width': int_or_none(video.get('width')),
                'height': int_or_none(video.get('height')),
                'vcodec': video.get('codecs'),
                'acodec': 'none' if audios else None,
                'tbr': float_or_none(video.get('bandwidth'), scale=1000),
                'filesize': int_or_none(video.get('size')),
                'quality': video.get('id'),
                'format_note': format_desc_dict.get(video.get('id')),
            })

        for audio in audios:
            info['formats'].append({
                'url': audio.get('baseUrl') or audio.get('base_url') or audio.get('url'),
                'ext': mimetype2ext(audio.get('mimeType') or audio.get('mime_type')),
                'acodec': audio.get('codecs'),
                'vcodec': 'none',
                'tbr': float_or_none(audio.get('bandwidth'), scale=1000),
                'filesize': int_or_none(audio.get('size'))
            })

        self._sort_formats(info['formats'])

        if not info['formats']:
            if 'dash' not in play_info:
                # old video
                info = self.parse_old_flv_formats(video_id, bv_id, video_data.get('cid'),
                                                  play_info['support_formats'] or [], id_str,
                                                  title, http_headers)
            else:
                raise ExtractorError(f'Unknown webpage schema{bug_reports_message()}')

        if is_bangumi:
            season_id = traverse_obj(initial_state, ('mediaInfo', 'season_id'))

            season_number = season_id and next((
                idx + 1 for idx, e in enumerate(
                    traverse_obj(initial_state, ('mediaInfo', 'seasons')) or [])
                if e.get('season_id') == season_id
            ), None)

            # There is no description for episode, only has description for season
            info.update({
                'timestamp': traverse_obj(initial_state, ('epInfo', 'pub_time')),
                'thumbnail': traverse_obj(initial_state, ('epInfo', 'cover')),

                'series': traverse_obj(initial_state, ('mediaInfo', 'series')),
                'season': traverse_obj(initial_state, ('mediaInfo', 'season_title')),
                'season_id': season_id,
                'season_number': season_number,
                'episode': traverse_obj(initial_state, ('epInfo', 'long_title')),
                'episode_number': int_or_none(traverse_obj(initial_state, ('epInfo', 'title'))),
            })
        else:
            info.update({
                # description in meta has many other infos about related videos
                'description': traverse_obj(initial_state, ('videoData', 'desc')),
                'timestamp': traverse_obj(initial_state, ('videoData', 'pubdate')),
                'thumbnail': traverse_obj(initial_state, ('videoData', 'pic')),
                'view_count': traverse_obj(initial_state, ('videoData', 'stat', 'view')),
                'like_count': traverse_obj(initial_state, ('videoData', 'stat', 'like')),
                'comment_count': traverse_obj(initial_state, ('videoData', 'stat', 'reply')),
                'uploader': traverse_obj(initial_state, ('upData', 'name')),
                'uploader_id': traverse_obj(initial_state, ('upData', 'mid')),
                'tags': [t['tag_name'] for t in initial_state.get('tags', []) if 'tag_name' in t],
            })

        return {
            **info,
            'id': id_str,
            'title': title,
            'duration': float_or_none(play_info.get('timelength'), scale=1000),
            'subtitles': self.extract_subtitles(video_id, initial_state, video_data.get("cid"), is_bangumi),
            'http_headers': http_headers,
            '__post_extractor': self.extract_comments(video_data.get('aid')),
        }

    def fix_fps(self, s):
        if s is None:
            return None
        try:
            v = float(s)
        except Exception:
            return None

        if v <= 0:
            return None

        all_fps = [8, 16, 24, 25, 30, 48, 50, 60]
        all_fps.sort(key=lambda f: abs(1 - v / f))
        if abs(1 - v / all_fps[0]) < max(3.0 / 60, 2.0 / 24):
            return all_fps[0]

        return v

    def parse_old_flv_formats(self, video_id, bv_id, cid, support_formats, id_str, title, http_headers):
        formats = []
        for f in support_formats:
            playurl = f'https://api.bilibili.com/x/player/playurl?bvid={bv_id}&cid={cid}&qn={f["quality"]}'
            video_info_ext = self._download_json(playurl, video_id, headers=http_headers, fatal=False)
            if not video_info_ext:
                continue
            video_info_ext = video_info_ext['data']

            slices = []
            for durl in video_info_ext['durl']:
                slices.append({
                    'url': durl['url'],
                    'filesize': int_or_none(durl['size'])
                })
            ext = f['format']
            if ext.startswith('flv'):
                # flv, flv360, flv720
                ext = 'flv'

            filesize = 0
            for s in slices:
                if s['filesize'] is None:
                    filesize = None
                else:
                    filesize += s['filesize']

            if len(slices) == 0:
                continue

            fmt = {
                'url': slices[0]['url'],
                'ext': ext,
                'quality': f['quality'],
                'format_note': traverse_obj(f, 'new_description', 'display_desc'),
                'height': int_or_none(f['display_desc'].rstrip('P')),
                'vcodec': f.get('codecs'),
                'entries': slices,
                'filesize': filesize
            }
            formats.append(fmt)

        self._sort_formats(formats)

        # if all formats have same num of slices, rewrite it as multi_video
        return self.rewrite_as_multi_video(formats, id_str, title, http_headers)

    def rewrite_as_multi_video(self, formats, id_str, title, http_headers):
        slice_num_set = set(len(f['entries']) for f in formats)
        if len(slice_num_set) > 1:
            fallback_fmt = formats[-1]
            self.report_warning(
                f'Found formats have different num of slices. Fallback to best format {fallback_fmt["quality_desc"]}{bug_reports_message()}')
            formats = [fallback_fmt]
            slice_num = len(fallback_fmt['entries'])
        else:
            slice_num = slice_num_set.pop()
        entries = []
        for idx in range(slice_num):
            slice_formats = [{**f} for f in formats]
            for f in slice_formats:
                f['url'] = f['entries'][idx]['url']
                f['filesize'] = f['entries'][idx]['filesize']
                del f['entries']

            entries.append({
                'id': f'{id_str}-Frag{idx + 1:02d}',
                'title': f'{title}-Frag{idx + 1:02d}',
                'formats': slice_formats,
                'http_headers': http_headers,
            })
        if len(entries) <= 1:
            info_fmt = {
                'formats': formats,
            }
        else:
            info_fmt = {
                '_type': 'multi_video',
                'entries': entries
            }
        return info_fmt

    def _get_subtitles(self, video_id, initial_state, cid, is_bangumi):
        subtitles = collections.defaultdict(list)
        if not is_bangumi and self.get_param('writesubtitles', False):
            subtitle_info = traverse_obj(initial_state, ('videoData', 'subtitle')) or {}

            for s in subtitle_info.get('list', []):
                subtitle_url = s['subtitle_url']
                subtitle_json = self._download_json(subtitle_url, video_id)
                subtitles[s['lan']].append({
                    'ext': 'srt',
                    'data': self.json2srt(subtitle_json)
                })
            subtitles['danmaku'] = [{
                'ext': 'xml',
                'url': f'https://comment.bilibili.com/{cid}.xml',
            }]
        return dict(subtitles)

    def _get_comments(self, aid, commentPageNumber=0):
        for idx in itertools.count(1):
            replies = traverse_obj(
                self._download_json(
                    f'https://api.bilibili.com/x/v2/reply?pn={idx}&oid={aid}&type=1&jsonp=jsonp&sort=2&_=1567227301685',
                    aid, note=f'Extracting comments from page {idx}', fatal=False),
                ('data', 'replies'))
            if not replies:
                return
            for children in map(self._get_all_children, replies):
                yield from children

    def _get_all_children(self, reply):
        yield {
            'author': traverse_obj(reply, ('member', 'uname')),
            'author_id': traverse_obj(reply, ('member', 'mid')),
            'id': reply.get('rpid'),
            'text': traverse_obj(reply, ('content', 'message')),
            'timestamp': reply.get('ctime'),
            'parent': reply.get('parent') or 'root',
        }
        for children in map(self._get_all_children, reply.get('replies') or []):
            yield from children


class BilibiliBangumiMediaIE(InfoExtractor):
    _VALID_URL = r'https?://www\.bilibili\.com/bangumi/media/md(?P<id>\d+)'
    _TESTS = [{
        'url': 'https://www.bilibili.com/bangumi/media/md24097891',
        'only_matching': True,
    }]

    def _real_extract(self, url):
        media_id = self._match_id(url)

        webpage = self._download_webpage(url, media_id)
        initial_state = self._search_json(r'window.__INITIAL_STATE__\s*=\s*', webpage, 'initial_state', media_id)

        season_id = traverse_obj(initial_state, ('mediaInfo', 'season_id'))

        episode_list = traverse_obj(
            self._download_json(
                f'https://api.bilibili.com/pgc/web/season/section?season_id={season_id}',
                media_id, note='Downloading season info'
            ).get('result', {}),
            ('main_section', 'episodes')) or []

        return self.playlist_result(
            [self.url_result(entry['share_url'], BiliBiliIE.ie_key(), entry['aid']) for entry in episode_list],
            media_id)


class BilibiliChannelIE(InfoExtractor):
    _VALID_URL = r'https?://space.bilibili\.com/(?P<id>\d+)(:?/channel/collectiondetail\?sid=(?P<sid>\d+))?'
    _TESTS = [{
        'url': 'https://space.bilibili.com/3985676/video',
        'info_dict': {
            'id': '3985676',
        },
        'playlist_mincount': 112,
    }]

    def get_space_entries(self, mid):
        count, max_count = 0, None

        for page_num in itertools.count(1):
            url = f"https://api.bilibili.com/x/space/arc/search?mid={mid}&pn={page_num}&jsonp=jsonp"
            data = self._download_json(url, mid, note=f'Downloading page {page_num}').get('data', {})

            max_count = max_count or traverse_obj(data, ('page', 'count'))

            entries = traverse_obj(data, ('list', 'vlist'))
            if not entries:
                return
            for entry in entries:
                yield self.url_result(f'https://www.bilibili.com/video/{entry["bvid"]}',
                                      BiliBiliIE.ie_key(), entry['bvid'])

            count += len(entries)
            if max_count and count >= max_count:
                return

    def get_space_season_entries(self, mid, sid):
        count, max_count = 0, None

        for page_num in itertools.count(1):
            data = self._download_json(
                f"https://api.bilibili.com/x/polymer/space/seasons_archives_list?mid={mid}&season_id={sid}&page_num={page_num}&page_size=30",
                sid, note=f'Downloading page {page_num}').get('data', {})

            max_count = max_count or traverse_obj(data, ('page', 'total'))

            entries = data.get('archives', [])
            for entry in entries:
                yield self.url_result(f'https://www.bilibili.com/video/{entry["bvid"]}',
                                      BiliBiliIE.ie_key(), entry['bvid'])

            count += len(entries)
            if max_count and count >= max_count:
                return

    def _real_extract(self, url):
        mobj = self._match_valid_url(url)
        mid = mobj.group('id')

        if mobj.group('sid'):
            sid = mobj.group('sid')
            list_id = f'{mid}_{sid}'
            entries = list(self.get_space_season_entries(mid, sid))
        else:
            list_id = mid
            entries = list(self.get_space_entries(mid))

        return self.playlist_result(entries, list_id)


class BilibiliCategoryIE(InfoExtractor):
    IE_NAME = 'Bilibili category extractor'
    _MAX_RESULTS = 1000000
    _VALID_URL = r'https?://www\.bilibili\.com/v/[a-zA-Z]+\/[a-zA-Z]+'
    _TESTS = [{
        'url': 'https://www.bilibili.com/v/kichiku/mad',
        'info_dict': {
            'id': 'kichiku: mad',
            'title': 'kichiku: mad'
        },
        'playlist_mincount': 45,
        'params': {
            'playlistend': 45
        }
    }]

    def _fetch_page(self, api_url, num_pages, query, page_num):
        parsed_json = self._download_json(
            api_url, query, query={'Search_key': query, 'pn': page_num},
            note='Extracting results from page %s of %s' % (page_num, num_pages))

        video_list = traverse_obj(parsed_json, ('data', 'archives'), expected_type=list)
        if not video_list:
            raise ExtractorError('Failed to retrieve video list for page %d' % page_num)

        for video in video_list:
            yield self.url_result(
                'https://www.bilibili.com/video/%s' % video['bvid'], 'BiliBili', video['bvid'])

    def _entries(self, category, subcategory, query):
        # map of categories : subcategories : RIDs
        rid_map = {
            'kichiku': {
                'mad': 26,
                'manual_vocaloid': 126,
                'guide': 22,
                'theatre': 216,
                'course': 127
            },
        }

        if category not in rid_map:
            raise ExtractorError(
                f'The category {category} isn\'t supported. Supported categories: {list(rid_map.keys())}')
        if subcategory not in rid_map[category]:
            raise ExtractorError(
                f'The subcategory {subcategory} isn\'t supported for this category. Supported subcategories: {list(rid_map[category].keys())}')
        rid_value = rid_map[category][subcategory]

        api_url = 'https://api.bilibili.com/x/web-interface/newlist?rid=%d&type=1&ps=20&jsonp=jsonp' % rid_value
        page_json = self._download_json(api_url, query, query={'Search_key': query, 'pn': '1'})
        page_data = traverse_obj(page_json, ('data', 'page'), expected_type=dict)
        count, size = int_or_none(page_data.get('count')), int_or_none(page_data.get('size'))
        if count is None or not size:
            raise ExtractorError('Failed to calculate either page count or size')

        num_pages = math.ceil(count / size)

        return OnDemandPagedList(functools.partial(
            self._fetch_page, api_url, num_pages, query), size)

    def _real_extract(self, url):
        u = compat_urllib_parse_urlparse(url)
        category, subcategory = u.path.split('/')[2:4]
        query = '%s: %s' % (category, subcategory)

        return self.playlist_result(self._entries(category, subcategory, query), query, query)


class BiliBiliSearchIE(SearchInfoExtractor):
    IE_DESC = 'Bilibili video search'
    _MAX_RESULTS = 100000
    _SEARCH_KEY = 'bilisearch'

    def _search_results(self, query):
        for page_num in itertools.count(1):
            videos = self._download_json(
                'https://api.bilibili.com/x/web-interface/search/type', query,
                note=f'Extracting results from page {page_num}', query={
                    'Search_key': query,
                    'keyword': query,
                    'page': page_num,
                    'context': '',
                    'order': 'pubdate',
                    'duration': 0,
                    'tids_2': '',
                    '__refresh__': 'true',
                    'search_type': 'video',
                    'tids': 0,
                    'highlight': 1,
                })['data'].get('result') or []
            for video in videos:
                yield self.url_result(video['arcurl'], 'BiliBili', str(video['aid']))


class BilibiliAudioBaseIE(InfoExtractor):
    def _call_api(self, path, sid, query=None):
        if not query:
            query = {'sid': sid}
        return self._download_json(
            'https://www.bilibili.com/audio/music-service-c/web/' + path,
            sid, query=query)['data']


class BilibiliAudioIE(BilibiliAudioBaseIE):
    _VALID_URL = r'https?://(?:www\.)?bilibili\.com/audio/au(?P<id>\d+)'
    _TEST = {
        'url': 'https://www.bilibili.com/audio/au1003142',
        'md5': 'fec4987014ec94ef9e666d4d158ad03b',
        'info_dict': {
            'id': '1003142',
            'ext': 'm4a',
            'title': '【tsukimi】YELLOW / 神山羊',
            'artist': 'tsukimi',
            'comment_count': int,
            'description': 'YELLOW的mp3版！',
            'duration': 183,
            'subtitles': {
                'origin': [{
                    'ext': 'lrc',
                }],
            },
            'thumbnail': r're:^https?://.+\.jpg',
            'timestamp': 1564836614,
            'upload_date': '20190803',
            'uploader': 'tsukimi-つきみぐー',
            'view_count': int,
        },
    }

    def _real_extract(self, url):
        au_id = self._match_id(url)

        play_data = self._call_api('url', au_id)
        formats = [{
            'url': play_data['cdns'][0],
            'filesize': int_or_none(play_data.get('size')),
            'vcodec': 'none'
        }]

        for a_format in formats:
            a_format.setdefault('http_headers', {}).update({
                'Referer': url,
            })

        song = self._call_api('song/info', au_id)
        title = song['title']
        statistic = song.get('statistic') or {}

        subtitles = None
        lyric = song.get('lyric')
        if lyric:
            subtitles = {
                'origin': [{
                    'url': lyric,
                }]
            }

        return {
            'id': au_id,
            'title': title,
            'formats': formats,
            'artist': song.get('author'),
            'comment_count': int_or_none(statistic.get('comment')),
            'description': song.get('intro'),
            'duration': int_or_none(song.get('duration')),
            'subtitles': subtitles,
            'thumbnail': song.get('cover'),
            'timestamp': int_or_none(song.get('passtime')),
            'uploader': song.get('uname'),
            'view_count': int_or_none(statistic.get('play')),
        }


class BilibiliAudioAlbumIE(BilibiliAudioBaseIE):
    _VALID_URL = r'https?://(?:www\.)?bilibili\.com/audio/am(?P<id>\d+)'
    _TEST = {
        'url': 'https://www.bilibili.com/audio/am10624',
        'info_dict': {
            'id': '10624',
            'title': '每日新曲推荐（每日11:00更新）',
            'description': '每天11:00更新，为你推送最新音乐',
        },
        'playlist_count': 19,
    }

    def _real_extract(self, url):
        am_id = self._match_id(url)

        songs = self._call_api(
            'song/of-menu', am_id, {'sid': am_id, 'pn': 1, 'ps': 100})['data']

        entries = []
        for song in songs:
            sid = str_or_none(song.get('id'))
            if not sid:
                continue
            entries.append(self.url_result(
                'https://www.bilibili.com/audio/au' + sid,
                BilibiliAudioIE.ie_key(), sid))

        if entries:
            album_data = self._call_api('menu/info', am_id) or {}
            album_title = album_data.get('title')
            if album_title:
                for entry in entries:
                    entry['album'] = album_title
                return self.playlist_result(
                    entries, am_id, album_title, album_data.get('intro'))

        return self.playlist_result(entries, am_id)


class BiliBiliPlayerIE(InfoExtractor):
    _VALID_URL = r'https?://player\.bilibili\.com/player\.html\?.*?\baid=(?P<id>\d+)'
    _TEST = {
        'url': 'http://player.bilibili.com/player.html?aid=92494333&cid=157926707&page=1',
        'only_matching': True,
    }

    def _real_extract(self, url):
        aid = self._match_id(url)

        bv_id = traverse_obj(
            self._download_json(f'https://api.bilibili.com/x/web-interface/view?aid={aid}', aid),
            ('data', 'bvid'))
        return self.url_result(f'http://www.bilibili.com/video/{bv_id}/',
                               ie=BiliBiliIE.ie_key(), video_id=bv_id)


class BiliIntlBaseIE(InfoExtractor):
    _API_URL = 'https://api.bilibili.tv/intl/gateway'
    _NETRC_MACHINE = 'biliintl'

    def _call_api(self, endpoint, *args, **kwargs):
        json = self._download_json(self._API_URL + endpoint, *args, **kwargs)
        if json.get('code'):
            if json['code'] in (10004004, 10004005, 10023006):
                self.raise_login_required()
            elif json['code'] == 10004001:
                self.raise_geo_restricted()
            else:
                if json.get('message') and str(json['code']) != json['message']:
                    errmsg = f'{kwargs.get("errnote", "Unable to download JSON metadata")}: {self.IE_NAME} said: {json["message"]}'
                else:
                    errmsg = kwargs.get('errnote', 'Unable to download JSON metadata')
                if kwargs.get('fatal'):
                    raise ExtractorError(errmsg)
                else:
                    self.report_warning(errmsg)
        return json.get('data')

    def json2srt(self, json):
        data = '\n\n'.join(
            f'{i + 1}\n{srt_subtitles_timecode(line["from"])} --> {srt_subtitles_timecode(line["to"])}\n{line["content"]}'
            for i, line in enumerate(traverse_obj(json, (
                'body', lambda _, l: l['content'] and l['from'] and l['to']))))
        return data

    def _get_subtitles(self, *, ep_id=None, aid=None):
        sub_json = self._call_api(
            '/web/v2/subtitle', ep_id or aid, note='Downloading subtitles list',
            errnote='Unable to download subtitles list', query=filter_dict({
                'platform': 'web',
                'episode_id': ep_id,
                'aid': aid,
            }))
        subtitles = {}
        for sub in sub_json.get('subtitles') or []:
            sub_url = sub.get('url')
            if not sub_url:
                continue
            sub_data = self._download_json(
                sub_url, ep_id or aid, errnote='Unable to download subtitles', fatal=False,
                note='Downloading subtitles%s' % f' for {sub["lang"]}' if sub.get('lang') else '')
            if not sub_data:
                continue
            subtitles.setdefault(sub.get('lang_key', 'en'), []).append({
                'ext': 'srt',
                'data': self.json2srt(sub_data)
            })
        return subtitles

    def _get_formats(self, *, ep_id=None, aid=None):
        video_json = self._call_api(
            '/web/playurl', ep_id or aid, note='Downloading video formats',
            errnote='Unable to download video formats', query=filter_dict({
                'platform': 'web',
                'ep_id': ep_id,
                'aid': aid,
            }))
        video_json = video_json['playurl']
        formats = []
        for vid in video_json.get('video') or []:
            video_res = vid.get('video_resource') or {}
            video_info = vid.get('stream_info') or {}
            if not video_res.get('url'):
                continue
            formats.append({
                'url': video_res['url'],
                'ext': 'mp4',
                'format_note': video_info.get('desc_words'),
                'width': video_res.get('width'),
                'height': video_res.get('height'),
                'vbr': video_res.get('bandwidth'),
                'acodec': 'none',
                'vcodec': video_res.get('codecs'),
                'filesize': video_res.get('size'),
            })
        for aud in video_json.get('audio_resource') or []:
            if not aud.get('url'):
                continue
            formats.append({
                'url': aud['url'],
                'ext': 'mp4',
                'abr': aud.get('bandwidth'),
                'acodec': aud.get('codecs'),
                'vcodec': 'none',
                'filesize': aud.get('size'),
            })

        self._sort_formats(formats)
        return formats

    def _extract_video_info(self, video_data, *, ep_id=None, aid=None):
        return {
            'id': ep_id or aid,
            'title': video_data.get('title_display') or video_data.get('title'),
            'thumbnail': video_data.get('cover'),
            'episode_number': int_or_none(self._search_regex(
                r'^E(\d+)(?:$| - )', video_data.get('title_display') or '', 'episode number', default=None)),
            'formats': self._get_formats(ep_id=ep_id, aid=aid),
            'subtitles': self._get_subtitles(ep_id=ep_id, aid=aid),
            'extractor_key': BiliIntlIE.ie_key(),
        }

    def _perform_login(self, username, password):
        try:
            from Cryptodome.PublicKey import RSA
            from Cryptodome.Cipher import PKCS1_v1_5
        except ImportError:
            try:
                from Crypto.PublicKey import RSA
                from Crypto.Cipher import PKCS1_v1_5
            except ImportError:
                raise ExtractorError('pycryptodomex not found. Please install', expected=True)

        key_data = self._download_json(
            'https://passport.bilibili.tv/x/intl/passport-login/web/key?lang=en-US', None,
            note='Downloading login key', errnote='Unable to download login key')['data']

        public_key = RSA.importKey(key_data['key'])
        password_hash = PKCS1_v1_5.new(public_key).encrypt((key_data['hash'] + password).encode('utf-8'))
        login_post = self._download_json(
            'https://passport.bilibili.tv/x/intl/passport-login/web/login/password?lang=en-US', None, data=urlencode_postdata({
                'username': username,
                'password': base64.b64encode(password_hash).decode('ascii'),
                'keep_me': 'true',
                's_locale': 'en_US',
                'isTrusted': 'true'
            }), note='Logging in', errnote='Unable to log in')
        if login_post.get('code'):
            if login_post.get('message'):
                raise ExtractorError(f'Unable to log in: {self.IE_NAME} said: {login_post["message"]}', expected=True)
            else:
                raise ExtractorError('Unable to log in')


class BiliIntlIE(BiliIntlBaseIE):
    _VALID_URL = r'https?://(?:www\.)?bili(?:bili\.tv|intl\.com)/(?:[a-z]{2}/)?(play/(?P<season_id>\d+)/(?P<ep_id>\d+)|video/(?P<aid>\d+))'
    _TESTS = [{
        # Bstation page
        'url': 'https://www.bilibili.tv/en/play/34613/341736',
        'info_dict': {
            'id': '341736',
            'ext': 'mp4',
            'title': 'E2 - The First Night',
            'thumbnail': r're:^https://pic\.bstarstatic\.com/ogv/.+\.png$',
            'episode_number': 2,
        }
    }, {
        # Non-Bstation page
        'url': 'https://www.bilibili.tv/en/play/1033760/11005006',
        'info_dict': {
            'id': '11005006',
            'ext': 'mp4',
            'title': 'E3 - Who?',
            'thumbnail': r're:^https://pic\.bstarstatic\.com/ogv/.+\.png$',
            'episode_number': 3,
        }
    }, {
        # Subtitle with empty content
        'url': 'https://www.bilibili.tv/en/play/1005144/10131790',
        'info_dict': {
            'id': '10131790',
            'ext': 'mp4',
            'title': 'E140 - Two Heartbeats: Kabuto\'s Trap',
            'thumbnail': r're:^https://pic\.bstarstatic\.com/ogv/.+\.png$',
            'episode_number': 140,
        },
        'skip': 'According to the copyright owner\'s request, you may only watch the video after you log in.'
    }, {
        'url': 'https://www.biliintl.com/en/play/34613/341736',
        'only_matching': True,
    }, {
        # User-generated content (as opposed to a series licensed from a studio)
        'url': 'https://bilibili.tv/en/video/2019955076',
        'only_matching': True,
    }, {
        # No language in URL
        'url': 'https://www.bilibili.tv/video/2019955076',
        'only_matching': True,
    }]

    def _real_extract(self, url):
        season_id, ep_id, aid = self._match_valid_url(url).group('season_id', 'ep_id', 'aid')
        video_id = ep_id or aid
        webpage = self._download_webpage(url, video_id)
        # Bstation layout
        initial_data = (
            self._search_json(r'window\.__INITIAL_(?:DATA|STATE)__\s*=', webpage, 'preload state', video_id, default={})
            or self._search_nuxt_data(webpage, video_id, '__initialState', fatal=False, traverse=None))
        video_data = traverse_obj(
            initial_data, ('OgvVideo', 'epDetail'), ('UgcVideo', 'videoData'), ('ugc', 'archive'), expected_type=dict)

        if season_id and not video_data:
            # Non-Bstation layout, read through episode list
            season_json = self._call_api(f'/web/v2/ogv/play/episodes?season_id={season_id}&platform=web', video_id)
            video_data = traverse_obj(season_json,
                                      ('sections', ..., 'episodes', lambda _, v: str(v['episode_id']) == ep_id),
                                      expected_type=dict, get_all=False)
        return self._extract_video_info(video_data or {}, ep_id=ep_id, aid=aid)


class BiliIntlSeriesIE(BiliIntlBaseIE):
    _VALID_URL = r'https?://(?:www\.)?bili(?:bili\.tv|intl\.com)/(?:[a-z]{2}/)?play/(?P<id>\d+)$'
    _TESTS = [{
        'url': 'https://www.bilibili.tv/en/play/34613',
        'playlist_mincount': 15,
        'info_dict': {
            'id': '34613',
            'title': 'Fly Me to the Moon',
            'description': 'md5:a861ee1c4dc0acfad85f557cc42ac627',
            'categories': ['Romance', 'Comedy', 'Slice of life'],
            'thumbnail': r're:^https://pic\.bstarstatic\.com/ogv/.+\.png$',
            'view_count': int,
        },
        'params': {
            'skip_download': True,
        },
    }, {
        'url': 'https://www.biliintl.com/en/play/34613',
        'only_matching': True,
    }]

    def _entries(self, series_id):
        series_json = self._call_api(f'/web/v2/ogv/play/episodes?season_id={series_id}&platform=web', series_id)
        for episode in traverse_obj(series_json, ('sections', ..., 'episodes', ...), expected_type=dict, default=[]):
            episode_id = str(episode.get('episode_id'))
            yield self._extract_video_info(episode, ep_id=episode_id)

    def _real_extract(self, url):
        series_id = self._match_id(url)
        series_info = self._call_api(f'/web/v2/ogv/play/season_info?season_id={series_id}&platform=web', series_id).get('season') or {}
        return self.playlist_result(
            self._entries(series_id), series_id, series_info.get('title'), series_info.get('description'),
            categories=traverse_obj(series_info, ('styles', ..., 'title'), expected_type=str_or_none),
            thumbnail=url_or_none(series_info.get('horizontal_cover')), view_count=parse_count(series_info.get('view')))


class BiliLiveIE(InfoExtractor):
    _VALID_URL = r'https?://live.bilibili.com/(?P<id>\d+)'

    _TESTS = [{
        'url': 'https://live.bilibili.com/196',
        'info_dict': {
            'id': '33989',
            'description': "周六杂谈回，其他时候随机游戏。 | \n录播：@下播型泛式录播组。 | \n直播通知群（全员禁言）：666906670，902092584，59971⑧481 （功能一样，别多加）",
            'ext': 'flv',
            'title': "太空狼人杀联动，不被爆杀就算赢",
            'thumbnail': "https://i0.hdslb.com/bfs/live/new_room_cover/e607bc1529057ef4b332e1026e62cf46984c314d.jpg",
            'timestamp': 1650802769,
        },
        'skip': 'not live'
    }, {
        'url': 'https://live.bilibili.com/196?broadcast_type=0&is_room_feed=1?spm_id_from=333.999.space_home.strengthen_live_card.click',
        'only_matching': True
    }]

    _FORMATS = {
        80: {'format_id': 'low', 'format_note': '流畅'},
        150: {'format_id': 'high_res', 'format_note': '高清'},
        250: {'format_id': 'ultra_high_res', 'format_note': '超清'},
        400: {'format_id': 'blue_ray', 'format_note': '蓝光'},
        10000: {'format_id': 'source', 'format_note': '原画'},
        20000: {'format_id': '4K', 'format_note': '4K'},
        30000: {'format_id': 'dolby', 'format_note': '杜比'},
    }

    _quality = staticmethod(qualities(list(_FORMATS)))

    def _call_api(self, path, room_id, query):
        api_result = self._download_json(f'https://api.live.bilibili.com/{path}', room_id, query=query)
        if api_result.get('code') != 0:
            raise ExtractorError(api_result.get('message') or 'Unable to download JSON metadata')
        return api_result.get('data') or {}

    def _parse_formats(self, qn, fmt):
        for codec in fmt.get('codec') or []:
            if codec.get('current_qn') != qn:
                continue
            for url_info in codec['url_info']:
                yield {
                    'url': f'{url_info["host"]}{codec["base_url"]}{url_info["extra"]}',
                    'ext': fmt.get('format_name'),
                    'vcodec': codec.get('codec_name'),
                    'quality': self._quality(qn),
                    **self._FORMATS[qn],
                }

    def _real_extract(self, url):
        room_id = self._match_id(url)
        room_data = self._call_api('room/v1/Room/get_info', room_id, {'id': room_id})
        if room_data.get('live_status') == 0:
            raise ExtractorError('Streamer is not live', expected=True)

        formats = []
        for qn in self._FORMATS.keys():
            stream_data = self._call_api('xlive/web-room/v2/index/getRoomPlayInfo', room_id, {
                'room_id': room_id,
                'qn': qn,
                'codec': '0,1',
                'format': '0,2',
                'mask': '0',
                'no_playurl': '0',
                'platform': 'web',
                'protocol': '0,1',
            })
            for fmt in traverse_obj(stream_data, ('playurl_info', 'playurl', 'stream', ..., 'format', ...)) or []:
                formats.extend(self._parse_formats(qn, fmt))
        self._sort_formats(formats)

        return {
            'id': room_id,
            'title': room_data.get('title'),
            'description': room_data.get('description'),
            'thumbnail': room_data.get('user_cover'),
            'timestamp': stream_data.get('live_time'),
            'formats': formats,
            'http_headers': {
                'Referer': url,
            },
        }
