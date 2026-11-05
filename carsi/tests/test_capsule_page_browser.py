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

    def test_holding_the_pill_freezes_hover_and_refresh_until_release(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = self.drag_page(p)
            page.wait_for_timeout(400)
            page.mouse.move(50, 25)
            page.mouse.down()
            before = page.locator("#root").inner_html()
            count = page.evaluate("sizes.length")
            page.evaluate("testState.title='Updated while held'; testState.done=1")
            page.wait_for_timeout(700)
            self.assertFalse(page.evaluate("open"))
            self.assertEqual(page.locator("#root").inner_html(), before)
            self.assertEqual(page.evaluate("sizes.length"), count)
            page.mouse.up()
            page.wait_for_function("open && root.innerText.includes('Updated while held')")
            self.assertEqual(page.evaluate("dragLocks"), [True, False])
            browser.close()

    def test_card_background_drags_but_buttons_and_settings_inputs_do_not(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            for platform in ("darwin", "win32"):
                with self.subTest(platform=platform):
                    browser, page = self.drag_page(p, platform)
                    page.mouse.move(50, 25)
                    page.wait_for_function("open")
                    page.wait_for_timeout(400)
                    target = page.locator(".stats b").first
                    point = target.bounding_box()
                    x, y = point['x'] + 5, point['y'] + 5
                    page.mouse.move(x, y)
                    page.mouse.down()
                    page.evaluate("window.heldStats = document.querySelector('.stats')")
                    count = page.evaluate("sizes.length")
                    page.mouse.move(x + 35, y + 20, steps=4)
                    page.evaluate("testState.title='Refreshed article'; tick()")
                    page.wait_for_timeout(550)
                    self.assertGreater(page.evaluate("nativeMoves.length"), 0)
                    self.assertTrue(page.evaluate("heldStats.isConnected"))
                    self.assertEqual(page.evaluate("sizes.length"), count)
                    page.mouse.up()
                    page.wait_for_function("root.innerText.includes('Refreshed article')")
                    page.evaluate("nativeMoves=[]; dragLocks=[]")
                    page.locator('[data-act=settings]').click()
                    page.locator('#download-dir').fill('/edited while focused')
                    page.mouse.move(80, 60)
                    self.assertEqual(page.evaluate("nativeMoves"), [])
                    self.assertEqual(page.evaluate("dragLocks"), [])
                    browser.close()

    @staticmethod
    def drag_page(playwright, platform='darwin'):
        from pathlib import Path
        import time
        import webview
        from paper_search_carsi.progress_view import view
        state = view(dict(status='running', current='10.1000/drag', title='Drag test article', publisher='Test',
                          total=3, done=0, success=0, failed=0, stage='fetching_pdf', started_at=time.time()), time.time())
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': 800, 'height': 800})
        page.set_content(PAGE.read_text())
        page.evaluate("""({state, platform}) => {
          window.testState=state; window.sizes=[]; window.dragLocks=[]; window.nativeMoves=[];
          window.pywebview={platform:platform==='darwin'?'cocoa':'edgechromium', api:{
            platform:async()=>platform, state:async()=>testState, resize:async(w,h)=>sizes.push([w,h]),
            set_dragging:async(active)=>dragLocks.push(active),
            move_drag:async(x,y)=>nativeMoves.push([x,y]),
            settings:async()=>({fields:[], notify:true, download_dir:'/original'})},
            _jsApiCallback:(name,args)=>{if(name==='pywebviewMoveWindow')nativeMoves.push(args)}};
        }""", {'state': state, 'platform': platform})
        # Use pywebview's actual drag listener, including its default ancestor hit testing.
        customize = Path(webview.__file__).parent / 'js/customize.js'
        page.evaluate(customize.read_text() % {
            'text_select':'False', 'drag_region_direct_target_only':'False',
            'drag_selector':'.pywebview-drag-region', 'easy_drag':'False',
            'zoomable':'False', 'draggable':'False'})
        page.evaluate("window.dispatchEvent(new Event('pywebviewready'))")
        page.wait_for_function("lastCls==='pill'")
        return browser, page
