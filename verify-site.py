import sys, json
from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv)>1 else "https://www.jkrsolutions.net"
OUT = "."

results = []
def check(name, ok, detail=""):
    results.append((ok, name, detail))
    print(("PASS " if ok else "FAIL ") + name + (("  -- " + str(detail)) if detail else ""))

with sync_playwright() as pw:
    b = pw.chromium.launch()
    page = b.new_page(viewport={"width":1440,"height":900})

    errors, pageerrors = [], []
    page.on("console", lambda m: errors.append(m.text) if m.type=="error" else None)
    page.on("pageerror", lambda e: pageerrors.append(str(e)))

    page.goto(URL, wait_until="networkidle")

    # ---------- console health ----------
    check("no uncaught page errors", len(pageerrors)==0, pageerrors[:3])
    check("no console errors", len(errors)==0, errors[:3])

    # ---------- structure ----------
    cards = page.locator("[data-carousel]")
    check("7 project carousels present", cards.count()==7, cards.count())

    prod = page.locator("#work .grid").nth(0).locator("[data-carousel]")
    conc = page.locator("#work .grid").nth(1).locator("[data-carousel]")
    check("4 client-work cards", prod.count()==4, prod.count())
    check("3 in-house cards", conc.count()==3, conc.count())
    check("3 in-house chips", page.locator(".concept-chip").count()==3,
          page.locator(".concept-chip").count())

    # honesty: old overclaim must be gone
    body = page.inner_text("body")
    check("old overclaim removed", "Every product here runs in production" not in body)
    check("'Client Story' present", "client story" in body.lower())
    check("'Six ways' heading correct", "Six ways we grow" in body)
    check("'Five ways' gone", "Five ways" not in body)

    # ---------- fisheye animation gone ----------
    css_has_fi = page.evaluate("""() => {
      for (const s of document.styleSheets) {
        let rules; try { rules = s.cssRules } catch(e) { continue }
        for (const r of rules||[]) if ((r.cssText||'').includes('fi-in')) return true;
      }
      return false;
    }""")
    check("fisheye keyframes removed", not css_has_fi)

    # ---------- carousel survives auto-advance ----------
    # Regression: a slides/dots count mismatch used to throw inside the 3.8s
    # interval, stripping .active and blanking every card permanently.
    parity = page.evaluate("""() => document.querySelectorAll('[data-carousel]').length
      && [...document.querySelectorAll('[data-carousel]')].map(c => ({
           key: c.dataset.carousel,
           slides: c.querySelectorAll('.carousel-slide').length,
           dots: c.querySelectorAll('.carousel-dots button').length
         })).filter(o => o.slides !== o.dots);""")
    check("every carousel has 1 dot per slide", parity==[], parity)

    page.wait_for_timeout(13000)          # ~3 auto-advances
    blank = page.evaluate("""() => [...document.querySelectorAll('[data-carousel]')]
      .filter(c => !c.querySelector('.carousel-slide.active'))
      .map(c => c.dataset.carousel);""")
    check("no card blanked after auto-advance", blank==[], blank)
    check("still no console errors after advancing", len(errors)==0, errors[:3])

    # ---------- open detail modal ----------
    page.locator('[data-carousel="billing"] .carousel-expand').click(force=True)
    page.wait_for_selector("#pm:not(.hidden)", timeout=4000)
    check("modal opens", page.locator("#pm").is_visible())
    check("modal title correct", page.inner_text("#pmTitle").strip()=="JKR Billing",
          page.inner_text("#pmTitle"))
    feats = page.locator("#pmFeatures .pm-feat").count()
    check("billing has 5 features", feats==5, feats)
    mets = page.locator("#pmMetrics .pm-metric").count()
    check("billing shows 3 metrics", mets==3, mets)
    check("metrics block visible", page.locator("#pmMetricsWrap").is_visible())
    check("body scrolls not clipped",
          page.evaluate("()=>{const b=document.querySelector('.pm-body');return b.scrollHeight>b.clientHeight}"))

    # image must be inside the panel (the min-height:0 bug)
    geom = page.evaluate("""() => {
      const m = document.querySelector('.pm-media').getBoundingClientRect();
      const p = document.querySelector('.pm-panel').getBoundingClientRect();
      const s = document.querySelector('#pmShots').getBoundingClientRect();
      return {mediaBottom:m.bottom, panelBottom:p.bottom,
              shotTop:s.top, shotBottom:s.bottom,
              mediaTop:m.top, mediaH:m.height, panelH:p.height};
    }""")
    check("media column fits panel", abs(geom["mediaH"]-geom["panelH"])<3, geom)
    slack_top = geom["shotTop"]-geom["mediaTop"]
    slack_bot = geom["mediaBottom"]-geom["shotBottom"]
    check("screenshot vertically centred", abs(slack_top-slack_bot)<40,
          f"top gap {slack_top:.0f} vs bottom gap {slack_bot:.0f}")

    page.screenshot(path=OUT+r"\pw-modal-desktop.png")

    # arrows advance
    first = page.locator(".pm-shot.active").get_attribute("src")
    page.click("#pmNext")
    page.wait_for_timeout(600)
    second = page.locator(".pm-shot.active").get_attribute("src")
    check("next arrow changes screenshot", first!=second, f"{first} -> {second}")

    # nested lightbox
    page.click("#pmZoom")
    page.wait_for_timeout(400)
    check("'View full size' opens lightbox", page.locator("#lb").is_visible())
    page.keyboard.press("Escape"); page.wait_for_timeout(300)
    check("Esc closes lightbox, modal stays", page.locator("#lb").is_hidden() and page.locator("#pm").is_visible())
    page.keyboard.press("Escape"); page.wait_for_timeout(300)
    check("Esc then closes modal", page.locator("#pm").is_hidden())
    check("body scroll restored",
          page.evaluate("()=>document.body.style.overflow")=="", page.evaluate("()=>document.body.style.overflow"))

    # ---------- in-house build: no metrics ----------
    page.locator('[data-carousel="copperco"] .carousel-expand').click(force=True)
    page.wait_for_selector("#pm:not(.hidden)", timeout=4000)
    check("in-house modal title", page.inner_text("#pmTitle").strip().startswith("Copper"))
    check("in-house build shows no metrics", page.locator("#pmMetricsWrap").is_hidden())
    badges = page.inner_text("#pmBadges")
    check("in-house badge in modal", "in-house" in badges.lower(), badges.replace("\n"," / "))
    page.keyboard.press("Escape"); page.wait_for_timeout(300)

    # ---------- keyboard access ----------
    reachable = page.evaluate("""() => {
      const el = document.querySelector('[data-carousel="billing"] .carousel-expand');
      return el && el.tagName === 'BUTTON' && el.tabIndex >= 0;
    }""")
    check("detail trigger is keyboard-focusable button", reachable)

    # ---------- mobile 375 ----------
    m = b.new_page(viewport={"width":375,"height":812}, is_mobile=True, has_touch=True,
                   device_scale_factor=2)
    m.goto(URL, wait_until="networkidle")
    ov = m.evaluate("()=>({sw:document.documentElement.scrollWidth, cw:document.documentElement.clientWidth})")
    check("no horizontal overflow @375", ov["sw"]<=ov["cw"]+1, ov)
    m.locator('[data-carousel="billing"]').first.click(force=True)
    m.wait_for_selector("#pm:not(.hidden)", timeout=4000)
    ov2 = m.evaluate("()=>({sw:document.documentElement.scrollWidth, cw:document.documentElement.clientWidth})")
    check("no horizontal overflow @375 with modal", ov2["sw"]<=ov2["cw"]+1, ov2)
    m.screenshot(path=OUT+r"\pw-modal-mobile.png", full_page=False)

    b.close()

bad = [r for r in results if not r[0]]
print("\n%d/%d passed" % (len(results)-len(bad), len(results)))
if bad:
    print("FAILURES:")
    for _,n,d in bad: print("  -", n, d)
sys.exit(1 if bad else 0)
