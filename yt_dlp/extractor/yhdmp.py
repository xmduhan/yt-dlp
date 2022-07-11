import json
import re
import time

from .common import InfoExtractor
from ..utils import ExtractorError, int_or_none, float_or_none


class YhdmpIE(InfoExtractor):
    _VALID_URL = r'(?x)https?://(?:www\.yhdmp\.cc/vp/)(?P<id>\d+-\d+-\d+)\.html'

    _TESTS = [{
        #  yhdmp_obfuscate_m3u8
        'url': 'https://www.yhdmp.cc/vp/22216-2-0.html',
        'info_dict': {
            'id': '22216-2-0',
            'ext': 'mp4',
            'title': '异世界舅舅 第1集',
        },
        'params': {
            'skip_download': True,
        },
    }, {
        'url': 'https://www.yhdmp.cc/vp/22096-1-9.html',
        'info_dict': {
            'id': '22096-1-9',
            'ext': 'mp4',
        },
    }]

    def _real_extract(self, url):
        video_id = self._match_id(url)

        # yhdmp obfuscate video info, use headless browner to run it

        chrome_wait_timeout = self.get_param('selenium_browner_timeout', 20)
        headless = self.get_param('selenium_browner_headless', True)

        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.common.desired_capabilities import DesiredCapabilities

        chrome_options = Options()
        chrome_options.add_argument('--log-level=3')

        if headless:
            chrome_options.add_argument('--headless')

        prefs = {"profile.managed_default_content_settings": {'images': 2}}
        chrome_options.add_experimental_option("prefs", prefs)

        caps = DesiredCapabilities.CHROME
        caps['goog:loggingPrefs'] = {'performance': 'ALL'}

        self.to_screen(f'start chrome to query video page (timeout {chrome_wait_timeout}s) ...')
        driver = webdriver.Chrome(options=chrome_options, desired_capabilities=caps)
        try:
            driver.get(url)

            iframe_e = WebDriverWait(driver, chrome_wait_timeout).until(
                EC.presence_of_element_located((By.ID, 'yh_playfram'))
            )

            title = driver.find_element(By.TAG_NAME, 'title').get_attribute('innerText')
            title_mobj = re.match(r'(?P<t>.*?)\—在线播放\—樱花动漫\(P\)', title)
            if title_mobj.group('t'):
                title = title_mobj.group('t')

            driver.switch_to.frame(iframe_e)
            video_e = WebDriverWait(driver, chrome_wait_timeout).until(
                EC.presence_of_element_located((By.TAG_NAME, 'video'))
            )

            info_dict = {
                    'id': video_id,
                    'title': title,
                    '_type': 'video',
                }

            video_url = video_e.get_attribute('src')

            self.to_screen('play video to detect video metadata ...')
            driver.execute_script("document.getElementsByTagName('video')[0].volume = 0")
            driver.execute_script("document.getElementsByTagName('video')[0].muted = true")
            driver.execute_script("document.getElementsByTagName('video')[0].playbackRate=16")
            driver.execute_script("document.getElementsByTagName('video')[0].play()")

            videoHeight, videoWidth = None, None
            for _ in range(chrome_wait_timeout):
                videoHeight = driver.execute_script("return document.getElementsByTagName('video')[0].videoHeight")
                videoWidth = driver.execute_script("return document.getElementsByTagName('video')[0].videoWidth")

                if videoHeight == 0:
                    videoHeight, videoWidth = None, None
                    time.sleep(1)
                else:
                    break

            self.to_screen('Check chrome media-internals info ...')
            driver.switch_to.new_window()
            driver.get('chrome://media-internals/')
            time.sleep(1)
            driver.execute_script("document.getElementsByClassName('player-name')[0].click()")
            video_info_e = driver.find_element(By.XPATH, '//table[@id="player-property-table"]//td[text()="kVideoTracks"]/following-sibling::td')
            audio_info_e = driver.find_element(By.XPATH, '//table[@id="player-property-table"]//td[text()="kAudioTracks"]/following-sibling::td')

            video_info_dict = json.loads(video_info_e.get_attribute('innerText'))[0]
            audio_info_dict = json.loads(audio_info_e.get_attribute('innerText'))[0]

            vcodec = video_info_dict['codec']
            acodec = audio_info_dict['codec']
            video_size = video_info_dict['coded size']
            videoWidth, videoHeight = video_size.split('x')
            asr = audio_info_dict['samples per second']

            fmt_info = {
                'width': int_or_none(videoWidth),
                'height': int_or_none(videoHeight),
                'vcodec': vcodec,
                'acodec': acodec,
                'asr': asr
            }

            if '.mp4?' in video_url:
                return {
                    **info_dict,
                    'formats': [{'url': video_url, **fmt_info}],
                }
            if '?dpvt=' in video_url:
                return {
                    **info_dict,
                    'formats': [{'url': video_url, 'ext': 'mp4', **fmt_info}],
                }
            if video_url.startswith('blob:https://www.yhdmp.cc/'):
                return {
                    **info_dict,
                    'formats': [{'url': url,
                                 'protocol': 'yhdmp_obfuscate_m3u8',
                                 'ext': 'mp4', **fmt_info}],
                }
        finally:
            self.to_screen('Quit chrome and cleanup temp profile...')
            driver.quit()

        raise ExtractorError(f'unknown format {url}')
