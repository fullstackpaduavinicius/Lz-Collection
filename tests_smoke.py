"""Run locally with: python tests_smoke.py (uses an isolated temporary DB)."""
import os,tempfile,subprocess,time,json,urllib.request,urllib.error,http.cookiejar,sys,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parent
port='18391'
with tempfile.TemporaryDirectory(prefix='lz-test-') as tmp:
    env={**os.environ,'LZ_DATA_DIR':tmp+'/data','LZ_MEDIA_DIR':tmp+'/media','PORT':port}
    Path(env['LZ_DATA_DIR']).mkdir();Path(env['LZ_MEDIA_DIR']).mkdir()
    # initialize test DB and controlled owner directly (never shipped with production DB)
    os.environ['LZ_DATA_DIR']=env['LZ_DATA_DIR'];os.environ['LZ_MEDIA_DIR']=env['LZ_MEDIA_DIR']
    import server
    server.init_db()
    with server.con() as db:db.execute('INSERT INTO admins VALUES(?,?,?,?)',('test-id','owner@example.com',server.pwd_hash('Some-very-long-test-password-123'),int(time.time())))
    p=subprocess.Popen([sys.executable,str(ROOT/'server.py')],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    import socket
    for _ in range(30):
        try:
            sock=socket.create_connection(('127.0.0.1',int(port)),timeout=.3);sock.close();break
        except ConnectionRefusedError:time.sleep(.2)
    if p.poll() is not None: print("SERVER FAILED", p.stderr.read().decode())
    cookie=urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    opener=urllib.request.build_opener(cookie)
    base='http://127.0.0.1:'+port
    def call(path,data=None,method='GET',csrf=None,expect=None):
        request=urllib.request.Request(base+path,method=method,data=(json.dumps(data).encode() if data is not None else None),headers={'Content-Type':'application/json',**({'X-CSRF-Token':csrf} if csrf else {})})
        try:
            with opener.open(request,timeout=3) as res:
                body=res.read();out=json.loads(body) if res.headers.get_content_type()=='application/json' else body
                print(method,path,'=>',res.status)
                assert expect is None or res.status==expect
                return out
        except urllib.error.HTTPError as e:
            out=json.loads(e.read());print(method,path,'=>',e.code,out)
            assert expect==e.code
            return out
    try:
        html=call('/',expect=200);assert b'LZ Collection' in html
        cat=call('/api/catalog',expect=200);assert len(cat['categories'])==8
        call('/api/admin/data',expect=401)
        login=call('/api/auth/login',{'email':'owner@example.com','password':'Some-very-long-test-password-123'},'POST',expect=200)
        csrf=login['csrf']
        call('/api/admin/data',expect=200)
        import base64
        pixel=base64.b64encode(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/xS0AAAAASUVORK5CYII=')).decode()
        up=call('/api/admin/upload',{'data':pixel},'POST',csrf,200)
        assert up['url'].startswith('/media/')
        picture=call(up['url'],expect=200)
        assert picture.startswith(b'\x89PNG')
        cats=cat['categories']+[{'id':0,'name':'Acessórios','active':True,'description':'Peças adicionais','image_url':up['url']}]
        call('/api/admin/categories',{'categories':cats},'PUT',csrf,200)
        assert len(call('/api/catalog',expect=200)['categories'])==9
        product={'name':'Camisa UV Cinza','sku':'LZ001','description':'Camisa manga longa para pesca e praia','price_cents':8990,'sale_cents':None,'category_id':cat['categories'][1]['id'],'tags':['uv'],'keywords':'proteção solar cinza','images':[],'published':True,'featured':True,'variants':[{'color':'Cinza','size':'G','stock':2,'sku':'LZ001G'}]}
        res=call('/api/admin/products',product,'POST',csrf,200);pid=res['id']
        pub=call('/api/catalog',expect=200);assert len(pub['products'])==1 and pub['products'][0]['name']==product['name']
        srch=call('/api/products?q=camiza%20uv%20cinza',expect=200);assert len(srch['products'])==1
        tag=call('/api/products?cat=uv',expect=200);assert len(tag['products'])==1
        prod=pub['products'][0]; variant=prod['variants'][0]
        cart={'items':[{'product_id':pid,'variant_id':variant['id'],'quantity':1}]}
        checkout=call('/api/validate',cart,'POST',expect=200)
        assert checkout['valid'] and checkout['subtotal_cents']==8990
        bad=call('/api/validate',{'items':[{'product_id':pid,'variant_id':variant['id'],'quantity':3}]},'POST',expect=200)
        assert not bad['valid']
        product['variants'][0]['stock']=0
        call('/api/admin/products/'+pid,product,'PUT',csrf,200)
        prod=call('/api/catalog',expect=200)['products'][0]
        assert prod['stock']==0
        call('/api/admin/products/'+pid,{},'DELETE',None,403)
        call('/api/admin/products/'+pid,{},'DELETE',csrf,200)
        assert not call('/api/catalog',expect=200)['products']
        call('/api/auth/logout',{},'POST',csrf,200)
        call('/api/admin/data',expect=401)
        print('\nALL SMOKE TESTS PASSED')
    finally:
        p.terminate()
        try:p.wait(timeout=3)
        except:p.kill()
