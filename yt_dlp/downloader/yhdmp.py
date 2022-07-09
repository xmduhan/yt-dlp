import collections
import json
import os.path
import time
from pathlib import Path
import base64
import logging

from . import get_suitable_downloader
from ..utils import traverse_obj
from .fragment import FragmentFD
from ..postprocessor import FFmpegConcatPP, FFmpegPostProcessor


class YhdmpFD(FragmentFD):
    FD_NAME = 'yhdmp'

    def __init__(self, ydl, params):
        FragmentFD.__init__(self, ydl, params)

        self.verbose = params.get('verbose', False)
        self.chrome_wait_timeout = params.get('selenium_browner_timeout', 10)
        self.headless = params.get('selenium_browner_headless', True)

    def type1_download_frags(self, url, temp_output_fn_prefix):
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.common.desired_capabilities import DesiredCapabilities

        from selenium.webdriver.remote.remote_connection import LOGGER
        LOGGER.setLevel(logging.WARNING)

        chrome_options = Options()

        if self.headless:
            chrome_options.add_argument('--headless')

        prefs = {"profile.managed_default_content_settings": {'images': 2}}
        chrome_options.add_experimental_option("prefs", prefs)

        caps = DesiredCapabilities.CHROME
        caps['goog:loggingPrefs'] = {'performance': 'ALL'}

        self.to_screen(f'[yhdmp] start chrome to query video page (timeout {self.chrome_wait_timeout}s) ...')
        driver = webdriver.Chrome(options=chrome_options, desired_capabilities=caps)

        try:
            driver.execute_cdp_cmd('Network.enable', {
                'maxResourceBufferSize': 1024 * 1024 * 1024,
                'maxTotalBufferSize': 1024 * 1024 * 1024,
            })

            driver.get(url)

            iframe_e = WebDriverWait(driver, self.chrome_wait_timeout).until(
                EC.presence_of_element_located((By.ID, 'yh_playfram'))
            )

            driver.switch_to.frame(iframe_e)

            WebDriverWait(driver, self.chrome_wait_timeout).until(
                EC.presence_of_element_located((By.TAG_NAME, 'video'))
            )

            buttons = [b for b in driver.find_elements(By.TAG_NAME, 'button')]
            play_button = [b for b in buttons
                           if b.get_attribute('class') == 'dplayer-icon dplayer-play-icon'
                           ][0]

            volume_button = [b for b in buttons
                             if b.get_attribute('class') == 'dplayer-icon dplayer-volume-icon'
                             ][0]

            self.to_screen('[yhdmp] start play video at x16 speed ...')
            play_button.click()
            volume_button.click()  # set volume=0

            driver.execute_script("document.getElementsByTagName('video')[0].playbackRate=16")

            response_dict = dict()
            m3u8_text = None
            m3u8_frag_urls = None
            m3u8_frag_file_list = []
            while True:
                stopped = driver.execute_script("return document.getElementsByTagName('video')[0].ended")
                if stopped:
                    break

                browser_log = driver.get_log('performance')

                request_id_data = collections.defaultdict(list)

                events = [json.loads(entry['message'])['message'] for entry in browser_log]
                events = [e for e in events
                          if e['method'].startswith('Network.requestWillBeSent')
                          or e['method'].startswith('Network.responseReceived')
                          ]

                for e in events:
                    request_url = traverse_obj(e, ('params', 'request', 'url'))
                    if request_url is not None:
                        e['request_url'] = request_url
                    request_id_data[e['params']['requestId']].append(e)

                for requestId, request_list in request_id_data.items():
                    request_list.sort(key=lambda d: d['method'])
                    request_url = traverse_obj(request_list, (0, 'request_url'))
                    if request_url is None:
                        request_url = f"requestId:{requestId}"
                    if request_url.startswith('chrome'):
                        continue

                    try:
                        resp = driver.execute_cdp_cmd('Network.getResponseBody', {'requestId': requestId})

                        if resp['base64Encoded']:
                            resp_body = base64.b64decode(resp['body'])
                            try:
                                resp_body = resp_body.decode('utf8')
                                resp_body_text = True
                            except Exception:
                                resp_body_text = False
                        else:
                            resp_body = resp['body']
                            resp_body_text = True

                        if request_url not in response_dict:
                            response_dict[request_url] = resp_body
                            if self.verbose:
                                self.to_screen(f'[yhdmp] Record {request_url}, size: {len(resp_body)}, text:{resp_body_text}')

                            if not m3u8_text and resp_body_text and resp_body.startswith('#EXTM3U'):
                                m3u8_text = resp_body
                                # self.to_screen('[yhdmp] load m3u8')

                                m3u8_frag_urls = [l for l in m3u8_text.split('\n') if l.startswith('http')]
                                if self.verbose:
                                    self.to_screen(f'[yhdmp] has {len(m3u8_frag_urls)} fragments')

                            if m3u8_frag_urls:
                                try:
                                    frag_idx = m3u8_frag_urls.index(request_url)
                                    # skip fake png header
                                    resp_body = resp_body[126:]
                                except ValueError:
                                    frag_idx = -1
                                if frag_idx != -1:
                                    fn = f'{temp_output_fn_prefix}.Frag{frag_idx:04d}.ts'
                                    m3u8_frag_file_list.append(fn)
                                    with open(fn, 'wb') as f:
                                        f.write(resp_body)

                                    self.to_screen(f'[yhdmp] {fn} dumped, {frag_idx+1} / {len(m3u8_frag_urls)} done.')

                    except Exception as e:
                        if 'No data found for resource with given identifier' in str(e):
                            if '.m3u8' not in request_url:
                                # m3u8 is always failed
                                if self.verbose:
                                    print(f'[yhdmp] {request_url}, No data found for resource with given identifier')
                        elif 'No resource with given identifier found' in str(e):
                            if self.verbose:
                                print(f'[yhdmp] {request_url}, No resource with given identifier found')
                        else:
                            raise

                time.sleep(1)

            m3u8_frag_file_list.sort(key=lambda s: s)
            return m3u8_frag_file_list
        finally:
            self.to_screen('[yhdmp] Quit chrome and cleanup temp profile...')
            driver.quit()

    def type2_get_video_url(self, url):
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.common.desired_capabilities import DesiredCapabilities

        from selenium.webdriver.remote.remote_connection import LOGGER
        LOGGER.setLevel(logging.WARNING)

        chrome_options = Options()

        if self.headless:
            chrome_options.add_argument('--headless')

        prefs = {"profile.managed_default_content_settings": {'images': 2}}
        chrome_options.add_experimental_option("prefs", prefs)

        caps = DesiredCapabilities.CHROME
        caps['goog:loggingPrefs'] = {'performance': 'ALL'}

        self.to_screen(f'[yhdmp] start chrome to query video page (timeout {self.chrome_wait_timeout}s) ...')
        driver = webdriver.Chrome(options=chrome_options, desired_capabilities=caps)

        try:
            driver.get(url)

            iframe_e = WebDriverWait(driver, self.chrome_wait_timeout).until(
                EC.presence_of_element_located((By.ID, 'yh_playfram'))
            )

            driver.switch_to.frame(iframe_e)

            video_e = WebDriverWait(driver, self.chrome_wait_timeout).until(
                EC.presence_of_element_located((By.TAG_NAME, 'video'))
            )

            video_url = video_e.get_attribute('src')
            if self.verbose:
                self.to_screen(f'[yhdmp] get video_url {video_url}')

            return video_url

        finally:
            self.to_screen('[yhdmp] Quit chrome and cleanup temp profile...')
            driver.quit()

    def real_download(self, filename, info_dict):
        requested_formats = [{**info_dict, **fmt} for fmt in info_dict.get('requested_formats', [])]
        target_formats = requested_formats or [info_dict]

        ffmpeg_tester = FFmpegPostProcessor()

        for fmt in target_formats:
            url = fmt['url']

            if url.endswith('-1-0.html'):
                if self.verbose:
                    self.to_screen('[yhdmp] Type 1 Video')

                fmt_output_filename = filename
                temp_output_fn = fmt_output_filename[:-len(Path(fmt_output_filename).suffix)]

                frag_file_list = self.type1_download_frags(url, temp_output_fn)

                assert ffmpeg_tester.available and ffmpeg_tester.probe_available

                concat_pp = FFmpegConcatPP(self.ydl)
                concat_pp.concat_files(frag_file_list, fmt_output_filename)
                if os.path.exists(fmt_output_filename):
                    for fn in frag_file_list:
                        os.remove(fn)
            elif url.endswith('-2-0.html'):
                if self.verbose:
                    self.to_screen('[yhdmp] Type 2 Video')

                video_url = self.type2_get_video_url(url)

                dl = get_suitable_downloader({'url': video_url}, self.params, to_stdout=(filename == '-'))
                dl = dl(self.ydl, self.params)
                info = {
                    'http_headers': fmt.get('http_headers'),
                    'url': video_url
                }
                dl.download(filename, info)
            else:
                self.to_screen(f'{url} is not supported')
                return False

        return True
