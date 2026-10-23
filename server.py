#!/usr/bin/env python3
"""LZ Collection: zero-dependency Python/SQLite storefront + owner-only admin API."""
import os, re, sys, json, sqlite3, hashlib, hmac, secrets, base64, mimetypes, unicodedata, uuid, time, threading
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote, quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('LZ_DATA_DIR', ROOT / 'data')).resolve()
MEDIA = Path(os.environ.get('LZ_MEDIA_DIR', ROOT / 'media')).resolve()
WEB = ROOT / 'frontend'
DB = DATA / 'lz.sqlite3'
MAX_BODY = 9 * 1024 * 1024
DATABASE_URL = os.environ.get('DATABASE_URL', '')
SUPABASE_URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
SUPABASE_SERVICE_ROLE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
STORAGE_BUCKET = os.environ.get('SUPABASE_STORAGE_BUCKET', 'lz-images')
try:
    from psycopg import IntegrityError as DatabaseIntegrityError
except ImportError:
    class DatabaseIntegrityError(Exception): pass
DEFAULT_CATEGORIES = ['Calçados', 'Camisas', 'Calças', 'Bermudas', 'Shorts', 'Regatas', 'Dry Fit', 'UV']
DATA.mkdir(parents=True, exist_ok=True); MEDIA.mkdir(parents=True, exist_ok=True)

class HybridRow(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)

class CursorAdapter:
    def __init__(self, cursor): self.cursor = cursor
    def fetchone(self):
        row = self.cursor.fetchone()
        return HybridRow(row) if row is not None else None
    def fetchall(self): return [HybridRow(r) for r in self.cursor.fetchall()]
    def __iter__(self):
        for row in self.cursor: yield HybridRow(row)

class PostgresConnection:
    def __init__(self):
        import psycopg
        from psycopg.rows import dict_row
        self.db = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=12)
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type: self.db.rollback()
            else: self.db.commit()
        finally: self.db.close()
    def execute(self, sql, params=None):
        # Original application uses SQLite's '?' parameter placeholders.
        sql = sql.replace('?', '%s')
        return CursorAdapter(self.db.execute(sql, params or ()))
    def commit(self): self.db.commit()

def con():
    if DATABASE_URL:
        return PostgresConnection()
    db=sqlite3.connect(str(DB), timeout=10)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=10000')
    return db

def storage_request(method, filename, data=None, content_type=None):
    if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY):
        raise RuntimeError('Supabase Storage não configurado.')

    url = (
        f'{SUPABASE_URL}/storage/v1/object/'
        f'{quote(STORAGE_BUCKET, safe="")}/'
        f'{quote(filename, safe="")}'
    )

    headers = {
        'Authorization': 'Bearer ' + SUPABASE_SERVICE_ROLE_KEY,
        'apikey': SUPABASE_SERVICE_ROLE_KEY
    }

    if content_type:
        headers['Content-Type'] = content_type

    request = Request(
        url,
        data=data,
        headers=headers,
        method=method
    )

    try:
        with urlopen(request, timeout=30) as response:
            return response.read()

    except HTTPError as exc:
        error_body = exc.read().decode('utf-8', errors='replace')
        print(f'SUPABASE STORAGE ERROR [{exc.code}]: {error_body}')
        raise
    if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY):
        raise RuntimeError('Supabase Storage não configurado.')
    url = f'{SUPABASE_URL}/storage/v1/object/{quote(STORAGE_BUCKET, safe="")}/{quote(filename, safe="")}'
    headers={'Authorization': 'Bearer '+SUPABASE_SERVICE_ROLE_KEY,
             'apikey': SUPABASE_SERVICE_ROLE_KEY}
    if content_type: headers['Content-Type']=content_type
    request=Request(url, data=data, headers=headers, method=method)
    try:
     with urlopen(request, timeout=30) as response:
            return response.read()
    except HTTPError as exc:
     error_body = exc.read().decode('utf-8', errors='replace')
    print(f'SUPABASE STORAGE ERROR [{exc.code}]: {error_body}')
    raise


def slug(value):
    value=''.join(ch for ch in unicodedata.normalize('NFKD',str(value).lower()) if not unicodedata.combining(ch))
    return re.sub(r'-+','-',re.sub(r'[^a-z0-9]+','-',value)).strip('-') or 'produto'

