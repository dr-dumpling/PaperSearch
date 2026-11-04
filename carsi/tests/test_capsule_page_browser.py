"""Real DOM events and animated sizes with an isolated page/bridge fixture."""
import json
import os
import unittest
from paper_search_carsi.progress_capsule import PAGE


@unittest.skipUnless(os.environ.get('CARSI_BROWSER_TESTS') == '1', 'opt-in native Chrome test')
class CapsulePageTests(unittest.TestCase):
    def test_hover_without_click_animated_resize_and_directory_input(self):
        from playwright.sync_api import sync_playwright
        from paper_search_carsi.progress_view import view
        import time
        state = view(dict(status='running', current='10.1000/example', title='Test article', publisher='Test', total=3,
                          done=0, success=0, failed=0, stage='fetching_pdf', started_at=time.time()), time.time())
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            page = browser.new_page(viewport={'width':800,'height':800})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.set_content(PAGE.read_text())
            page.evaluate('''state => {
              window.sizes=[]; window.saved=null;
              window.pywebview={api:{platform:async()=> 'darwin', state:async()=>state,
                resize:async(w,h)=>sizes.push([w,h]),
                settings:async()=>({fields:[],notify:true,download_dir:'/original'}),
                choose_download_directory:async()=>'/chosen folder',
                save_settings:async(v,n,d)=>{saved=d;return {ok:true}}}};
              window.dispatchEvent(new Event('pywebviewready'));
            }''', state)
            page.wait_for_function('lastCls === "pill" && sizes.length > 5')
            page.wait_for_timeout(400)
            page.evaluate('sizes=[]')
            page.mouse.move(50,25)  # no click/focus call
            page.wait_for_function('open === true')
            page.wait_for_timeout(400)
            heights = page.evaluate('sizes.map(x=>x[1])')
            self.assertGreater(len(set(heights)), 4)
            self.assertEqual(heights, sorted(heights))
            page.evaluate("open=false;render(true);root.dispatchEvent(new MouseEvent('mouseenter'))")
            page.wait_for_function('open === true')
            page.mouse.move(700,700)
            page.wait_for_function('open === false')
            page.wait_for_timeout(400)
            page.mouse.move(50,25)
            page.wait_for_function('open === true')
            page.locator('[data-act=settings]').click()
            page.locator('[data-act=choose_folder]').click()
            self.assertEqual(page.locator('#download-dir').input_value(), '/chosen folder')
            page.locator('#download-dir').fill('/typed folder')
            page.locator('[data-act=save]').click()
            page.wait_for_function('saved === "/typed folder"')
            self.assertEqual(errors, [])
