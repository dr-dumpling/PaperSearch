"""Real DOM events and animated sizes with an isolated page/bridge fixture."""
import json
import os
import unittest
from paper_search_carsi.progress_capsule import PAGE


@unittest.skipUnless(os.environ.get('CARSI_BROWSER_TESTS') == '1', 'opt-in native Chrome test')
class CapsulePageTests(unittest.TestCase):
    def test_browser_request_waits_for_click_activation(self):
        from playwright.sync_api import sync_playwright
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

    def test_expanded_attention_fits_and_keeps_browser_action(self):
        from playwright.sync_api import sync_playwright
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
        from playwright.sync_api import sync_playwright
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
        from playwright.sync_api import sync_playwright
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
                    self.assertTrue(page.get_by_role('switch', name='系统通知').is_visible())
                    page.locator('[data-act=back]').click()
                    page.wait_for_selector('#root.warn')
                    page.evaluate("testState.mode='running'; testState.attention=null; tick()")
                    page.wait_for_function("!root.classList.contains('warn')")
                    self.assertFalse(page.evaluate("root.getAnimations({subtree:true}).some(a => a.animationName === 'breathe')"))
                    browser.close()

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
                save_settings:async(v,n,d)=>{saved=d;savedValues=v;return {ok:true}}}};
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
            switch = page.get_by_role('switch', name='系统通知')
            self.assertEqual(switch.get_attribute('aria-checked'), 'true')
            switch.click()
            page.wait_for_function('notificationPreference === false')
            self.assertEqual(switch.get_attribute('aria-checked'), 'false')
            page.locator('[data-act=back]').click()
            page.locator('[data-act=settings]').click()
            self.assertEqual(page.get_by_role('switch', name='系统通知').get_attribute('aria-checked'), 'false')
            page.get_by_role('switch', name='系统通知').click()
            page.wait_for_function('notificationPreference === true')
            idle = page.get_by_role('textbox', name='页面持续无进展')
            self.assertEqual(idle.input_value(), '30')
            idle.fill('45')
            page.locator('[data-act=defaults]').click()
            self.assertEqual(idle.input_value(), '30')
            idle.fill('45')
            page.locator('[data-act=choose_folder]').click()
            self.assertEqual(page.locator('#download-dir').input_value(), '/chosen folder')
            page.locator('#download-dir').fill('/typed folder')
            page.locator('[data-act=save]').click()
            page.wait_for_function('saved === "/typed folder"')
            self.assertEqual(page.evaluate('savedValues.stalled'), '45')
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

    def test_mac_window_motion_does_not_retrigger_hover_without_pointer_motion(self):
        from playwright.sync_api import sync_playwright
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
        from playwright.sync_api import sync_playwright
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
        from playwright.sync_api import sync_playwright
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
        from playwright.sync_api import sync_playwright
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
          window.testPointer={x:-1,y:-1};
              document.addEventListener('pointermove', e=>{testPointer={x:e.clientX,y:e.clientY}});
              window.pointerSnapshot=()=>{const r=root.getBoundingClientRect();return {...testPointer,
                inside:testPointer.x>=r.left && testPointer.x<r.right && testPointer.y>=r.top && testPointer.y<r.bottom}};
              window.testState=state; window.sizes=[]; window.dragLocks=[]; window.nativeMoves=[]; window.requestedActions=[];
          window.pywebview={platform:platform==='darwin'?'cocoa':'edgechromium', api:{
            platform:async()=>platform, state:async()=>testState, hover_state:async()=>pointerSnapshot(), resize:async(w,h)=>sizes.push([w,h]),
                begin_layout:async(expanded,w,h)=>({vertical:'down',horizontal:'right',width:w,height:h,
                  from_width:parseFloat(root.style.width)+(document.body.classList.contains('mac')?20:0),
                  from_height:parseFloat(root.style.height)+(document.body.classList.contains('mac')?20:0)}),
                finish_layout:async()=>{},
            set_dragging:async(active)=>dragLocks.push(active),
            act:async(...args)=>{requestedActions.push(args); return '正在切到下载浏览器'},
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