def init_db():
    if DATABASE_URL:
        with con() as db:
            statements = [
                "CREATE TABLE IF NOT EXISTS admins (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, created_at BIGINT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, admin_id TEXT NOT NULL REFERENCES admins(id) ON DELETE CASCADE, csrf TEXT NOT NULL, expires_at BIGINT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS login_attempts (ip TEXT PRIMARY KEY, failures INTEGER NOT NULL, retry_after BIGINT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS categories (id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, name TEXT UNIQUE NOT NULL, slug TEXT UNIQUE NOT NULL, active INTEGER DEFAULT 1, sort_order INTEGER NOT NULL, description TEXT NOT NULL DEFAULT '', image_url TEXT NOT NULL DEFAULT '')",
                "CREATE TABLE IF NOT EXISTS products (id TEXT PRIMARY KEY, name TEXT NOT NULL, slug TEXT UNIQUE NOT NULL, sku TEXT DEFAULT '', description TEXT DEFAULT '', price_cents INTEGER NOT NULL CHECK(price_cents>=0), sale_cents INTEGER CHECK(sale_cents IS NULL OR sale_cents>=0), category_id INTEGER REFERENCES categories(id), tags TEXT NOT NULL DEFAULT '[]', keywords TEXT DEFAULT '', images TEXT NOT NULL DEFAULT '[]', published INTEGER NOT NULL DEFAULT 0, featured INTEGER NOT NULL DEFAULT 0, created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS variants (id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE, color TEXT DEFAULT '', size TEXT DEFAULT '', sku TEXT DEFAULT '', stock INTEGER NOT NULL DEFAULT 0 CHECK(stock>=0))",
                "CREATE INDEX IF NOT EXISTS idx_products_public ON products(published, category_id, created_at)",
                "CREATE INDEX IF NOT EXISTS idx_variants_product ON variants(product_id)",
                "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
                "ALTER TABLE categories ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE categories ADD COLUMN IF NOT EXISTS image_url TEXT NOT NULL DEFAULT ''",
            ]
            for sql in statements: db.execute(sql)
            for i,name in enumerate(DEFAULT_CATEGORIES):
                db.execute('INSERT INTO categories(name,slug,sort_order) VALUES(?,?,?) ON CONFLICT DO NOTHING',(name,slug(name),i))
            defaults = {
                'whatsapp': '5579998932703',
                'instagram': 'https://www.instagram.com/lz.collection__/',
                'hero_title': 'Presença em cada detalhe.',
                'hero_text': 'Uma curadoria de moda masculina para acompanhar a sua rotina e o seu estilo.',
                'hero_eyebrow': 'LZ COLLECTION · MODA MASCULINA',
                'hero_image': '',
                'announcement': 'UMA CURADORIA PARA O SEU ESTILO',
                'about': 'Estilo, versatilidade e personalidade em cada escolha.'
            }

            for k, v in defaults.items():
                db.execute(
                    'INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT DO NOTHING',
                    (k, v)
                )

        return
    init_sqlite_db()

