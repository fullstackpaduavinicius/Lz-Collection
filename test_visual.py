"""Offline screenshots: browser policy forbids navigation, so inject UI source in about:blank."""
import base64
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parent
css=(ROOT/'frontend/styles.css').read_text()
js=(ROOT/'frontend/app.js').read_text()
mark=base64.b64encode((ROOT/'frontend/assets/mark.png').read_bytes()).decode()
js=js.replace('/assets/mark.png','data:image/png;base64,'+mark).replace('const path=location.pathname;const app=',"const path=(window.__previewRoute||location.pathname);const app=")
js=js.rsplit('init();',1)[0]+'''window.__previewRoute='/';state.categories=['Calçados','Camisas','Calças','Bermudas','Shorts','Regatas','Dry Fit','UV'].map((n,i)=>({id:i+1,name:n,slug:n.toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').replace(/ /g,'-')}));state.settings={hero_title:'Presença em cada detalhe.',hero_eyebrow:'LZ COLLECTION · MODA MASCULINA',hero_text:'Uma curadoria de moda masculina para acompanhar a sua rotina e o seu estilo.',announcement:'UMA CURADORIA PARA O SEU ESTILO',about:'Estilo, versatilidade e personalidade em cada escolha.',whatsapp:'5579998932703',instagram:'https://www.instagram.com/lz.collection__/'};render();'''
with sync_playwright() as play:
 browser=play.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
 page=browser.new_page(viewport={'width':1440,'height':900},device_scale_factor=1)
 errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.set_content('<html lang="pt-BR"><head><title>LZ Collection</title></head><body><div id="app"></div><div id="toast"></div></body></html>')
 page.add_style_tag(content=css)
 page.add_script_tag(content=js)
 page.wait_for_timeout(800)
 print('H1',page.locator('h1').all_text_contents())
 page.screenshot(path=str(ROOT/'preview-desktop.png'),full_page=True)
 page.set_viewport_size({'width':390,'height':844})
 page.wait_for_timeout(300)
 page.screenshot(path=str(ROOT/'preview-mobile.png'),full_page=True)
 print('MOBILE SCROLL',page.evaluate('({body:document.body.scrollWidth,inner:innerWidth})'))
 print('SECTIONS',page.evaluate("[...document.querySelectorAll('.hero,.hero-art,.intro-bar,.intro-bar .wrap,.section')].map(e=>({cl:e.className,y:e.getBoundingClientRect().y,height:e.getBoundingClientRect().height}))"))
 page.set_viewport_size({'width':1440,'height':900})
 page.evaluate("window.__previewRoute='/admin/login';render()")
 page.wait_for_timeout(350)
 page.screenshot(path=str(ROOT/'preview-admin.png'),full_page=True)
 print('ADMIN H2',page.locator('h2').all_text_contents())
 print('JS ERRORS',errors)
 browser.close()
