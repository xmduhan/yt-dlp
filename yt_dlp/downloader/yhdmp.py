import collections
import datetime
import json
import os.path
import time
from pathlib import Path
import base64

from ..utils import traverse_obj, PostProcessingError
from .fragment import FragmentFD
from ..postprocessor import FFmpegConcatPP, FFmpegPostProcessor


class YhdmpObfuscateM3U8FD(FragmentFD):
    FD_NAME = 'yhdmp'

    def __init__(self, ydl, params):
        FragmentFD.__init__(self, ydl, params)

        self.verbose = params.get('verbose', False)
        self.chrome_wait_timeout = params.get('selenium_browner_timeout', 20)
        self.headless = params.get('selenium_browner_headless', True)

    def type1_download_frags(self, url, temp_output_fn_prefix):
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.common.desired_capabilities import DesiredCapabilities

        chrome_options = Options()
        chrome_options.add_argument('--log-level=3')

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

            self.add_progress_hook(self.report_progress)

            response_dict = dict()
            m3u8_text = None
            m3u8_frag_urls = None
            m3u8_frag_file_list = []

            progress_bytes_counter = 0
            progress_start_dt = datetime.datetime.now()
            last_tick_bytes_counter = 0
            progress_report_finished = False
            while True:
                stopped = driver.execute_script("return document.getElementsByTagName('video')[0].ended")

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

                            if not m3u8_text and resp_body_text and resp_body.startswith('#EXTM3U'):
                                m3u8_text = resp_body
                                if self.verbose:
                                    self.to_screen('[yhdmp] load m3u8')

                                m3u8_frag_urls = [l for l in m3u8_text.split('\n') if l.startswith('http')]

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

                                    progress_bytes_counter += len(resp_body)
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
                            self.report_progress({
                                        'info_dict': {},
                                        'status': 'error',
                                        'filename': temp_output_fn_prefix,
                                        'downloaded_bytes': progress_bytes_counter,
                                        'elapsed': (datetime.datetime.now() - progress_start_dt).seconds,
                                        'fragment_count': len(m3u8_frag_urls)
                                    })
                            raise

                if not progress_report_finished and m3u8_frag_urls is not None:
                    elapsed = (datetime.datetime.now() - progress_start_dt).seconds
                    progress_info = {
                        'info_dict': {},
                        'status': 'downloading',
                        'filename': temp_output_fn_prefix,
                        'fragment_index': len(m3u8_frag_file_list),
                        'fragment_count': len(m3u8_frag_urls),
                        'elapsed': elapsed,
                        'downloaded_bytes': progress_bytes_counter,
                        'speed': (progress_bytes_counter - last_tick_bytes_counter) / 1.0,
                    }
                    if len(m3u8_frag_file_list) == len(m3u8_frag_urls):
                        progress_info['status'] = 'finished'
                        progress_report_finished = True
                    elif len(m3u8_frag_file_list) >= 10:
                        total_bytes_estimate = progress_bytes_counter * 1.0 / len(m3u8_frag_file_list) * len(m3u8_frag_urls)
                        progress_info.update({
                            'total_bytes_estimate': total_bytes_estimate,
                            'eta': elapsed * (1.0 / progress_bytes_counter * total_bytes_estimate - 1.0)
                        })
                    self.report_progress(progress_info)
                last_tick_bytes_counter = progress_bytes_counter

                if stopped:
                    break

                time.sleep(1)

            # end line for progress
            print()

            m3u8_frag_file_list.sort(key=lambda s: s)
            return m3u8_frag_file_list
        finally:
            self.to_screen('[yhdmp] Quit chrome and cleanup temp profile...')
            driver.quit()

    def real_download(self, filename, info_dict):
        requested_formats = [{**info_dict, **fmt} for fmt in info_dict.get('requested_formats', [])]
        target_formats = requested_formats or [info_dict]

        ffmpeg_tester = FFmpegPostProcessor()

        for fmt in target_formats:
            url = fmt['url']

            if self.verbose:
                self.to_screen('[yhdmp] format: yhdmp_obfuscate_m3u8')

            fmt_output_filename = filename
            temp_output_fn = fmt_output_filename[:-len(Path(fmt_output_filename).suffix)]

            frag_file_list = self.type1_download_frags(url, temp_output_fn)

            if not (ffmpeg_tester.available and ffmpeg_tester.probe_available):
                raise PostProcessingError('ffmpeg or ffprobe is missing, cannot merge frags.')

            self.to_screen(f'[yhdmp] Concatenating {len(frag_file_list)} files ...')
            origin_verbose = self.params['verbose']
            self.params['verbose'] = False
            concat_pp = FFmpegConcatPP(self.ydl)
            concat_pp.concat_files(frag_file_list, fmt_output_filename)
            self.params['verbose'] = origin_verbose

            if os.path.exists(fmt_output_filename):
                for fn in frag_file_list:
                    os.remove(fn)

        return True