def init_sqlite_db():
    with con() as db:
        db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS admins (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, admin_id TEXT NOT NULL REFERENCES admins(id) ON DELETE CASCADE, csrf TEXT NOT NULL, expires_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS login_attempts (ip TEXT PRIMARY KEY, failures INTEGER NOT NULL, retry_after INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, slug TEXT UNIQUE NOT NULL, active INTEGER DEFAULT 1, sort_order INTEGER NOT NULL, description TEXT NOT NULL DEFAULT '', image_url TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS products (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, slug TEXT UNIQUE NOT NULL, sku TEXT DEFAULT '', description TEXT DEFAULT '',
          price_cents INTEGER NOT NULL CHECK(price_cents>=0), sale_cents INTEGER CHECK(sale_cents IS NULL OR sale_cents>=0),
          category_id INTEGER REFERENCES categories(id), tags TEXT NOT NULL DEFAULT '[]', keywords TEXT DEFAULT '', images TEXT NOT NULL DEFAULT '[]',
          published INTEGER NOT NULL DEFAULT 0, featured INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS variants (
          id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
          color TEXT DEFAULT '', size TEXT DEFAULT '', sku TEXT DEFAULT '', stock INTEGER NOT NULL DEFAULT 0 CHECK(stock>=0)
        );
        CREATE INDEX IF NOT EXISTS idx_products_public ON products(published, category_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_variants_product ON variants(product_id);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ''')
        columns={r['name'] for r in db.execute('PRAGMA table_info(categories)')}
        if 'description' not in columns: db.execute("ALTER TABLE categories ADD COLUMN description TEXT NOT NULL DEFAULT ''")
        if 'image_url' not in columns: db.execute("ALTER TABLE categories ADD COLUMN image_url TEXT NOT NULL DEFAULT ''")
        for i,name in enumerate(DEFAULT_CATEGORIES):
            db.execute('INSERT OR IGNORE INTO categories(name,slug,sort_order) VALUES(?,?,?)',(name,slug(name),i))
        defaults={
          'whatsapp':'5579998932703', 'instagram':'https://www.instagram.com/lz.collection__/',
          'hero_title':'Presença em cada detalhe.', 'hero_text':'Uma curadoria de moda masculina para acompanhar a sua rotina e o seu estilo.',
          'hero_eyebrow':'LZ COLLECTION · MODA MASCULINA', 'hero_image':'',
          'announcement':'UMA CURADORIA PARA O SEU ESTILO', 'about':'Estilo, versatilidade e personalidade em cada escolha.'
        }
        for k,v in defaults.items(): db.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)',(k,v))


def pwd_hash(password):
    salt=os.urandom(16)
    dk=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1)
    return base64.b64encode(salt).decode()+':'+base64.b64encode(dk).decode()

def check_password(password, hashed):
    try:
        salt,digest=[base64.b64decode(s) for s in hashed.split(':')]
        return hmac.compare_digest(hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1),digest)
    except Exception: return False

def create_admin():
    import getpass
    with con() as db:
        existing=db.execute('SELECT count(*) FROM admins').fetchone()[0]
        if existing:
            print('Já existe um administrador. Por segurança, não é permitido criar outro por este comando.')
            return
    email=input('E-mail do proprietário: ').strip().lower()
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$',email): raise SystemExit('E-mail inválido.')
    password=getpass.getpass('Nova senha forte (mínimo 12 caracteres): ')
    if len(password)<12 or len(set(password))<6: raise SystemExit('Use uma senha mais forte (12+ caracteres e variada).')
    repeat=getpass.getpass('Repita a senha: ')
    if password != repeat: raise SystemExit('As senhas são diferentes.')
    with con() as db: db.execute('INSERT INTO admins VALUES(?,?,?,?)',(uuid.uuid4().hex,email,pwd_hash(password),int(time.time())))
    print('Administrador cadastrado. Acesse /admin/login')

def rowdict(row): return dict(row) if row is not None else None

def list_categories(db, public=True):
    sql='SELECT id,name,slug,active,sort_order,description,image_url FROM categories'
    if public: sql+=' WHERE active=1'
    return [dict(r) for r in db.execute(sql+' ORDER BY sort_order,name')]

def get_settings(db,public=True):
    x={r['key']:r['value'] for r in db.execute('SELECT key,value FROM settings')}
    if public: return {k:v for k,v in x.items() if k in {'whatsapp','instagram','hero_title','hero_text','hero_eyebrow','hero_image','announcement','about'}}
    return x

def product_dict(db,row):
    p=dict(row)
    p['images']=json.loads(p['images'] or '[]')
    p['tags']=json.loads(p['tags'] or '[]')
    p['variants']=[dict(r) for r in db.execute('SELECT id,color,size,sku,stock FROM variants WHERE product_id=? ORDER BY id',(p['id'],))]
    p['stock']=sum(v['stock'] for v in p['variants'])
    p['published']=bool(p['published']); p['featured']=bool(p['featured'])
    p['category']=rowdict(db.execute('SELECT id,name,slug FROM categories WHERE id=?',(p['category_id'],)).fetchone())
    return p

def list_products(db, public=True, q='', cat='', featured=False, limit=100):
    sql='SELECT * FROM products'
    wh=[]; params=[]
    if public: wh.append('published=1')
    if featured: wh.append('featured=1')
    if cat:
        cat_row=db.execute('SELECT id FROM categories WHERE slug=? AND active=1',(cat,)).fetchone()
        if not cat_row:return []
        wh.append('(category_id=? OR tags LIKE ?)'); params += [cat_row['id'], '%"'+cat+'"%']
    if wh: sql+=' WHERE '+' AND '.join(wh)
    sql+=' ORDER BY featured DESC, created_at DESC LIMIT 1500'
    products=[product_dict(db,r) for r in db.execute(sql, params)]
    if q:
        words=slug(q).replace('-',' ').split()
        from difflib import SequenceMatcher
        def score(p):
            text=slug(' '.join([p['name'],p['keywords'],p['description'], p['category']['name'] if p['category'] else '', ' '.join(p['tags']), ' '.join(v['color']+' '+v['size'] for v in p['variants'])])).replace('-',' ')
            title=slug(p['name']).replace('-',' ')
            tokens=text.split()
            rating=0
            for w in words:
                if w in title.split(): rating+=12
                elif w in title: rating+=8
                elif w in tokens: rating+=5
                elif w in text: rating+=3
                elif any(SequenceMatcher(None,w,t).ratio()>=.78 for t in tokens if len(t)>2): rating+=1
                else: return 0
            if len(words)>1 and ' '.join(words) in title: rating+=10
            return rating
        products=[(score(p),p) for p in products]
        products=[p for s,p in sorted(products,key=lambda pair:pair[0],reverse=True) if s>0]
    return products[:min(max(limit,1),500)]

class Handler(BaseHTTPRequestHandler):
    server_version='LZCollection/1.0'
    def log_message(self,fmt,*args):
        print('%s - %s' %(self.address_string(),fmt%args),file=sys.stderr)
    def headers_base(self,ctype='application/json; charset=utf-8',size=None,status=200,extra=None):
        self.send_response(status); self.send_header('Content-Type',ctype)
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','strict-origin-when-cross-origin')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Permissions-Policy','camera=(), microphone=(), geolocation=()')
        if size is not None:self.send_header('Content-Length',str(size))
        if extra:
            for k,v in extra.items(): self.send_header(k,v)
        self.end_headers()
    def out(self,data,status=200,extra=None):
        body=json.dumps(data,ensure_ascii=False,default=str).encode()
        self.headers_base(size=len(body),status=status,extra=extra)
        self.wfile.write(body)
    def error_json(self,status,message): self.out({'error':message},status)
    def route(self):return urlparse(self.path).path
    def query(self):return {k:v[0] for k,v in parse_qs(urlparse(self.path).query).items()}
    def read_json(self):
        length=int(self.headers.get('Content-Length','0'))
        if length<0 or length>MAX_BODY:raise ValueError('Arquivo ou solicitação muito grande.')
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('Envie JSON.')
        return json.loads(self.rfile.read(length).decode('utf-8'))
    def cookie_token(self):
        for pair in self.headers.get('Cookie','').split(';'):
            k,sep,v=pair.strip().partition('=')
            if k=='lz_session' and sep:return v
        return None
    def session(self,db):
        tok=self.cookie_token()
        if not tok:return None
        digest=hashlib.sha256(tok.encode()).hexdigest()
        return db.execute('SELECT s.csrf,s.expires_at,a.id,a.email FROM sessions s JOIN admins a ON a.id=s.admin_id WHERE s.token_hash=? AND expires_at>?',(digest,int(time.time()))).fetchone()
    def guard(self,db,write=False):
        sess=self.session(db)
        if not sess:
            self.error_json(401,'Faça login para continuar.'); return None
        if write:
            origin=self.headers.get('Origin','')
            host=self.headers.get('Host','')
            if origin and urlparse(origin).netloc!=host:
                self.error_json(403,'Origem não permitida.');return None
            if not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),sess['csrf']):
                self.error_json(403,'Proteção de sessão inválida. Atualize a página.');return None
        return sess
    def do_GET(self):
        p=self.route(); q=self.query()
        try:
            if p.startswith('/api/'):
                with con() as db:
                    if p=='/api/catalog':
                        self.out({'categories':list_categories(db),'settings':get_settings(db),'products':list_products(db,True,q.get('q',''),q.get('cat',''),q.get('featured')=='1',int(q.get('limit',200)))})
                    elif p=='/api/products':
                        self.out({'products':list_products(db,True,q.get('q',''),q.get('cat',''),False,int(q.get('limit',200)))})
                    elif p.startswith('/api/product/'):
                        key=unquote(p[len('/api/product/'):]); row=db.execute('SELECT * FROM products WHERE (slug=? OR id=?) AND published=1',(key,key)).fetchone()
                        if not row:self.error_json(404,'Produto não encontrado.');return
                        self.out({'product':product_dict(db,row)})
                    elif p=='/api/admin/me':
                        sess=self.guard(db)
                        if sess:self.out({'email':sess['email'],'csrf':sess['csrf']})
                    elif p=='/api/admin/data':
                        if not self.guard(db):return
                        self.out({'categories':list_categories(db,False),'settings':get_settings(db,False),'products':list_products(db,False,limit=500)})
                    else:self.error_json(404,'Recurso não encontrado.')
                return
            if p.startswith('/media/'):
                name=p.rsplit('/',1)[-1]
                if not re.fullmatch(r'[a-f0-9]{32}\.(jpg|png|webp)',name): self.error_json(404,'Imagem não encontrada.');return
                file=MEDIA/name
                if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
                    try: blob=storage_request('GET', name)
                    except HTTPError as exc:
                        if exc.code == 404: self.error_json(404,'Imagem não encontrada.');return
                        raise
                else:
                    if not file.is_file():self.error_json(404,'Imagem não encontrada.');return
                    blob=file.read_bytes()
                ctype=mimetypes.guess_type(name)[0] or 'application/octet-stream'
                self.headers_base(ctype,len(blob),extra={'Cache-Control':'public, max-age=31536000, immutable'})
                self.wfile.write(blob);return
            path=p.lstrip('/')
            if path in ('','index.html') or not Path(path).suffix:
                file=WEB/'index.html'
            else:
                file=(WEB/path).resolve()
                if not file.is_relative_to(WEB.resolve()):self.error_json(403,'Acesso negado.');return
            if not file.is_file():self.error_json(404,'Arquivo não encontrado.');return
            data=file.read_bytes()
            ctype=mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
            self.headers_base(ctype,len(data),extra={'Cache-Control':'no-cache' if file.name.endswith(('.js','.css','.html')) else 'public, max-age=604800'})
            self.wfile.write(data)
        except (ValueError,TypeError) as exc:self.error_json(400,str(exc))
        except Exception as exc:print('GET ERROR:',repr(exc),file=sys.stderr);self.error_json(500,'Erro interno no servidor.')
    def do_POST(self): self.mutate('POST')
    def do_PUT(self): self.mutate('PUT')
    def do_DELETE(self): self.mutate('DELETE')
    def mutate(self,method):
        p=self.route()
        try:
            if not p.startswith('/api/'): self.error_json(404,'Recurso não encontrado.');return
            data=self.read_json() if method!='DELETE' else {}
            with con() as db:
                if p=='/api/auth/login' and method=='POST':
                    ip=self.client_address[0]; now=int(time.time())
                    attempt=db.execute('SELECT * FROM login_attempts WHERE ip=?',(ip,)).fetchone()
                    if attempt and attempt['retry_after']>now: self.error_json(429,'Muitas tentativas. Tente novamente em alguns minutos.');return
                    email=str(data.get('email','')).strip().lower(); pw=str(data.get('password',''))
                    admin=db.execute('SELECT * FROM admins WHERE email=?',(email,)).fetchone()
                    if not admin or not check_password(pw,admin['password_hash']):
                        failures=(attempt['failures'] if attempt else 0)+1
                        retry=now+300 if failures>=5 else 0
                        db.execute('INSERT INTO login_attempts VALUES(?,?,?) ON CONFLICT(ip) DO UPDATE SET failures=?,retry_after=?',(ip,failures,retry,failures,retry))
                        db.commit();self.error_json(401,'E-mail ou senha incorretos.');return
                    db.execute('DELETE FROM login_attempts WHERE ip=?',(ip,))
                    token=secrets.token_urlsafe(48);csrf=secrets.token_urlsafe(32)
                    db.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),admin['id'],csrf,now+7*86400))
                    extra={'Set-Cookie':f'lz_session={token}; HttpOnly; Path=/; SameSite=Lax; Max-Age=604800'+('; Secure' if os.getenv('LZ_SECURE_COOKIES')=='1' else '')}
                    db.commit();self.out({'ok':True,'email':admin['email'],'csrf':csrf},extra=extra);return
                if p=='/api/validate' and method=='POST':
                    requested=data.get('items',[])
                    if not isinstance(requested,list) or len(requested)>50: self.error_json(400,'Carrinho inválido.');return
                    result=[]; subtotal=0; errors=[]
                    for item in requested:
                        qty=int(item.get('quantity',1))
                        if not 1<=qty<=99:errors.append('Quantidade inválida.');continue
                        row=db.execute('SELECT * FROM products WHERE id=? AND published=1',(str(item.get('product_id','')),)).fetchone()
                        if not row:errors.append('Um produto foi removido da vitrine.');continue
                        pitem=product_dict(db,row)
                        v=next((x for x in pitem['variants'] if x['id']==item.get('variant_id')),None)
                        if not v:errors.append(f'Variação indisponível: {pitem["name"]}.');continue
                        if v['stock']<qty:errors.append(f'Estoque insuficiente para {pitem["name"]} ({v["size"]} / {v["color"]}).');continue
                        price=pitem['sale_cents'] if pitem['sale_cents'] is not None else pitem['price_cents']
                        subtotal+=price*qty
                        result.append({'name':pitem['name'],'sku':v['sku'] or pitem['sku'],'color':v['color'],'size':v['size'],'quantity':qty,'price_cents':price,'url':'/produto/'+pitem['slug']})
                    db.commit();self.out({'valid':not errors,'errors':errors,'items':result,'subtotal_cents':subtotal});return
                sess=self.guard(db,write=True)
                if not sess:return
                if p=='/api/auth/logout' and method=='POST':
                    tok=self.cookie_token()
                    if tok:db.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(tok.encode()).hexdigest(),))
                    db.commit();self.out({'ok':True},extra={'Set-Cookie':'lz_session=; HttpOnly; Path=/; SameSite=Lax; Max-Age=0'});return
                if p=='/api/admin/settings' and method=='PUT':
                    allowed={'whatsapp','instagram','hero_title','hero_text','hero_eyebrow','hero_image','announcement','about'}
                    for k,v in data.items():
                        if k in allowed:
                            if not isinstance(v,str) or len(v)>1200:raise ValueError('Campo inválido: '+k)
                            if k=='whatsapp' and not re.fullmatch(r'\d{10,15}',v):raise ValueError('WhatsApp inválido: use DDI e DDD.')
                            if k=='instagram' and not v.startswith('https://www.instagram.com/'):raise ValueError('Link do Instagram inválido.')
                            db.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,v))
                    db.commit();self.out({'ok':True});return
                if p=='/api/admin/categories' and method=='PUT':
                    items=data.get('categories',[])
                    if not isinstance(items,list) or len(items)>40:raise ValueError('Categorias inválidas.')
                    for i,x in enumerate(items):
                        cid=int(x.get('id',0)); name=str(x.get('name','')).strip()
                        description=str(x.get('description','')).strip()[:350]
                        image_url=str(x.get('image_url','')).strip()
                        if image_url and not re.fullmatch(r'/media/[a-f0-9]{32}\.(jpg|png|webp)', image_url): raise ValueError('Imagem de categoria inválida.')
                        if not name or len(name)>70:raise ValueError('Nome de categoria inválido.')
                        if cid:
                            db.execute('UPDATE categories SET name=?,active=?,sort_order=?,description=?,image_url=? WHERE id=?',(name,1 if x.get('active') else 0,i,description,image_url,cid))
                        else:
                            base=slug(name);candidate=base;count=2
                            while db.execute('SELECT 1 FROM categories WHERE slug=?',(candidate,)).fetchone():candidate=base+'-'+str(count);count+=1
                            db.execute('INSERT INTO categories(name,slug,active,sort_order,description,image_url) VALUES(?,?,?,?,?,?)',(name,candidate,1 if x.get('active') else 0,i,description,image_url))
                    db.commit();self.out({'ok':True});return
                if p=='/api/admin/products' and method=='POST' or p.startswith('/api/admin/products/') and method in ('PUT','DELETE'):
                    pid=p.split('/')[-1] if p!='/api/admin/products' else uuid.uuid4().hex
                    if method=='DELETE':
                        db.execute('DELETE FROM products WHERE id=?',(pid,))
                        db.commit();self.out({'ok':True});return
                    name=str(data.get('name','')).strip()
                    if not name or len(name)>180:raise ValueError('Informe o nome do produto (máximo 180 caracteres).')
                    price=int(data.get('price_cents',0)); sale=data.get('sale_cents')
                    sale=None if sale in ('',None) else int(sale)
                    if price<0 or (sale is not None and (sale<0 or sale>=price)):raise ValueError('Preço inválido.')
                    cat=data.get('category_id')
                    if cat is not None and not db.execute('SELECT 1 FROM categories WHERE id=?',(cat,)).fetchone():raise ValueError('Categoria inválida.')
                    vars=data.get('variants',[])
                    if not isinstance(vars,list) or len(vars)>100:raise ValueError('Variações inválidas.')
                    if not vars:vars=[{'size':'Único','color':'','stock':0,'sku':''}]
                    for v in vars:
                        if not 0<=int(v.get('stock',0))<=100000:raise ValueError('Quantidade de estoque inválida.')
                    imgs=data.get('images',[])
                    if not isinstance(imgs,list) or len(imgs)>15 or any(not isinstance(i,str) or not (i.startswith('/media/') or i.startswith('/assets/')) for i in imgs):raise ValueError('Imagens inválidas.')
                    tags=data.get('tags',[])
                    if not isinstance(tags,list) or len(tags)>30:raise ValueError('Coleções inválidas.')
                    allowed_tags={r['slug'] for r in db.execute('SELECT slug FROM categories')}
                    tags=[t for t in tags if t in allowed_tags]
                    now=int(time.time())
                    base_slug=slug(name);desired=base_slug;step=2
                    while db.execute('SELECT 1 FROM products WHERE slug=? AND id<>?',(desired,pid)).fetchone():desired=base_slug+'-'+str(step);step+=1
                    arguments=(name,desired,str(data.get('sku',''))[:80],str(data.get('description',''))[:4000],price,sale,cat,json.dumps(tags),str(data.get('keywords',''))[:500],json.dumps(imgs),int(bool(data.get('published'))),int(bool(data.get('featured'))),now)
                    if method=='POST':
                        db.execute('INSERT INTO products(id,name,slug,sku,description,price_cents,sale_cents,category_id,tags,keywords,images,published,featured,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(pid,)+arguments[:-1]+(now,now))
                    else:
                        if not db.execute('SELECT 1 FROM products WHERE id=?',(pid,)).fetchone():self.error_json(404,'Produto não encontrado.');return
                        db.execute('UPDATE products SET name=?,slug=?,sku=?,description=?,price_cents=?,sale_cents=?,category_id=?,tags=?,keywords=?,images=?,published=?,featured=?,updated_at=? WHERE id=?',arguments+(pid,))
                    db.execute('DELETE FROM variants WHERE product_id=?',(pid,))
                    for v in vars:
                        db.execute('INSERT INTO variants(id,product_id,color,size,sku,stock) VALUES(?,?,?,?,?,?)',(uuid.uuid4().hex,pid,str(v.get('color',''))[:60],str(v.get('size',''))[:40],str(v.get('sku',''))[:80],int(v.get('stock',0))))
                    db.commit();self.out({'ok':True,'id':pid});return
                if p=='/api/admin/upload' and method=='POST':
                    s=str(data.get('data',''))
                    if ',' in s:s=s.split(',',1)[-1]
                    raw=base64.b64decode(s,validate=True)
                    if len(raw)>6*1024*1024:raise ValueError('A imagem deve ter no máximo 6 MB.')
                    if raw.startswith(b'\xff\xd8\xff'):ext='jpg'
                    elif raw.startswith(b'\x89PNG\r\n\x1a\n'):ext='png'
                    elif raw[:4]==b'RIFF' and raw[8:12]==b'WEBP':ext='webp'
                    else:raise ValueError('Formato inválido. Use JPG, PNG ou WebP.')
                    filename=uuid.uuid4().hex+'.'+ext
                    if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
                        storage_request('POST', filename, raw, mimetypes.guess_type(filename)[0] or 'application/octet-stream')
                    else:
                        (MEDIA/filename).write_bytes(raw)
                    db.commit();self.out({'url':'/media/'+filename});return
                self.error_json(404,'Operação não encontrada.')
        except (ValueError,TypeError,KeyError,OverflowError,base64.binascii.Error) as e:self.error_json(400,str(e))
        except (sqlite3.IntegrityError, DatabaseIntegrityError):self.error_json(409,'Conflito de dados. Revise as informações enviadas.')
        except Exception as e:print('API ERROR:',repr(e),file=sys.stderr);self.error_json(500,'Erro interno no servidor.')

if __name__=='__main__':
    init_db()
    if len(sys.argv)>1 and sys.argv[1]=='create-admin':create_admin()
    else:
        port=int(os.environ.get('PORT','8000'))
        print(f'LZ Collection em http://localhost:{port} | Painel: /admin/login')
        ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
