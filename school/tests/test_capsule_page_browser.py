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

    def test_the_page_stays_put_when_the_window_lays_out_without_changing_size(self):
        """User, 2026-11-22: on an external 1080p screen beside a Retina one (and at times on Windows) the window's
        page moved a pixel left and back. Sizes read back a fraction of a pixel off between the page and the screen made
        a layout that changed nothing run its animation, anchored to the window's moving edge (it stood on the right of
        the screen); and the page was a pixel wider than what the card's border leaves (0.5px a side is a whole pixel on
        a 1x screen), so anchored to the right it lay a pixel to the left. A routine check, as the card's height is."""
        from patchright.sync_api import sync_playwright
        for platform, scale in (('darwin', 1), ('darwin', 2), ('win32', 1.25), ('win32', 1.5)):
            with self.subTest(platform=platform, scale=scale), sync_playwright() as p:
                browser, page = self.drag_page(p, platform, scale=scale)
                try:
                    page.evaluate("""() => { Object.assign(pywebview.api, {
                        settings: async () => ({notify: true, download_dir: '/papers', language: 'zh', fields: []}),
                        api_keys: async () => ({ok: true, filled: 0, total: 0, groups: []}),
                        // On the screen's right and low: the window grows to the left and up.
                        begin_layout: async (expanded, w, h) => { const pad = document.body.classList.contains('mac') ? 20 : 0;
                          const now = root.getBoundingClientRect();
                          return {vertical: 'up', horizontal: 'left', width: w, height: h,
                                  from_width: now.width + pad, from_height: now.height + pad}; }});
                        testState = {...testState, mode: 'idle'}; }""")
                    page.evaluate("async () => { await tick(); await act('settings'); }")
                    page.wait_for_selector('.nav-row')
                    page.wait_for_function("!root.classList.contains('animating')")
                    seen = page.evaluate("""async () => {
                        const at = () => { const r = root.querySelector('.nav-row').getBoundingClientRect();
                          return Math.round(r.left * devicePixelRatio) + ',' + Math.round(r.top * devicePixelRatio); };
                        const places = new Set([at()]); let laidOut = 0, looking = true;
                        (function look() { places.add(at()); laidOut += root.classList.contains('animating');
                          if (looking) requestAnimationFrame(look); })();
                        settledSize = null; render(true);  // a layout that changes nothing
                        await new Promise((done) => setTimeout(done, 600));
                        looking = false;
                        return {places: [...places], laidOut}; }""")
                    self.assertGreater(seen['laidOut'], 0)  # the layout did run
                    self.assertEqual(len(seen['places']), 1, seen)
                finally:
                    browser.close()

    def test_the_running_card_keeps_its_height_whatever_the_paper(self):
        """The running card is one height whatever the paper (user, 2026-11-21: it shook up and down as papers went by,
        many times; each change of height resizes the window, whose edge moves): titles long and short, with symbols or
        other scripts (drawn in fallback fonts, a line a pixel or two taller on Windows), a notice, a long journal, the
        step's bar or the lane's line or neither, the counts going on. A routine check:
        run on the Mac and on Windows; content new to the card goes into the cases."""
        from patchright.sync_api import sync_playwright
        long = ('Blockchain and PUF-based secure key establishment protocol for cross-domain authentication in the '
                'industrial internet of things')
        cases = [
            {'title': long},
            {'title': 'Short title'},
            {'title': 'β-Catenin–dependent Wnt signalling in the 5′-UTR: ∑ ≥ 0.5 μm, “quoted” — αβγ ≤ ∞'},
            {'title': '基于区块链与物理不可克隆函数的跨域密钥协商协议：设计、实现与评估'},
            {'title': '한국어 제목과 日本語のタイトル — Ελληνικά ✓ 🧬 Ünïcødé'},
            {'title': '', 'current': '10.1016/j.jare.2025.09.053'},
            {'title': long, 'step': None, 'line': '开放下载：已查 870/1551 篇，找到 869 篇'},
            {'title': long, 'step': None, 'line': '这篇文章只在 ScienceDirect 平台提供，PaperSearch 还没有这个平台的规则，当前路径已停止'},
            {'title': long, 'step': None, 'line': ''},
            {'title': long, 'notice': '已在浏览器打开这篇文章'},
            {'title': long, 'where': 'The Journal of Clinical Endocrinology & Metabolism · Oxford University Press'},
            {'title': long, 'browser': False},
            {'title': long, 'done': 870, 'ok': 869, 'bad': 1, 'left': 681},
            # The papers held for a later try (重试), and the next school named under the title (2026-11-23).
            {'title': long, 'later': {'total': 5, 'no_access': 2, 'unexplained': 2, 'blocked': 1, 'blocked_at': '16:58', 'login': 0}},
            {'title': long, 'switch_note': '换Hongmulan University of Science and Technology at Lingnan再试'},
        ]
        with sync_playwright() as p:
            browser, page = self.drag_page(p, 'darwin')
            try:
                page.evaluate("""() => { window.layouts = 0; const begin = pywebview.api.begin_layout;
                    pywebview.api.begin_layout = (...args) => { layouts++; return begin(...args); };
                    window.baseState = {...testState}; open = true; tick(); }""")
                page.wait_for_selector('.paper')
                page.wait_for_function("!root.classList.contains('animating')")
                heights = []
                for case in cases:
                    page.evaluate("async c => { testState = {...baseState, ...c}; await tick(); }", case)
                    page.wait_for_function("!root.classList.contains('animating')")
                    heights.append(page.evaluate("root.querySelector('.card-body').getBoundingClientRect().height"))
                self.assertEqual(heights, [heights[0]] * len(cases), list(zip(heights, cases)))
                layouts = page.evaluate('layouts')
                # Gone through again: the window not laid out once more.
                for case in cases:
                    page.evaluate("async c => { testState = {...baseState, ...c}; await tick(); }", case)
                self.assertEqual(page.evaluate('layouts'), layouts)
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

    def test_the_card_folds_to_the_capsule_before_it_minimizes(self):
        """User, 2026-11-21 (Mac): minimized from the card and brought back from the Dock, the card showed a moment
        before the capsule; the window had gone into the Dock while it still shrank. And 最小化 was hard to hit: the
        header's buttons are 32 px targets, their icons where they were."""
        from patchright.sync_api import sync_playwright
        from paper_search_school.progress_view import view
        import time
        state = view(dict(status='running', current='10.1000/example', title='Test article', publisher='Test', total=3,
                          done=0, success=0, failed=0, stage='fetching_pdf', started_at=time.time()), time.time())
        # A native resize takes a while, as on a busy Mac.
        script = '''state => {
          window.calls=[];
          window.pywebview={api:{platform:async()=> 'darwin', state:async()=>state,
            hover_state:async()=>({x:0,y:0,inside:false}),
            begin_layout:async(expanded,w,h)=>{calls.push(['begin', expanded]); return {vertical:'down',horizontal:'right',width:w,height:h,
              from_width:parseFloat(root.style.width)+20, from_height:parseFloat(root.style.height)+20}},
            finish_layout:async()=>{calls.push(['finish'])},
            resize:async(w,h)=>{await new Promise((r)=>setTimeout(r, 15)); calls.push(['resize', w, h])},
            minimize:async()=>{calls.push(['minimize', lastCls, Math.round(root.getBoundingClientRect().width)])}}};
          window.dispatchEvent(new Event('pywebviewready'));
        }'''
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            try:
                page = page_world(browser.new_page(viewport={'width': 800, 'height': 800}))
                page.set_content(PAGE.read_text(encoding='utf-8'))
                page.evaluate(script, state)
                page.wait_for_function('lastCls === "pill"')
                page.evaluate("() => { open = true; render(true); }")
                page.wait_for_function("lastCls === 'card' && !root.classList.contains('animating')")
                boxes = [page.locator(f'.tools [data-act={name}]').bounding_box() for name in ('pin', 'settings', 'minimize')]
                for box in boxes:
                    self.assertGreaterEqual(min(box['width'], box['height']), 32)
                icons = [page.locator(f'.tools [data-act={name}] svg').bounding_box() for name in ('pin', 'settings', 'minimize')]
                self.assertEqual([round(b['x'] - a['x']) for a, b in zip(icons, icons[1:])], [24, 24])
                page.evaluate("() => { calls.length = 0; }")
                page.locator('[data-act=minimize]').click()
                page.wait_for_function("calls.some((c) => c[0] === 'minimize')")
                calls = page.evaluate('calls')
                at = next(i for i, c in enumerate(calls) if c[0] == 'minimize')
                # Folded first: the collapse's last resize and its finish before the minimize, the window a capsule then.
                self.assertEqual(calls[0], ['begin', False])
                self.assertEqual(calls[at - 1], ['finish'])
                self.assertEqual(calls[at][1], 'pill')
                self.assertLess(calls[at][2], 300)
                self.assertFalse(page.evaluate('open'))
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

    def test_the_papers_to_be_tried_again_are_counted_as_retry_beside_failed(self):
        """The papers held for a later try (user, 2026-11-23): 重试 beside 成功 and 失败, its list by why, 剩余 those not started (user, 2026-11-24: in place of the card
        the ring showed when pointed at, which is gone); the next school named a moment on the line under the title, one
        line whatever its length. Nothing held: 重试 0, nothing to open."""
        import time
        from datetime import datetime
        from patchright.sync_api import sync_playwright
        from paper_search_school.progress_view import view
        now = time.time()
        raw = dict(status='running', run_id='r-later', current='10.1053/j.gastro.2025.08.034', total=67, done=32, success=30,
                   failed=2, title='Validation of a Serum-Based Biomarker Signature for Detection of Early-Stage Cancer',
                   publisher='Elsevier', journal='Gastroenterology', stage='checking_access', part='main', lists=True,
                   started_at=datetime.fromtimestamp(now - 673).isoformat(timespec='seconds'),
                   later={'no_access': 2, 'unexplained': 2, 'blocked': 1, 'blocked_at': now + 600, 'login': 0})
        at = time.strftime('%H:%M', time.localtime(now + 600))
        school = 'Hongmulan University of Science and Technology at Lingnan'
        height = "root.querySelector('.card-body').getBoundingClientRect().height"
        with sync_playwright() as p:
            for english in (False, True):
                with self.subTest(english=english):
                    browser, page = self.drag_page(p, 'win32', english=english)
                    lang = {'lang': 'en'} if english else {}
                    try:
                        page.evaluate("s => { testState = s; open = true; tick(); }", {**view(raw, now), 'lists': True, **lang})
                        page.wait_for_function("root.querySelector('.card-body > .head .ring') && !root.classList.contains('animating')")
                        # The ring: the batch's progress, one blue arc; 成功 green (user, 2026-11-24: as before).
                        arcs = page.evaluate("""() => [...root.querySelectorAll('.card-body > .head .ring circle:not(.track)')].map(c =>
                            [c.getAttribute('class'), parseFloat(c.getAttribute('stroke-dasharray')), getComputedStyle(c).stroke])""")
                        self.assertEqual([name for name, *_ in arcs], ['fill'])
                        accent, ok = page.evaluate("""() => { const s = getComputedStyle(document.documentElement);
                            const color = v => { const e = document.createElement('i'); e.style.color = v; document.body.append(e);
                              const c = getComputedStyle(e).color; e.remove(); return c; };
                            return [color(s.getPropertyValue('--accent')), color(s.getPropertyValue('--ok'))]; }""")
                        self.assertEqual(arcs[0][2], accent)
                        self.assertAlmostEqual(arcs[0][1] / (2 * 3.14159 * 18), 32 / 67, delta=0.01)
                        self.assertEqual(page.evaluate("getComputedStyle(root.querySelector('.stats b')).color"), ok)
                        self.assertEqual(page.locator('.card-body > .head .ring text').text_content(), '48%')
                        self.assertEqual(page.locator('.stats b').all_inner_texts(), ['30', '2', '5', '30'])
                        self.assertEqual(page.locator('.stats span').all_inner_texts(),
                                         ['Saved', 'Failed', 'Retry', 'Left'] if english else ['成功', '失败', '重试', '剩余'])
                        # Pointed at, the ring shows nothing more.
                        before = page.evaluate(height)
                        page.hover('.card-body > .head .ring')
                        page.wait_for_timeout(400)
                        self.assertEqual(page.locator('.ring-pop').count(), 0)
                        self.assertEqual(page.evaluate(height), before)
                        # 重试's list: by why (from the counts, the papers' list naming none here).
                        page.locator('.stats [data-list=retry]').click()
                        page.wait_for_function("panel === 'papers' && !!root.querySelector('.grp')")
                        self.assertEqual(page.locator('.head .title').inner_text(), 'Retry 5' if english else '重试 5 篇')
                        rows = [line for line in page.locator('.papers-scroll').inner_text().split('\n') if line.strip()]
                        self.assertEqual(rows, ['Other school · No access', '2', 'One last try · Unclear', '2',
                                                f'Retry at {at} · Blocked by site', '1'] if english else
                                         ['换学校再试 · 没权限', '2 篇', '最后再试一次 · 原因不明', '2 篇', f'{at} 再试 · 被网站拦截', '1 篇'])
                        page.locator('[data-act=back]').click()
                        page.wait_for_function("panel === ''")
                        # The next school: in the place of the line under the title, one line (the rest on hover), the card's
                        # height as it was whether that line takes one line or two.
                        page.evaluate("async s => { testState = s; await tick(); }",
                                      {**view({**raw, 'switch_note': {'school': school, 'at': now}}, now), 'lists': True, **lang})
                        sub = page.evaluate("""() => { const note = root.querySelector('.head .sub .note'), range = document.createRange();
                            range.selectNodeContents(note); return [root.querySelector('.head .sub').innerText, note.title,
                              new Set([...range.getClientRects()].map(r => Math.round(r.top))).size]; }""")
                        said = f'Retrying with {school}' if english else f'换{school}再试'
                        self.assertEqual(sub, [said, said, 1])
                        self.assertEqual(page.evaluate(height), before)
                        # Nothing held: 重试 0, nothing to open; 剩余 all not done.
                        page.evaluate("async s => { testState = s; await tick(); }", {**view({**raw, 'later': None}, now), 'lists': True, **lang})
                        self.assertEqual(page.locator('.stats b').all_inner_texts(), ['30', '2', '0', '35'])
                        self.assertEqual(page.locator('.stats [data-list=retry]').count(), 0)
                        # Neither 失败后自动重试 nor 没权限时换下一所学校 on (user, 2026-11-24): no 重试, 剩余 all not
                        # done (a paper paused for the school's login among them).
                        page.evaluate("async s => { testState = s; await tick(); }", {**view(raw, now), 'holds': False, 'lists': True, **lang})
                        self.assertEqual(page.locator('.stats span').all_inner_texts(),
                                         ['Saved', 'Failed', 'Left'] if english else ['成功', '失败', '剩余'])
                        self.assertEqual(page.locator('.stats b').all_inner_texts(), ['30', '2', '35'])
                        # Collapsed: the capsule's ring, one blue arc too.
                        page.evaluate("async s => { testState = s; open = false; await tick(); }", {**view(raw, now), **lang})
                        page.wait_for_function("root.querySelector('.pillrow .ring')")
                        self.assertEqual(page.evaluate("[...root.querySelectorAll('.pillrow .ring circle:not(.track)')].map(c => c.getAttribute('class'))"),
                                         ['fill'])
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
                                   'supplement_failures': [item('被网站拦截', 'external', 'Blocked file'),
                                                           item('附录暂未适配', 'unsupported', 'No rule')],
                                   'markdown_failures': [item('网页只有摘要', 'external', 'Abstract only'),
                                                         item('网页只有摘要', 'external', 'Abstract too'),
                                                         item('网站暂不支持转换', 'unsupported', 'No page rule')]}), now)
        with sync_playwright() as p:
            browser, page = self.drag_page(p, 'darwin')
            try:
                page.evaluate("async state => { testState = state; open = true; await tick(); }", state)
                page.wait_for_function("!root.classList.contains('animating')")
                text = page.locator('#root').inner_text()
                for expected in ('PDF 未下到 5 篇', '补充材料未下全 2 篇', '被网站拦截', '附录暂未适配',
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
        failures.append({'cls': 'user_side', 'reason': '等你登录超时', 'title': 'Late', 'journal': 'Thieme',
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

    def test_sites_not_yet_supported_are_reported_from_the_failed_list(self):
        """Pages whose Markdown came by rules not listed for their site: no dot nor card on the running card (user,
        2026-11-24: not understood, and its counts took the papers whose PDF failed in too); their group in 失败 with its
        note, the supported sites and 提 issue (user, 2026-11-16); the finished card's group as before."""
        import time
        from patchright.sync_api import sync_playwright
        from paper_search_school.progress_view import paper_lists, summary_view, view
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
            paper(4, 'ok', supplement_cls='external', supplement_reason='被网站拦截'),
            paper(5, 'school'), paper(6, 'open'))}}
        lists = paper_lists(listed, raw)
        state = {**view(raw, time.time()), 'lists': True}
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
                    # No line, dot or card of its own on the running card.
                    self.assertEqual(page.locator('.held, .rules-dot, .rules-pop').count(), 0)
                    # 失败's list: the site's group, with its note and buttons once opened.
                    page.locator('.stat[data-list=failed]').click()
                    page.wait_for_function("panel === 'papers' && papersList && !root.classList.contains('animating')")
                    group = page.locator('[data-act=list_group]', has_text='Incomplete' if english else '内容不完整')
                    if group.get_attribute('aria-expanded') != 'true':
                        group.click()
                        page.wait_for_function("!root.classList.contains('animating')")
                    if english:
                        self.assertIsNone(page.evaluate(r"""() => [root.innerText, ...[...root.querySelectorAll('[title], [aria-label]')]
                            .flatMap(e => [e.title, e.getAttribute('aria-label') || ''])].join('\n').match(/[一-鿿]+/g)"""))
                        continue
                    text = page.locator('#root').inner_text()
                    for expected in ('补充材料未下全 1 篇', 'Markdown 未生成 1 篇', '内容不完整',
                                     '这些网站尚未正式支持 Markdown，内容不完整的未保存。如需支持，欢迎提 issue 或 PR。', note):
                        self.assertIn(expected, text)
                    self.assertEqual(page.locator('.grp', has=group).locator('.paper-list li').all_inner_texts(), [f'Paper 3\n{note}'])
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
            paper(4, 'failed', cls='user_side', reason='等你登录超时'),
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
                    self.assertEqual(page.locator('.grp .row').inner_text().split('\n')[:2], ['要你处理', '等你登录超时'])
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
            paper(1, 'failed', cls='external', reason='出版社网站出错'),
            paper(2, 'ok', via='机构下载', supplement_cls='external', supplement_reason='被网站拦截'),
            paper(3, 'ok', via='机构下载', supplement_cls='external', supplement_reason='被网站拦截'),
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
                    self.assertEqual(order, ['heading', '出版社网站出错', 'heading', '被网站拦截'])
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
        """All the services (twelve then, thirteen with Bright Data) no longer stretch the window: the list scrolls
        under its title, an opened one's editor comes into view and the list stays put (user, 2026-11-11)."""
        from patchright.sync_api import sync_playwright
        from paper_search_school import api_keys
        services = sum(len(g['services']) for g in api_keys.groups())
        listing = {'ok': True, 'filled': 0, 'total': services, 'groups': [
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
                self.assertEqual(page.locator('.keys-scroll [data-act=edit_key]').count(), services)
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

    def test_the_markdown_page_counts_and_lists_the_sites(self):
        """The Markdown page drawn on 2026-11-19 (user): what a Markdown keeps, the Markdown saved on
        this computer, the sites with rules (opened in place), whether Pro is free; in English too. Its version and
        updates are on 关于 PaperSearch now (test_one_version_and_one_update_on_the_about_page)."""
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
                          install_pro: async () => { installs++; installing = true; return {state: 'running', done: 0, total: 0}; },
                          pro_install_state: async () => (installing ? {state: 'running', done: 0, total: 0} : {state: 'idle'})});
                        if (english) testState = {...testState, lang: 'en'}; }""", english)
                    page.evaluate("async () => { testState = {...testState, mode: 'idle'}; await tick(); await act('settings'); }")
                    # Pro installed: its features on the home page, each marked Pro (user, 2026-11-19: 铺开; 2026-11-21: X1).
                    page.wait_for_selector('[data-page=markdown]')
                    self.assertEqual(page.locator('[data-page=markdown] .pro-pill').inner_text(), 'Pro')
                    self.assertIn('1,437 converted · 7 platforms' if english else '已转换 1,437 篇 · 7 个平台',
                                  page.locator('[data-page=markdown]').inner_text())
                    page.locator('[data-page=markdown]').click()
                    page.wait_for_selector('.pro-stats')
                    stats = page.locator('.pro-stats').inner_text()
                    for said in ('1,437', '96%', '7'):
                        self.assertIn(said, stats)
                    self.assertEqual(page.locator('.pro-chip').count(), 4)
                    # What sets it apart: a row like the platforms', its three names under it, each said in full once
                    # opened (user, 2026-11-21).
                    merits = page.locator('[data-act=pro_merits]')
                    self.assertIn('Original text · Gaps marked · Traceable' if english else '出版社原文 · 缺失会标明 · 来源可追溯',
                                  merits.inner_text())
                    self.assertEqual(page.locator('.pro-merit').count(), 0)
                    merits.click()
                    page.wait_for_selector('.pro-merit')
                    self.assertEqual(page.locator('.pro-merit b').all_inner_texts(),
                                     ['Original text', 'Gaps marked', 'Traceable'] if english
                                     else ['出版社原文', '缺失会标明', '来源可追溯'])
                    self.assertIn('source list' if english else '来源清单', page.locator('.pro-merits').inner_text())
                    merits.click()
                    page.wait_for_function("!document.querySelector('.pro-merit')")
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
                    # Back on the home page; 关于 PaperSearch says until when Pro is free (user, 2026-11-19, -21).
                    page.locator('[data-act=back]').click()
                    page.wait_for_selector('.version-link')
                    page.locator('.version-link').click()
                    page.wait_for_selector('.about-hero')
                    rows = page.evaluate("[...document.querySelectorAll('.pro-use')].map((r) => [...r.children].map((c) => c.textContent).join('|'))")
                    self.assertEqual(rows, ['Access|Free in beta', 'Ends|2027-03-01'] if english
                                     else ['使用方式|测试期间免费', '截止日期|2027-03-01'])
                    if english:
                        self.assertIsNone(page.evaluate("root.innerText.replace('中文', '').match(/[一-鿿]+/g)"))
                finally:
                    browser.close()

    def test_one_version_and_one_update_on_the_about_page(self):
        """User, 2026-11-21: one version and one update, Pro with it. The home page's foot says PaperSearch's version;
        a newer one there, the whole line in red, and a red dot on the card's settings button. 关于 PaperSearch: its
        icon and name (Pro's icon and pill once bought, the line a little to the right), 更新到 X; its steps as it goes,
        then the window opening again. An update made elsewhere: 重新打开 at the top of the settings."""
        from patchright.sync_api import sync_playwright
        for english in (False, True):
            with self.subTest(english=english), sync_playwright() as p:
                browser, page = self.drag_page(p, 'darwin', english=True)
                try:
                    page.evaluate("""english => { window.reopened = []; window.notes = 0; window.updates = 0;
                        window.info = {running: '0.7.2', installed: '0.7.2'}; window.check = {state: 'running'}; window.run = {state: 'idle'};
                        Object.assign(pywebview.api, {
                          settings: async () => ({notify: true, download_dir: '/papers', language: english ? 'en' : 'zh', fields: []}),
                          api_keys: async () => ({ok: true, filled: 0, total: 0, groups: []}),
                          pro_status: async () => ({ok: true, installed: true, version: '0.3.3', access: {mode: 'free'}}),
                          pro_install_state: async () => ({state: 'idle'}),
                          versions: async () => info, check_versions: async () => check, versions_state: async () => check,
                          update_all: async () => { updates++; run = {state: 'running', steps: ['paper_search', 'school', 'skills', 'pro'], step: 0,
                                                                         target: '0.7.3'}; return run; },
                          update_state: async () => run,
                          reopen_window: async (page) => { reopened.push(page); return {ok: true}; },
                          open_release_notes: async () => { notes++; return {ok: true}; }});
                        lang = english ? 'en' : 'zh'; testState = {...testState, mode: 'idle', lang: lang}; }""", english)
                    page.evaluate("async () => { await tick(); await act('settings'); await checkVersions(); }")
                    page.wait_for_selector('.version-link')
                    self.assertEqual(page.locator('.version-link .pl-text').inner_text(), 'PaperSearch 0.7.2')
                    # Pro installed: its pill after the version, as on its features' rows (user, 2026-11-22).
                    self.assertEqual(page.locator('.version-link .pro-pill').inner_text(), 'Pro')
                    # A newer one: the foot's whole line in red.
                    page.evaluate("() => { check = {state: 'done', current: '0.7.2', latest: '0.7.3', update: true, notes: 'https://x', pro_update: true, pro_latest: '0.3.4'}; }")
                    page.wait_for_selector('.version-link.new')
                    self.assertEqual(page.locator('.version-link').inner_text(), 'New version 0.7.3: update' if english else '有新版本 0.7.3，点此更新')
                    self.assertEqual(page.locator('.version-link .pro-pill').count(), 0)  # the red line alone
                    self.assertNotEqual(page.evaluate("getComputedStyle(document.querySelector('.version-link')).color"),
                                        page.evaluate("getComputedStyle(document.querySelector('.lang-btn')).color"))  # red, not the grey beside it
                    # The card: its settings button with a red dot.
                    page.evaluate("() => { panel = ''; open = true; render(true); }")
                    page.wait_for_selector('.iconbtn.has-dot[data-act=settings]')
                    page.evaluate("async () => { await act('settings'); }")
                    page.locator('.version-link').click()
                    page.wait_for_selector('.about-hero')
                    # Its head says 设置 alone, the name under the icon (user, 2026-11-21).
                    self.assertEqual(page.locator('.head .title').inner_text(), 'Settings' if english else '设置')
                    self.assertEqual(page.locator('.head .sub').count(), 0)
                    self.assertEqual(page.evaluate("[...document.querySelector('.about-name').childNodes].map((n) => n.textContent.trim()).filter(Boolean)"),
                                     ['PaperSearch', 'Pro'])
                    self.assertEqual(page.locator('.about-hero .app-icon.pro').count(), 1)
                    # The line with Pro's pill a little to the right of centre (user, 2026-11-21: 中间这档).
                    self.assertEqual(page.evaluate("new DOMMatrix(getComputedStyle(document.querySelector('.about-name')).transform).m41"), 8)
                    self.assertEqual(page.locator('.about-version').inner_text(), '0.7.2 · New version 0.7.3' if english else '0.7.2 · 有新版本 0.7.3')
                    self.assertIn('new', page.locator('.about-version').get_attribute('class'))
                    self.assertEqual(page.locator('[data-act=update_all]').inner_text(), 'Update to 0.7.3' if english else '更新到 0.7.3')
                    # What is new: 有新版本 X in the line is its link, ↗ after it, nothing under the button (user, 2026-11-22: 乙).
                    self.assertEqual(page.locator('.about-version [data-act=release_notes]').inner_text(),
                                     'New version 0.7.3' if english else '有新版本 0.7.3')
                    self.assertEqual(page.locator('.about-version [data-act=release_notes] svg.i').count(), 1)
                    self.assertEqual(page.locator('.about-action [data-act=release_notes]').count(), 0)
                    page.locator('[data-act=release_notes]').click()
                    page.wait_for_function('notes === 1')
                    # 更新: its steps as they go, the window opening again once PaperSearch itself is updated.
                    page.locator('[data-act=update_all]').click()
                    page.wait_for_selector('.update-steps')
                    self.assertEqual(page.locator('.update-steps li').all_inner_texts(),
                                     ['PaperSearch 0.7.3', 'School extension', 'Skill', 'Pro'] if english
                                     else ['PaperSearch 0.7.3', '学校订阅下载扩展', 'Skill', 'Pro'])
                    self.assertEqual(page.locator('.about-version').inner_text(), 'Updating to 0.7.3…' if english else '正在更新到 0.7.3…')
                    self.assertEqual(page.locator('.about-caption').first.inner_text(),
                                     'The window reopens when done' if english else '完成后窗口会自动重新打开')
                    page.evaluate("() => { run = {...run, step: 2}; }")
                    page.wait_for_function("document.querySelectorAll('.update-steps li.done').length === 2")
                    self.assertEqual(page.locator('.update-steps li.now').inner_text(), 'Skill')
                    page.evaluate("() => { run = {...run, state: 'done', step: 4, reopen: true}; }")
                    page.wait_for_function("reopened.length === 1")
                    self.assertEqual(page.evaluate('reopened'), ['about'])
                    # A download running: the update waits for it.
                    page.evaluate("() => { updateRun = {state: 'idle'}; check = {state: 'done', current: '0.7.2', latest: '0.7.3', update: true, notes: ''};"
                                  " versionCheck = check; V = {...V, mode: 'running'}; render(true); }")
                    waiting = page.locator('.about-action .btn.primary')
                    self.assertTrue(waiting.is_disabled())
                    self.assertEqual(waiting.inner_text(), 'Update when done' if english else '下载结束后更新')
                    self.assertEqual(page.locator('[data-act=release_notes]').count(), 0)  # no notes to show
                    # Up to date: said so, and 检查更新.
                    page.evaluate("() => { V = {...V, mode: 'idle'}; versionCheck = {state: 'done', current: '0.7.3', latest: '0.7.3', update: false};"
                                  " info = {running: '0.7.3', installed: '0.7.3'}; versionInfo = info; render(true); }")
                    self.assertEqual(page.locator('.about-version').inner_text(), '0.7.3 · Up to date' if english else '0.7.3 · 已是最新版本')
                    self.assertEqual(page.locator('[data-act=check_versions]').inner_text(), 'Check for updates' if english else '检查更新')
                    # Updated elsewhere since this window started: 重新打开 at the top of the settings pages.
                    page.evaluate("async () => { info = {running: '0.7.3', installed: '0.7.4'}; await refreshVersions(); settingsPage = 'home'; render(true); }")
                    page.wait_for_selector('.reopen-line')
                    self.assertEqual(page.locator('.reopen-line').inner_text().split('\n'),
                                     ['Updated to 0.7.4', 'Reopen'] if english else ['已更新到 0.7.4', '重新打开'])
                    page.locator('.reopen-line').click()
                    page.wait_for_function("reopened.length === 2")
                    self.assertEqual(page.evaluate('reopened[1]'), 'home')
                finally:
                    browser.close()

    def test_the_download_folder_on_the_home_page_fits_its_line(self):
        """The home page's 下载 line (user, 2026-11-24, 乙): the folder whole when it fits, else its middle folders left out,
        the first ones first; the drive, the folder's own name and the hourly limit always shown, the line never cut."""
        from patchright.sync_api import sync_playwright
        cases = [  # folder, its first part, its own name, whether it is shortened in English
            (r'D:\Refs', 'D:\\', 'Refs', False),
            (r'D:\Project-XY\References', 'D:\\', 'References', None),
            (r'D:\Project-XY\Literature\Systematic reviews\2026 update\References', 'D:\\', 'References', True),
            ('/Volumes/Research Data/Literature/Systematic reviews/2026 update/Papers', '/', 'Papers', True)]
        for english in (False, True):
            with self.subTest(english=english), sync_playwright() as p:
                browser, page = self.drag_page(p, 'win32', english=english)
                try:
                    for folder, first, own, shortened in cases:
                        page.evaluate("""([folder, english]) => { Object.assign(pywebview.api, {
                              settings: async () => ({notify: true, download_dir: folder, language: english ? 'en' : 'zh', fields: [
                                {name: 'hourly', label: '每家出版社每小时最多', value: 200, default: 200, page: 'download'}]}),
                              api_keys: async () => ({ok: true, filled: 5, total: 13, groups: []}),
                              pro_status: async () => ({ok: true, installed: false, version: ''}),
                              pro_install_state: async () => ({state: 'idle'})});
                            testState = {...testState, mode: 'idle', ...(english ? {lang: 'en'} : {})}; }""", [folder, english])
                        page.evaluate("async () => { panel = ''; await tick(); await act('settings'); await loadSettings(); render(true); }")
                        page.wait_for_function("!root.classList.contains('animating') && !!root.querySelector('.nav-sub[data-path]')")
                        line = page.locator('.nav-row[data-page=download] .nav-sub')
                        text = line.inner_text()
                        self.assertTrue(page.evaluate("(e) => e.scrollWidth <= e.clientWidth", line.element_handle()), text)
                        self.assertTrue(text.startswith(first), text)
                        limit = '200/h per publisher' if english else '每家每小时 200 篇'
                        self.assertTrue(text.endswith(own + ' · ' + limit), text)
                        if shortened is False:
                            self.assertEqual(text, folder + ' · ' + limit)
                        if shortened:
                            self.assertIn('…', text)
                finally:
                    browser.close()

    def test_the_download_strip_shows_the_publisher_whole_in_every_language(self):
        """The settings' download strip (user, 2026-11-24, 甲): a download icon for 正在下载, an arrow for 返回进度 (its words
        on pointing at it), so the count and a long publisher's name fit in every language."""
        from patchright.sync_api import sync_playwright
        publisher = 'American Meteorological Society'
        for code in ('zh', 'en', 'ja', 'ko', 'fr'):
            with self.subTest(lang=code), sync_playwright() as p:
                browser, page = self.drag_page(p, 'win32', english=code != 'zh')
                try:
                    page.evaluate("""([code, publisher]) => { Object.assign(pywebview.api, {
                          settings: async () => ({notify: true, download_dir: 'D:\\\\Refs', language: code, fields: []}),
                          api_keys: async () => ({ok: true, filled: 5, total: 13, groups: []}),
                          pro_status: async () => ({ok: true, installed: false, version: ''}),
                          pro_install_state: async () => ({state: 'idle'})});
                        testState = {...testState, publisher, done: 14, total: 71}; lang = code; }""", [code, publisher])
                    page.evaluate("async () => { await tick(); await act('settings'); render(true); }")
                    page.wait_for_function("!!document.querySelector('#task-strip .strip svg.i')")
                    grow = page.locator('#task-strip .grow')
                    self.assertEqual(grow.inner_text(), '14/71 · ' + publisher)
                    self.assertTrue(page.evaluate("(e) => e.scrollWidth <= e.clientWidth", grow.element_handle()))
                    title = {'zh': '返回进度', 'en': 'Back to progress', 'ja': '進捗に戻る', 'ko': '진행 상황으로', 'fr': 'Retour au suivi'}[code]
                    self.assertEqual(page.locator('#task-strip .strip').get_attribute('title'), title)
                finally:
                    browser.close()

    def test_the_language_is_one_menu_at_the_home_pages_foot(self):
        """The home page's last line (user, 2026-11-21): PaperSearch's version at its left, to 关于 PaperSearch; the
        language at its right, one menu of the languages each in its own name, more to come. It opens over the page without
        changing the window's size and closes on a choice, a click elsewhere or Esc."""
        from patchright.sync_api import sync_playwright
        for english in (False, True):
            with self.subTest(english=english), sync_playwright() as p:
                browser, page = self.drag_page(p, 'darwin', english=english)
                try:
                    page.evaluate("""english => { window.langs = [];
                        Object.assign(pywebview.api, {
                          settings: async () => ({notify: true, download_dir: '/papers', language: english ? 'en' : 'zh', fields: []}),
                          api_keys: async () => ({ok: true, filled: 0, total: 0, groups: []}),
                          pro_status: async () => ({ok: true, installed: false, version: ''}),
                          pro_install_state: async () => ({state: 'idle'}),
                          set_language: async (code) => { langs.push(code); return {ok: true, language: code}; }});
                        if (english) testState = {...testState, lang: 'en'}; }""", english)
                    page.evaluate("async () => { testState = {...testState, mode: 'idle'}; await tick(); await act('settings'); }")
                    page.wait_for_function("lang === '%s' && !root.classList.contains('animating')" % ('en' if english else 'zh'))
                    page.wait_for_selector('.lang-btn')
                    own, other = ('English', '简体中文') if english else ('简体中文', 'English')
                    self.assertEqual(page.locator('.version-link .pl-text').inner_text(), 'PaperSearch')
                    self.assertEqual(page.locator('.lang-btn').inner_text(), own)
                    self.assertEqual(page.locator('.lang-btn').get_attribute('aria-expanded'), 'false')
                    self.assertEqual(page.locator('.lang-menu').count(), 0)
                    # One line: the version at the left, the language at the right, the two at one height.
                    link, button, row = (page.locator(sel).bounding_box() for sel in ('.version-link', '.lang-btn', '.home-foot'))
                    self.assertLess(link['x'] + link['width'], button['x'])
                    self.assertAlmostEqual(link['x'], row['x'], delta=1)
                    self.assertAlmostEqual(button['x'] + button['width'], row['x'] + row['width'], delta=1)
                    self.assertAlmostEqual(link['y'] + link['height'] / 2, button['y'] + button['height'] / 2, delta=1)
                    height = page.evaluate("root.getBoundingClientRect().height")

                    # Opened: each language in its own name, the one in use ticked, more to come; inside the window.
                    page.locator('.lang-btn').click()
                    page.wait_for_selector('.lang-menu')
                    self.assertEqual(page.locator('.lang-btn').get_attribute('aria-expanded'), 'true')
                    self.assertEqual(page.locator('.lang-menu [data-act=language]').all_inner_texts(),
                                     ['简体中文', '繁體中文', 'English', '日本語', '한국어', 'Français'])
                    self.assertEqual(page.locator('.lang-menu [aria-checked=true]').inner_text(), own)
                    self.assertEqual(page.locator('.lang-more').inner_text(), 'More languages coming' if english else '更多语言陆续加入')
                    self.assertEqual(page.evaluate("root.getBoundingClientRect().height"), height)
                    self.assertTrue(page.evaluate("""() => { const m = document.querySelector('.lang-menu').getBoundingClientRect(),
                        r = root.getBoundingClientRect(); return m.top >= r.top && m.right <= r.right && m.left >= r.left; }"""))
                    # Esc closes it, and only it.
                    page.keyboard.press('Escape')
                    page.wait_for_function("!document.querySelector('.lang-menu')")
                    self.assertEqual(page.evaluate("[panel, settingsPage]"), ['settings', 'home'])
                    # A click elsewhere closes it.
                    page.locator('.lang-btn').click()
                    page.wait_for_selector('.lang-menu')
                    page.locator('.home-foot').click(position={'x': row['width'] / 2, 'y': row['height'] / 2})
                    page.wait_for_function("!document.querySelector('.lang-menu')")
                    self.assertEqual(page.evaluate('langs'), [])
                    # Another language: saved, the menu closed, its name on the button.
                    page.locator('.lang-btn').click()
                    page.locator('.lang-menu [data-act=language]', has_text=other).click()
                    page.wait_for_function("langs.length === 1 && !document.querySelector('.lang-menu')")
                    self.assertEqual(page.evaluate('langs'), ['zh' if english else 'en'])
                    page.wait_for_function("document.querySelector('.lang-btn')?.textContent === %r" % other)
                finally:
                    browser.close()

    def test_the_settings_in_traditional_chinese(self):
        """繁體中文 (user, 2026-11-21): the windows' texts in Taiwan's wording, anything else in its characters; no
        character left that has a traditional form."""
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = self.drag_page(p, 'darwin', english=True)  # the page with its tables
            try:
                page.evaluate("""() => { Object.assign(pywebview.api, {
                      settings: async () => ({notify: true, download_dir: '/papers', language: 'zh-Hant', fields: [
                        {name: 'hourly', label: '每家出版社每小时最多', unit: '篇', value: 500, default: 100, page: 'download'},
                        {name: 'login', label: '学校登录页最多等', unit: '秒', value: 180, default: 180, page: 'wait'}]}),
                      api_keys: async () => ({ok: true, filled: 4, total: 12, groups: []}),
                      pro_status: async () => ({ok: true, installed: false, version: ''}),
                      pro_install_state: async () => ({state: 'idle'})});
                    testState = {...testState, lang: 'zh-Hant', mode: 'idle'}; }""")
                page.evaluate("async () => { await tick(); await act('settings'); }")
                page.wait_for_function("lang === 'zh-Hant' && document.querySelector('.lang-btn')")
                left = "() => [...root.innerText].filter((c) => TABLES['zh-Hant'].chars[c]).join('')"
                self.assertEqual(page.locator('.head .title').inner_text(), '設定')
                self.assertEqual(page.locator('.lang-btn').inner_text(), '繁體中文')
                self.assertIn('登入頁 180 秒', page.locator('[data-page=wait]').inner_text())
                self.assertEqual(page.evaluate(left), '')
                page.locator('.nav-row[data-page=about]').click()
                page.wait_for_selector('[data-page=pro_activate]')
                self.assertEqual(page.locator('[data-page=pro_activate]').inner_text(), '啟用 Pro')
                self.assertEqual(page.locator('.head .title').inner_text(), '設定')  # its head says 设置 alone (user, 2026-11-21)
                self.assertEqual(page.evaluate(left), '')
            finally:
                browser.close()

    def test_the_retry_switch_is_off_and_says_what_it_retries_on_its_icon(self):
        """失败后自动重试 (user, 2026-11-24): on the 等待和提醒 page before the notifications' row, off by default, saved at
        once; what it retries in a tip on its small icon, not on the page."""
        from patchright.sync_api import sync_playwright
        for english in (False, True):
            with self.subTest(english=english), sync_playwright() as p:
                browser, page = self.drag_page(p, 'darwin', english=english)
                try:
                    page.evaluate("""english => { window.saved = [];
                        Object.assign(pywebview.api, {
                          settings: async () => ({notify: true, retry: false, download_dir: '/papers', language: english ? 'en' : 'zh',
                            fields: [{name: 'login_timeout_sec', label: '学校登录页最多等', unit: '秒', value: 180, default: 180, page: 'wait'}]}),
                          set_retry: async (on) => { saved.push(on); return {ok: true, retry: on}; }});
                        if (english) testState = {...testState, lang: 'en'}; }""", english)
                    page.evaluate("async () => { await tick(); await openSettings({page: 'wait'}); }")
                    switch = page.locator('[data-act=retry]')
                    switch.wait_for()
                    # Before the notifications' row; off.
                    rows = page.evaluate("[...document.querySelectorAll('.row')].map((r) => !!r.querySelector('[data-act=retry]') ? 'retry'"
                                         " : !!r.querySelector('[data-act=notify]') ? 'notify' : '')")
                    self.assertLess(rows.index('retry'), rows.index('notify'))
                    self.assertEqual(switch.get_attribute('aria-checked'), 'false')
                    label = page.locator('[data-act=retry]').locator('xpath=..').locator('.tip-label')
                    self.assertEqual(label.inner_text().strip(), 'Auto-retry failures' if english else '失败后自动重试')
                    tip = page.locator('.mini-wrap.info .mini-tip')
                    self.assertFalse(tip.is_visible())
                    page.wait_for_timeout(600)
                    page.locator('.mini-wrap.info').hover()
                    tip.wait_for(state='visible')
                    self.assertEqual(tip.locator('div').all_inner_texts(),
                                     ['Unclear: retried at the end', 'Blocked by site: retried in 10 min'] if english
                                     else ['原因不明的失败，最后再重试', '被网站拦截的，10 分钟后再重试'])
                    self.assertTrue(page.evaluate("document.querySelector('.mini-wrap.info .mini-tip').getBoundingClientRect().right"
                                                  " <= root.getBoundingClientRect().right"))
                    switch.click()
                    page.wait_for_function("saved.length === 1")
                    self.assertEqual(page.evaluate('saved'), [True])
                    self.assertEqual(switch.get_attribute('aria-checked'), 'true')
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
                self.assertIn('0/3 · Test', page.locator('#task-strip').inner_text())
                self.assertEqual(page.locator('#task-strip .strip').get_attribute('title'), '返回进度')
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
                # Its features rows of the home page, each marked Pro; PaperSearch's version at the left of the last line,
                # the language at its right (user, 2026-11-21: one version, Pro with it).
                self.assertEqual([page.locator(f'[data-page={name}] .pro-pill').inner_text() for name in ('markdown', 'login')], ['Pro', 'Pro'])
                self.assertIn('学校自动登录', page.locator('[data-page=login]').inner_text())
                self.assertEqual(page.locator('.home-foot > *').count(), 2)
                self.assertEqual(page.locator('.home-foot .version-link').count() + page.locator('.home-foot .lang-btn').count(), 2)
                self.assertEqual(page.locator('.nav-row[data-page=about]').count(), 0)
                self.assertTrue(page.evaluate("!!(document.querySelector('[data-page=login]').compareDocumentPosition("
                                              "document.querySelector('.home-foot')) & Node.DOCUMENT_POSITION_FOLLOWING)"))
                self.assertEqual(page.locator('.pro-entry').count() + page.locator('.pro-head').count(), 0)
                row.click()
                page.wait_for_selector('.pro-stats')
                text = page.locator('.settings').inner_text()
                for said in ('以下内容一并保留', '图片', '表格', '公式', '参考文献', '已转换（篇）', '完整无缺', '转换有缺漏、出错，或想加出版社？'):
                    self.assertIn(said, text)
                page.locator('[data-act=pro_issue]').click()
                page.wait_for_function('issues === 1')
                # Pro's page by its old name is 关于 PaperSearch (user, 2026-11-21): bought, the icon Pro's and Pro beside the
                # name, no title of Pro's own; its state, what is coming, 提交 issue.
                page.evaluate("async () => { await act('back'); await act('settings_page', {dataset: {page: 'pro'}}); }")
                page.wait_for_selector('.about-hero')
                text = page.locator('.settings').inner_text()
                self.assertEqual(page.locator('.head .title').inner_text(), '设置')  # its head says 设置 alone (user, 2026-11-21)
                self.assertEqual(page.evaluate("[...document.querySelector('.about-name').childNodes].map((n) => n.textContent.trim()).filter(Boolean)"), ['PaperSearch', 'Pro'])
                self.assertEqual(page.locator('.about-hero .app-icon.pro').count(), 1)
                self.assertEqual(page.locator('.about-sec').count(), 0)
                for said in ('测试期间免费', '待定', '即将推出', 'Zotero 整合', '文献关系图', '用着有问题？'):
                    self.assertIn(said, text)
                self.assertEqual(page.locator('[data-act=install_pro]').count(), 0)
                # Nothing of paying for it (the feature 文献订阅, a subscription to papers, is not that).
                for word in ('订阅', 'key', '购买'):
                    self.assertNotIn(word, text.replace('文献订阅', ''))
                page.locator('[data-act=pro_issue]').click()
                page.wait_for_function('issues === 2')

                # Not bought (user, 2026-11-21, 乙): no rows that cannot be used; one row of Pro's, last, 需要激活, to
                # 关于 PaperSearch, which says what Pro does now and what is coming, then 激活 Pro.
                page.evaluate("async () => { pro = {ok:true, installed:false, version:''}; await act('back'); await loadSettings(); render(true); }")
                self.assertEqual(page.locator('[data-page=markdown]').count() + page.locator('[data-page=login]').count(), 0)
                pro_row = page.locator('.nav-row[data-page=about]')
                self.assertEqual(page.evaluate("[...document.querySelector('.nav-row[data-page=about] .nav-title').childNodes].map((n) => n.textContent.trim()).filter(Boolean)"), ['PaperSearch', 'Pro'])
                self.assertEqual(pro_row.locator('.nav-sub').inner_text(), '需要激活')
                self.assertEqual(pro_row.locator('.app-icon.pro').count(), 1)
                self.assertEqual(page.locator('.version-link').inner_text(), 'PaperSearch')
                # A feature's page (paper-search settings markdown) says it needs the activation, and leads to it;
                # nothing converted to report.
                page.evaluate("async () => { await act('settings_page', {dataset: {page: 'markdown'}}); }")
                page.wait_for_selector('.pro-needed')
                self.assertEqual(page.locator('.pro-needed span').inner_text(), '激活 PaperSearch Pro 后可用')
                self.assertEqual(page.locator('[data-act=pro_issue]').count(), 0)
                page.evaluate("() => { schoolLogin = {ok: true, pro: false}; settingsPage = 'login'; render(true); }")
                self.assertIn('学校登录页自动填写账号和密码', page.locator('.settings').inner_text())
                page.locator('.pro-needed [data-page=about]').click()
                page.wait_for_selector('[data-page=pro_activate]')
                # The plain icon and name at the top; Pro's part under it, its title with its icon and pill, its
                # features and what is coming (计划中 after each name), 激活 Pro at the foot (user, 2026-11-21).
                self.assertEqual(page.locator('.head .title').inner_text(), '设置')  # its head says 设置 alone (user, 2026-11-21)
                self.assertEqual(page.locator('.about-name').inner_text(), 'PaperSearch')
                self.assertEqual(page.locator('.about-hero .app-icon.pro').count(), 0)
                self.assertEqual(page.evaluate("[...document.querySelector('.about-sec').childNodes].map((n) => n.textContent.trim()).filter(Boolean)"), ['PaperSearch', 'Pro'])
                self.assertEqual(page.locator('.about-sec .app-icon.pro').count(), 1)
                # Nothing to report before Pro is there (user, 2026-11-21).
                self.assertEqual(page.locator('[data-act=pro_issue]').count() + page.locator('.pro-foot').count(), 0)
                self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('.about-hero')).alignItems"), 'center')
                self.assertEqual(page.locator('[data-page=pro_activate]').inner_text(), '激活 Pro')
                self.assertEqual(page.locator('.about-caption').inner_text(), '测试期间免费')
                self.assertEqual(page.locator('[data-act=install_pro]').count() + page.locator('#pro-code').count(), 0)
                self.assertEqual(page.locator('.about-feat b').all_inner_texts(), ['Markdown 全文', '学校自动登录', 'Zotero 整合', '文献关系图', '文献订阅'])
                self.assertEqual(page.locator('.pro-tag').all_inner_texts(), ['计划中', '计划中', '计划中'])
                self.assertTrue(page.evaluate("[...document.querySelectorAll('.about-feat')].slice(2).every((f) => f.firstElementChild.tagName === 'B'"
                                              " && f.children[1].classList.contains('pro-tag'))"))  # the name first, 计划中 after it
                self.assertEqual(page.locator('.pro-stats').count(), 0)

                # The activation's page: the code and 激活; back is Pro's page.
                page.locator('[data-page=pro_activate]').click()
                page.wait_for_selector('#pro-code')
                self.assertEqual(page.locator('.head .title').inner_text(), '激活 Pro')
                self.assertEqual(page.locator('[data-act=activate_pro]').inner_text(), '激活')
                page.locator('[data-act=back]').click()
                page.wait_for_selector('[data-page=pro_activate]')
                self.assertEqual(page.evaluate('settingsPage'), 'about')
                page.locator('[data-page=pro_activate]').click()
                page.wait_for_selector('#pro-code')

                # No code: asked for one, nothing sent.
                page.locator('[data-act=activate_pro]').click()
                page.wait_for_selector('.pro-code-err')
                self.assertEqual(page.locator('.pro-code-err').inner_text(), '请输入激活码')
                self.assertEqual(page.evaluate('installs'), 0)
                # Refused (or no activation server yet): why, under the code, which stays; typing again clears it.
                page.evaluate("""() => { pywebview.api.install_pro = async (code) => { installs++; window.sentCode = code;
                                         return {state: 'running', step: 'activate'}; }; installing = [{state: 'running', step: 'activate'}]; }""")
                page.locator('#pro-code').fill('PSPRO-7KQ2-M4XD')
                self.assertEqual(page.locator('.pro-code-err').count(), 0)
                page.locator('#pro-code').press('Enter')
                page.wait_for_function("document.querySelector('[data-act=activate_pro]')?.textContent === '正在激活…'")
                self.assertEqual(page.evaluate('sentCode'), 'PSPRO-7KQ2-M4XD')
                self.assertTrue(page.locator('[data-act=activate_pro]').is_disabled())
                page.evaluate("() => { installing = [{state: 'failed', step: 'activate', message: '激活服务还没开放'}]; }")
                page.wait_for_selector('.pro-code-err')
                self.assertEqual(page.locator('.pro-code-err').inner_text(), '激活服务还没开放')
                self.assertEqual(page.locator('[data-act=activate_pro]').inner_text(), '激活')
                self.assertEqual(page.locator('#pro-code').input_value(), 'PSPRO-7KQ2-M4XD')
                page.locator('#pro-code').press('End')
                page.keyboard.type('X')
                self.assertEqual(page.locator('.pro-code-err').count(), 0)

                # Taken: activated, then the install's progress, in place; installed, the home page with Pro's
                # features, and the link saying so (user, 2026-11-21).
                page.evaluate("() => { installing = [{state: 'running', step: 'activate'}, {state:'running', step: 'install', done: 1258291, total: 2306867}]; }")
                page.locator('[data-act=activate_pro]').click()
                page.wait_for_function("document.querySelector('#pro-progress')?.textContent === '正在下载 1.2 / 2.2 MB'")
                self.assertEqual(page.evaluate('installs'), 2)
                self.assertEqual(page.locator('[data-act=install_pro]').count() + page.locator('#pro-code').count(), 0)
                width = page.evaluate("parseFloat(document.querySelector('.pro-bar span').style.width)")
                self.assertAlmostEqual(width, 54.5, delta=0.2)
                page.evaluate("() => { pro = {ok:true, installed:true, version:'0.1.0'}; installing = [{state:'done', version:'0.1.0'}]; }")
                page.wait_for_selector('[data-page=markdown]')
                self.assertEqual(page.evaluate('settingsPage'), 'home')
                self.assertEqual(page.locator('.settings-note').inner_text(), 'PaperSearch Pro 已安装')
                self.assertEqual(page.locator('.nav-row[data-page=about]').count(), 0)
                self.assertEqual(page.locator('.pro-bar').count(), 0)

                # Activated, installed not: 安装; a failed one: why, and 重试; on the activation's page too.
                page.evaluate("""async () => { pro = {ok:true, installed:false, version:'', activation: {state: 'active', tail: 'M4XD', until: ''}};
                                  installing = []; await loadSettings(); settingsPage = 'home'; render(true); }""")
                self.assertEqual(page.locator('.nav-row[data-page=about] .nav-sub').inner_text(), '已激活 · 未安装')
                page.evaluate("() => { settingsPage = 'about'; render(true); }")
                page.wait_for_selector('[data-act=install_pro]')
                self.assertEqual(page.locator('[data-act=install_pro]').inner_text(), '安装')
                self.assertEqual(page.locator('#pro-code').count(), 0)
                page.evaluate("""async () => { installing = [{state:'running', done: 0, total: 0}]; await loadSettings(); render(true); }""")
                page.wait_for_selector('#pro-progress')
                self.assertEqual(page.locator('#pro-progress').inner_text(), '正在下载…')
                page.evaluate("() => { installing = [{state:'failed', message:'网络连接中断'}]; }")
                page.wait_for_selector('[data-act=install_pro]')
                self.assertEqual(page.locator('.pro-code-err').inner_text(), '安装没有完成：网络连接中断')
                self.assertEqual(page.locator('[data-act=install_pro]').inner_text(), '重试')
                self.assertEqual(page.locator('.pro-hint').count(), 0)
                page.evaluate("() => { settingsPage = 'pro_activate'; render(true); }")
                self.assertEqual(page.locator('.pro-code-err').inner_text(), '安装没有完成：网络连接中断')
                self.assertEqual(page.locator('[data-act=install_pro]').inner_text(), '重试')
                self.assertEqual(page.locator('#pro-code').count(), 0)

                # An activation run out (once there is a server): said, and the code asked for again.
                page.evaluate("""async () => { pro = {ok:true, installed:true, version:'0.1.0', activation: {state: 'expired', tail: 'M4XD', until: '2026-01-31'}};
                                  installing = []; await loadSettings(); settingsPage = 'home'; render(true); }""")
                page.locator('.version-link').click()
                page.wait_for_selector('[data-act=activate_pro]')
                self.assertEqual(page.locator('[data-act=activate_pro]').inner_text(), '重新激活')
                rows = page.evaluate("[...document.querySelectorAll('.pro-use')].map((r) => [...r.children].map((c) => c.textContent).join('|'))")
                self.assertEqual(rows, ['激活状态|已过期', '激活码|••••M4XD', '有效期|至 2026-01-31'])
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

    def test_the_sign_in_page_is_a_card_per_school_its_rarer_actions_in_a_menu(self):
        """User, 2026-11-22 (甲): the schools hard to tell apart in one list, each one's inside too busy, and the
        confirmation of 清除账号密码 moving the page down. A card per school, a gap between them, the open one marked; its
        last line 自动登录's switch and 保存; 设为默认, 清除账号密码 and 移除这所学校 in ⋯; a clearing asked again in that
        line's place, nothing below it moving; a press elsewhere closes the menu."""
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = self.drag_page(p, 'darwin')
            try:
                page.evaluate("""() => {
                    window.schools = [
                      {key: 'A', name: '红木兰大学', name_en: 'Hongmulan University', current: true, entity: true, saved: true,
                       username: '2******4', enabled: true, off: '', status: 'surveyed'},
                      {key: 'B', name: '蓝杉大学', name_en: 'Lanshan University', current: false, entity: true, saved: true,
                       username: 'l******n', enabled: true, off: '', status: 'surveyed'}];
                    window.cleared = [];
                    const state = () => ({ok: true, pro: true, switch: true, schools: [...schools], counts: {filled: 461, check: 287}, ...schools[0]});
                    Object.assign(pywebview.api, {
                        settings: async () => ({notify: true, download_dir: '/papers', language: 'zh', fields: []}),
                        api_keys: async () => ({ok: true, filled: 0, total: 0, groups: []}),
                        pro_status: async () => ({ok: true, installed: true, version: '0.3.4'}),
                        pro_install_state: async () => ({state: 'idle'}),
                        school_login_state: async () => state(),
                        school_login_saved: async (key) => ({username: key === 'A' ? '20261234' : 'lanshan-1', password: 'pw'}),
                        clear_school_login: async (key) => { cleared.push(key); const s = schools.find((x) => x.key === key);
                          Object.assign(s, {saved: false, username: '', enabled: false}); return state(); }});
                }""")
                page.evaluate("async () => { testState = {mode: 'idle'}; await tick(); await act('settings'); }")
                page.locator('[data-page=login]').click()
                page.wait_for_selector('#login-user')
                page.locator('.login-row[data-act=login_open]').nth(1).click()
                page.wait_for_function("document.querySelectorAll('.login-school.open').length === 1 && !root.classList.contains('animating')")
                cards = page.evaluate("""() => [...document.querySelectorAll('.login-list > .login-school')].map((c) => {
                    const r = c.getBoundingClientRect(), style = getComputedStyle(c);
                    return {top: r.top, bottom: r.bottom, open: c.classList.contains('open'), add: c.classList.contains('add'),
                            fill: style.backgroundColor, edge: style.boxShadow !== 'none' || style.borderStyle !== 'none'}; })""")
                self.assertEqual([(c['open'], c['add']) for c in cards], [(False, False), (True, False), (False, True)])
                for upper, lower in zip(cards, cards[1:]):
                    self.assertGreaterEqual(lower['top'] - upper['bottom'], 6)  # apart
                self.assertNotEqual(cards[0]['fill'], 'rgba(0, 0, 0, 0)')  # a closed school filled
                self.assertTrue(cards[1]['edge'] and cards[2]['edge'])     # the open one edged, 添加学校 dashed
                # Its last line: 自动登录 and 保存; nothing of the rarer actions until ⋯.
                self.assertEqual(page.locator('.login-school.open .login-foot').inner_text().split('\n')[0], '自动登录')
                self.assertEqual(page.get_attribute('.login-foot [data-act=login_switch]', 'aria-label'), '自动登录')
                self.assertEqual(page.locator('.ls-dots').count(), 1)
                self.assertEqual(page.locator('[data-act=clear_login]').count(), 0)
                page.locator('.ls-dots').click()
                self.assertEqual(page.locator('.ls-menu button').all_inner_texts(), ['设为默认', '清除账号密码', '移除这所学校'])
                page.mouse.click(30, 30)  # elsewhere: the menu closes
                page.wait_for_function("!document.querySelector('.ls-menu')")
                # The clearing asked again in its last line's place: the card and what follows it stay where they were.
                before = page.evaluate("[...document.querySelectorAll('.login-list > .login-school')].map((c) => [c.getBoundingClientRect().top, c.getBoundingClientRect().height])")
                page.locator('.ls-dots').click()
                page.locator('.ls-menu [data-act=clear_login]').click()
                page.wait_for_selector('.login-foot.asking')
                self.assertEqual(page.locator('.login-foot.asking .q').inner_text(), '清除账号和密码？')
                self.assertEqual(page.locator('.login-foot.asking .btn').all_inner_texts(), ['取消', '清除'])
                after = page.evaluate("[...document.querySelectorAll('.login-list > .login-school')].map((c) => [c.getBoundingClientRect().top, c.getBoundingClientRect().height])")
                self.assertEqual(after, before)
                page.locator('[data-act=cancel_confirm]').click()
                page.wait_for_selector('.login-foot [data-act=login_switch]')
                self.assertEqual(page.evaluate('cleared'), [])
                page.locator('.ls-dots').click()
                page.locator('.ls-menu [data-act=clear_login]').click()
                page.locator('.login-foot.asking [data-act=clear_login]').click()
                page.wait_for_function("cleared.length === 1")
                self.assertEqual(page.evaluate('cleared'), ['B'])
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
                # The default switched here, from ⋯ (user, 2026-11-22: 甲); the default one cannot be removed, another can.
                page.locator('.ls-dots').click()
                page.locator('.ls-menu [data-act=set_default]').click()
                page.wait_for_function("schools.find((s) => s.key === 'B').current")
                self.assertIn('蓝杉大学', page.locator('.login-row[data-act=login_open]').first.inner_text())
                self.assertEqual(page.locator('[data-act=forget_school]').count(), 0)
                page.locator('.login-row[data-act=login_open]').nth(1).click()
                page.wait_for_selector('.ls-dots')
                # Every school alike: 自动登录's switch and 保存 on its last line, the rarer actions in ⋯ (user, 2026-11-22: 甲).
                self.assertEqual(page.get_attribute('.login-foot [data-act=login_switch]', 'aria-label'), '自动登录')
                self.assertEqual(page.locator('.login-foot [data-act=save_login]').inner_text(), '保存')
                page.locator('.ls-dots').click()
                self.assertEqual(page.locator('.ls-menu button').all_inner_texts(), ['设为默认', '清除账号密码', '移除这所学校'])
                page.locator('.ls-menu [data-act=forget_school]').click()
                self.assertEqual(page.locator('.login-foot.asking .q').inner_text(), '移除这所学校？')
                page.locator('.login-foot.asking [data-act=forget_school]').click()
                page.wait_for_function("document.querySelectorAll('.login-row[data-act=login_open]').length === 1")
                # 支持哪些学校: a page of its own, how many of each kind, in two pages: the world's regions, each opening in
                # place to its countries (Asia first, China first in it), and a country's schools all together on a page of
                # their own (user, 2026-11-20, 2026-11-21), narrowed by what is typed.
                page.evaluate('''() => Object.assign(pywebview.api, {school_support_list: async () => ({ok: true, schools: [
                    {name: '红木兰大学', country: '中国', province: '广东', status: 'surveyed'},
                    {name: '蓝杉大学', country: '中国', province: '广东', status: 'check'},
                    {name: '白桦大学', country: '中国', province: '吉林', status: 'surveyed'},
                    {name: '香江大学', country: '香港', province: '', status: 'surveyed'},
                    {name: '木兰大学', name_en: 'Mulan University', country: '日本', province: '', status: 'surveyed'},
                    ...['樱', '枫', '松', '竹'].map((w) => ({name: w + '大学', country: '日本', province: '', status: 'surveyed'})),
                    {name: '西沼大学', country: '英国', province: '', status: 'surveyed'}]})})''')
                page.locator('[data-page=login_schools]').click()
                page.wait_for_selector('#support-list')
                self.assertEqual(page.locator('.stats b').all_inner_texts(), ['9', '1'])
                # The numbers say what they count; no line explaining them (user, 2026-11-21).
                self.assertNotIn('自动填写：打开学校登录页时', page.locator('body').inner_text())
                self.assertEqual(page.get_attribute('#support-filter', 'placeholder'), '搜索学校或地区')
                # In English (user, 2026-11-20): a school's English name (its country's and province's: test_i18n).
                self.assertEqual(page.evaluate("""() => { const kept = [lang, supportOpen]; lang = 'en'; supportOpen = '日本';
                    const html = supportListHtml(); [lang, supportOpen] = kept; return html.includes('Mulan University'); }"""), True)
                # Each school's name in the window's language (user, 2026-11-21): in Chinese its Chinese name where Pro has
                # one, else its own name, not a translation; in English its English name; found by any of them.
                self.assertEqual(page.evaluate("""() => { const kept = [lang, supportList, supportOpen];
                    supportList = {ok: true, schools: [
                      {name: 'Linden-Universität Bergtal', name_en: 'University of Bergtal', country: '德国',
                       names: {zh: '贝格塔尔大学', ja: 'ベルクタール大学'}, status: 'surveyed'},
                      {name: 'Hochschule Tannenfeld', name_en: 'Tannenfeld University', country: '德国', names: {}, status: 'surveyed'}]};
                    supportOpen = '德国'; const shown = {};
                    for (const code of ['zh', 'en', 'ja']) { lang = code; shown[code] = [...new DOMParser().parseFromString(
                      supportListHtml(), 'text/html').querySelectorAll('.ls-name')].map((n) => n.textContent).sort(); }
                    lang = 'zh'; supportFilter = 'ベルクタール'; shown.found = supportListHtml().includes('贝格塔尔大学'); supportFilter = '';
                    [lang, supportList, supportOpen] = kept; return shown; }"""),
                    {'zh': sorted(['贝格塔尔大学', 'Hochschule Tannenfeld']), 'en': sorted(['University of Bergtal', 'Tannenfeld University']),
                     'ja': sorted(['ベルクタール大学', 'Hochschule Tannenfeld']), 'found': True})
                # A big country's schools in parts on its page, each opening in place (user, 2026-11-21, 甲): a US school's
                # state, the most schools first, those without one last; a state's name finds its schools, each with its
                # state beside it. Germany's by kind in their order (Pro names no German states); a smaller country whole.
                self.assertEqual(page.evaluate("""() => { const kept = [supportList, supportOpen, supportParts];
                    const many = (country, area, kind, n) => Array.from({length: n}, (_, i) => ({name: (area || kind) + i, country,
                      province: '', area, kind, status: 'surveyed'}));
                    const parts = () => [...new DOMParser().parseFromString(supportListHtml(), 'text/html')
                      .querySelectorAll('[data-act=support_part]')].map((b) => [b.dataset.key, b.querySelector('.n').textContent]);
                    const rows = () => (supportListHtml().match(/class="login-found"/g) || []).length;
                    supportList = {ok: true, schools: [...many('美国', '纽约州', '大学', 100), ...many('美国', '加利福尼亚州', '大学', 150),
                      ...many('美国', '', '医院', 1), ...many('德国', '', '其他', 60), ...many('德国', '', '大学', 250),
                      ...many('德国', '', '研究机构', 45), ...many('法国', '', '大学', 300)]};
                    supportParts = new Set(); supportOpen = '美国'; const shown = {us: parts(), usRows: rows()};
                    supportParts = new Set(['纽约州']); shown.opened = rows();
                    supportFilter = '加利福尼亚'; const found = new DOMParser().parseFromString(supportListHtml(), 'text/html')
                      .querySelectorAll('.ls-name'); shown.found = [found.length, found[0].textContent]; supportFilter = '';
                    supportParts = new Set(); supportOpen = '德国'; shown.de = parts();
                    supportOpen = '法国'; shown.fr = [parts().length, rows()];
                    [supportList, supportOpen, supportParts] = kept; return shown; }"""),
                    {'us': [['加利福尼亚州', '150'], ['纽约州', '100'], ['未注明州', '1']], 'usRows': 0, 'opened': 100,
                     'found': [150, '加利福尼亚州0 · 加利福尼亚州'],
                     'de': [['大学', '250'], ['研究机构', '45'], ['其他', '60']], 'fr': [0, 300]})
                # A school in two federations, listed once by its country and its name as shown, with the better of what Pro
                # does for it; counted once (user, 2026-11-21: a university of Beijing's twice there).
                self.assertEqual(page.evaluate("""() => { const kept = [supportList, lang];
                    supportList = {ok: true, schools: [
                      {name: '蓝杉大学', country: '中国', province: '广东', status: 'check'},
                      {name: 'Lanshan University', name_en: 'Lanshan University', names: {zh: '蓝杉大学'}, country: '中国', province: '广东', status: 'surveyed'},
                      {name: '蓝杉大学', country: '台湾', status: 'surveyed'},
                      {name: 'Kirigaoka University', country: '日本', status: 'surveyed'}, {name: 'Kirigaoka University', country: '日本', status: 'surveyed'}]};
                    const once = supportSchools().map((s) => [s.country, schoolName(s), s.status]);
                    lang = 'en'; const english = supportSchools().length;
                    [supportList, lang] = kept; return [once, english]; }"""),
                    [[['中国', '蓝杉大学', 'surveyed'], ['台湾', '蓝杉大学', 'surveyed'], ['日本', 'Kirigaoka University', 'surveyed']], 4])
                self.assertEqual(page.locator('#support-list .reason').all_inner_texts(), ['亚洲', '欧洲'])
                # A region opens in place to its countries, the page and its title as they were; several may be open.
                page.locator('[data-act=support_region][data-key=欧洲]').click()
                page.wait_for_selector('[data-act=support_group][data-key=英国]')
                self.assertEqual(page.locator('.head .title').inner_text(), '支持的学校')
                self.assertEqual(page.get_attribute('[data-act=support_region][data-key=欧洲]', 'aria-expanded'), 'true')
                page.locator('[data-act=support_region][data-key=亚洲]').click()
                page.wait_for_selector('[data-act=support_group][data-key=中国]')
                self.assertEqual(page.locator('#support-list .reason').all_inner_texts(), ['亚洲', '中国', '日本', '欧洲', '英国'])
                self.assertEqual(page.locator('.stats').count(), 1)
                # A country: a page of its own, its schools; the numbers on the first page only.
                page.locator('[data-act=support_group][data-key=英国]').click()
                page.wait_for_selector('#support-list .login-found')
                self.assertEqual((page.locator('.head .title').inner_text(), page.locator('.head .sub').inner_text()), ('英国', '1 所'))
                self.assertEqual(page.locator('#support-list .ls-name').all_inner_texts(), ['西沼大学'])
                self.assertEqual(page.locator('.stats').count(), 0)
                self.assertEqual(page.get_attribute('#support-filter', 'placeholder'), '搜索学校')
                page.locator('[data-act=back]').click()
                page.wait_for_selector('[data-act=support_group][data-key=英国]')
                self.assertEqual(page.locator('.head .title').inner_text(), '支持的学校')
                self.assertEqual(page.locator('#support-list .reason').all_inner_texts(), ['亚洲', '中国', '日本', '欧洲', '英国'])
                # China: its provinces, the most schools first, then Hong Kong; each opens in place to its schools by name
                # (pinyin), the page where it was. Its search narrows China only, a province's name finding its schools,
                # each with its province beside it.
                page.locator('[data-act=support_group][data-key=中国]').click()
                page.wait_for_selector('[data-act=support_part]')
                self.assertEqual(page.locator('.head .title').inner_text(), '中国')
                self.assertEqual(page.locator('#support-list .reason').all_inner_texts(), ['广东', '吉林', '香港'])
                self.assertEqual(page.locator('#support-list .login-found').count(), 0)
                page.locator('[data-act=support_part][data-key=广东]').click()
                page.wait_for_selector('#support-list .login-found')
                self.assertEqual(page.locator('#support-list .ls-name').all_inner_texts(), ['红木兰大学', '蓝杉大学'])
                self.assertIn('需自己登录', page.locator('#support-list').inner_text())
                page.locator('[data-act=support_part][data-key=香港]').click()
                page.wait_for_function("document.querySelectorAll('#support-list .login-found').length === 3")
                page.locator('[data-act=support_part][data-key=广东]').click()
                page.wait_for_function("document.querySelectorAll('#support-list .login-found').length === 1")
                self.assertEqual(page.locator('#support-list .ls-name').all_inner_texts(), ['香江大学'])
                page.fill('#support-filter', '广东')
                self.assertEqual(page.locator('#support-list .ls-name').all_inner_texts(), ['红木兰大学 · 广东', '蓝杉大学 · 广东'])
                page.locator('[data-act=back]').click()
                page.wait_for_selector('[data-act=support_group][data-key=中国]')
                self.assertEqual(page.input_value('#support-filter'), '')
                self.assertEqual(page.evaluate('supportParts.size'), 0)  # closed again for the next country
                # Pressed again, a region closes; the other stays open.
                page.locator('[data-act=support_region][data-key=欧洲]').click()
                page.wait_for_function("!document.querySelector('[data-act=support_group][data-key=英国]')")
                self.assertEqual(page.locator('#support-list .reason').all_inner_texts(), ['亚洲', '中国', '日本', '欧洲'])
                # A long list, the window held to the screen's height: a region opened or closed leaves the page where it
                # was; a country's page starts at its top, and back finds the regions' page where it was; the head stays on
                # top while the list scrolls, a long name wraps, not cut; a press in the list drags nothing and leaves it
                # where it was, a redraw keeps its place (user, 2026-11-21).
                page.evaluate("""async () => { window.keptList = supportList;
                    pywebview.api.begin_layout = async (expanded, w, h) => ({vertical: 'down', horizontal: 'right', width: w,
                      height: Math.min(h, 520), from_width: parseFloat(root.style.width) + 20, from_height: parseFloat(root.style.height) + 20});
                    const every = SUPPORT_REGIONS.flatMap((region) => (SUPPORT_COUNTRIES[region] || '').split(' ').filter(Boolean));
                    supportList = {ok: true, schools: [...every.map((c) => ({name: c + '大学', country: c, status: 'surveyed'})),
                      ...Array.from({length: 120}, (_, i) => ({name: 'Hochschule für angewandte interdisziplinäre Wissenschaften und Künste Nummer ' + i,
                        country: '德国', status: 'surveyed'}))]};
                    supportRegions = new Set(); supportOpen = ''; supportBack = 0; render(true); }""")
                page.wait_for_function("!root.classList.contains('animating')")
                surface = "root.querySelector(':scope > .surface')"
                page.locator('[data-act=support_region][data-key=欧洲]').click()
                page.wait_for_function("supportRegions.has('欧洲') && !root.classList.contains('animating')")
                page.evaluate("document.querySelector('[data-act=support_region][data-key=北美洲]').scrollIntoView({block: 'center'})")
                region_top = page.evaluate(surface + '.scrollTop')
                self.assertGreater(region_top, 0)
                page.locator('[data-act=support_region][data-key=北美洲]').click()
                page.wait_for_function("supportRegions.has('北美洲') && !root.classList.contains('animating')")
                page.wait_for_timeout(200)
                self.assertLess(abs(page.evaluate(surface + '.scrollTop') - region_top), 2)
                key = page.locator('[data-act=support_group]').last.get_attribute('data-key')
                page.evaluate("k => document.querySelector(`[data-act=support_group][data-key='${k}']`).scrollIntoView({block: 'center'})", key)
                region_top = page.evaluate(surface + '.scrollTop')
                self.assertGreater(region_top, 0)
                page.locator(f'[data-act=support_group][data-key="{key}"]').click()
                page.wait_for_function(f"supportOpen === '{key}' && !root.classList.contains('animating')")
                self.assertEqual(page.evaluate(surface + '.scrollTop'), 0)
                page.locator('[data-act=back]').click()
                page.wait_for_function("supportOpen === '' && !root.classList.contains('animating')")
                page.wait_for_timeout(200)
                self.assertLess(abs(page.evaluate(surface + '.scrollTop') - region_top), 2)
                self.assertEqual(page.evaluate("[...supportRegions]"), ['欧洲', '北美洲'])
                page.locator('[data-act=support_group][data-key=德国]').click()
                page.wait_for_function("supportOpen === '德国' && !root.classList.contains('animating')")
                self.assertEqual(page.locator('#support-list .login-found').count(), 121)  # one of the countries' and 120
                page.evaluate("document.querySelectorAll('#support-list .login-found')[80].scrollIntoView({block: 'center'})")
                top = page.evaluate(surface + '.scrollTop')
                self.assertGreater(top, 0)
                self.assertLess(abs(page.evaluate("root.querySelector('.support-top').getBoundingClientRect().top - "
                                                  + surface + ".getBoundingClientRect().top")), 1)
                name = "document.querySelectorAll('#support-list .ls-name')[80]"
                self.assertGreater(page.evaluate(name + ".getBoundingClientRect().height"), 25)
                self.assertLessEqual(page.evaluate(name + ".scrollWidth - " + name + ".clientWidth"), 0)
                drags = page.evaluate('dragLocks.length')
                box = page.locator('#support-list .login-found').nth(80).bounding_box()
                page.mouse.click(box['x'] + 4, box['y'] + box['height'] / 2)
                page.wait_for_timeout(300)
                self.assertEqual(page.evaluate('dragLocks.length'), drags)
                self.assertLess(abs(page.evaluate(surface + '.scrollTop') - top), 2)
                page.evaluate("render(true)")
                page.wait_for_function("!root.classList.contains('animating')")
                page.wait_for_timeout(200)
                self.assertLess(abs(page.evaluate(surface + '.scrollTop') - top), 2)
                page.evaluate("() => { supportList = window.keptList; supportRegions = new Set(); supportOpen = ''; supportBack = 0; render(true); }")
                # Found across countries, each with its country.
                page.fill('#support-filter', '白桦')
                self.assertEqual(page.locator('#support-list .ls-name').all_inner_texts(), ['白桦大学 · 中国'])
                self.assertEqual(page.evaluate('document.activeElement.id'), 'support-filter')  # still typing there
                page.locator('[data-act=back]').click()
                page.wait_for_selector('[data-act=login_add]')
            finally:
                browser.close()

    def test_the_next_school_when_no_access_one_row_and_the_schools_numbered(self):
        # 没权限时换下一所学校 (user, 2026-11-21): with more than one school, the schools numbered in the order tried (1
        # the default) and one row with its switch, on by default, no note under it; one school alone, neither.
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = self.drag_page(p, 'darwin')
            try:
                page.evaluate("""() => {
                    window.calls = []; window.switchOn = true;
                    const one = {key: 'A', name: '红木兰大学', current: true, entity: true, saved: true, username: '2******4',
                                 enabled: true, off: '', status: 'surveyed'};
                    const two = {key: 'B', name: '白杨大学', current: false, entity: true, saved: true, username: '3******1',
                                 enabled: true, off: '', status: 'surveyed'};
                    window.schoolsNow = [one, two];
                    const state = () => ({ok: true, pro: true, schools: schoolsNow, counts: {}, switch: switchOn});
                    Object.assign(pywebview.api, {
                        settings: async () => ({notify: true, download_dir: '/papers', language: 'zh', fields: []}),
                        api_keys: async () => ({ok: true, filled: 0, total: 0, groups: []}),
                        pro_status: async () => ({ok: true, installed: true, version: '0.3.3'}),
                        pro_install_state: async () => ({state: 'idle'}),
                        school_login_state: async () => state(),
                        set_school_switch: async (on) => { calls.push(['switch', on]); switchOn = on; return state(); }});
                }""")
                page.evaluate("async () => { testState = {mode: 'idle'}; await tick(); await act('settings'); }")
                page.locator('[data-page=login]').click()
                page.wait_for_selector('.switch-row')
                self.assertEqual(page.locator('.login-row .ls-n').all_inner_texts(), ['1', '2'])
                self.assertEqual(page.locator('.switch-row > span').inner_text(), '没权限时换下一所学校')
                self.assertEqual(page.get_attribute('[data-act=school_switch]', 'aria-checked'), 'true')
                # One line, a switch of its usual size (the first drawing stretched it, user 2026-11-21).
                size = page.evaluate("""() => { const row = document.querySelector('.switch-row'), sw = row.querySelector('.switch');
                    const text = row.querySelector('span').getBoundingClientRect();
                    return [sw.getBoundingClientRect().width, Math.round(text.height), row.children.length]; }""")
                self.assertEqual(size[0], 34)
                self.assertLess(size[1], 24)
                self.assertEqual(size[2], 2)
                # One line between it and the schools above, not two.
                self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('.switch-row')).borderTopStyle"), 'none')
                page.locator('[data-act=school_switch]').click()
                page.wait_for_function("document.querySelector('[data-act=school_switch]').getAttribute('aria-checked') === 'false'")
                self.assertEqual(page.evaluate('calls'), [['switch', False]])
                # One school: nothing to switch to.
                page.evaluate("async () => { schoolsNow = schoolsNow.slice(0, 1); schoolLogin = await pywebview.api.school_login_state(); render(true); }")
                page.wait_for_function("!document.querySelector('.switch-row')")
                self.assertEqual(page.locator('.login-row .ls-n').count(), 0)
            finally:
                browser.close()

    def test_the_settings_fit_in_languages_that_say_them_longer(self):
        """User, 2026-11-25 (French on the Mac): the key editor's Save cut off at the window's edge and the key list
        scrolling sideways; a service's note in an ellipsis; a school's English name cut to "Hongmulan …" by its tags.
        Linux's fonts are narrower than the Mac's: the editor's buttons drawn larger here, as wide as there."""
        from patchright.sync_api import sync_playwright
        from paper_search_school import api_keys
        listing = {'ok': True, 'filled': 1, 'total': 1, 'groups': [
            {'title': g['title'], 'services': [{**s, 'guide': s.get('guide', ''), 'guide_label': s.get('guide_label', ''),
             'signup_label': s.get('signup_label', ''), 'set': True, 'masked': '••••9362',
             'keys': [{**k, 'kind': k.get('kind', 'key'), 'set': True, 'masked': '••••9362'} for k in s['keys']]}
             for s in g['services']]} for g in api_keys.groups()]}
        fits = """() => { const list = root.querySelector('.keys-scroll'), edit = root.querySelector('.key-edit').getBoundingClientRect();
            const notes = [...root.querySelectorAll('.key-row .nav-sub')].filter((n) => n.scrollWidth > n.clientWidth + 1);
            return {sideways: list.scrollWidth - list.clientWidth, notes: notes.map((n) => n.textContent),
                    out: [...root.querySelectorAll('.key-actions .btn')].filter((b) => b.getBoundingClientRect().right > edit.right + 0.5)
                         .map((b) => b.textContent)}; }"""
        with sync_playwright() as p:
            for lang in ('fr', 'en', 'zh'):
                with self.subTest(lang=lang):
                    browser, page = self.drag_page(p, 'darwin', english=True)
                    try:
                        page.evaluate("""([lang, listing]) => { Object.assign(pywebview.api, {
                            settings: async () => ({notify: true, download_dir: '/papers', language: lang, fields: []}),
                            api_keys: async () => listing, api_key_values: async () => ({ok: true, values: {}})});
                            const wide = document.createElement('style'); wide.textContent = '.key-actions .btn { font-size: 13.5px; }';
                            document.head.appendChild(wide); testState = {...testState, mode: 'idle', lang: lang}; }""", [lang, listing])
                        page.evaluate("async () => { await tick(); await act('settings'); await act('settings_page', {dataset: {page: 'keys'}}); }")
                        page.wait_for_function("!root.classList.contains('animating')")
                        page.locator('.key-row[data-service="yescaptcha"]').click()
                        page.wait_for_function("!root.classList.contains('animating') && document.querySelector('.key-edit')")
                        self.assertEqual(page.evaluate(fits), {'sideways': 0, 'notes': [], 'out': []})
                        # Where they fit, on one line as before.
                        tops = page.evaluate("[...root.querySelectorAll('.key-actions .btn')].map((b) => Math.round(b.getBoundingClientRect().top))")
                        if lang == 'zh':
                            self.assertEqual(len(set(tops)), 1, tops)
                    finally:
                        browser.close()
            for lang, name, whole in (('en', 'Hongmulan University of Science and Technology', True), ('zh', '红木兰大学', False)):
                with self.subTest(lang=lang, school=name):
                    browser, page = self.drag_page(p, 'darwin', english=True)
                    try:
                        page.evaluate("""([lang, name]) => {
                            const one = {key: 'A', name: '红木兰大学', name_en: name, current: true, entity: true, saved: true,
                                         username: '2******4', enabled: true, off: '', status: 'surveyed'};
                            const two = {key: 'B', name: '蓝杉大学', name_en: 'Lanshan University', current: false, entity: true,
                                         saved: false, username: '', enabled: false, off: '', status: 'check'};
                            const state = () => ({ok: true, pro: true, schools: [one, two], counts: {}, switch: true});
                            Object.assign(pywebview.api, {
                                settings: async () => ({notify: true, download_dir: '/papers', language: lang, fields: []}),
                                api_keys: async () => ({ok: true, filled: 0, total: 0, groups: []}),
                                pro_status: async () => ({ok: true, installed: true, version: '0.4.0'}),
                                pro_install_state: async () => ({state: 'idle'}),
                                school_login_state: async () => state(), school_login_saved: async () => ({username: '20261234', password: 'pw'})});
                            testState = {...testState, mode: 'idle', lang: lang}; }""", [lang, name])
                        page.evaluate("async () => { await tick(); await act('settings'); await act('settings_page', {dataset: {page: 'login'}}); }")
                        page.wait_for_selector('.ls-dots')  # the default school's card open, the other closed
                        page.wait_for_function("!root.classList.contains('animating')")
                        seen = page.evaluate("""() => [...root.querySelectorAll('.ls-head')].map((head) => {
                            const r = head.getBoundingClientRect(), named = head.querySelector('.ls-name');
                            const dots = head.parentNode.querySelector('.ls-dots'), d = dots && dots.getBoundingClientRect();
                            const parts = [...head.children].map((c) => c.getBoundingClientRect()).filter((b) => b.height);
                            return {name: named.textContent, cut: named.scrollWidth > named.clientWidth + 1,
                                    lines: new Set(parts.map((b) => Math.round(b.top + b.height / 2))).size,
                                    inside: parts.every((b) => b.right <= r.right + 0.5),
                                    clear: !d || [...head.querySelectorAll('.ls-name, .tag')].map((t) => t.getBoundingClientRect())
                                      .every((b) => b.right <= d.left || b.top >= d.bottom)}; })""")
                        self.assertEqual(seen[0]['name'], name)
                        for card in seen:
                            self.assertFalse(card['cut'], card)
                            self.assertTrue(card['inside'], card)
                            self.assertTrue(card['clear'], card)  # nothing under ⋯
                        if whole:
                            self.assertGreater(seen[0]['lines'], 1, seen)  # its tags under the name
                        else:
                            self.assertEqual([card['lines'] for card in seen], [1, 1], seen)  # as before
                    finally:
                        browser.close()

    def test_a_schools_sign_in_tested_from_its_page(self):
        # 测试登录 (user, 2026-11-21, as drawn): the article it opens, set by the user (乙: its DOI and 修改, a DOI or the
        # article's address; none set for them, its box open), changed fields saved first, the steps while it runs in
        # rows that do not move, 停止测试, then how it went.
        from patchright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = self.drag_page(p, 'darwin', english=True)
            try:
                page.evaluate("""() => {
                    window.calls = []; window.testNow = {state: 'idle'};
                    const school = {key: 'A', name: '红木兰大学', current: true, entity: true, saved: true, username: '2******4',
                                    enabled: true, off: '', status: 'surveyed'};
                    const state = () => ({ok: true, pro: true, schools: [school], counts: {}, ...school});
                    Object.assign(pywebview.api, {
                        settings: async () => ({notify: true, download_dir: '/papers', language: 'zh', fields: []}),
                        api_keys: async () => ({ok: true, filled: 0, total: 0, groups: []}),
                        pro_status: async () => ({ok: true, installed: true, version: '0.3.2'}),
                        pro_install_state: async () => ({state: 'idle'}),
                        school_login_state: async () => state(),
                        school_login_saved: async () => ({username: '20261234', password: 'pw-a'}),
                        save_school_login: async (u, pw, on, key) => { calls.push(['save', u, pw, key]); return state(); },
                        school_test_article: async (key) => ({ok: true, doi: ''}),
                        set_school_test_article: async (key, text) => { calls.push(['article', key, text]);
                            return text.includes('wiley') ? {ok: true, doi: '10.1111/dom.15869'}
                              : {ok: false, error: '认不出这篇文章：请填 DOI 或文章网址'}; },
                        start_school_test: async (key, doi) => { calls.push(['start', key, doi]);
                            testNow = {state: 'running', key, doi, step: 0, phase: ''}; return testNow; },
                        school_test_state: async () => testNow,
                        stop_school_test: async () => { calls.push(['stop']); testNow = {...testNow, stopping: true}; return testNow; }});
                }""")
                page.evaluate("async () => { testState = {mode: 'idle'}; await tick(); await act('settings'); }")
                page.locator('[data-page=login]').click()
                # None set: a short line saying what to do, 填写, and the test's button 测试 at the line's end, beside its
                # article (甲); 测试 opens the box and asks for one. 账号, 密码 and 文章 end alike on the right, the eye inside
                # the password's box (user, 2026-11-21).
                page.wait_for_selector('.test-article .what.empty')
                self.assertEqual(page.locator('.test-article .what').inner_text(), '填入学校订阅文章 DOI 或网址')
                self.assertEqual(page.evaluate("document.querySelector('.test-article .what').scrollWidth <= document.querySelector('.test-article .what').clientWidth"), True)  # one line, whole
                self.assertEqual(page.locator('[data-act=test_article_edit]').inner_text(), '填写')
                self.assertEqual(page.locator('.test-article [data-act=school_test]').inner_text(), '测试')
                self.assertEqual(page.locator('.login-foot [data-act=save_login]').inner_text(), '保存')
                self.assertEqual(page.get_attribute('.login-foot [data-act=login_switch]', 'aria-checked'), 'true')
                edges = "['#login-user', '#login-password', '[data-act=school_test]'].map((q) => Math.round(document.querySelector(q).getBoundingClientRect().right))"
                self.assertEqual(len(set(page.evaluate(edges))), 1)
                page.locator('[data-act=school_test]').click()
                page.wait_for_selector('.test-err')
                self.assertEqual(page.locator('.test-err').inner_text(), '先填测试文章')
                self.assertEqual(page.evaluate('document.activeElement.id'), 'test-article')
                self.assertEqual(page.input_value('#test-article'), '')
                self.assertEqual(page.get_attribute('#test-article', 'placeholder'), 'DOI 或文章网址')
                self.assertEqual(len(set(page.evaluate(edges))), 1)
                page.press('#test-article', 'Escape')
                page.wait_for_selector('.test-article .what.empty')
                # One not recognised said so, the box kept open; one taken shown with 修改, which opens it again.
                page.locator('[data-act=test_article_edit]').click()
                page.fill('#test-article', '那篇')
                page.press('#test-article', 'Enter')
                page.wait_for_function("document.querySelector('.test-err')?.textContent === '认不出这篇文章：请填 DOI 或文章网址'")
                # While it looks the article up, 查找中… beside the text, not over it (user, 2026-11-21).
                page.fill('#test-article', 'https://linkinghub.elsevier.com/retrieve/pii/S0883540324006557')
                page.evaluate("() => { testArticleText = document.querySelector('#test-article').value; testArticleSaving = true; render(true); }")
                page.wait_for_function("document.querySelector('[data-act=test_article_save]').disabled")
                gap = page.evaluate("""() => { const box = document.querySelector('.test-edit'), input = box.querySelector('input'),
                    button = box.querySelector('[data-act=test_article_save]');
                    return [button.getBoundingClientRect().left - input.getBoundingClientRect().right,
                            box.getBoundingClientRect().right - button.getBoundingClientRect().right]; }""")
                self.assertGreaterEqual(gap[0], 0)  # the text ends before the button
                self.assertGreaterEqual(gap[1], 0)  # the button inside the box
                self.assertEqual(page.locator('[data-act=test_article_save]').inner_text(), '查找中…')
                page.evaluate("() => { testArticleSaving = false; render(true); }")
                page.fill('#test-article', 'https://onlinelibrary.wiley.com/doi/full/10.1111/dom.15869')
                page.locator('[data-act=test_article_save]').click()
                page.wait_for_function("!document.querySelector('#test-article')")
                self.assertEqual(page.locator('.test-article .what').inner_text(), '10.1111/dom.15869')
                self.assertEqual(page.get_attribute('[data-act=test_article_edit]', 'aria-label'), '修改')  # a pencil (user, 2026-11-22)
                page.locator('[data-act=test_article_edit]').click()
                self.assertEqual(page.input_value('#test-article'), '10.1111/dom.15869')
                page.press('#test-article', 'Escape')
                page.wait_for_function("!document.querySelector('#test-article')")
                self.assertEqual(page.locator('.head .title').inner_text(), '学校自动登录')  # Esc left the page where it was
                # The test uses the account as saved: a password typed since is saved first.
                page.fill('#login-password', 'pw-new')
                page.locator('[data-act=school_test]').click()
                page.wait_for_selector('.test-steps')
                self.assertEqual(page.evaluate('calls.slice(2)'), [['save', '20261234', 'pw-new', 'A'], ['start', 'A', '10.1111/dom.15869']])
                self.assertEqual(page.locator('#login-user').count(), 0)  # the steps in the form's place, as drawn
                self.assertEqual(page.locator('.test-steps li').all_inner_texts(), ['打开文章页', '学校登录', '下载全文', '核对 PDF'])
                self.assertEqual(page.locator('.test-steps li.now').inner_text(), '打开文章页')
                height = page.evaluate("document.querySelector('.login-test').getBoundingClientRect().height")
                page.evaluate("testNow = {...testNow, step: 1, phase: '等待在浏览器完成机构登录：学校的页面要你自己操作时，在下载浏览器里完成，完成后会继续下载'}")
                page.wait_for_function("document.querySelector('.test-steps li.now')?.textContent === '学校登录'")
                self.assertEqual(page.locator('.test-steps li.done').count(), 1)
                self.assertTrue(page.locator('.test-phase').inner_text().startswith('等待在浏览器完成机构登录'))
                self.assertEqual(page.evaluate("document.querySelector('.login-test').getBoundingClientRect().height"), height)
                page.locator('[data-act=school_test_stop]').click()
                page.wait_for_function("document.querySelector('.test-phase')?.textContent === '正在停止…'")
                self.assertEqual(page.evaluate('calls.at(-1)'), ['stop'])
                self.assertTrue(page.locator('[data-act=school_test_stop]').is_disabled())
                # How it went: above the article, the form back.
                page.evaluate("testNow = {state: 'done', key: 'A', doi: '10.1111/dom.15869', ok: true, title: '登录和下载都正常', detail: '自动填写了账号密码，全文已下载并核对', seconds: 38}")
                page.wait_for_selector('.test-result.ok')
                self.assertEqual(page.locator('.test-result').inner_text().split('\n'),
                                 ['登录和下载都正常', '自动填写了账号密码，全文已下载并核对', '用时 38 秒 · 测试下的 PDF 已删掉'])
                self.assertEqual(page.locator('#login-user').count(), 1)
                page.evaluate("() => { testNow = {state: 'done', key: 'A', ok: false, title: '学校说密码不对', detail: '自动登录已关闭；改好密码后保存，再测一次', seconds: 20}; schoolTest = testNow; render(true); }")
                page.wait_for_selector('.test-result.bad')
                self.assertNotIn('用时', page.locator('.test-result').inner_text())
                # In English, its words from the table.
                page.evaluate("() => { lang = 'en'; render(true); }")
                self.assertEqual(page.locator('.test-result .t').inner_text(), 'Password refused')
                self.assertEqual(page.locator('[data-act=school_test]').inner_text(), 'Test')
            finally:
                browser.close()

    def test_no_text_cut_short_on_any_settings_page_in_any_language(self):
        # User, 2026-11-21: in English the home page's folder line and Pro's line ended in "…". Every settings page, in
        # each language, with values as long as real ones: no line of text cut short (one meant to be, with its whole
        # text in its title, aside). A text added to the windows must fit in every language.
        from patchright.sync_api import sync_playwright
        scan = """() => [...root.querySelectorAll('*')].filter((el) => {
            const st = getComputedStyle(el);
            return el.offsetParent && !el.title && el.children.length < 3 && !['INPUT', 'TEXTAREA'].includes(el.tagName)
              && (st.textOverflow === 'ellipsis' || st.whiteSpace === 'nowrap') && el.scrollWidth > el.clientWidth + 1;
          }).map((el) => el.textContent.trim().slice(0, 80))"""
        with sync_playwright() as p:
            for code in ('en', 'zh-Hant', 'zh', 'ja', 'ko', 'fr'):
                browser, page = self.drag_page(p, 'darwin', english=True)
                try:
                    page.evaluate("""() => { Object.assign(pywebview.api, {
                        settings: async () => ({notify: true, download_dir: '/Users/alexandria/Downloads', language: 'zh', fields: [
                          {name: 'hourly', label: '每家出版社每小时最多', value: 200, default: 200, page: 'download'},
                          {name: 'login', label: '学校登录最多等', value: 180, default: 180, page: 'wait'}]}),
                        api_keys: async () => ({ok: true, filled: 12, total: 12, groups: []}),
                        pro_status: async () => ({ok: true, installed: true, version: '0.13.12', access: {mode: 'free'}, converted: 12858,
                          sites: Array.from({length: 40}, (_, i) => ({name: 'site' + i}))}),
                        pro_install_state: async () => ({state: 'idle'}),
                        school_login_state: async () => ({ok: true, pro: true, counts: {}, school: '红木兰大学', saved: true,
                          username: 'x*****5', enabled: true, schools: [{key: 'A', name: '红木兰大学', current: true, entity: true,
                          saved: true, username: 'x*****5', enabled: true, off: '', status: 'surveyed'}]}),
                        school_login_saved: async () => ({username: '20261234', password: 'pw'}),
                        school_test_article: async () => ({ok: true, doi: ''}), school_test_state: async () => ({state: 'idle'}),
                        school_support_list: async () => ({ok: true, schools: [
                          {key: 'B', name: '蓝杉大学', country: '中国', province: '广东', status: 'surveyed'}]})}); }""")
                    page.evaluate("async () => { testState = {mode: 'idle'}; await tick(); await act('settings'); }")
                    page.evaluate("code => { lang = code; render(true); }", code)
                    for name in ('home', 'about', 'download', 'wait', 'keys', 'markdown', 'login', 'login_schools'):
                        with self.subTest(language=code, page=name):
                            if name != 'home':
                                page.evaluate("async (name) => { settingsPage = 'home'; await act('settings_page', {dataset: {page: name}}); }", name)
                            page.wait_for_timeout(150)
                            self.assertEqual(page.evaluate(scan), [])
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
                # Its version and updates, nothing of Pro's.
                page.locator('.version-link').click()
                page.wait_for_selector('.about-hero')
                self.assertEqual(page.locator('.about-sec').count() + page.locator('.pro-pill').count()
                                 + page.locator('.about-feat').count() + page.locator('.app-icon.pro').count(), 0)
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

    def test_japanese_korean_and_french_leave_no_chinese(self):
        # User, 2026-11-21: Japanese, Korean and French as well. Their cards and settings pages say nothing in Chinese:
        # in Korean and French no Chinese character at all, in Japanese none that only simplified Chinese writes. (Its schools'
        # own names are not Chinese: a school's own name is shown where it has none in the language.)
        from patchright.sync_api import sync_playwright
        from paper_search_school.progress_view import view
        import time
        now = time.time()
        running = dict(status='running', run_id='r', current='10.1000/x', title='Test article', publisher='Test',
                       journal='Spine', total=3, done=1, success=1, failed=0, content='both', part='main', stage='fetching_pdf')
        cards = {'running': view(running, now),
                 'switching': view({**running, 'stage': 'switching_school', 'phase': '没权限，换Hongmulan University'}, now),
                 'done': view({**running, 'status': 'done', 'done': 3, 'failed': 1, 'results': {
                     'content': 'both', 'main': 2, 'supplements': 1, 'sources': [['机构下载', 2]],
                     'failures': [{'cls': 'no_access', 'reason': '2 所学校都没有权限', 'journal': 'Spine', 'title': 'Other', 'doi': '10.1000/y'}],
                     'supplement_failures': []}}, now)}
        simplified = ''.join(sorted(__import__('test_i18n').SIMPLIFIED_ONLY))
        with sync_playwright() as p:
            for code in ('ja', 'ko', 'fr'):
                pattern = f'[{simplified}]+' if code == 'ja' else '[一-鿿]+'
                leftover = """(pattern) => { const attributes = [...root.querySelectorAll('[aria-label], [title], [placeholder]')]
                    .flatMap((e) => ['aria-label', 'title', 'placeholder'].map((n) => e.getAttribute(n) || ''));
                    return [root.innerText, ...attributes].join('\\n').replace('简体中文', '').replace('繁體中文', '').match(new RegExp(pattern, 'g')); }"""
                browser, page = self.drag_page(p, 'darwin', english=True)
                try:
                    for name, state in cards.items():
                        with self.subTest(language=code, card=name):
                            page.evaluate("async ([s, code]) => { clearInterval(pollTimer); testState = {...s, lang: code}; open = true; panel = '';"
                                          " await tick(); render(true); }", [state, code])
                            page.wait_for_function("!root.classList.contains('animating')")
                            self.assertIsNone(page.evaluate(leftover, pattern))
                    page.evaluate("""code => Object.assign(pywebview.api, {
                        settings: async () => ({notify: true, download_dir: '/papers', language: code, fields: [
                          {name: 'hourly', label: '每家出版社每小时最多', unit: '篇', value: 200, default: 200, page: 'download'},
                          {name: 'login', label: '学校登录页最多等', unit: '秒', value: 180, default: 180, page: 'wait'}]}),
                        api_keys: async () => ({ok: true, filled: 3, total: 12, groups: []}),
                        pro_status: async () => ({ok: true, installed: true, version: '0.3.4', access: {mode: 'free'}, converted: 12,
                          sites: [{name: 'site'}]}),
                        pro_install_state: async () => ({state: 'idle'}),
                        school_login_state: async () => ({ok: true, pro: true, counts: {}, switch: true, schools: [
                          {key: 'A', name: 'Hongmulan University', name_en: 'Hongmulan University', current: true, entity: true, saved: true,
                           username: 'x*****5', enabled: true, off: '', status: 'surveyed'},
                          {key: 'B', name: 'Lanshan University', name_en: 'Lanshan University', current: false, entity: true, saved: true,
                           username: 'y*****1', enabled: true, off: '', status: 'surveyed'}]}),
                        school_login_saved: async () => ({username: '20261234', password: 'pw'}),
                        school_test_article: async () => ({ok: true, doi: ''}), school_test_state: async () => ({state: 'idle'}),
                        school_support_list: async () => ({ok: true, schools: [
                          {key: 'B', name: 'Lanshan University', name_en: 'Lanshan University', country: '中国', province: '广东', status: 'surveyed'}]})})""", code)
                    page.evaluate("async code => { testState = {mode: 'idle', lang: code}; await tick(); await act('settings'); lang = code; render(true); }", code)
                    for name in ('home', 'about', 'download', 'wait', 'keys', 'markdown', 'login', 'login_schools'):
                        with self.subTest(language=code, page=name):
                            if name != 'home':
                                page.evaluate("async (name) => { settingsPage = 'home'; await act('settings_page', {dataset: {page: name}}); }", name)
                            page.wait_for_timeout(150)
                            self.assertIsNone(page.evaluate(leftover, pattern))
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
                'supplement_failures': [{'cls': 'unsupported', 'reason': '附录暂未适配', 'title': 'Third', 'doi': '10.1000/z'}]}}, now),
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
                # The about page's Pro while Pro is not here, installing, or failed to install.
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
                        page.evaluate("async () => { await loadSettings(); settingsPage = 'about'; render(true); }")
                        page.wait_for_function("!root.classList.contains('animating')")
                        self.assertIsNone(page.evaluate(leftover))
                        if name == 'installing':
                            self.assertIn('Downloading 1.2 / 2.2 MB', page.locator('.settings').inner_text())
                        page.evaluate("() => clearInterval(proInstallTimer)")
            finally:
                browser.close()

    @staticmethod
    def drag_page(playwright, platform='darwin', english=False, scale=1):
        from pathlib import Path
        import time
        import webview
        from paper_search_school.progress_view import view
        state = view(dict(status='running', current='10.1000/drag', title='Drag test article', publisher='Test',
                          total=3, done=0, success=0, failed=0, stage='fetching_pdf', started_at=time.time()), time.time())
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        page = page_world(browser.new_page(viewport={'width': 800, 'height': 800}, device_scale_factor=scale))
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
