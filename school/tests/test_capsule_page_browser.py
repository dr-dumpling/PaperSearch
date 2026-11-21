"""Real DOM events and animated sizes with an isolated page/bridge fixture."""
import json
import os
import time
import unittest
from paper_search_school.progress_capsule import PAGE


def page_world(page):
    """The fixture reads the capsule page's own globals. Patchright evaluates in
    an isolated world by default and has no main-world wait_for_function, so
    both go to the page's world here (a test harness, not the download browser)."""
    evaluate = page.evaluate

    def evaluate_in_page(expression, arg=None, **options):
        return evaluate(expression, arg, **{"isolated_context": False, **options})

    def wait_for_function(expression, *, arg=None, timeout=30_000, polling=None):
        check = ("(arg) => { const value = (" + expression + ");"
                 " return !!(typeof value === 'function' ? value(arg) : value); }")
        deadline = time.monotonic() + timeout / 1000
        while not evaluate_in_page(check, arg):
            if time.monotonic() > deadline:
                raise AssertionError(f"wait_for_function timed out: {expression}")
            page.wait_for_timeout(polling if isinstance(polling, (int, float)) else 50)

    page.evaluate = evaluate_in_page
    page.wait_for_function = wait_for_function
    return page


@unittest.skipUnless(os.environ.get('SCHOOL_BROWSER_TESTS') == '1', 'opt-in native Chrome test')
class CapsulePageTests(unittest.TestCase):
    def test_verification_click_survives_countdown_refresh(self):
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            for expanded in (False, True):
                with self.subTest(expanded=expanded):
                    browser, page = self.drag_page(p, 'win32')
                    try:
                        page.evaluate("""async expanded => {
                            testState.mode='attention';
                            testState.attention={message:'请完成验证', short:'请完成验证', login:false,
                                remaining:'0:29', more:0};
                            open=expanded; await tick();
                        }""", expanded)
                        button = page.get_by_role('button', name='打开下载浏览器')
                        page.wait_for_function("!root.classList.contains('animating')")
                        page.evaluate("window.pressedButton = root.querySelector('[data-act=show_browser]')")
                        box = button.bounding_box()
                        page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                        page.mouse.down()
                        page.evaluate("async () => { testState.attention.remaining='0:28'; await tick(); }")
                        page.wait_for_timeout(150)  # also cross the pill's hover-to-expand timer
                        self.assertTrue(page.evaluate("pressedButton.isConnected"))
                        self.assertIn('0:28', button.get_attribute('title') if expanded else button.inner_text())
                        page.mouse.up()
                        page.wait_for_function('requestedActions.length === 1', timeout=2500)
                        self.assertEqual(page.evaluate('requestedActions[0][0]'), 'show_browser')
                    finally:
                        browser.close()

    def test_browser_request_waits_for_click_activation(self):
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = self.drag_page(p, 'win32')
            try:
                page.evaluate("""() => {
                    testState.mode='attention';
                    testState.attention={message:'请登录学校', short:'请登录学校', login:true, more:0};
                    pywebview.api.activate_on_input=()=>new Promise(resolve=>{finishActivation=resolve});
                    tick();
                }""")
                page.wait_for_selector('[data-act=show_browser]')
                page.locator('[data-act=show_browser]').click()
                page.wait_for_function("typeof finishActivation === 'function'")
                page.wait_for_timeout(100)
                self.assertEqual(page.evaluate('requestedActions'), [])
                page.evaluate('finishActivation()')
                page.wait_for_function('requestedActions.length === 1')
                self.assertEqual(page.evaluate('requestedActions[0][0]'), 'show_browser')
            finally:
                browser.close()

    def test_the_downloading_paper_shows_its_browser(self):
        """The paper on the expanded card is a link to its browser (user request,
        2026-11-08); not while the open-access stretch has no browser."""
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = self.drag_page(p, 'darwin')
            try:
                page.evaluate("() => { open=true; tick(); }")
                page.wait_for_selector('.paper-link')
                page.locator('.paper-link').click()
                page.wait_for_function('requestedActions.length === 1')
                self.assertEqual(page.evaluate('requestedActions[0]'), ['show_browser', '10.1000/drag', ''])
                page.evaluate("async () => { testState.browser=false; await tick(); }")
                page.wait_for_selector('.paper .name')
                self.assertEqual(page.locator('.paper-link').count(), 0)
            finally:
                browser.close()

    def test_expanded_attention_fits_and_keeps_browser_action(self):
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            for platform in ('darwin', 'win32'):
                browser, page = self.drag_page(p, platform)
                try:
                    page.evaluate("""() => {
                        testState.mode='attention';
                        testState.attention={message:'页面持续没有进展，请查看浏览器，可能需要手动操作',
                            short:'页面暂时无进展', login:false, remaining:'2:41', more:0};
                        open=true; tick();
                    }""")
                    page.wait_for_selector('.attention-copy')
                    page.wait_for_timeout(400)
                    self.assertEqual(page.locator('.prompt .t').inner_text(), '页面暂时无进展')
                    for selector in ('.prompt .t', '.prompt .s'):
                        self.assertTrue(page.locator(selector).evaluate('el => el.scrollWidth <= el.clientWidth'))
                        self.assertEqual(page.locator(selector).evaluate('el => getComputedStyle(el).whiteSpace'), 'nowrap')
                    self.assertNotIn('等待你处理', page.locator('#root').inner_text())
                    self.assertNotIn('当前第', page.locator('#root').inner_text())
                    page.locator('[data-act=show_browser]').click()
                    page.wait_for_function('requestedActions.length === 1')
                    self.assertEqual(page.evaluate('requestedActions[0][0]'), 'show_browser')
                    self.assertEqual(page.evaluate('dragLocks'), [])
                finally:
                    browser.close()

    def test_login_reminder_keeps_an_icon_drag_handle(self):
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            for platform in ('darwin', 'win32'):
                with self.subTest(platform=platform):
                    browser, page = self.drag_page(p, platform)
                    page.evaluate("""() => {
                        testState.mode='attention';
                        testState.attention={message:'请登录学校', short:'请登录学校', login:true, more:0};
                        tick();
                    }""")
                    page.wait_for_function("V.mode === 'attention'")
                    page.wait_for_timeout(400)  # the pill's animated resize must settle before grabbing it
                    handle = page.locator('.pillrow > svg')
                    point = handle.bounding_box()
                    x, y = point['x'] + point['width']/2, point['y'] + point['height']/2
                    page.mouse.move(x, y)
                    page.mouse.down()
                    page.mouse.move(x + 30, y + 15, steps=3)
                    page.mouse.up()
                    self.assertTrue(page.evaluate('nativeMoves.length > 0'))
                    self.assertEqual(page.evaluate('requestedActions'), [])
                    browser.close()

    def test_attention_breathes_across_countdown_updates_and_respects_reduced_motion(self):
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            for platform in ("darwin", "win32"):
                with self.subTest(platform=platform):
                    browser, page = self.drag_page(p, platform)
                    page.evaluate("""() => {
                        testState.mode='attention';
                        testState.attention={message:'请在浏览器里登录学校', short:'请登录学校',
                            login:true, remaining:'2:41', more:0};
                        tick();
                    }""")
                    page.wait_for_selector('#root.warn')
                    page.wait_for_function("root.getAnimations({subtree:true}).some(a => a.animationName === 'breathe' && a.currentTime > 600)")
                    before = page.evaluate("root.getAnimations({subtree:true}).find(a => a.animationName === 'breathe').currentTime")
                    page.evaluate("testState.attention.remaining='2:40'; tick()")
                    page.wait_for_function("root.textContent.includes('2:40')")
                    self.assertGreaterEqual(page.evaluate("root.getAnimations({subtree:true}).find(a => a.animationName === 'breathe').currentTime"), before)
                    self.assertEqual(page.locator('#root').evaluate("el => getComputedStyle(el).opacity"), '1')
                    page.locator('[data-act=show_browser]').click()
                    page.wait_for_function("requestedActions.length === 1")
                    self.assertEqual(page.evaluate('requestedActions[0][0]'), 'show_browser')
                    self.assertEqual(page.evaluate('dragLocks'), [])
                    page.mouse.move(50,25)
                    page.wait_for_function('open')
                    page.locator('[data-act=show_browser]').click()
                    page.wait_for_function("requestedActions.length === 2")
                    amber = page.locator('#root').evaluate("el => getComputedStyle(el).backgroundColor")
                    page.emulate_media(reduced_motion='reduce')
                    self.assertEqual(page.locator('#root').evaluate("el => getComputedStyle(el, '::after').animationName"), 'none')
                    self.assertEqual(page.locator('#root').evaluate("el => getComputedStyle(el).backgroundColor"), amber)
                    page.locator('[data-act=settings]').click()
                    page.locator('[data-page=wait]').click()
                    self.assertTrue(page.get_by_role('switch', name='系统通知').is_visible())
                    self.assertTrue(page.locator('.strip.warn-strip').is_visible())  # the prompt stays in reach
                    page.locator('[data-act=back]').click()
                    page.locator('[data-act=back]').click()
                    page.wait_for_selector('#root.warn')
                    page.evaluate("testState.mode='running'; testState.attention=null; tick()")
                    page.wait_for_function("!root.classList.contains('warn')")
                    self.assertFalse(page.evaluate("root.getAnimations({subtree:true}).some(a => a.animationName === 'breathe')"))
                    browser.close()

    def test_a_pinned_card_stays_open_when_the_pointer_leaves(self):
        """钉住 (user, 2026-11-17): pressed, the card stays open; not remembered, the next window starts as a capsule."""
        from patchright.sync_api import sync_playwright
        from paper_search_school.progress_view import view
        import time
        state = view(dict(status='running', current='10.1000/example', title='Test article', publisher='Test', total=3,
                          done=0, success=0, failed=0, stage='fetching_pdf', started_at=time.time()), time.time())
        script = '''state => {
          window.testPointer={x:-1,y:-1};
          document.addEventListener('pointermove', e=>{testPointer={x:e.clientX,y:e.clientY}});
          window.pointerSnapshot=()=>{const r=root.getBoundingClientRect();return {...testPointer,
            inside:testPointer.x>=r.left && testPointer.x<r.right && testPointer.y>=r.top && testPointer.y<r.bottom}};
          window.sizes=[];
          window.pywebview={api:{platform:async()=> 'darwin', state:async()=>state, hover_state:async()=>pointerSnapshot(),
            begin_layout:async(expanded,w,h)=>({vertical:'down',horizontal:'right',width:w,height:h,
              from_width:parseFloat(root.style.width)+20, from_height:parseFloat(root.style.height)+20}),
            finish_layout:async()=>{}, resize:async(w,h)=>sizes.push([w,h])}};
          window.dispatchEvent(new Event('pywebviewready'));
        }'''
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            try:
                page = page_world(browser.new_page(viewport={'width':800,'height':800}))
                page.set_content(PAGE.read_text(encoding='utf-8'))
                page.evaluate(script, state)
                page.wait_for_function('lastCls === "pill"')
                page.wait_for_timeout(400)
                page.mouse.move(50,25)
                page.wait_for_function("open === true && root.querySelector('[data-act=pin]')")
                pin = page.locator('[data-act=pin]').first
                self.assertEqual(pin.get_attribute('aria-pressed'), 'false')
                pin.click()
                page.wait_for_function('pinned === true')
                self.assertEqual(page.locator('[data-act=pin]').first.get_attribute('aria-pressed'), 'true')
                page.mouse.move(700,700)
                page.wait_for_timeout(700)
                self.assertTrue(page.evaluate('open'))
                # Unpinned, it closes as before when the pointer leaves.
                page.mouse.move(50,25)
                page.locator('[data-act=pin]').first.click()
                page.wait_for_function('pinned === false')
                page.mouse.move(700,700)
                page.wait_for_function('open === false')
                # Pinned, then a new window: not remembered, it starts as the capsule.
                page.mouse.move(50,25)
                page.locator('[data-act=pin]').first.click()
                page.wait_for_function('pinned === true')
                second = page_world(browser.new_page(viewport={'width':800,'height':800}))
                second.set_content(PAGE.read_text(encoding='utf-8'))
                second.evaluate(script, state)
                second.wait_for_function('lastCls === "pill"')
                second.wait_for_timeout(400)
                self.assertFalse(second.evaluate('open || pinned'))
            finally:
                browser.close()

    def test_a_pinned_card_comes_back_open_after_a_minimize(self):
        """User, 2026-11-20 (Windows): pinned, minimized and restored, the card had shrunk to the capsule."""
        from patchright.sync_api import sync_playwright
        from paper_search_school.progress_view import view
        import time
        state = view(dict(status='running', current='10.1000/example', title='Test article', publisher='Test', total=3,
                          done=0, success=0, failed=0, stage='fetching_pdf', started_at=time.time()), time.time())
        script = '''state => {
          window.minimized=0;
          window.pywebview={api:{platform:async()=> 'win32', state:async()=>state,
            begin_layout:async(expanded,w,h)=>({vertical:'down',horizontal:'right',width:w,height:h,
              from_width:parseFloat(root.style.width)+20, from_height:parseFloat(root.style.height)+20}),
            finish_layout:async()=>{}, resize:async()=>{}, minimize:async()=>{minimized++}}};
          window.dispatchEvent(new Event('pywebviewready'));
        }'''
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            try:
                page = page_world(browser.new_page(viewport={'width':800,'height':800}))
                page.set_content(PAGE.read_text(encoding='utf-8'))
                page.evaluate(script, state)
                page.wait_for_function('lastCls === "pill"')
                page.wait_for_timeout(400)
                page.mouse.move(50,25)
                page.wait_for_function("open === true && root.querySelector('[data-act=pin]')")
                page.locator('[data-act=pin]').first.click()
                page.wait_for_function('pinned === true')
                page.locator('[data-act=minimize]').first.click()
                page.wait_for_function('minimized === 1')
                page.mouse.move(700,700)  # restored from the taskbar: the pointer elsewhere
                page.wait_for_timeout(700)
                self.assertTrue(page.evaluate('open && pinned'))
                # Not pinned, it comes back as the capsule, as before.
                page.mouse.move(50,25)
                page.locator('[data-act=pin]').first.click()
                page.wait_for_function('pinned === false')
                page.locator('[data-act=minimize]').first.click()
                page.wait_for_function('minimized === 2')
                self.assertFalse(page.evaluate('open'))
            finally:
                browser.close()

    def test_hover_without_click_animated_resize_and_directory_input(self):
        from patchright.sync_api import sync_playwright
        from paper_search_school.progress_view import view
        import time
        state = view(dict(status='running', current='10.1000/example', title='Test article', publisher='Test', total=3,
                          done=0, success=0, failed=0, stage='fetching_pdf', started_at=time.time()), time.time())
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            page = page_world(browser.new_page(viewport={'width':800,'height':800}))
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.set_content(PAGE.read_text(encoding='utf-8'))
            page.evaluate('''state => {
              window.testPointer={x:-1,y:-1};
              document.addEventListener('pointermove', e=>{testPointer={x:e.clientX,y:e.clientY}});
              window.pointerSnapshot=()=>{const r=root.getBoundingClientRect();return {...testPointer,
                inside:testPointer.x>=r.left && testPointer.x<r.right && testPointer.y>=r.top && testPointer.y<r.bottom}};
              window.sizes=[]; window.saved=null; window.savedValues=null; window.notificationPreference=true;
              window.pywebview={api:{platform:async()=> 'darwin', state:async()=>state, hover_state:async()=>pointerSnapshot(),
                resize:async(w,h)=>sizes.push([w,h]),
                begin_layout:async(expanded,w,h)=>({vertical:'down',horizontal:'right',width:w,height:h,
                  from_width:parseFloat(root.style.width)+(document.body.classList.contains('mac')?20:0),
                  from_height:parseFloat(root.style.height)+(document.body.classList.contains('mac')?20:0)}),
                finish_layout:async()=>{},
                settings:async()=>({fields:[{name:'stalled',label:'页面持续无进展',unit:'秒',value:30,default:30}],
                  notify:notificationPreference,download_dir:'/original'}),
                set_notifications:async n=>{notificationPreference=n;return {ok:true,notify:n}},
                choose_download_directory:async()=>'/chosen folder',
                save_settings:async(v,d)=>{saved=d;savedValues=v;return {ok:true}}}};
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
            page.evaluate("open=false;render(true)")
            page.wait_for_function("!root.classList.contains('animating')")
            # A stationary cursor must not reopen a window that just moved.
            # Re-enter with real pointer motion, as an inactive Cocoa hover does.
            page.mouse.move(700,700)
            page.wait_for_timeout(550)
            page.mouse.move(50,25)
            page.wait_for_function('open === true')
            page.mouse.move(700,700)
            page.wait_for_function('open === false')
            page.wait_for_timeout(400)
            page.mouse.move(50,25)
            page.wait_for_function('open === true')
            page.locator('[data-act=settings]').click()
            self.assertIn('通知开', page.locator('[data-page=wait]').inner_text())
            page.locator('[data-page=wait]').click()
            switch = page.get_by_role('switch', name='系统通知')
            self.assertEqual(switch.get_attribute('aria-checked'), 'true')
            switch.click()
            page.wait_for_function('notificationPreference === false')
            self.assertEqual(switch.get_attribute('aria-checked'), 'false')
            page.locator('[data-act=back]').click()
            self.assertIn('通知关', page.locator('[data-page=wait]').inner_text())
            page.locator('[data-page=wait]').click()
            self.assertEqual(page.get_by_role('switch', name='系统通知').get_attribute('aria-checked'), 'false')
            page.get_by_role('switch', name='系统通知').click()
            page.wait_for_function('notificationPreference === true')
            idle = page.get_by_role('textbox', name='页面持续无进展')
            self.assertEqual(idle.input_value(), '30')
            idle.fill('45')
            page.locator('[data-act=defaults]').click()
            self.assertEqual(idle.input_value(), '30')
            idle.fill('45')
            page.locator('[data-act=save]').click()
            page.wait_for_function('savedValues && savedValues.stalled === "45"')
            self.assertIsNone(page.evaluate('saved'))  # the waits page has no folder
            page.wait_for_selector('.settings-note')
            page.locator('[data-page=download]').click()
            page.locator('[data-act=choose_folder]').click()
            self.assertEqual(page.locator('#download-dir').input_value(), '/chosen folder')
            page.locator('#download-dir').fill('/typed folder')
            page.locator('[data-act=save]').click()
            page.wait_for_function('saved === "/typed folder"')
            self.assertEqual(errors, [])

    def test_holding_the_pill_freezes_hover_and_refresh_until_release(self):
        from patchright.sync_api import sync_playwright
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
        from patchright.sync_api import sync_playwright
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
                    page.locator('[data-page=download]').click()
                    page.locator('#download-dir').fill('/edited while focused')
                    page.mouse.move(80, 60)
                    self.assertEqual(page.evaluate("nativeMoves"), [])
                    self.assertEqual(page.evaluate("dragLocks"), [])
                    browser.close()

    def test_what_is_typed_in_the_settings_survives_a_click_on_the_card(self):
        """A click on the card's background is a drag, and its end redraws the card: a typed
        hourly limit went back to the saved one unless 保存 was the next click (Windows,
        2026-11-13). What is typed stays until it is saved or its page is left."""
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            for platform in ("win32", "darwin"):
                with self.subTest(platform=platform):
                    browser, page = self.drag_page(p, platform)
                    try:
                        page.evaluate("""() => {
                            window.savedSettings = [];
                            Object.assign(pywebview.api, {
                                settings: async()=>({fields:[{name:'hourly', label:'每家出版社每小时最多', unit:'篇',
                                    value:150, default:100, page:'download'}], notify:true, download_dir:'/original'}),
                                save_settings: async(values, folder)=>{savedSettings.push([values, folder]); return {ok:true}},
                                api_keys: async()=>({ok:true, filled:0, total:1, groups:[{title:'查期刊、搜正文', services:[
                                    {id:'semantic', name:'Semantic Scholar', use:'', url:'https://example.org/s', set:false,
                                     guide:'', masked:'', keys:[{key:'SEMANTIC_KEY', label:'API key', set:false, masked:''}]}]}]}),
                                api_key_values: async()=>({ok:true, values:{}}),
                            });
                        }""")
                        page.mouse.move(50, 25)
                        page.wait_for_function('open')
                        page.locator('[data-act=settings]').click()
                        page.locator('[data-page=download]').click()
                        hourly = page.get_by_label('每家出版社每小时最多')
                        hourly.fill('200')
                        page.locator('#download-dir').fill('/typed')
                        page.evaluate('dragLocks = []')
                        page.get_by_text('每家出版社每小时最多').click()  # the card's background
                        page.wait_for_function('dragLocks.length === 2 && !dragging && !endingDrag')
                        self.assertEqual(hourly.input_value(), '200')
                        self.assertEqual(page.locator('#download-dir').input_value(), '/typed')
                        page.locator('[data-act=save]').click()
                        page.wait_for_function('savedSettings.length === 1')
                        self.assertEqual(page.evaluate('savedSettings[0]'), [{'hourly': '200'}, '/typed'])
                        # Typed, then left without saving: the saved value again.
                        page.locator('[data-page=download]').click()
                        hourly.fill('300')
                        page.locator('[data-act=back]').click()
                        page.locator('[data-page=download]').click()
                        self.assertEqual(hourly.input_value(), '150')
                        # A key being typed stays too.
                        page.locator('[data-act=back]').click()
                        page.locator('[data-page=keys]').click()
                        page.locator('[data-service=semantic]').click()
                        key = page.get_by_label('Semantic Scholar API key')
                        key.fill('sk-typed-1234')
                        page.evaluate('dragLocks = []')
                        page.locator('.head .title').click()  # the key list itself does not drag; its header does
                        page.wait_for_function('dragLocks.length === 2 && !dragging && !endingDrag')
                        self.assertEqual(key.input_value(), 'sk-typed-1234')
                    finally:
                        browser.close()

    def test_a_held_batch_card_keeps_its_header_to_one_line_and_says_the_hold_once(self):
        """Held by the hourly limit: "148/392 · 已达每小时上限 · 已用 40:09" broke into two
        lines, and the hold's phase repeated the notice below it (Windows, 2026-11-13)."""
        import time
        from datetime import datetime
        from patchright.sync_api import sync_playwright
        from paper_search_school.progress_view import view
        now = time.time()
        paused = "Elsevier 一小时内已打开 150 篇（每小时上限），13:05 继续这一篇"
        state = dict(status='running', run_id='r', current='10.1016/x', total=392, done=148, success=146, failed=2,
                     title='Age- and sex-specific knee alignment patterns in symptomatic patients: a cross-sectional study',
                     publisher='Elsevier', awaiting_next=True, phase=paused,
                     started_at=datetime.fromtimestamp(now - 2409).isoformat(timespec='seconds'),
                     hourly_wait={'publisher': 'Elsevier', 'limit': 150, 'until': now + 1200, 'phase': paused})
        one_line = """() => { const sub = root.querySelector('.head .sub'); const range = document.createRange();
            range.selectNodeContents(sub); return [sub.innerText, range.getClientRects().length]; }"""
        with sync_playwright() as p:
            for english in (False, True):
                with self.subTest(english=english):
                    browser, page = self.drag_page(p, 'win32', english=english)
                    try:
                        page.evaluate("s => { testState = s; open = true; tick(); }", view(state, now))
                        page.wait_for_function("root.querySelector('.head .sub') && !root.classList.contains('animating')")
                        text, lines = page.evaluate(one_line)
                        self.assertEqual(lines, 1, text)
                        self.assertNotIn('已用' if not english else 'elapsed', text)
                        # The notice says the hold once; its phase does not follow it.
                        shown = page.locator('#root').inner_text()
                        resume = time.strftime('%H:%M', time.localtime(now + 1200))
                        self.assertEqual(shown.count(resume), 1, shown)
                        self.assertNotIn('opened this hour' if english else '一小时内已打开', shown)
                    finally:
                        browser.close()

    def test_a_batch_waiting_for_held_publishers_says_so_collapsed_too(self):
        """Nothing left but the held publishers: the collapsed capsule said 下载中 and the last
        paper as if it still ran, not that the user is to come back (Windows, 2026-11-15). A
        held publisher shows beside the progress as soon as it is held, as a tag apart from
        the breathing prompt of a sign-in the browser waits on (Mac, 2026-11-15)."""
        import time
        from patchright.sync_api import sync_playwright
        from paper_search_school.progress_view import view
        now = time.time()
        wait = "其他篇目已完成，等你回来点“登录并继续”"
        state = dict(status='running', run_id='r', total=8, done=4, success=4, failed=0, current='10.1038/old',
                     title='The paper that ran last', publisher='Springer Nature', stage='starting', awaiting_next=True,
                     phase=wait, held_wait=True, held=[{'key': '10.1038/', 'name': 'Springer Nature', 'count': 4}])
        with sync_playwright() as p:
            for english in (False, True):
                with self.subTest(english=english):
                    browser, page = self.drag_page(p, 'win32', english=english)
                    try:
                        page.evaluate("s => { testState = s; open = false; tick(); }",
                                      {**view(state, now), **({'lang': 'en'} if english else {})})
                        page.wait_for_function("root.classList.contains('pill') && !root.classList.contains('animating')")
                        self.assertNotIn('warn', page.evaluate("root.className"))
                        self.assertEqual(page.locator('#root').inner_text().split('\n'),
                                         ['Sign in to school again', '4 paused'] if english else ['请重新登录学校', '已暂停 4 篇'])
                        self.assertEqual(page.locator('.held-tag').count(), 1)
                        page.evaluate("open = true; tick()")
                        page.wait_for_function("root.classList.contains('card') && !root.classList.contains('animating')")
                        shown = page.locator('#root').inner_text()
                        self.assertNotIn('The paper that ran last', shown)
                        self.assertIn('Others done; press Sign in & resume' if english else wait, shown)
                        self.assertEqual(page.locator('[data-act="resume_held"]').count(), 1)
                        self.assertEqual(page.locator('[data-act="confirm"]').count(), 1)
                        # Held while other papers still download: their progress, the tag beside it.
                        running = dict(state, held_wait=False, awaiting_next=False, stage='fetching_pdf', part='main',
                                       current='10.1002/now', title='Downloading now', publisher='Wiley')
                        page.evaluate("s => { testState = s; open = false; tick(); }",
                                      {**view(running, now), **({'lang': 'en'} if english else {})})
                        page.wait_for_function("root.classList.contains('pill') && !root.classList.contains('animating')")
                        self.assertNotIn('warn', page.evaluate("root.className"))
                        pill = page.locator('#root').inner_text()
                        self.assertIn('4/8', pill)
                        self.assertIn('4 paused' if english else '已暂停 4 篇', pill)
                        page.locator('.held-tag').click()
                        page.wait_for_function("root.classList.contains('card') && !root.classList.contains('animating')")
                        self.assertIn('Downloading now', page.locator('#root').inner_text())
                        self.assertEqual(page.locator('[data-act="resume_held"]').count(), 1)
                    finally:
                        browser.close()

    def test_logging_in_to_go_on_answers_at_once(self):
        """登录并继续 looked as if nothing happened in the seconds before the papers went on
        (Mac, 2026-11-15): the button, the line and the tag say it was taken at once, until
        the held publishers change; a press that was not taken gives the button back."""
        import time
        from patchright.sync_api import sync_playwright
        from paper_search_school.progress_view import view
        now = time.time()
        held = [{'key': '10.1038/', 'name': 'Springer Nature', 'count': 4}]
        running = dict(status='running', run_id='r', total=8, done=3, success=3, failed=0, current='10.1002/now',
                       title='Downloading now', publisher='Wiley', stage='fetching_pdf', part='main', held=held)
        slow = """window.pywebview.api.act = async (...args) => { requestedActions.push(args);
            await new Promise((done) => setTimeout(done, 3000)); return '已收到：这一篇下完后接着下暂停的篇目'; }"""
        with sync_playwright() as p:
            for english in (False, True):
                with self.subTest(english=english):
                    browser, page = self.drag_page(p, 'win32', english=english)
                    lang = {'lang': 'en'} if english else {}
                    try:
                        page.evaluate(slow)
                        page.evaluate("async s => { testState = s; open = true; await tick(); }", {**view(running, now), **lang})
                        page.wait_for_function("root.querySelector('[data-act=\"resume_held\"]') && !root.classList.contains('animating')")
                        page.locator('[data-act="resume_held"]').click()
                        # At once, though the answer takes seconds.
                        page.wait_for_function("root.querySelector('.held .btn.done')", timeout=500)
                        held_text = page.locator('.held').inner_text()
                        self.assertIn('Confirmed' if english else '已确认', held_text)
                        self.assertIn('4 paused resume next' if english else '本篇完成后继续下载 4 篇', held_text)
                        # Each line of the block is one line (user, 2026-11-15).
                        self.assertEqual(page.evaluate("""() => [...root.querySelectorAll('.held .copy, .held .names')]
                            .map((line) => { const range = document.createRange(); range.selectNodeContents(line);
                              return range.getClientRects().length; })"""), [1, 1])
                        self.assertEqual(page.locator('[data-act="resume_held"]').count(), 0)
                        page.evaluate("async () => { open = false; await tick(); }")
                        page.wait_for_function("root.classList.contains('pill') && !root.classList.contains('animating')")
                        self.assertIn('4 to resume' if english else '待继续 4 篇', page.locator('.held-tag').inner_text())
                        # Gone on with, then held again: the button is back.
                        page.evaluate("async s => { testState = s; await tick(); }", {**view(dict(running, held=[]), now), **lang})
                        page.evaluate("async s => { testState = s; open = true; await tick(); }", {**view(running, now), **lang})
                        page.wait_for_function("root.querySelector('[data-act=\"resume_held\"]')")
                        # Only the held left: the card's title and line change at once too.
                        wait = dict(running, held_wait=True, awaiting_next=True, stage='starting',
                                    phase='其他篇目已完成，等你回来点“登录并继续”')
                        page.evaluate(slow)
                        page.evaluate("async s => { testState = s; open = true; await tick(); }", {**view(wait, now), **lang})
                        page.wait_for_function("root.querySelector('[data-act=\"resume_held\"]')")
                        page.locator('[data-act="resume_held"]').click()
                        page.wait_for_function("root.querySelector('.held .btn.done')", timeout=500)
                        self.assertEqual(page.locator('.head .title').inner_text(), 'Resuming' if english else '正在继续下载')
                        self.assertEqual(page.locator('.paper .line').inner_text(),
                                         'Sign-in page opens if needed' if english else '如需登录，会打开学校登录页')
                        page.evaluate("async s => { testState = s; await tick(); }", {**view(dict(wait, held=[]), now), **lang})
                        page.evaluate("async s => { testState = s; await tick(); }", {**view(running, now), **lang})
                        page.wait_for_function("root.querySelector('[data-act=\"resume_held\"]')")
                        # A press not taken (nothing held any more) gives the button back, with why.
                        page.evaluate("window.pywebview.api.act = async () => '这批下载已没有暂停的篇目'")
                        page.locator('[data-act="resume_held"]').click()
                        page.wait_for_function("root.querySelector('[data-act=\"resume_held\"]') && !root.querySelector('.held .btn.done')")
                    finally:
                        browser.close()

    def test_mac_window_motion_does_not_retrigger_hover_without_pointer_motion(self):
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser,page=self.drag_page(p,'darwin')
            try:
                page.wait_for_timeout(400)
                page.evaluate("""async () => {
                    clearInterval(pollTimer);
                    nativePointer={x:1000,y:1000,inside:true};
                    pywebview.api.hover_state=async()=>({...nativePointer});
                    await observeHover(true);
                }""")
                page.wait_for_function("open && !root.classList.contains('animating')")
                before=page.evaluate('sizes.length')
                for inside in (False,True,False,True):
                    page.evaluate('async inside=>{nativePointer.inside=inside;await observeHover(inside)}',inside)
                    page.wait_for_timeout(320)
                    self.assertTrue(page.evaluate('open'))
                self.assertEqual(page.evaluate('sizes.length'),before)
                page.evaluate('async()=>{nativePointer={x:1001,y:1000,inside:false};await observeHover()}')
                page.wait_for_function("!open && !root.classList.contains('animating')")
                page.evaluate('async()=>{nativePointer.inside=true;await observeHover()}')
                page.wait_for_timeout(300)
                self.assertFalse(page.evaluate('open'))
                page.evaluate('async()=>{nativePointer.x=1002;await observeHover()}')
                page.wait_for_function('open')
            finally:
                browser.close()

    def test_same_size_progress_updates_do_not_restart_native_animation(self):
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser,page = self.drag_page(p,'darwin')
            try:
                page.wait_for_timeout(400)
                page.evaluate("""() => { clearInterval(pollTimer); open=true; render(true); }""")
                page.wait_for_function("!root.classList.contains('animating')")
                page.evaluate("""() => {
                    layoutCalls=0;
                    const original=pywebview.api.begin_layout;
                    pywebview.api.begin_layout=async(...args)=>{
                        layoutCalls++;
                        await new Promise(resolve=>setTimeout(resolve,100));
                        return original(...args);
                    };
                }""")
                before=page.locator('.surface').bounding_box()
                for i in range(4):
                    page.evaluate("i=>{testState.elapsed='1:1'+i;tick()}",i)
                    page.wait_for_timeout(130)
                    now=page.locator('.surface').bounding_box()
                    self.assertAlmostEqual(now['width'],before['width'],delta=1)
                    self.assertAlmostEqual(now['height'],before['height'],delta=1)
                    self.assertFalse(page.locator('#root').evaluate("el=>el.classList.contains('animating')"))
                self.assertEqual(page.evaluate('layoutCalls'),0)
            finally:
                browser.close()

    def test_four_directions_align_content_during_animation_and_settings(self):
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            for platform in ('darwin', 'win32'):
                browser, page = self.drag_page(p, platform)
                try:
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.wait_for_timeout(400)
                    for vertical, horizontal in [('down','right'), ('down','left'), ('up','right'), ('up','left')]:
                        with self.subTest(platform=platform, vertical=vertical, horizontal=horizontal):
                            page.mouse.move(790,790)
                            page.evaluate("""([v,h]) => {
                                clearInterval(pollTimer); clearTimeout(hoverTimer); clearTimeout(leaveTimer);
                                panel=''; open=false;
                                pywebview.api.begin_layout=async(expanded,w,height)=>({
                                    vertical:v, horizontal:h, width:w, height,
                                    from_width:parseFloat(root.style.width)+(document.body.classList.contains('mac')?20:0),
                                    from_height:parseFloat(root.style.height)+(document.body.classList.contains('mac')?20:0)});
                                render(true);
                            }""", [vertical,horizontal])
                            page.wait_for_function("!root.classList.contains('animating')")
                            page.evaluate("""() => {
                                samples=[];
                                sampleTimer=setInterval(()=>{
                                    if (!root.classList.contains('animating')) return;
                                    const r=root.getBoundingClientRect(), s=root.firstElementChild.getBoundingClientRect();
                                    samples.push({left:s.left-r.left,right:r.right-s.right,
                                        top:s.top-r.top,bottom:r.bottom-s.bottom,width:r.width,height:r.height});
                                }, 15);
                                open=true; render(true);
                            }""")
                            page.wait_for_function("!root.classList.contains('animating')")
                            page.evaluate('clearInterval(sampleTimer)')
                            samples = page.evaluate('samples')
                            self.assertGreater(len(samples), 3)
                            for sample in samples:
                                self.assertLess(abs(sample['left' if horizontal=='right' else 'right']), 1.1)
                                self.assertLess(abs(sample['top' if vertical=='down' else 'bottom']), 1.1)
                            # Frame cadence varies under load; require visible intermediate sizes.
                            self.assertGreater(len({round(s['height']) for s in samples}), 1)
                            page.locator('[data-act=settings]').click()
                            page.wait_for_function("panel==='settings' && !root.classList.contains('animating')")
                            page.locator('[data-page=wait]').click()
                            page.wait_for_function("settingsPage==='wait' && !root.classList.contains('animating')")
                            self.assertTrue(page.locator('body').evaluate(
                                "(el,c)=>el.classList.contains(c)", 'grow-'+vertical))
                            self.assertTrue(page.get_by_role('switch',name='系统通知').is_visible())
                            size = page.evaluate('sizes.at(-1)')
                            box = page.locator('#root').bounding_box()
                            pad = 20 if platform=='darwin' else 0
                            self.assertAlmostEqual(size[0],box['width']+pad,delta=1)
                            self.assertAlmostEqual(size[1],box['height']+pad,delta=1)
                    self.assertEqual(errors, [])
                finally:
                    browser.close()

    def test_short_work_area_scrolls_settings_and_reversed_animation_finishes(self):
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser,page = self.drag_page(p,'win32')
            try:
                page.wait_for_timeout(400)
                page.evaluate("""() => {
                    clearInterval(pollTimer);
                    pywebview.api.begin_layout=async(expanded,w,h)=>({vertical:'up',horizontal:'left',
                        width:Math.min(w,300),height:Math.min(h,180),
                        from_width:parseFloat(root.style.width),from_height:parseFloat(root.style.height)});
                    open=true;render(true);
                }""")
                page.wait_for_function("!root.classList.contains('animating')")
                page.locator('[data-act=settings]').click()
                page.wait_for_function("panel==='settings' && !root.classList.contains('animating')")
                page.locator('[data-page=wait]').click()
                page.wait_for_function("settingsPage==='wait' && !root.classList.contains('animating')")
                self.assertLessEqual(page.locator('#root').bounding_box()['height'],180)
                self.assertTrue(page.locator('.surface').evaluate('el=>el.scrollHeight>el.clientHeight'))
                page.locator('[data-act=save]').scroll_into_view_if_needed()
                self.assertTrue(page.locator('[data-act=save]').is_visible())
                page.evaluate("""() => {
                    panel=''; open=false; render(true);
                    setTimeout(()=>{open=true;render(true)},40);
                    setTimeout(()=>{open=false;render(true)},80);
                }""")
                page.wait_for_timeout(450)
                page.wait_for_function("!root.classList.contains('animating')")
                self.assertTrue(page.locator('#root').evaluate("el=>el.classList.contains('pill')"))
                self.assertLess(page.locator('#root').bounding_box()['height'],70)
            finally:
                browser.close()

    def test_finished_card_tells_main_text_and_supplementary_files_apart_briefly(self):
        """Papers saved without every supplementary file: their own short section,
        rows closed and without the journal line (user, 2026-11-08)."""
        import time
        from patchright.sync_api import sync_playwright
        from paper_search_school.progress_view import view
        now = time.time()
        def item(reason, cls, title):
            return {'cls': cls, 'reason': reason, 'title': title, 'journal': 'APL', 'doi': '', 'note': ''}
        state = view(dict(status='done', run_id='r-apart', total=12, done=12, success=7, failed=5, output_dir='/tmp',
                          results={'content': 'both', 'main': 7, 'supplements': 4, 'sources': [['机构订阅', 7]],
                                   'failures': [item('学校没有订阅', 'no_access', 'No access')],
                                   'supplement_failures': [item('网站人机验证拦截', 'publisher_or_network', 'Blocked file'),
                                                           item('网站暂不支持自动下载附录', 'unsupported', 'No rule')],
                                   'markdown_failures': [item('网页只有摘要', 'unsupported', 'Abstract only'),
                                                         item('网页只有摘要', 'unsupported', 'Abstract too'),
                                                         item('网站暂不支持转换', 'unsupported', 'No page rule')]}), now)
        with sync_playwright() as p:
            browser, page = self.drag_page(p, 'darwin')
            try:
                page.evaluate("async state => { testState = state; open = true; await tick(); }", state)
                page.wait_for_function("!root.classList.contains('animating')")
                text = page.locator('#root').inner_text()
                for expected in ('PDF 未下到 5 篇', '补充材料未下全 2 篇', '网站人机验证拦截', '网站暂不支持自动下载附录',
                                 'Markdown 未生成 3 篇', '网页只有摘要', '网站暂不支持转换'):
                    self.assertIn(expected, text)
                self.assertNotIn('未完成', text)
                self.assertEqual(page.locator('.grp').count(), 5)
                self.assertEqual(page.locator('.grp .m').count(), 0)  # main row open, supplement rows without a journal line
                page.locator('[data-act=group][data-group="1"]').click()
                page.wait_for_function("!root.classList.contains('animating')")
                self.assertEqual(page.locator('.grp').nth(1).locator('.paper-list li .t').all_inner_texts(), ['Blocked file'])
                # The Markdown's rows open on their own index, after the files' rows (2026-11-15).
                page.locator('[data-act=group][data-group="3"]').click()
                page.wait_for_function("!root.classList.contains('animating')")
                self.assertEqual(page.locator('.grp').nth(3).locator('.paper-list li .t').all_inner_texts(), ['Abstract only', 'Abstract too'])
                # The others stay open (user, 2026-11-17).
                self.assertEqual(page.locator('.paper-list').count(), 3)
            finally:
                browser.close()

    def test_finished_card_opens_each_reason_on_its_own_and_its_list_scrolls_without_dragging(self):
        from datetime import datetime
        import time
        from patchright.sync_api import sync_playwright
        from paper_search_school.progress_view import view
        now = time.time()
        failures = [{'cls': 'no_access', 'reason': '学校没有订阅', 'title': f'Paper {i}', 'journal': 'Spine',
                     'doi': '', 'note': ''} for i in range(12)]
        failures.append({'cls': 'user_side', 'reason': '等学校登录超时', 'title': 'Late', 'journal': 'Thieme',
                         'doi': '10.1055/a-2979-4843', 'note': ''})
        state = view(dict(status='done', run_id='r-done', total=200, done=200, success=187, failed=13,
                          started_at=datetime.fromtimestamp(now - 6730).isoformat(timespec='seconds'),
                          finished_at=datetime.fromtimestamp(now).isoformat(timespec='seconds'), output_dir='/tmp',
                          results={'content': 'both', 'main': 187, 'supplements': 9,
                                   'sources': [['机构订阅', 150], ['开放获取', 37]], 'failures': failures}), now)
        with sync_playwright() as p:
            browser, page = self.drag_page(p, 'win32')
            try:
                page.evaluate("async state => { testState = state; open = true; await tick(); }", state)
                page.wait_for_function("!root.classList.contains('animating')")
                text = page.locator('#root').inner_text()
                for expected in ('共 200 篇', '1:52:10', 'PDF 未下到 13 篇', '学校没有订阅', '12 篇', 'Spine 12',
                                 '已完成 187 篇', 'PDF 187 篇 · 补充材料 9 个', '机构订阅 150 · 开放获取 37'):
                    self.assertIn(expected, text)
                self.assertEqual(page.locator('.paper-list').count(), 0)
                # Every line of the card stays on one line.
                self.assertTrue(page.evaluate("""[...root.querySelectorAll('.head .sub, .stats b, .grp .row, .grp .m, .saved-line')]
                    .every(el => el.getClientRects().length === 1 && el.getBoundingClientRect().height < 30)"""))
                rows = page.locator('[data-act=group]')
                rows.nth(0).click()
                page.wait_for_function("!root.classList.contains('animating')")
                self.assertEqual(page.locator('.paper-list li').count(), 12)
                self.assertTrue(page.locator('.paper-list').evaluate('el => el.scrollHeight > el.clientHeight'))
                box = page.locator('.paper-list').bounding_box()
                page.mouse.move(box['x'] + 20, box['y'] + 20)
                page.mouse.down(); page.mouse.move(box['x'] + 60, box['y'] + 60); page.mouse.up()
                self.assertEqual(page.evaluate('dragLocks'), [])
                # Another reason opens beside it, the first staying open (user, 2026-11-17).
                rows.nth(1).click()
                page.wait_for_function("!root.classList.contains('animating')")
                self.assertEqual(page.locator('.paper-list').count(), 2)
                self.assertEqual(page.locator('.grp').nth(1).locator('.paper-list li').all_inner_texts(), ['Late\nThieme'])
                # A listed paper opens its article page, to be fetched by hand (user, 2026-11-08).
                page.locator('.grp').nth(1).locator('.paper-list [data-act=open_article]').click()
                page.wait_for_function("openedArticles.length === 1")
                self.assertEqual(page.evaluate('openedArticles'), ['10.1055/a-2979-4843'])
                self.assertEqual(page.evaluate('dragLocks'), [])
                rows.nth(1).click()
                page.wait_for_function("!root.classList.contains('animating')")
                self.assertEqual(page.locator('.paper-list').count(), 1)
                self.assertEqual(page.locator('.paper-list li').count(), 12)
            finally:
                browser.close()

    def test_sites_not_yet_supported_are_said_while_running_and_reported_from_the_lists(self):
        """Pages whose Markdown came by rules not listed for their site, while the batch runs:
        no line of their own, a dot beside 成功 (beside 失败 when none was saved, opening their
        group in 失败 with its note, the supported sites and the report buttons) and, pointed
        at, a card above the counts: the site and whose rules, the counts, and 提 issue only
        when some were not saved; the finished card's group as before (user, 2026-11-16; the
        dot and its card 2026-11-17)."""
        import time
        from patchright.sync_api import sync_playwright
        from paper_search_school.progress_view import paper_lists, summary_view, unverified_sites, view
        raw = dict(status='running', batch_id='b-sites', run_id='r-sites', current='10.1016/5', title='Being fetched',
                   publisher='Elsevier', journal='Journal of the American College of Cardiology', total=6, done=4, success=4, failed=0,
                   content='both', markdown=True, stage='fetching_pdf')
        note = 'www.jacc.org · 不完整：参考文献少 1 条，少 1 张图'
        def paper(index, state, **fields):
            return {'index': index, 'doi': f'10.1016/{index}', 'title': f'Paper {index}', 'journal': 'JACC',
                    'state': state, **fields}
        listed = {'batch_id': 'b-sites', 'folder': '/papers', 'papers': {str(p['index']): p for p in (
            paper(1, 'ok', markdown_host='www.jacc.org', markdown_saved=True, markdown_rules='Atypon'),
            paper(2, 'ok', markdown_host='www.jacc.org', markdown_saved=True, markdown_rules='Atypon'),
            paper(3, 'ok', markdown_cls='unsupported', markdown_reason='内容不完整', markdown_host='www.jacc.org',
                  markdown_note=note, markdown_rules='Atypon'),
            paper(4, 'ok', supplement_cls='publisher_or_network', supplement_reason='网站人机验证拦截'),
            paper(5, 'school'), paper(6, 'open'))}}
        lists = paper_lists(listed, raw)
        state = {**view(raw, time.time()), 'lists': True, 'sites': unverified_sites(listed, raw)}
        for english in (False, True):
            with self.subTest(english=english), sync_playwright() as p:
                browser, page = self.drag_page(p, 'win32', english=english)
                try:
                    page.evaluate("""({state, lists}) => { window.asked = [];
                        Object.assign(pywebview.api, {paper_lists: async () => lists,
                          markdown_issue: async () => { asked.push('issue'); return '已导出报告 PaperSearch-Markdown报告-20261116-2005.zip 并打开 issue 页面，把它拖进去'; },
                          open_markdown_support: async () => { asked.push('support'); return '已在浏览器打开'; }});
                        testState = state; open = true; }""", {'state': {**state, **({'lang': 'en'} if english else {})}, 'lists': lists})
                    page.evaluate("async () => { await tick(); }")
                    page.wait_for_function("!root.classList.contains('animating')")
                    # No line of its own: a dot beside 成功, on the label's one line; its card hidden.
                    self.assertEqual(page.locator('.held').count(), 0)
                    self.assertEqual(page.locator('.stat[data-list=ok] .rules-dot').count(), 1)
                    self.assertEqual(page.locator('.stat[data-list=failed] .rules-dot').count(), 0)
                    self.assertTrue(page.evaluate("() => root.querySelector('.stat[data-list=ok] span').getClientRects().length === 1"))
                    self.assertFalse(page.locator('.rules-pop').is_visible())
                    # Pointed at: the card above the counts, inside the window; away, it closes.
                    page.hover('.rules-dot')
                    page.wait_for_function("root.querySelector('.rules-pop.show')")
                    self.assertTrue(page.evaluate("""() => { const c = root.querySelector('.rules-pop').getBoundingClientRect(),
                        s = root.querySelector('.stats').getBoundingClientRect(), r = root.getBoundingClientRect();
                        return c.bottom <= s.top && c.top >= r.top && c.left >= r.left && c.right <= r.right; }"""))
                    # Its text in line with 成功 below; 成功, 失败 and 剩余 where they are without the dot.
                    self.assertTrue(page.evaluate("""() => Math.abs(root.querySelector('.rules-pop .r').getBoundingClientRect().left
                        - root.querySelector('.stat[data-list=ok] span').getBoundingClientRect().left) < 1
                        && [...root.querySelectorAll('.stats .stat')].every(st => Math.abs(st.querySelector('b').getBoundingClientRect().left
                        - st.querySelector('span').getBoundingClientRect().left) < 1)"""))
                    card = page.locator('.rules-pop').inner_text().split('\n')
                    if english:
                        self.assertEqual(card, ['Markdown: rules borrowed from other sites', 'www.jacc.org · Atypon rules', '2 complete, saved · 1 incomplete, not saved',
                                                'Open an issue to list it'])
                    else:
                        self.assertEqual(card, ['Markdown：借用其他网站的规则转换', 'www.jacc.org · 采用 Atypon 规则', '完整已保存 2 篇 · 不完整未保存 1 篇',
                                                '提 issue 纳入已登记网站'])
                    page.mouse.move(2, 2)
                    page.wait_for_function("!root.querySelector('.rules-pop.show')")
                    if not english:
                        # Two sites borrowing two sets of rules, both named; all saved, 提 issue too: the site
                        # can be listed (user, 2026-11-17).
                        page.evaluate("async (s) => { testState = s; await tick(); }",
                                      {**state, 'sites': {**state['sites'], 'hosts': ['www.jacc.org', 'b.example.org'],
                                                          'rules': ['Atypon', 'Silverchair'], 'saved': 3, 'unsaved': 0}})
                        page.hover('.rules-dot')
                        page.wait_for_function("root.querySelector('.rules-pop.show')")
                        self.assertEqual(page.locator('.rules-pop').inner_text().split('\n'),
                                         ['Markdown：借用其他网站的规则转换', '2 个网站 · 采用 Atypon / Silverchair 规则', '完整已保存 3 篇 · 不完整未保存 0 篇',
                                          '提 issue 纳入已登记网站'])
                        # 提 issue from the card.
                        page.evaluate("async (s) => { testState = s; await tick(); }", state)
                        page.hover('.rules-dot')
                        page.wait_for_function("root.querySelector('.rules-pop.show .issue')")
                        page.locator('.rules-pop .issue').click()
                        page.wait_for_function("asked.includes('issue')")
                        page.evaluate("async () => { window.asked = []; showRules(false); await tick(); }")
                    # None saved: the dot beside 失败, opening their group.
                    page.evaluate("async (s) => { testState = s; await tick(); }",
                                  {**state, **({'lang': 'en'} if english else {}), 'sites': {**state['sites'], 'saved': 0}})
                    self.assertEqual(page.locator('.stat[data-list=ok] .rules-dot').count(), 0)
                    page.locator('.stat[data-list=failed] .rules-dot').click()
                    page.wait_for_function("panel === 'papers' && papersList && !root.classList.contains('animating')")
                    if english:
                        self.assertIsNone(page.evaluate(r"""() => [root.innerText, ...[...root.querySelectorAll('[title], [aria-label]')]
                            .flatMap(e => [e.title, e.getAttribute('aria-label') || ''])].join('\n').match(/[一-鿿]+/g)"""))
                        continue
                    text = page.locator('#root').inner_text()
                    for expected in ('补充材料未下全 1 篇', 'Markdown 未生成 1 篇', '内容不完整',
                                     '这些网站尚未正式支持 Markdown，内容不完整的未保存。如需支持，欢迎提 issue 或 PR。', note):
                        self.assertIn(expected, text)
                    # Only the site's group is open, with its one button: 提 issue exports the report too (2026-11-17).
                    self.assertEqual(page.locator('.paper-list li').all_inner_texts(), [f'Paper 3\n{note}'])
                    self.assertEqual(page.locator('.unverified-actions .btn').all_inner_texts(), ['提 issue'])
                    for act, said in (('markdown_support', '已在浏览器打开'), ('markdown_issue', '已导出报告 PaperSearch-Markdown报告-20261116-2005.zip 并打开 issue 页面，把它拖进去')):
                        page.locator(f'[data-act={act}]').click()
                        page.wait_for_function(f"document.getElementById('root').innerText.includes({json.dumps(said)})")
                    self.assertEqual(page.evaluate('asked'), ['support', 'issue'])
                finally:
                    browser.close()
        # The finished card: the same group, its note and buttons, the export said under them.
        done = {**raw, 'status': 'done', 'done': 6, 'results': {
            'content': 'both', 'folder': '/papers', 'started': int(time.time()) - 600, 'main': 6, 'supplements': 3, 'markdown': 5,
            'failures': [], 'supplement_failures': [], 'sources': [['机构下载', 6]],
            'markdown_failures': [{'cls': 'unsupported', 'reason': '内容不完整', 'title': 'Paper 3', 'doi': '10.1016/3',
                                   'note': note, 'unverified': True}]}}
        shown = view(done, time.time())
        self.assertTrue(summary_view(done['results'])['markdown_groups'][0]['unverified'])
        with sync_playwright() as p:
            browser, page = self.drag_page(p, 'win32')
            try:
                page.evaluate("""state => { Object.assign(pywebview.api, {markdown_issue: async () => '已导出报告 PaperSearch-Markdown报告-20261116-2005.zip 并打开 issue 页面，把它拖进去'});
                    testState = state; open = true; }""", {**shown, 'lists': True})
                page.evaluate("async () => { await tick(); }")
                page.wait_for_function("!root.classList.contains('animating')")
                page.locator('[data-act=group]').last.click()
                page.wait_for_function("!root.classList.contains('animating')")
                self.assertIn('这些网站尚未正式支持 Markdown', page.locator('#root').inner_text())
                page.locator('.unverified-actions [data-act=markdown_issue]').click()
                page.wait_for_function("root.querySelector('.unverified-actions + .line')")
                self.assertEqual(page.locator('.unverified-actions + .line').inner_text(), '已导出报告 PaperSearch-Markdown报告-20261116-2005.zip 并打开 issue 页面，把它拖进去')
            finally:
                browser.close()
        # Saved with a Markdown its checks found short (a registered site's page): a section of its
        # own after the Markdown not made, in both languages (user, 2026-11-17).
        doubted = {**done, 'results': {**done['results'], 'markdown_failures': [], 'markdown_doubts': [
            {'reason': '参考文献可能不全', 'note': '可能缺：参考文献少 2 条，正文缺约 12%', 'title': 'Paper 4', 'journal': 'NEJM', 'doi': '10.1056/4'}]}}
        for english in (False, True):
            with self.subTest(doubt_english=english), sync_playwright() as p:
                browser, page = self.drag_page(p, 'win32', english=english)
                try:
                    page.evaluate("async state => { testState = state; open = true; await tick(); }",
                                  {**view(doubted, time.time()), 'lists': True, **({'lang': 'en'} if english else {})})
                    page.wait_for_function("!root.classList.contains('animating')")
                    page.locator('[data-act=group]').last.click()
                    page.wait_for_function("!root.classList.contains('animating')")
                    text = page.locator('#root').inner_text()
                    if english:
                        self.assertIn('Markdown may be short: 1', text)
                        self.assertIn('May lack: ', text)
                        self.assertIsNone(page.evaluate("() => root.innerText.match(/[一-鿿]+/g)"))
                    else:
                        for said in ('Markdown 可能不全 1 篇', '待核对', '参考文献可能不全', 'NEJM · 可能缺：参考文献少 2 条，正文缺约 12%'):
                            self.assertIn(said, text)
                finally:
                    browser.close()
        # Two groups of such pages (a batch of the Markdown alone): the one opened has the note
        # and the buttons, the second too (Cambridge's had none, 2026-11-17).
        alone = {**raw, 'status': 'done', 'content': 'markdown', 'done': 2, 'results': {
            'content': 'markdown', 'folder': '/papers', 'started': int(time.time()) - 60, 'main': 0, 'supplements': 0,
            'supplement_failures': [], 'sources': [],
            'failures': [{'cls': 'unsupported', 'reason': '网页只有摘要', 'title': '', 'doi': '10.1130/ges02964.1',
                          'note': 'pubs.geoscienceworld.org · 只读到摘要', 'unverified': True},
                         {'cls': 'unsupported', 'reason': '网站暂不支持转换', 'title': '', 'doi': '10.1017/jfm.2026.12248',
                          'note': 'www.cambridge.org · 没有规则能读出正文', 'unverified': True}]}}
        with sync_playwright() as p:
            browser, page = self.drag_page(p, 'win32')
            try:
                page.evaluate("async state => { testState = state; open = true; await tick(); }", {**view(alone, time.time()), 'lists': True})
                page.wait_for_function("!root.classList.contains('animating')")
                # Both start open (two reasons): the note and the buttons once, under the first.
                self.assertEqual(page.locator('.unverified-note').count(), 1)
                self.assertEqual(page.locator('.grp').first.locator('.unverified-actions .btn').count(), 1)
                # The first closed, the second still open: they move to it.
                page.locator('[data-act=group]').first.click()
                page.wait_for_function("!root.classList.contains('animating')")
                self.assertEqual(page.locator('.paper-list').count(), 1)
                self.assertEqual(page.locator('.unverified-note').count(), 1)
                self.assertEqual(page.locator('.grp').last.locator('.unverified-actions .btn').all_inner_texts(), ['提 issue'])
            finally:
                browser.close()

    def test_the_counts_open_their_lists_of_papers(self):
        """成功, 失败 and 剩余 open the batch's papers: a saved one shows its PDF in its folder,
        a failed or waiting one opens its article page (waiting: 2026-11-11); no line under the title, each group opened on its
        own, the whole list scrolling within half the screen (user, 2026-11-10)."""
        import time
        from patchright.sync_api import sync_playwright
        from paper_search_school.progress_view import paper_lists, view
        raw = dict(status='running', batch_id='b-lists', run_id='r-lists', current='10.1000/5', title='Being fetched',
                   publisher='Karger', journal='Digestion', total=8, done=4, success=3, failed=1, stage='fetching_pdf')
        def paper(index, state, **fields):
            return {'index': index, 'doi': f'10.1000/{index}', 'title': f'Paper {index}', 'journal': 'Nature',
                    'state': state, **fields}
        listed = {'batch_id': 'b-lists', 'folder': '/papers', 'papers': {str(p['index']): p for p in (
            paper(1, 'ok', via='开放下载'), paper(2, 'ok', via='开放下载', detail='出版社 API'), paper(3, 'ok', via='机构下载'),
            paper(4, 'failed', cls='user_side', reason='等学校登录超时'),
            paper(5, 'school', journal='Digestion'), paper(6, 'school'), paper(7, 'open'), paper(8, 'open'))}}
        lists = paper_lists(listed, raw)
        state = {**view(raw, time.time()), 'lists': True}
        for english in (False, True):
            with self.subTest(english=english), sync_playwright() as p:
                browser, page = self.drag_page(p, 'darwin', english=english)
                try:
                    page.evaluate("""({state, lists}) => { window.openedPapers = [];
                        Object.assign(pywebview.api, {paper_lists: async () => lists,
                          show_paper: async (index) => { openedPapers.push(index); return '已打开所在文件夹'; }});
                        testState = state; open = true; }""", {'state': {**state, **({'lang': 'en'} if english else {})},
                                                              'lists': lists})
                    page.evaluate("async lists => { window.firstLists = lists; await tick(); }", lists)
                    page.wait_for_function("!root.classList.contains('animating')")
                    if english:
                        for kind in ('ok', 'failed', 'left'):
                            page.locator(f'[data-act=papers][data-list={kind}]').click()
                            page.wait_for_function("panel === 'papers' && papersList && !root.classList.contains('animating')")
                            page.locator('[data-act=list_group]').last.click()
                            page.wait_for_function("!root.classList.contains('animating')")
                            self.assertIsNone(page.evaluate(r"""() => [root.innerText, ...[...root.querySelectorAll('[title], [aria-label]')]
                                .flatMap(e => [e.title, e.getAttribute('aria-label') || ''])].join('\n').match(/[一-鿿]+/g)"""), kind)
                            page.locator('[data-act=back]').click()
                        continue
                    page.locator('[data-act=papers][data-list=ok]').click()
                    page.wait_for_function("panel === 'papers' && papersList && !root.classList.contains('animating')")
                    self.assertEqual(page.locator('.head .title').inner_text(), '成功 3 篇')
                    self.assertEqual(page.locator('.head .sub').count(), 0)  # no line under the title
                    self.assertEqual(page.locator('.grp .row .reason').all_inner_texts(), ['开放下载（出版社 API 1）', '机构下载'])
                    self.assertEqual(page.locator('.paper-list li').all_inner_texts(),
                                     ['Paper 1\nNature · 开放获取', 'Paper 2\nNature · 出版社 API'])
                    page.locator('.paper-list [data-act=show_paper]').nth(1).click()
                    page.wait_for_function("openedPapers.length === 1")
                    self.assertEqual(page.evaluate('openedPapers'), [2])
                    self.assertIn('已打开所在文件夹', page.locator('#root').inner_text())
                    page.locator('[data-act=list_group][data-group="1"]').click()  # both groups open
                    page.wait_for_function("!root.classList.contains('animating')")
                    self.assertEqual(page.locator('.paper-list li').all_inner_texts(),
                                     ['Paper 1\nNature · 开放获取', 'Paper 2\nNature · 出版社 API', 'Paper 3\nNature'])
                    page.locator('[data-act=list_group][data-group="0"]').click()
                    page.wait_for_function("!root.classList.contains('animating')")
                    self.assertEqual(page.locator('.paper-list li').all_inner_texts(), ['Paper 3\nNature'])
                    # Dozens of papers scroll inside one area of half the screen; the title stays.
                    many = {**lists, 'ok': {'count': 60, 'groups': [{'label': '机构下载', 'count': 60, 'more': 0, 'open': True,
                            'papers': [{'index': i, 'title': f'Paper {i}', 'where': 'Nature', 'doi': ''} for i in range(1, 61)]}]}}
                    page.evaluate("async many => { pywebview.api.paper_lists = async () => many; listOpen = null; await tick(); }", many)
                    page.wait_for_function("!root.classList.contains('animating') && document.querySelectorAll('.paper-list li').length === 60")
                    scroll = page.evaluate("""() => { const s = root.querySelector('.papers-scroll');
                        return {most: parseFloat(s.style.maxHeight), height: s.clientHeight, inner: s.scrollHeight,
                                half: Math.max(240, Math.round(screen.availHeight / 2) - 64), lists: root.querySelectorAll('.paper-list').length}; }""")
                    self.assertEqual(scroll['most'], scroll['half'])
                    self.assertLessEqual(scroll['height'], scroll['half'])
                    self.assertGreater(scroll['inner'], scroll['height'])
                    page.evaluate("pywebview.api.paper_lists = async () => window.firstLists")
                    page.locator('[data-act=back]').click()
                    page.wait_for_function("panel === '' && !root.classList.contains('animating')")
                    self.assertEqual(page.locator('.stats [data-act=papers]').count(), 3)

                    page.locator('[data-act=papers][data-list=failed]').click()
                    page.wait_for_function("panel === 'papers' && papersList && !root.classList.contains('animating')")
                    self.assertEqual(page.locator('.head .title').inner_text(), '失败 1 篇')
                    self.assertEqual(page.locator('.grp .row').inner_text().split('\n')[:2], ['你这边', '等学校登录超时'])
                    page.locator('.paper-list [data-act=open_article]').click()
                    page.wait_for_function("openedArticles.length === 1")
                    self.assertEqual(page.evaluate('openedArticles'), ['10.1000/4'])
                    page.keyboard.press('Escape')
                    page.wait_for_function("panel === ''")

                    page.locator('[data-act=papers][data-list=left]').click()
                    page.wait_for_function("panel === 'papers' && papersList && !root.classList.contains('animating')")
                    self.assertEqual(page.locator('.head .title').inner_text(), '剩余 4 篇')
                    self.assertEqual(page.locator('.grp .row .reason').all_inner_texts(),
                                     ['正在下载', '排队等机构下载', '开放下载还没查'])
                    self.assertEqual(page.locator('.paper-list li').all_inner_texts(), ['Paper 5\nDigestion · 机构下载'])
                    page.locator('[data-act=list_group][data-group="2"]').click()  # a paper open download has not checked yet
                    page.wait_for_function("!root.classList.contains('animating')")
                    page.locator('.paper-list [data-act=open_article]').last.click()
                    page.wait_for_function("openedArticles.length === 2")
                    self.assertEqual(page.evaluate('openedArticles'), ['10.1000/4', '10.1000/8'])
                    # Without the batch's papers the counts stay plain numbers.
                    page.evaluate("async s => { panel = ''; testState = s; await tick(); }", {**state, 'lists': False})
                    page.wait_for_function("!root.classList.contains('animating')")
                    self.assertEqual(page.locator('.stats [data-act=papers]').count(), 0)
                finally:
                    browser.close()

    def test_the_failed_list_also_shows_saved_papers_missing_supplementary_files(self):
        """While the batch runs, 失败 lists the papers without their main text, then those
        saved without every supplementary file under their own heading (user, 2026-11-11)."""
        import time
        from patchright.sync_api import sync_playwright
        from paper_search_school.progress_view import paper_lists, view
        raw = dict(status='running', batch_id='b-supp', run_id='r-supp', current='10.1000/9', title='Being fetched',
                   publisher='Elsevier', journal='Obesity', total=5, done=4, success=3, failed=1, stage='fetching_pdf',
                   content='both')
        def paper(index, state, **fields):
            return {'index': index, 'doi': f'10.1000/{index}', 'title': f'Paper {index}', 'journal': 'Nature',
                    'state': state, **fields}
        listed = {'batch_id': 'b-supp', 'folder': '/papers', 'papers': {str(p['index']): p for p in (
            paper(1, 'failed', cls='publisher_or_network', reason='出版社页面出错'),
            paper(2, 'ok', via='机构下载', supplement_cls='publisher_or_network', supplement_reason='网站人机验证拦截'),
            paper(3, 'ok', via='机构下载', supplement_cls='publisher_or_network', supplement_reason='网站人机验证拦截'),
            paper(4, 'ok', via='机构下载'), paper(5, 'school'))}}
        lists = paper_lists(listed, raw)
        state = {**view(raw, time.time()), 'lists': True}
        for english in (False, True):
            with self.subTest(english=english), sync_playwright() as p:
                browser, page = self.drag_page(p, 'darwin', english=english)
                try:
                    page.evaluate("""({state, lists}) => { Object.assign(pywebview.api, {paper_lists: async () => lists});
                        testState = state; open = true; }""", {'state': {**state, **({'lang': 'en'} if english else {})},
                                                              'lists': lists})
                    page.evaluate("() => tick()")
                    page.wait_for_function("!root.classList.contains('animating')")
                    page.locator('[data-act=papers][data-list=failed]').click()
                    page.wait_for_function("panel === 'papers' && papersList && !root.classList.contains('animating')")
                    if english:
                        page.locator('[data-act=list_group]').last.click()
                        page.wait_for_function("!root.classList.contains('animating')")
                        self.assertIsNone(page.evaluate(r"""() => [root.innerText, ...[...root.querySelectorAll('[title], [aria-label]')]
                            .flatMap(e => [e.title, e.getAttribute('aria-label') || ''])].join('\n').match(/[一-鿿]+/g)"""))
                        continue
                    self.assertEqual(page.locator('.head .title').inner_text(), '失败 1 篇')
                    # Each part under its own heading: the PDF not got, then the saved ones missing files
                    # ("未完成" beside "Markdown 未生成" did not say it was the PDF, 2026-11-17).
                    order = page.evaluate("""() => [...root.querySelectorAll('.papers-scroll > *')].map(e =>
                        e.classList.contains('list-sub') ? 'heading' : e.querySelector('.reason').textContent)""")
                    self.assertEqual(order, ['heading', '出版社页面出错', 'heading', '网站人机验证拦截'])
                    self.assertEqual(page.locator('.list-sub').all_inner_texts(), ['PDF 未下到 1 篇', '补充材料未下全 2 篇'])
                    page.locator('[data-act=list_group][data-group="1"]').click()
                    page.wait_for_function("!root.classList.contains('animating')")
                    page.locator('.grp').nth(1).locator('[data-act=open_article]').first.click()
                    page.wait_for_function("openedArticles.length === 1")
                    self.assertEqual(page.evaluate('openedArticles'), ['10.1000/2'])
                finally:
                    browser.close()

    def test_a_contact_email_says_what_it_is_for_and_is_tested_like_a_key(self):
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = self.drag_page(p, 'darwin')
            try:
                page.evaluate("""() => { window.signups = [];
                    const email = {id:'unpaywall', name:'Unpaywall', use:'下载时找免费全文', url:'https://unpaywall.org/products/api',
                        note:'填你常用的邮箱就行，不用注册', signup_label:'说明', guide:'', guide_label:'', set:false, masked:'',
                        keys:[{key:'PAPER_SEARCH_UNPAYWALL_EMAIL', label:'email', kind:'email', set:false, masked:''}]};
                    const key = {id:'easyscholar', name:'EasyScholar', use:'', url:'https://example.org/e', signup_label:'', guide:'',
                        guide_label:'', set:false, masked:'', keys:[{key:'EASYSCHOLAR_KEY', label:'API key', kind:'key', set:false, masked:''}]};
                    Object.assign(pywebview.api, {
                        api_keys: async () => ({ok:true, filled:0, total:2, groups:[{title:'查期刊、搜正文、找免费全文（推荐配置）', services:[key, email]}]}),
                        api_key_values: async () => ({ok:true, values:{}}),
                        open_signup: async (id, guide) => { signups.push([id, !!guide]); return {ok:true}; },
                        test_api_key: async (id, values) => ({status: 'valid', message: '可以用：Unpaywall 接受这个邮箱'})});
                }""")
                page.mouse.move(50, 25)
                page.wait_for_function('open')
                page.locator('[data-act=settings]').click()
                page.locator('[data-page=keys]').click()
                page.locator('[data-service=unpaywall]').click()
                email = page.get_by_label('Unpaywall email')
                self.assertEqual((email.get_attribute('placeholder'), email.get_attribute('type')), ('填你常用的邮箱', 'text'))
                self.assertEqual(page.locator('.key-note').inner_text(), '填你常用的邮箱就行，不用注册')
                self.assertEqual(page.locator('[data-act=signup]').inner_text(), '说明')
                self.assertEqual(page.locator('[data-act=reveal]').count(), 0)  # an email is not hidden
                email.fill('me@lab.example.org')
                page.locator('[data-act=test_key]').click()
                page.wait_for_function("document.querySelector('#key-error').textContent === '可以用：Unpaywall 接受这个邮箱'")
                page.locator('[data-act=signup]').click()
                page.wait_for_function("signups.length === 1")
                self.assertEqual(page.evaluate('signups'), [['unpaywall', False]])
                page.locator('[data-act=cancel_key]').click()
                page.locator('[data-service=easyscholar]').click()
                self.assertEqual(page.get_by_label('EasyScholar API key').get_attribute('placeholder'), '粘贴 key')
                self.assertEqual(page.locator('[data-act=signup]').inner_text(), '去申请')
                self.assertEqual(page.locator('[data-act=test_key]').count(), 1)
                self.assertEqual(page.locator('[data-act=reveal]').count(), 1)
                self.assertEqual(page.locator('.key-note').count(), 0)
            finally:
                browser.close()

    def test_the_api_key_list_scrolls_within_half_the_screen_and_keeps_its_place(self):
        """Twelve services no longer stretch the window: the list scrolls under its title,
        an opened one's editor comes into view and the list stays put (user, 2026-11-11)."""
        from patchright.sync_api import sync_playwright
        from paper_search_school import api_keys
        listing = {'ok': True, 'filled': 0, 'total': 12, 'groups': [
            {'title': g['title'], 'services': [{**s, 'guide': s.get('guide', ''), 'guide_label': s.get('guide_label', ''),
             'signup_label': s.get('signup_label', ''), 'set': False, 'masked': '',
             'keys': [{**k, 'kind': k.get('kind', 'key'), 'set': False, 'masked': ''} for k in s['keys']]}
             for s in g['services']]} for g in api_keys.groups()]}
        last = listing['groups'][-1]['services'][-1]['id']
        with sync_playwright() as p:
            browser, page = self.drag_page(p, 'darwin')
            try:
                page.evaluate("""listing => Object.assign(pywebview.api, {api_keys: async () => listing,
                    api_key_values: async () => ({ok: true, values: {}})})""", listing)
                page.mouse.move(50, 25)
                page.wait_for_function('open')
                page.locator('[data-act=settings]').click()
                page.locator('[data-page=keys]').click()
                page.wait_for_function("settingsPage === 'keys' && !root.classList.contains('animating')")
                box = page.evaluate("""() => { const s = root.querySelector('.keys-scroll');
                    return {most: parseFloat(s.style.maxHeight), height: s.clientHeight, inner: s.scrollHeight,
                            half: Math.max(240, Math.round(screen.availHeight / 2) - 64),
                            title: root.querySelector('.head .title').getBoundingClientRect().top}; }""")
                self.assertEqual(box['most'], box['half'])
                self.assertLessEqual(box['height'], box['half'])
                self.assertGreater(box['inner'], box['height'])
                self.assertEqual(page.locator('.keys-scroll [data-act=edit_key]').count(), 12)
                # The last one, opened from the bottom of the list: its editor in view, the title in place.
                page.evaluate("() => { const s = root.querySelector('.keys-scroll'); s.scrollTop = s.scrollHeight; }")
                page.locator(f'[data-service={last}]').click()
                page.wait_for_function("!root.classList.contains('animating') && document.querySelector('.key-edit')")
                seen = page.evaluate("""() => { const s = root.querySelector('.keys-scroll').getBoundingClientRect();
                    const e = root.querySelector('.key-actions').getBoundingClientRect();
                    return {inside: e.top >= s.top - 1 && e.bottom <= s.bottom + 1, top: root.querySelector('.keys-scroll').scrollTop,
                            title: root.querySelector('.head .title').getBoundingClientRect().top}; }""")
                self.assertTrue(seen['inside'])
                self.assertGreater(seen['top'], 0)
                self.assertEqual(seen['title'], box['title'])
                page.locator('[data-act=cancel_key]').click()
                page.wait_for_function("!document.querySelector('.key-edit')")
                self.assertGreater(page.evaluate("root.querySelector('.keys-scroll').scrollTop"), 0)
                # Another page starts at its top.
                page.locator('[data-act=back]').click()
                page.locator('[data-page=keys]').click()
                page.wait_for_function("settingsPage === 'keys' && !root.classList.contains('animating')")
                self.assertEqual(page.evaluate("root.querySelector('.keys-scroll').scrollTop"), 0)
            finally:
                browser.close()

    def test_the_notification_switch_checks_the_system_and_sends_a_test(self):
        """Under the switch: a test notification, and what to change when the system keeps
        them from showing or the user did not see one (user, 2026-11-10)."""
        from patchright.sync_api import sync_playwright
        for platform, english in (('darwin', False), ('win32', False), ('darwin', True)):
            with self.subTest(platform=platform, english=english), sync_playwright() as p:
                browser, page = self.drag_page(p, platform, english=english)
                try:
                    page.evaluate("""english => { window.settingsOpened = 0; window.check = 'off'; window.testResult = {state: 'sent'};
                        Object.assign(pywebview.api, {
                          settings: async () => ({notify: false, download_dir: '/papers', language: english ? 'en' : 'zh', fields: [
                            {name: 'login', label: '学校登录页最多等', unit: '秒', value: 180, default: 180, page: 'wait'}]}),
                          set_notifications: async (on) => ({ok: true, notify: on}),
                          check_notifications: async () => ({state: check}),
                          test_notification: async () => testResult,
                          open_notification_settings: async () => { settingsOpened += 1; return true; }});
                        if (english) testState = {...testState, lang: 'en'}; }""", english)
                    page.evaluate("async () => { await tick(); await openSettings({page: 'wait'}); }")
                    page.wait_for_selector('[data-act=notify]')
                    self.assertEqual(page.locator('[data-act=test_notify]').count(), 0)  # switch off: nothing to test
                    page.locator('input').first.fill('200')  # typed, not saved: kept through the checks below
                    page.locator('[data-act=notify]').click()
                    page.wait_for_selector('.nbox')
                    box = page.locator('.nbox').inner_text()
                    if english:
                        self.assertIn("macOS blocks PaperSearch's notifications", box)
                    elif platform == 'darwin':
                        self.assertIn('macOS 没有允许 PaperSearch 发通知', box)
                        self.assertIn('系统设置 › 通知 › PaperSearch', box)
                    else:
                        self.assertIn('Windows 关掉了 PaperSearch 的通知', box)
                        self.assertIn('Windows PowerShell', box)
                    page.locator('.nbox [data-act=notify_settings]').click()
                    page.wait_for_function("settingsOpened === 1")
                    page.locator('[data-act=test_notify]').click()
                    page.wait_for_selector('.nnote.ok')
                    self.assertEqual(page.locator('.nbox').count(), 0)
                    sent = page.locator('.nnote.ok').inner_text()
                    self.assertEqual(sent, '✓ Sent; see the top right' if english
                                     else '✓ 已发出，右上角应弹出一条通知' if platform == 'darwin' else '✓ 已发出，右下角应弹出一条通知')
                    page.locator('[data-act=notify_unseen]').click()
                    page.wait_for_selector('.nbox ol')
                    self.assertEqual(page.locator('.nbox li').count(), 3)
                    if english:
                        self.assertIsNone(page.evaluate("root.innerText.replace('中文', '').match(/[一-鿿]+/g)"))
                    page.evaluate("testResult = {state: 'failed', message: '测试通知没有发出：RuntimeError'}")
                    page.locator('[data-act=test_notify]').click()
                    page.wait_for_selector('.nnote.bad')
                    self.assertEqual(page.locator('input').first.input_value(), '200')
                    # Off again: the test goes with the switch; on with nothing wrong: no box.
                    page.locator('[data-act=notify]').click()
                    page.wait_for_function("!document.querySelector('[data-act=test_notify]')")
                    page.evaluate("check = 'ok'")
                    page.locator('[data-act=notify]').click()
                    page.wait_for_selector('[data-act=test_notify]')
                    self.assertEqual(page.locator('.nbox').count(), 0)
                finally:
                    browser.close()

    def test_the_pro_page_counts_lists_the_sites_and_checks_for_updates(self):
        """The Markdown page drawn on 2026-11-19 (user): what a Markdown keeps, the Markdown saved on
        this computer, the sites with rules (opened in place), whether Pro is free, and 检查更新,
        whose newer version is installed with 更新到; in English too."""
        from patchright.sync_api import sync_playwright
        for english in (False, True):
            with self.subTest(english=english), sync_playwright() as p:
                browser, page = self.drag_page(p, 'darwin', english=english)
                try:
                    page.evaluate("""english => { window.checks = []; window.installs = 0; window.installing = false;
                        window.pro = {ok: true, installed: true, version: '0.1.1', converted: 1437, complete: 1380,
                                      sites: ['Science', 'NEJM', 'PNAS', 'Sage', 'Neurology', 'Wiley', 'BMJ'],
                                      access: {mode: 'free', until: '2027-03-01'}};
                        Object.assign(pywebview.api, {
                          settings: async () => ({notify: true, download_dir: '/papers', language: english ? 'en' : 'zh', fields: []}),
                          api_keys: async () => ({ok: true, filled: 0, total: 0, groups: []}),
                          pro_status: async () => pro,
                          check_pro: async () => ({state: 'running'}),
                          pro_check_state: async () => checks.length > 1 ? checks.shift() : (checks[0] || {state: 'running'}),
                          install_pro: async () => { installs++; installing = true; return {state: 'running', done: 0, total: 0}; },
                          pro_install_state: async () => (installing ? {state: 'running', done: 0, total: 0} : {state: 'idle'})});
                        if (english) testState = {...testState, lang: 'en'}; }""", english)
                    page.evaluate("async () => { testState = {...testState, mode: 'idle'}; await tick(); await act('settings'); }")
                    # Pro installed: its features on the home page (user, 2026-11-19: 铺开).
                    page.wait_for_selector('.pro-group')
                    self.assertIn('Beta' if english else '测试版', page.locator('.pro-group').inner_text())
                    self.assertIn('1,437 converted · 7 platforms' if english else '已转换 1,437 篇 · 7 个平台',
                                  page.locator('[data-page=markdown]').inner_text())
                    page.locator('[data-page=markdown]').click()
                    page.wait_for_selector('.pro-stats')
                    stats = page.locator('.pro-stats').inner_text()
                    for said in ('1,437', '96%', '7'):
                        self.assertIn(said, stats)
                    self.assertEqual(page.locator('.pro-chip').count(), 4)
                    sites = page.locator('[data-act=pro_sites]')
                    # Platforms, each with its publisher's journals (user, 2026-11-19).
                    self.assertIn('7, with all their journals' if english else '共 7 个，平台下的期刊都适用', sites.inner_text())
                    self.assertIn('Publisher platforms' if english else '出版社平台', stats)
                    self.assertEqual(page.locator('.pro-sites').count(), 0)
                    sites.click()
                    page.wait_for_selector('.pro-sites')
                    self.assertIn('BMJ', page.locator('.pro-sites').inner_text())
                    # In groups, each site once, the multidisciplinary platforms first (user, 2026-11-20).
                    groups = page.locator('.site-group').all_inner_texts()
                    self.assertEqual(groups, ['Multi-subject platforms · 2', 'General journals · 2', 'Medicine · 3']
                                     if english else ['多学科出版平台 · 2', '综合期刊 · 2', '医学 · 3'])
                    self.assertEqual(page.locator('.site-chip').count(), 7)
                    # Back on the home page; 版本与更新 says whether Pro is free and until when (user, 2026-11-19).
                    page.locator('[data-act=back]').click()
                    page.wait_for_selector('.pro-group')
                    free = 'Free while in testing, until 2027-03-01' if english else '测试期间免费，至 2027-03-01'
                    self.assertIn(free, page.locator('[data-page=pro]').inner_text())
                    page.locator('[data-page=pro]').click()
                    page.wait_for_selector('[data-act=check_pro]')
                    self.assertIn(free, page.locator('.pro-row.static').inner_text())
                    self.assertEqual(page.locator('[data-page=markdown]').count(), 0)  # on the home page instead
                    # 检查更新: checking, then a newer version and 更新到 it.
                    page.locator('[data-act=check_pro]').click()
                    page.wait_for_function("document.querySelector('.pro-state')?.textContent.includes("
                                           + ("'Checking'" if english else "'正在检查更新'") + ")")
                    self.assertEqual(page.locator('[data-act=check_pro]').count(), 0)
                    page.evaluate("() => { checks = [{state: 'done', latest: '0.1.2', update: true}]; }")
                    page.wait_for_selector('[data-act=install_pro]')
                    if english:
                        self.assertIn('Version 0.1.2 available', page.locator('.pro-state').inner_text())
                        self.assertEqual(page.locator('[data-act=install_pro]').inner_text(), 'Update to 0.1.2')
                        self.assertIsNone(page.evaluate("root.innerText.replace('中文', '').match(/[一-鿿]+/g)"))
                    else:
                        self.assertEqual(page.locator('.pro-state').inner_text(), '已安装 · 0.1.1 · 有新版本 0.1.2')
                        self.assertEqual(page.locator('[data-act=install_pro]').inner_text(), '更新到 0.1.2')
                    page.locator('[data-act=install_pro]').click()
                    page.wait_for_function('installs === 1')
                    # Up to date: said so, no button.
                    page.evaluate("async () => { proInstall = {state: 'idle'}; proCheck = {state: 'done', latest: '0.1.1', update: false}; render(true); }")
                    self.assertIn('Up to date' if english else '已是最新', page.locator('.pro-state').inner_text())
                    self.assertEqual(page.locator('[data-act=install_pro]').count(), 0)
                finally:
                    browser.close()

    def test_the_small_switch_beside_the_hourly_limit_says_what_it_does(self):
        """马上生效 (user, 2026-11-19): a small switch in the hourly limit's row, off by default,
        saved at once; its note, two lines of the same length, shows on hover."""
        from patchright.sync_api import sync_playwright
        for english in (False, True):
            with self.subTest(english=english), sync_playwright() as p:
                browser, page = self.drag_page(p, 'darwin', english=english)
                try:
                    page.evaluate("""english => { window.saved = [];
                        Object.assign(pywebview.api, {
                          settings: async () => ({notify: false, hourly_now: false, download_dir: '/papers', language: english ? 'en' : 'zh',
                            fields: [{name: 'hourly', label: '每家出版社每小时最多', unit: '篇', value: 500, default: 100, page: 'download'}]}),
                          set_hourly_now: async (on) => { saved.push(on); return {ok: true, hourly_now: on}; }});
                        if (english) testState = {...testState, lang: 'en'}; }""", english)
                    page.evaluate("async () => { await tick(); await openSettings({page: 'download'}); }")
                    switch = page.locator('[data-act=hourly_now]')
                    switch.wait_for()
                    # In the limit's own row, after its unit; off.
                    self.assertEqual(page.evaluate("document.querySelector('[data-act=hourly_now]').closest('.row')"
                                                   " === document.querySelector('input[data-field=hourly]').closest('.row')"), True)
                    self.assertEqual(switch.get_attribute('aria-checked'), 'false')
                    self.assertFalse(page.locator('.mini-tip').is_visible())
                    page.locator('input[data-field=hourly]').fill('600')  # typed, not saved: kept through the switch
                    # The page in its language and settled: a render after the switch of language puts
                    # new elements under a pointer that has not moved, which takes no hover.
                    page.wait_for_function("lang === (english ? 'en' : 'zh')".replace("english", "true" if english else "false"))
                    page.wait_for_timeout(600)
                    switch.hover()
                    page.wait_for_selector('.mini-tip', state='visible')
                    lines = page.locator('.mini-tip div').all_inner_texts()
                    if english:
                        self.assertEqual(page.locator('.mini-tip b').inner_text(), 'Apply now')
                        self.assertIsNone(page.evaluate("document.querySelector('.mini-tip').innerText.match(/[一-鿿]+/g)"))
                    else:
                        self.assertEqual(lines, ['开立即按新上限继续下载', '关这一小时过后按新上限'])
                        self.assertEqual(len(lines[0]), len(lines[1]))
                    # Inside the window: not cut off on the right.
                    self.assertTrue(page.evaluate("document.querySelector('.mini-tip').getBoundingClientRect().right"
                                                  " <= root.getBoundingClientRect().right"))
                    switch.click()
                    page.wait_for_function("saved.length === 1")
                    self.assertEqual(page.evaluate("saved"), [True])
                    self.assertEqual(switch.get_attribute('aria-checked'), 'true')
                    self.assertEqual(page.locator('input[data-field=hourly]').input_value(), '600')
                finally:
                    browser.close()

    def test_api_keys_page_and_the_download_behind_the_settings(self):
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = self.drag_page(p, 'darwin')
            try:
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.evaluate("""() => {
                    const service = (id, name, set, keys) => ({id, name, use:'', url:'https://example.org/'+id, set,
                        guide: id === 'semantic' ? 'https://example.org/guide' : '', guide_label: '申请教程',
                        masked: set ? '••••9f3c' : '', keys: keys || [{key:id.toUpperCase()+'_KEY', label:'API key', set, masked: set ? '••••9f3c' : ''}]});
                    window.listing = (scholarSet) => ({ok:true, filled: scholarSet ? 2 : 1, total: 3, groups:[
                        {title:'查期刊、搜正文', services:[service('easyscholar','EasyScholar',true), service('semantic','Semantic Scholar',scholarSet)]},
                        {title:'出版社接口', services:[service('elsevier','Elsevier',false)]}]});
                    window.keySaves=[]; window.signups=[]; window.nextSave={ok:false, error:'key 里不能有空格、换行或中文字符'}; window.closeRequests=0;
                    Object.assign(pywebview.api, {
                        api_keys: async()=>listing(false),
                        save_api_key: async(id, values)=>{keySaves.push([id, values]); return nextSave},
                        clear_api_key: async()=>listing(false),
                        test_api_key: async(id, values)=>({status: values.EASYSCHOLAR_KEY ? 'valid' : 'missing',
                            message: values.EASYSCHOLAR_KEY ? '可以用' : '没有填'}),
                        api_key_values: async(id)=>({ok:true, values: id === 'easyscholar' ? {EASYSCHOLAR_KEY:'sk-abc-9f3c'} : {}}),
                        open_signup: async(id, guide)=>{signups.push([id, !!guide]); return {ok:false, message:'打开失败：没有找到默认浏览器'}},
                        request_close: async()=>{closeRequests++},
                    });
                }""")
                page.mouse.move(50, 25)
                page.wait_for_function('open')
                page.locator('[data-act=settings]').click()
                self.assertIn('已填 1/3', page.locator('[data-page=keys]').inner_text())
                self.assertIn('正在下载 0/3', page.locator('#task-strip').inner_text())
                page.locator('[data-page=keys]').click()
                self.assertEqual(page.locator('.key-group').all_inner_texts(), ['查期刊、搜正文', '出版社接口'])
                page.locator('[data-service=easyscholar]').click()  # a saved key is in its field, hidden
                saved = page.get_by_label('EasyScholar API key')
                self.assertEqual((saved.input_value(), saved.get_attribute('type')), ('sk-abc-9f3c', 'password'))
                page.locator('[data-act=reveal]').click()
                self.assertEqual(saved.get_attribute('type'), 'text')
                page.locator('[data-act=test_key]').click()  # tests what the field holds
                page.wait_for_function("document.querySelector('#key-error').textContent === '可以用'")
                self.assertEqual(page.locator('#key-error').get_attribute('class'), 'err ok')
                page.locator('[data-act=cancel_key]').click()
                page.locator('[data-service=elsevier]').click()
                self.assertEqual(page.locator('.key-edit input').count(), 1)
                page.locator('[data-act=cancel_key]').click()
                page.locator('[data-service=semantic]').click()
                key = page.get_by_label('Semantic Scholar API key')
                self.assertEqual(key.get_attribute('type'), 'password')
                key.fill('bad key')
                page.locator('[data-act=reveal]').click()
                self.assertEqual(key.get_attribute('type'), 'text')
                # The download moves on behind the settings: only its line changes.
                page.evaluate("async () => { testState.done = 1; await tick(); }")
                page.wait_for_function("document.querySelector('#task-strip').innerText.includes('1/3')")
                self.assertEqual(key.input_value(), 'bad key')
                page.locator('[data-act=save_key]').click()
                page.wait_for_function("document.querySelector('#key-error').textContent.includes('空格')")
                self.assertEqual(key.input_value(), 'bad key')
                page.locator('[data-act=signup]').click()
                page.wait_for_function("document.querySelector('#key-error').textContent.includes('打开失败')")
                page.locator('[data-act=guide]').click()
                page.wait_for_function("signups.length === 2")
                self.assertEqual(page.evaluate('signups'), [['semantic', False], ['semantic', True]])
                page.evaluate("nextSave = listing(true)")
                key.fill('sk-good-9f3c')
                key.press('Enter')
                page.wait_for_function("!document.querySelector('.key-edit')")
                self.assertEqual(page.evaluate('keySaves.at(-1)'), ['semantic', {'SEMANTIC_KEY': 'sk-good-9f3c'}])
                self.assertIn('••••9f3c', page.locator('[data-service=semantic]').inner_text())
                page.keyboard.press('Escape')  # back to the settings home
                self.assertIn('已填 2/3', page.locator('[data-page=keys]').inner_text())
                page.locator('#task-strip .strip').click()  # back to the download
                page.wait_for_function("panel === '' && root.innerText.includes('Drag test article')")
                self.assertEqual(page.evaluate('closeRequests'), 0)
                self.assertEqual(errors, [])
            finally:
                browser.close()

    def test_a_window_started_for_the_settings_closes_with_them(self):
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = self.drag_page(p, 'win32')
            try:
                page.evaluate("""() => {
                    window.closeRequests = 0;
                    window.pendingRequest = {page:'keys', service:'easyscholar', new_window:true};
                    testState = {mode:'idle'};
                    Object.assign(pywebview.api, {
                        state: async()=>{const s = pendingRequest ? {...testState, open_settings: pendingRequest} : testState;
                                         pendingRequest = null; return s},
                        api_keys: async()=>({ok:true, filled:0, total:1, groups:[{title:'查期刊、搜正文', services:[
                            {id:'easyscholar', name:'EasyScholar', use:'影响因子和分区', url:'', set:false, masked:'',
                             keys:[{key:'EASYSCHOLAR_KEY', label:'API key', set:false, masked:''}]}]}]}),
                        request_close: async()=>{closeRequests++},
                    });
                }""")
                page.wait_for_selector('.key-edit input')
                self.assertTrue(page.evaluate('settingsOnly'))
                self.assertEqual(page.locator('.settings [aria-label=关闭]').count(), 1)  # closes from any page
                page.keyboard.press('Escape')  # stop editing
                page.keyboard.press('Escape')  # the settings home, with a close button
                self.assertEqual(page.locator('.settings [aria-label=关闭]').count(), 1)
                page.keyboard.press('Escape')
                page.wait_for_function('closeRequests === 1')
            finally:
                browser.close()

    def test_the_markdown_page_installs_pro_and_opens_an_issue(self):
        # PaperSearch Pro's page (user, 2026-11-18): in testing; 安装 when it is not here, its
        # progress, 重试 after a failed one; report an issue. Nothing of subscriptions or buying;
        # free while in testing, as the page drawn on 2026-11-19 says (the user's).
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = self.drag_page(p, 'darwin')
            try:
                page.evaluate("""() => {
                    window.issues = 0; window.installs = 0; window.pro = {ok:true, installed:true, version:'0.1.0'};
                    window.installing = [];
                    Object.assign(pywebview.api, {
                        settings: async () => ({notify: true, download_dir: '/papers', language: 'zh', fields: []}),
                        api_keys: async () => ({ok:true, filled:0, total:0, groups:[]}),
                        pro_status: async () => pro, open_issue: async () => { issues++; return {ok:true}; },
                        install_pro: async () => { installs++; return {state: 'running', done: 0, total: 0}; },
                        pro_install_state: async () => installing.length > 1 ? installing.shift() : (installing[0] || {state: 'idle'})});
                }""")
                page.evaluate("async () => { testState = {mode: 'idle'}; await tick(); await act('settings'); }")
                row = page.locator('[data-page=markdown]')
                row.wait_for()
                self.assertIn('Markdown 全文', row.inner_text())
                self.assertEqual(page.locator('.pro-group').inner_text(), 'PaperSearch Pro · 测试版')
                self.assertIn('学校自动登录', page.locator('[data-page=login]').inner_text())
                self.assertIn('0.1.0 · 测试期间免费，截止日期待定', page.locator('[data-page=pro]').inner_text())
                row.click()
                page.wait_for_selector('.pro-stats')
                text = page.locator('.settings').inner_text()
                for said in ('以下内容一并保留', '图片', '表格', '公式', '参考文献', '已转换（篇）', '完整无缺', '转换有缺漏、出错，或想加出版社？'):
                    self.assertIn(said, text)
                page.locator('[data-act=pro_issue]').click()
                page.wait_for_function('issues === 1')
                page.evaluate("async () => { await act('back'); await act('settings_page', {dataset: {page: 'pro'}}); }")
                page.wait_for_selector('.pro-head')
                text = page.locator('.settings').inner_text()
                for said in ('版本与更新', 'PaperSearch Pro', '测试版', '已安装 · 0.1.0', '使用状态', '测试期间免费，截止日期待定', '用着有问题？'):
                    self.assertIn(said, text)
                self.assertIn('ok', page.locator('.pro-state').get_attribute('class'))
                self.assertEqual(page.locator('[data-act=install_pro]').count(), 0)
                for word in ('订阅', 'key', '购买'):
                    self.assertNotIn(word, text)
                page.locator('[data-act=pro_issue]').click()
                page.wait_for_function('issues === 2')

                # Not installed: one row on the home page; Pro's page has 安装 and what it brings.
                page.evaluate("async () => { pro = {ok:true, installed:false, version:''}; await act('back'); await loadSettings(); render(true); }")
                self.assertEqual(page.locator('[data-page=markdown]').count() + page.locator('.pro-group').count(), 0)
                self.assertIn('未安装', page.locator('[data-page=pro]').inner_text())
                page.locator('[data-page=pro]').click()
                page.wait_for_selector('[data-act=install_pro]')
                self.assertEqual(page.locator('.pro-state').inner_text(), '未安装')
                self.assertEqual(page.locator('[data-act=install_pro]').inner_text(), '安装')
                self.assertEqual(page.locator('.pro-hint').inner_text(), '约 4 MB · PDF 和补充材料不需要它')
                self.assertIn('把论文全文转成 Markdown', page.locator('[data-page=markdown]').inner_text())
                self.assertIn('学校自动登录', page.locator('[data-page=login]').inner_text())
                # Not installed: nothing counted or listed yet, and nothing to check.
                self.assertEqual(page.locator('.pro-stats').count() + page.locator('[data-act=check_pro]').count(), 0)

                # 安装: its progress, in place; then installed.
                page.evaluate("() => { installing = [{state:'running', done: 1258291, total: 2306867}]; }")
                page.locator('[data-act=install_pro]').click()
                page.wait_for_function("document.querySelector('#pro-progress')?.textContent === '正在下载 1.2 / 2.2 MB'")
                self.assertEqual(page.evaluate('installs'), 1)
                self.assertEqual(page.locator('.pro-state').inner_text(), '正在安装…')
                self.assertEqual(page.locator('[data-act=install_pro]').count(), 0)
                width = page.evaluate("parseFloat(document.querySelector('.pro-bar span').style.width)")
                self.assertAlmostEqual(width, 54.5, delta=0.2)
                page.evaluate("() => { pro = {ok:true, installed:true, version:'0.1.0'}; installing = [{state:'done', version:'0.1.0'}]; }")
                page.wait_for_function("document.querySelector('.pro-state')?.textContent === '已安装 · 0.1.0'")
                self.assertEqual(page.locator('.pro-bar').count(), 0)

                # A failed one: why, and 重试.
                page.evaluate("""async () => { pro = {ok:true, installed:false, version:''}; installing = [{state:'running', done: 0, total: 0}];
                                  await loadSettings(); render(true); }""")
                page.wait_for_selector('#pro-progress')
                self.assertEqual(page.locator('#pro-progress').inner_text(), '正在下载…')
                page.evaluate("() => { installing = [{state:'failed', message:'网络连接中断'}]; }")
                page.wait_for_selector('[data-act=install_pro]')
                self.assertEqual(page.locator('.pro-state').inner_text(), '安装没有完成：网络连接中断')
                self.assertIn('bad', page.locator('.pro-state').get_attribute('class'))
                self.assertEqual(page.locator('[data-act=install_pro]').inner_text(), '重试')
                self.assertEqual(page.locator('.pro-hint').inner_text(), '已下载的部分不会留下')
            finally:
                browser.close()

    def test_the_sign_in_page_says_what_saving_did_and_shows_the_password_on_asking(self):
        # PaperSearch Pro's school sign-in (user, 2026-11-19): 保存 said nothing; the password may be seen.
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = self.drag_page(p, 'darwin')
            try:
                page.evaluate("""() => {
                    window.saved = null;
                    const one = () => ({key: 'https://idp.hongmulan.example/idp', name: '红木兰大学', name_en: '', current: true, entity: true,
                                        saved: !!saved, username: saved ? '2******4' : '', enabled: true, off: '', status: 'trial'});
                    const state = () => ({ok: true, pro: true, schools: [one()], counts: {filled: 461, check: 287}, ...one(),
                                          school: '红木兰大学'});
                    Object.assign(pywebview.api, {
                        settings: async () => ({notify: true, download_dir: '/papers', language: 'zh', fields: []}),
                        api_keys: async () => ({ok:true, filled:0, total:0, groups:[]}),
                        pro_status: async () => ({ok: true, installed: true, version: '0.1.0'}),
                        pro_install_state: async () => ({state: 'idle'}),
                        school_login_state: async () => state(),
                        school_login_saved: async () => (saved || {}),
                        save_school_login: async (username, password, enabled, key) => { saved = {username, password, key}; return state(); }});
                }""")
                page.evaluate("async () => { testState = {mode: 'idle'}; await tick(); await act('settings'); }")
                page.locator('[data-page=login]').click()
                page.wait_for_selector('#login-user')  # the default school open first
                self.assertEqual(page.locator('#login-error').inner_text(), '')
                self.assertEqual(page.locator('.key-note').count(), 0)  # no line of numbers (user, 2026-11-20)
                self.assertEqual(page.locator('[data-page=login_schools]').inner_text(), '支持哪些学校')
                page.fill('#login-user', '20261234')
                page.fill('#login-password', 'Mulan-pw-2026')
                # A click elsewhere draws the page again: what was typed stays (user, 2026-11-20).
                page.evaluate("() => render(true)")
                self.assertEqual(page.input_value('#login-user'), '20261234')
                self.assertEqual(page.input_value('#login-password'), 'Mulan-pw-2026')
                page.locator('[data-act=save_login]').click()
                # Saved, said on the button itself a moment, no line below (user, 2026-11-20).
                page.wait_for_function("document.querySelector('[data-act=save_login]')?.textContent === '已保存'")
                self.assertEqual(page.locator('#login-error').inner_text(), '')
                page.wait_for_function("document.querySelector('[data-act=save_login]')?.textContent === '保存'", timeout=4000)
                # Saved: both in their fields, the password hidden until the eye shows it.
                self.assertEqual(page.input_value('#login-user'), '20261234')
                self.assertEqual(page.get_attribute('#login-password', 'type'), 'password')
                self.assertEqual(page.input_value('#login-password'), 'Mulan-pw-2026')
                page.locator('[data-act=login_reveal]').click()
                self.assertEqual(page.get_attribute('#login-password', 'type'), 'text')
                self.assertEqual(page.evaluate('saved.key'), 'https://idp.hongmulan.example/idp')
            finally:
                browser.close()

    def test_the_sign_in_page_holds_several_schools_one_the_default(self):
        # User, 2026-11-20: several schools, each with its account; one the default for downloads, switched
        # here; another added once found in the federations' lists, its status said before it is added.
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = self.drag_page(p, 'darwin')
            try:
                page.evaluate("""() => {
                    window.schools = [{key: 'A', name: '红木兰大学', name_en: 'Hongmulan University', current: true, entity: true,
                                       saved: true, username: '2******4', enabled: true, off: '', status: 'surveyed'}];
                    window.accounts = {A: {username: '20261234', password: 'pw-a'}};
                    window.asked = [];
                    const state = () => ({ok: true, pro: true, schools: [...schools].sort((x, y) => y.current - x.current),
                                          counts: {filled: 461, check: 287}, ...schools.find((s) => s.current)});
                    Object.assign(pywebview.api, {
                        settings: async () => ({notify: true, download_dir: '/papers', language: 'zh', fields: []}),
                        api_keys: async () => ({ok:true, filled:0, total:0, groups:[]}),
                        pro_status: async () => ({ok: true, installed: true, version: '0.2.0'}),
                        pro_install_state: async () => ({state: 'idle'}),
                        school_login_state: async () => state(),
                        school_login_saved: async (key) => accounts[key] || {},
                        find_school: async (query) => { asked.push(query); return {ok: true, note: '', results: [
                            {key: 'B', name: '蓝杉大学', name_en: 'Lanshan University', federation: 'CARSI', status: 'check', added: false}]}; },
                        add_school: async (key) => { schools.push({key, name: '蓝杉大学', name_en: 'Lanshan University', current: false,
                            entity: true, saved: false, username: '', enabled: false, off: '', status: 'check'}); return state(); },
                        set_default_school: async (key) => { schools.forEach((s) => { s.current = s.key === key; }); return state(); },
                        forget_school: async (key) => { schools = schools.filter((s) => s.key !== key); return state(); },
                        save_school_login: async (username, password, enabled, key) => {
                            accounts[key] = {username, password}; const s = schools.find((x) => x.key === key);
                            Object.assign(s, {saved: true, username: username[0] + '***', enabled: true}); return state(); }});
                }""")
                page.evaluate("async () => { testState = {mode: 'idle'}; await tick(); await act('settings'); }")
                page.locator('[data-page=login]').click()
                page.wait_for_selector('#login-user')
                self.assertEqual(page.input_value('#login-user'), '20261234')
                rows = page.locator('.login-row[data-act=login_open]')
                self.assertEqual(rows.count(), 1)
                self.assertIn('默认', rows.first.inner_text())
                self.assertIn('自动填写', rows.first.inner_text())
                # 添加学校: a row like the schools', opened to its search (user, 2026-11-20); found by name, its
                # status said, added; what was typed there kept on a redraw.
                self.assertEqual(page.locator('#school-query').count(), 0)
                page.locator('[data-act=login_add]').click()
                page.wait_for_selector('#school-query')
                page.fill('#school-query', 'Lanshan University')
                page.evaluate("() => render(true)")
                self.assertEqual(page.input_value('#school-query'), 'Lanshan University')
                page.press('#school-query', 'Enter')
                page.wait_for_selector('.login-found')
                self.assertEqual(page.evaluate('asked'), ['Lanshan University'])
                self.assertIn('需自己登录', page.locator('.login-found').inner_text())
                page.locator('[data-act=add_school]').click()
                page.wait_for_function("document.querySelectorAll('.login-row[data-act=login_open]').length === 2")
                self.assertEqual(page.locator('#login-error').inner_text(), '已添加，请填账号和密码')
                self.assertEqual(page.input_value('#login-user'), '')  # the new school's own fields
                page.fill('#login-user', 'lanshan-1')
                page.fill('#login-password', 'pw-b')
                page.locator('[data-act=save_login]').click()
                page.wait_for_function("accounts.B && accounts.B.username === 'lanshan-1'")
                self.assertEqual(page.evaluate('accounts.A.username'), '20261234')  # the other school's untouched
                # The default switched here; the default one cannot be removed, another can.
                page.locator('[data-act=set_default]').click()
                page.wait_for_function("schools.find((s) => s.key === 'B').current")
                self.assertIn('蓝杉大学', page.locator('.login-row[data-act=login_open]').first.inner_text())
                self.assertEqual(page.locator('[data-act=forget_school]').count(), 0)
                page.locator('.login-row[data-act=login_open]').nth(1).click()
                page.wait_for_selector('[data-act=forget_school]')
                # Every school's buttons alike, the rarer actions as links under them (user, 2026-11-20).
                self.assertEqual(page.locator('.key-actions .btn').all_inner_texts(), ['关闭自动登录', '保存'])
                self.assertEqual(page.locator('.login-links .link-btn').all_inner_texts(), ['设为默认', '清除账号密码', '移除这所学校'])
                page.locator('[data-act=forget_school]').click()
                self.assertEqual(page.locator('[data-act=forget_school]').inner_text(), '确认移除')
                page.locator('[data-act=forget_school]').click()
                page.wait_for_function("document.querySelectorAll('.login-row[data-act=login_open]').length === 1")
                # 支持哪些学校: a page of its own, how many of each kind, a mainland school by its province, any other by
                # its country (user, 2026-11-20), narrowed by what is typed.
                page.evaluate('''() => Object.assign(pywebview.api, {school_support_list: async () => ({ok: true, schools: [
                    {name: '红木兰大学', country: '中国', province: '广东', status: 'surveyed'},
                    {name: '蓝杉大学', country: '中国', province: '广东', status: 'check'},
                    {name: '白桦大学', country: '中国', province: '吉林', status: 'surveyed'},
                    {name: '木兰大学', name_en: 'Mulan University', country: '日本', province: '', status: 'surveyed'}]})})''')
                page.locator('[data-page=login_schools]').click()
                page.wait_for_selector('#support-list')
                self.assertEqual(page.locator('.stats b').all_inner_texts(), ['3', '1'])
                self.assertIn('自动填写：打开学校登录页时', page.locator('body').inner_text())
                # In English (user, 2026-11-20): a school's English name (its country's and province's: test_i18n).
                self.assertIn('Mulan University', page.evaluate("""() => { const kept = [lang, supportOpen]; lang = 'en';
                    supportOpen = '日本'; const html = supportListHtml(); [lang, supportOpen] = kept; return html; }"""))
                self.assertEqual(page.locator('.grp .reason').all_inner_texts(), ['广东', '吉林', '日本'])  # the most schools first
                page.locator('[data-act=support_group]').first.click()
                page.wait_for_function("document.querySelectorAll('#support-list .login-found').length === 2")
                self.assertIn('需自己登录', page.locator('#support-list').inner_text())
                page.fill('#support-filter', '白桦')
                self.assertEqual(page.locator('#support-list .ls-name').all_inner_texts(), ['白桦大学'])
                self.assertEqual(page.evaluate('document.activeElement.id'), 'support-filter')  # still typing there
                page.locator('[data-act=back]').click()
                page.wait_for_selector('[data-act=login_add]')
            finally:
                browser.close()

    def test_without_pros_features_the_settings_have_no_markdown_page(self):
        # The public edition before 1.0.0 (edition.py, user 2026-11-19): no Markdown row, no page, Pro not asked.
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = self.drag_page(p, 'darwin')
            try:
                page.evaluate("""() => {
                    window.asked = 0;
                    Object.assign(pywebview.api, {
                        settings: async () => ({notify: true, download_dir: '/papers', language: 'zh', fields: [], pro: false}),
                        api_keys: async () => ({ok:true, filled:0, total:0, groups:[]}),
                        pro_status: async () => { asked++; return {ok:true, installed:true, version:'0.1.0'}; },
                        pro_install_state: async () => { asked++; return {state: 'idle'}; }});
                }""")
                page.evaluate("async () => { testState = {mode: 'idle'}; await tick(); await act('settings'); }")
                page.locator('[data-page=keys]').wait_for()
                self.assertEqual(page.locator('[data-page=markdown]').count() + page.locator('[data-page=pro]').count()
                                 + page.locator('[data-page=login]').count(), 0)
                self.assertNotIn('Markdown', page.locator('.settings').inner_text())
                self.assertNotIn('PaperSearch Pro', page.locator('.settings').inner_text())
                page.evaluate("async () => { await openSettings({page: 'markdown', service: ''}); }")
                self.assertEqual(page.evaluate('settingsPage'), 'home')
                self.assertEqual(page.locator('.pro-head').count(), 0)
                self.assertEqual(page.evaluate('asked'), 0)
            finally:
                browser.close()

    def test_the_settings_pages_keep_the_home_pages_height(self):
        # Going to the Markdown page moved the window's edge by the difference, and the taller page
        # showed cut off for a moment (user, 2026-11-18): the shorter pages are as tall as home.
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = self.drag_page(p, 'darwin')
            try:
                page.evaluate("""() => {
                    // Pro installed with everything its page shows (2026-11-19): still as tall as home.
                    window.full = {converted: 1437, complete: 1380, access: {mode: 'free', until: '2027-03-01'},
                                   sites: ['Science', 'NEJM', 'PNAS', 'Sage', 'Neurology', 'AHA journals', 'Taylor & Francis']};
                    window.pro = {ok:true, installed:true, version:'0.1.0', ...full};
                    Object.assign(pywebview.api, {
                        settings: async () => ({notify: false, download_dir: '/papers', language: 'zh', fields: [
                            {name: 'login', label: '学校登录页最多等', unit: '秒', value: 180, default: 180, page: 'wait'},
                            {name: 'hourly', label: '每家出版社每小时最多', unit: '篇', value: 100, default: 100, page: 'download'}]}),
                        api_keys: async () => ({ok:true, filled:0, total:0, groups:[]}),
                        pro_status: async () => pro, pro_install_state: async () => ({state: 'idle'})});
                }""")
                page.evaluate("async () => { testState = {mode: 'idle'}; await tick(); await act('settings'); }")
                page.wait_for_selector('[data-page=markdown]')
                height = "document.querySelector('.card-body.settings').getBoundingClientRect().height"
                # Each page as tall as the home page at least (Pro installed, the home page holds its
                # features: 铺开, user 2026-11-19); a taller one grows the window, as API key's list does.
                for step, installed in (('markdown', True), ('pro', True), ('login', True), ('markdown', False),
                                        ('pro', False), ('download', None), ('wait', None)):
                    with self.subTest(page=step, installed=installed):
                        if installed is not None:
                            page.evaluate("installed => { pro = {ok:true, installed, version: installed ? '0.1.0' : '', ...(installed ? full : {})}; }", installed)
                            page.evaluate("async () => { await loadSettings(); }")
                        page.evaluate("() => { settingsPage = 'home'; render(true); }")
                        home = page.evaluate(height)
                        page.evaluate("async p => { await act('settings_page', {dataset: {page: p}}); }", step)
                        self.assertGreaterEqual(page.evaluate(height), home - 1)
                        if abs(page.evaluate(height) - home) > 1:
                            continue
                        # Held to the home page's height: its foot stays at the bottom, the space above it.
                        foot = page.evaluate("""() => { const body = document.querySelector('.card-body.settings').getBoundingClientRect();
                            const foot = document.querySelector('.card-body.settings > .foot, .card-body.settings > .pro-foot');
                            return foot ? body.bottom - foot.getBoundingClientRect().bottom : 0; }""")
                        self.assertLess(foot, 20)
                # Back home: no space added there.
                page.evaluate("async () => { await act('back'); }")
                self.assertEqual(page.locator('.settings-hold').count(), 0)
            finally:
                browser.close()

    def test_english_leaves_no_chinese_on_any_card_or_settings_page(self):
        from patchright.sync_api import sync_playwright
        from paper_search_school import api_keys
        from paper_search_school.progress_view import view
        import time
        now = time.time()
        running = dict(status='running', run_id='r', current='10.1000/x', title='Test article', publisher='Test',
                       journal='Spine', total=3, done=1, success=1, failed=0, content='both', part='main', stage='fetching_pdf')
        cards = {
            'running': view(running, now),
            'attention': view({**running, 'attention': {'login': {'message': '请在浏览器窗口完成机构登录', 'since': 1,
                                                                  'deadline': now + 100}}}, now),
            'done': view({**running, 'status': 'done', 'done': 3, 'failed': 1, 'results': {
                'content': 'both', 'main': 2, 'supplements': 1, 'sources': [['机构订阅', 2]],
                'failures': [{'cls': 'no_access', 'reason': '学校没有订阅', 'journal': 'Spine', 'title': 'Other', 'doi': '10.1000/y'}],
                'supplement_failures': [{'cls': 'unsupported', 'reason': '网站暂不支持自动下载附录', 'title': 'Third', 'doi': '10.1000/z'}]}}, now),
        }
        listing = {'ok': True, 'filled': 0, 'total': 12, 'groups': [
            {'title': g['title'], 'services': [{**s, 'guide': s.get('guide', ''), 'guide_label': s.get('guide_label', ''), 'set': False,
             'masked': '', 'keys': [{**k, 'set': False, 'masked': ''} for k in s['keys']]} for s in g['services']]} for g in api_keys.groups()]}
        # Every text and label on the window, less the language switch's own "中文".
        leftover = r"""() => {
            const attributes = [...root.querySelectorAll('[aria-label], [title], [placeholder]')]
              .flatMap((e) => ['aria-label', 'title', 'placeholder'].map((n) => e.getAttribute(n) || ''));
            return [root.innerText, ...attributes].join('\n').replace('中文', '').match(/[一-鿿]+/g);
        }"""
        with sync_playwright() as p:
            browser, page = self.drag_page(p, 'darwin', english=True)
            try:
                for name, state in cards.items():
                    with self.subTest(card=name):
                        page.evaluate("async s => { clearInterval(pollTimer); testState = {...s, lang: 'en'}; open = true; panel = '';"
                                      " await tick(); render(true); }", state)
                        page.wait_for_function("!root.classList.contains('animating')")
                        self.assertIsNone(page.evaluate(leftover))
                page.evaluate("""listing => Object.assign(pywebview.api, {
                    settings: async () => ({notify: true, download_dir: '/papers', language: 'en', fields: [
                        {name: 'login', label: '学校登录页最多等', unit: '秒', value: 180, default: 180, page: 'wait'},
                        {name: 'hourly', label: '每家出版社每小时最多', unit: '篇', value: 100, default: 100, page: 'download'}]}),
                    api_keys: async () => listing, api_key_values: async () => ({ok: true, values: {}}),
                    pro_status: async () => ({ok: true, installed: true, version: '0.1.0'}),
                    school_login_state: async () => ({ok: true, pro: true, counts: {filled: 461, check: 287}, schools: [
                        {key: 'A', name: 'Hongmulan University', name_en: 'Hongmulan University', current: true, entity: true, saved: true,
                         username: '2******4', enabled: true, off: 'rejected', status: 'trial'}],
                        school: 'Hongmulan University', entity: true, saved: true, username: '2******4', enabled: true, off: 'rejected', status: 'trial'}),
                    school_login_saved: async () => ({username: '20261234', password: 'x'}),
                    test_api_key: async () => ({status: 'invalid', message: '被拒绝：key 不对，或已失效（HTTP 401）'})})""", listing)
                page.evaluate("async () => { testState = {mode: 'idle', lang: 'en'}; await tick(); await act('settings'); }")
                page.wait_for_selector('[data-page=keys]')
                for step in ('home', 'download', 'wait', 'keys', 'markdown', 'pro', 'login'):
                    with self.subTest(settings=step):
                        if step != 'home':
                            page.evaluate("async p => { settingsPage = 'home'; await act('settings_page', {dataset: {page: p}}); }", step)
                        if step == 'keys':
                            page.locator('[data-service=unpaywall]').click()  # an email's field and link
                            page.wait_for_function("!root.classList.contains('animating')")
                            self.assertIsNone(page.evaluate(leftover))
                            page.locator('[data-act=cancel_key]').click()
                            page.locator('[data-service=elsevier]').click()
                            page.locator('[data-act=test_key]').click()
                            page.wait_for_function("document.querySelector('#key-error').textContent.includes('Rejected')")
                        page.wait_for_function("!root.classList.contains('animating')")
                        self.assertIsNone(page.evaluate(leftover))
                # Pro's page while Pro is not here, installing, or failed to install.
                for name, pro, installing in (
                        ('not installed', {'ok': True, 'installed': False, 'version': ''}, {'state': 'idle'}),
                        ('installing', {'ok': True, 'installed': False, 'version': ''}, {'state': 'running', 'done': 1258291, 'total': 2306867}),
                        ('installing, size unknown', {'ok': True, 'installed': False, 'version': ''}, {'state': 'running', 'done': 0, 'total': 0}),
                        ('failed', {'ok': True, 'installed': False, 'version': ''}, {'state': 'failed', 'message': 'PaperSearch Pro 的下载地址还没开放'}),
                        ('signed out', {'ok': True, 'installed': False, 'version': ''}, {'state': 'failed', 'message': '请先在终端运行 gh auth login 登录 GitHub'}),
                        ('unreadable', {'ok': False, 'error': '读取失败：OSError'}, {'state': 'idle'})):
                    with self.subTest(markdown=name):
                        page.evaluate("""([pro, installing]) => { Object.assign(pywebview.api, {pro_status: async () => pro,
                            pro_install_state: async () => installing}); }""", [pro, installing])
                        page.evaluate("async () => { await loadSettings(); settingsPage = 'pro'; render(true); }")
                        page.wait_for_function("!root.classList.contains('animating')")
                        self.assertIsNone(page.evaluate(leftover))
                        if name == 'installing':
                            self.assertIn('Downloading 1.2 / 2.2 MB', page.locator('.settings').inner_text())
                        page.evaluate("() => clearInterval(proInstallTimer)")
            finally:
                browser.close()

    @staticmethod
    def drag_page(playwright, platform='darwin', english=False):
        from pathlib import Path
        import time
        import webview
        from paper_search_school.progress_view import view
        state = view(dict(status='running', current='10.1000/drag', title='Drag test article', publisher='Test',
                          total=3, done=0, success=0, failed=0, stage='fetching_pdf', started_at=time.time()), time.time())
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        page = page_world(browser.new_page(viewport={'width': 800, 'height': 800}))
        from paper_search_school.progress_capsule import page_html
        page.set_content(page_html() if english else PAGE.read_text(encoding='utf-8'))
        page.evaluate("""({state, platform}) => {
          window.testPointer={x:-1,y:-1};
              document.addEventListener('pointermove', e=>{testPointer={x:e.clientX,y:e.clientY}});
              window.pointerSnapshot=()=>{const r=root.getBoundingClientRect();return {...testPointer,
                inside:testPointer.x>=r.left && testPointer.x<r.right && testPointer.y>=r.top && testPointer.y<r.bottom}};
              window.testState=state; window.sizes=[]; window.dragLocks=[]; window.nativeMoves=[]; window.requestedActions=[]; window.openedArticles=[];
          window.pywebview={platform:platform==='darwin'?'cocoa':'edgechromium', api:{
            platform:async()=>platform, state:async()=>testState, hover_state:async()=>pointerSnapshot(), resize:async(w,h)=>sizes.push([w,h]),
                begin_layout:async(expanded,w,h)=>({vertical:'down',horizontal:'right',width:w,height:h,
                  from_width:parseFloat(root.style.width)+(document.body.classList.contains('mac')?20:0),
                  from_height:parseFloat(root.style.height)+(document.body.classList.contains('mac')?20:0)}),
                finish_layout:async()=>{},
            set_dragging:async(active)=>dragLocks.push(active),
            act:async(...args)=>{requestedActions.push(args); return '正在切到下载浏览器'},
            open_article:async(doi)=>{openedArticles.push(doi); return '已在浏览器打开这篇文章'},
            move_drag:async(x,y)=>nativeMoves.push([x,y]),
            settings:async()=>({fields:[], notify:true, download_dir:'/original'})},
            _jsApiCallback:(name,args)=>{if(name==='pywebviewMoveWindow')nativeMoves.push(args)}};
        }""", {'state': state, 'platform': platform})
        # Use pywebview's actual drag listener, including its default ancestor hit testing.
        customize = Path(webview.__file__).parent / 'js/customize.js'
        page.evaluate(customize.read_text(encoding='utf-8') % {
            'text_select':'False', 'drag_region_direct_target_only':'False',
            'drag_selector':'.pywebview-drag-region', 'easy_drag':'False',
            'zoomable':'False', 'draggable':'False'})
        page.evaluate("window.dispatchEvent(new Event('pywebviewready'))")
        page.wait_for_function("lastCls==='pill'")
        return browser, page
