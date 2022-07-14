import datetime
import os.path
import time
from pathlib import Path

from ..utils import PostProcessingError
from .fragment import FragmentFD
from ..postprocessor import FFmpegConcatPP, FFmpegPostProcessor


class YhdmpObfuscateM3U8FD(FragmentFD):
    FD_NAME = 'yhdmp_obfuscate_m3u8'

    def __init__(self, ydl, params):
        FragmentFD.__init__(self, ydl, params)

        self.verbose = params.get('verbose', False)
        self.chrome_wait_timeout = params.get('selenium_browner_timeout', 20)
        self.headless = params.get('selenium_browner_headless', True)

    @staticmethod
    def try_call(*funcs, expected_type=None, args=[], kwargs={}):
        for f in funcs:
            try:
                val = f(*args, **kwargs)
            except Exception:
                pass
            else:
                if expected_type is None or isinstance(val, expected_type):
                    return val

    def type1_download_frags(self, url, temp_output_fn_prefix):

        from ..selenium_container import SeleniumContainer
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.common.by import By

        self.to_screen(f'start chrome to query video page...')
        with SeleniumContainer(
            headless=self.headless,
            close_log_callback=lambda: self.to_screen('Quit chrome and cleanup temp profile...')
        ) as engine:
            engine.start()

            engine.load(url)

            iframe_e = engine.wait(self.chrome_wait_timeout).until(
                EC.presence_of_element_located((By.ID, 'yh_playfram'))
            )

            engine.driver.switch_to.frame(iframe_e)

            engine.wait(self.chrome_wait_timeout).until(
                EC.presence_of_element_located((By.TAG_NAME, 'video'))
            )

            self.to_screen('[yhdmp] start play video at x16 speed ...')
            engine.execute_script("document.getElementsByTagName('video')[0].volume = 0")
            engine.execute_script("document.getElementsByTagName('video')[0].muted = true")
            engine.execute_script("document.getElementsByTagName('video')[0].playbackRate=16")
            engine.execute_script("document.getElementsByTagName('video')[0].play()")

            self.add_progress_hook(self.report_progress)

            m3u8_text = None
            m3u8_frag_urls = None
            frag_file_dict = {}

            progress_bytes_counter = 0
            progress_start_dt = datetime.datetime.now()
            progress_last_dt = datetime.datetime.now()
            last_tick_bytes_counter = 0
            progress_report_finished = False
            while True:
                stopped = engine.execute_script("return document.getElementsByTagName('video')[0].ended")

                try:
                    engine.extract_network()

                    for request_url in engine.response_updated_key_list:
                        resp_map = engine.response_dict[request_url]
                        resp = engine.get_response_frag_data(resp_map)

                        if not m3u8_text and resp['body_text'] and resp['body'].startswith('#EXTM3U'):
                            m3u8_text = resp['body']
                            if self.verbose:
                                self.to_screen('[yhdmp] load m3u8')

                            m3u8_frag_urls = [l for l in m3u8_text.split('\n') if l.startswith('http')]

                        if not m3u8_frag_urls:
                            continue

                        frag_idx = YhdmpObfuscateM3U8FD.try_call(lambda: m3u8_frag_urls.index(request_url))

                        if frag_idx is None:
                            continue

                        fn = f'{temp_output_fn_prefix}.Frag{frag_idx:04d}.ts'
                        if not resp['end']:
                            print(f'{fn} is not finished, skip')
                            continue

                        resp_body = resp['body']
                        # skip fake png header
                        resp_body = resp_body[126:]

                        if fn in frag_file_dict and frag_file_dict[fn] != len(resp_body):
                            print(f'Found {fn} twice, size {frag_file_dict[fn]} != {len(resp_body)}')

                        frag_file_dict[fn] = len(resp_body)

                        with open(fn, 'wb') as f:
                            f.write(resp_body)
                        progress_bytes_counter += len(resp_body)

                    if m3u8_frag_urls:
                        engine.response_updated_key_list.clear()
                except Exception:
                    if m3u8_frag_urls is not None:
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
                        'status': 'downloading',
                        'filename': temp_output_fn_prefix,
                        'fragment_index': len(frag_file_dict),
                        'fragment_count': len(m3u8_frag_urls),
                        'elapsed': elapsed,
                        'downloaded_bytes': progress_bytes_counter,
                        'speed': (progress_bytes_counter - last_tick_bytes_counter) / (datetime.datetime.now() - progress_last_dt).total_seconds(),
                    }
                    if self.params.get('test', False) and len(frag_file_dict) >= 2:
                        progress_info['status'] = 'finished'
                        break
                    elif len(frag_file_dict) == len(m3u8_frag_urls):
                        progress_info['status'] = 'finished'
                        progress_report_finished = True
                    elif len(frag_file_dict) >= 10:
                        total_bytes_estimate = progress_bytes_counter * 1.0 / len(frag_file_dict) * len(m3u8_frag_urls)
                        progress_info.update({
                            'total_bytes_estimate': total_bytes_estimate,
                            'eta': elapsed * (1.0 / progress_bytes_counter * total_bytes_estimate - 1.0)
                        })
                    self._hook_progress(progress_info, {})
                last_tick_bytes_counter = progress_bytes_counter
                progress_last_dt = datetime.datetime.now()

                if stopped:
                    break

                time.sleep(1)

            # end line for progress
            print()

            result_list = list(frag_file_dict.keys())
            result_list.sort(key=lambda s: s)

            return result_list

    def real_download(self, filename, info_dict):
        requested_formats = [{**info_dict, **fmt} for fmt in info_dict.get('requested_formats', [])]
        target_formats = requested_formats or [info_dict]

        ffmpeg_tester = FFmpegPostProcessor()

        for fmt in target_formats:
            url = fmt['url']

            fmt_output_filename = filename
            temp_output_fn = fmt_output_filename[:-len(Path(fmt_output_filename).suffix)]

            frag_file_list = self.type1_download_frags(url, temp_output_fn)

            if self.params.get('test', False):
                self._hook_progress({
                    'filename': filename,
                    'status': 'finished'
                }, {})

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
