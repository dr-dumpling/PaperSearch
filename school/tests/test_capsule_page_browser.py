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
            page.set_content(PAGE.read_text())
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
                                   'supplement_failures': [item('网站人机验证拦截', 'user_or_external', 'Blocked file'),
                                                           item('网站暂不支持自动下载附录', 'unsupported', 'No rule')]}), now)
        with sync_playwright() as p:
            browser, page = self.drag_page(p, 'darwin')
            try:
                page.evaluate("async state => { testState = state; open = true; await tick(); }", state)
                page.wait_for_function("!root.classList.contains('animating')")
                text = page.locator('#root').inner_text()
                for expected in ('正文未下到 5 篇', '附录未下全 2 篇', '正文已保存', '网站人机验证拦截', '网站暂不支持自动下载附录'):
                    self.assertIn(expected, text)
                self.assertNotIn('未完成', text)
                self.assertEqual(page.locator('.grp').count(), 3)
                self.assertEqual(page.locator('.grp .m').count(), 0)  # main row open, supplement rows without a journal line
                page.locator('[data-act=group][data-group="1"]').click()
                page.wait_for_function("!root.classList.contains('animating')")
                self.assertEqual(page.locator('.paper-list li .t').all_inner_texts(), ['Blocked file'])
            finally:
                browser.close()

    def test_finished_card_opens_one_reason_at_a_time_and_its_list_scrolls_without_dragging(self):
        from datetime import datetime
        import time
        from patchright.sync_api import sync_playwright
        from paper_search_school.progress_view import view
        now = time.time()
        failures = [{'cls': 'no_access', 'reason': '学校没有订阅', 'title': f'Paper {i}', 'journal': 'Spine',
                     'doi': '', 'note': ''} for i in range(12)]
        failures.append({'cls': 'user_or_external', 'reason': '等学校登录超时', 'title': 'Late', 'journal': 'Thieme',
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
                for expected in ('共 200 篇', '1:52:10', '未完成 13 篇', '学校没有订阅', '12 篇', 'Spine 12',
                                 '已完成 187 篇', '正文 187 篇 · 附录 9 个', '机构订阅 150 · 开放获取 37'):
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
                rows.nth(1).click()
                page.wait_for_function("!root.classList.contains('animating')")
                self.assertEqual(page.locator('.paper-list li').all_inner_texts(), ['Late\nThieme'])
                # A listed paper opens its article page, to be fetched by hand (user, 2026-11-08).
                page.locator('.paper-list [data-act=open_article]').click()
                page.wait_for_function("openedArticles.length === 1")
                self.assertEqual(page.evaluate('openedArticles'), ['10.1055/a-2979-4843'])
                self.assertEqual(page.evaluate('dragLocks'), [])
                rows.nth(1).click()
                page.wait_for_function("!root.classList.contains('animating')")
                self.assertEqual(page.locator('.paper-list').count(), 0)
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
            paper(4, 'failed', cls='user_or_external', reason='等学校登录超时'),
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
                    self.assertEqual(page.locator('.grp .row').inner_text().split('\n')[:2], ['外部原因', '等学校登录超时'])
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
            paper(1, 'failed', cls='user_or_external', reason='出版社页面出错'),
            paper(2, 'ok', via='机构下载', supplement_cls='user_or_external', supplement_reason='网站人机验证拦截'),
            paper(3, 'ok', via='机构下载', supplement_cls='user_or_external', supplement_reason='网站人机验证拦截'),
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
                    # The heading sits between the failed papers and the saved ones missing files.
                    order = page.evaluate("""() => [...root.querySelectorAll('.papers-scroll > *')].map(e =>
                        e.classList.contains('list-sub') ? 'heading' : e.querySelector('.reason').textContent)""")
                    self.assertEqual(order, ['出版社页面出错', 'heading', '网站人机验证拦截'])
                    self.assertEqual(page.locator('.list-sub').inner_text().split('\n'), ['附录未下全 2 篇', '正文已保存'])
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
                    test_api_key: async () => ({status: 'invalid', message: '被拒绝：key 不对，或已失效（HTTP 401）'})})""", listing)
                page.evaluate("async () => { testState = {mode: 'idle', lang: 'en'}; await tick(); await act('settings'); }")
                page.wait_for_selector('[data-page=keys]')
                for step in ('home', 'download', 'wait', 'keys'):
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
        page.set_content(page_html() if english else PAGE.read_text())
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
        page.evaluate(customize.read_text() % {
            'text_select':'False', 'drag_region_direct_target_only':'False',
            'drag_selector':'.pywebview-drag-region', 'easy_drag':'False',
            'zoomable':'False', 'draggable':'False'})
        page.evaluate("window.dispatchEvent(new Event('pywebviewready'))")
        page.wait_for_function("lastCls==='pill'")
        return browser, page
