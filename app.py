import base64, cgi, html, json, mimetypes, os, re, threading, time, uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'; TASKS=DATA/'tasks'; SETTINGS=DATA/'settings'
TASKS.mkdir(parents=True,exist_ok=True); SETTINGS.mkdir(parents=True,exist_ok=True)
SETFILE=SETTINGS/'config.json'
MARKETS={'US':'English','CA':'English','UK':'English','DE':'German','FR':'French','IT':'Italian','ES':'Spanish','JP':'Japanese','AU':'English','AE':'English','IN':'English','MX':'Spanish','BR':'Portuguese'}

# ---- local configuration -------------------------------------------------
def read_settings():
    try: value=json.loads(SETFILE.read_text('utf-8'))
    except Exception: value={}
    # Hosted deployments use environment variables; local settings remain file-backed.
    env_map={'sellersprite_url':'SELLERSPRITE_MCP_URL','minimax_key':'MINIMAX_API_KEY','minimax_base_url':'MINIMAX_API_URL','minimax_model':'MINIMAX_MODEL'}
    for key,env_name in env_map.items():
        if os.getenv(env_name): value[key]=os.getenv(env_name)
    return value
def write_settings(value): SETFILE.write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf-8')
def clean_name(value): return re.sub(r'[^\w.-]+','_',str(value))[:80]
def now(): return time.strftime('%H:%M:%S')

def request_json(url, payload, headers=None, timeout=90):
    raw=json.dumps(payload,ensure_ascii=False).encode('utf-8')
    h={'Content-Type':'application/json','Accept':'application/json'}; h.update(headers or {})
    req=Request(url,data=raw,headers=h,method='POST')
    try:
        with urlopen(req,timeout=timeout) as res:
            return json.loads(res.read().decode('utf-8','replace'))
    except HTTPError as exc:
        detail=exc.read().decode('utf-8','replace')[:800]
        raise RuntimeError(f'HTTP {exc.code}: {detail}')

def detect_mime(path):
    try:
        head=path.read_bytes()[:16]
        if head.startswith(b'\x89PNG'): return 'image/png'
        if head.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
        if head[:4]==b'RIFF' and head[8:12]==b'WEBP': return 'image/webp'
    except Exception: pass
    return mimetypes.guess_type(str(path))[0] or 'image/jpeg'

def has_cjk(value): return bool(re.search(r'[\u3400-\u9fff]',str(value or '')))

def parse_json_text(text):
    text=(text or '').strip()
    text=re.sub(r'<think>.*?</think>','',text,flags=re.I|re.S).strip()
    fenced=re.search(r'```(?:json)?\s*(\{.*?\})\s*```',text,flags=re.I|re.S)
    if fenced: text=fenced.group(1).strip()
    else: text=re.sub(r'^```(?:json)?\s*|\s*```$','',text,flags=re.I|re.S).strip()
    try: return json.loads(text)
    except Exception: pass
    decoder=json.JSONDecoder()
    for start,ch in enumerate(text):
        if ch!='{': continue
        try:
            value,_=decoder.raw_decode(text[start:])
            if isinstance(value,dict): return value
        except Exception: pass
    return None

# ---- provider adapters ---------------------------------------------------
def split_seller_credential(value):
    value=(value or '').strip()
    if '|' in value:
        url,key=value.split('|',1); return url.strip(),key.strip()
    if value.startswith('http://') or value.startswith('https://'): return value,''
    return '',value

def call_sellersprite(settings, marketplace, asins, task_dir):
    credential=settings.get('sellersprite_url','')
    endpoint,key=split_seller_credential(credential)
    if not endpoint: return {'configured':False,'keywords':[],'note':'未配置卖家精灵 MCP URL 密钥'}
    headers={'Accept':'application/json, text/event-stream'}; headers.update({'Authorization':f'Bearer {key}'} if key else {})
    result={'configured':True,'ok':False,'keywords':[],'raw':[],'note':''}
    request={'asinList':asins[:20],'marketplace':marketplace,'queryType':2,'page':1,'size':100,'order':{'field':'trafficPercentage','desc':True}}
    try:
        # Accept common MCP JSON-RPC endpoints. The stored single field may be URL|key.
        payload={'jsonrpc':'2.0','id':uuid.uuid4().hex,'method':'tools/call','params':{'name':'traffic_extend','arguments':{'request':request}}}
        data=request_json(endpoint,payload,headers=headers,timeout=60)
        (task_dir/'competitor_raw').mkdir(exist_ok=True)
        (task_dir/'competitor_raw'/'traffic_extend.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf-8')
        result['raw'].append(data)
        if isinstance(data,dict) and (data.get('isError') or (isinstance(data.get('result'),dict) and data['result'].get('isError'))):
            result['note']='卖家精灵返回工具错误，未采用其中的关键词。'
            return result
        result['ok']=True
        text=json.dumps(data,ensure_ascii=False)
        # Preserve candidate keywords from common response shapes without guessing metrics.
        for item in re.findall(r'"(?:keyword|searchTerm|word)"\s*:\s*"([^"]+)"',text,re.I):
            if item not in result['keywords']: result['keywords'].append(item)
        result['note']=f'已调用 traffic_extend，返回候选词 {len(result["keywords"])} 个；字段映射需按实际 MCP 响应确认。'
    except (HTTPError,URLError,TimeoutError,ValueError) as exc:
        result['note']=f'卖家精灵请求失败：{exc}'
    except Exception as exc: result['note']=f'卖家精灵响应解析失败：{exc}'
    return result

def call_minimax(settings, prompt, images):
    key=settings.get('minimax_key','').strip(); base=settings.get('minimax_base_url','https://api.minimaxi.com/v1').rstrip('/'); model=settings.get('minimax_model','MiniMax-M3')
    if not key: return None,'未配置 MiniMax API Key'
    content=[{'type':'text','text':prompt}]
    for image in images[:8]:
        try:
            b64=base64.b64encode(image.read_bytes()).decode('ascii'); mime=detect_mime(image); content.append({'type':'image_url','image_url':{'url':f'data:{mime};base64,{b64}'}})
        except Exception: pass
    payload={'model':model,'messages':[{'role':'system','content':'You are an evidence-led Amazon listing copywriter. Output the final JSON immediately. Do not output reasoning, <think>, length calculations, Markdown fences, or commentary. Never invent product facts, certifications, compatibility, materials, dimensions, or performance claims. All listing fields must use the requested marketplace language. Chinese is allowed only inside semantic_checks and notes.'},{'role':'user','content':content}], 'temperature':0.2, 'max_tokens':6000,'thinking':{'type':'disabled'},'response_format':{'type':'json_object'}}
    try:
        data=request_json(base+'/chat/completions',payload,headers={'Authorization':f'Bearer {key}'},timeout=45 if images else 90)
        text=data.get('choices',[{}])[0].get('message',{}).get('content','')
        if isinstance(text,list): text=''.join(x.get('text','') for x in text if isinstance(x,dict))
        parsed=parse_json_text(text)
        if parsed: return parsed,None
        preview=re.sub(r'\s+',' ',str(text))[:220]
        return None, f'MiniMax 返回不是有效 JSON：{preview}'
    except Exception as exc: return None,f'MiniMax 请求失败：{exc}'

# ---- listing logic -------------------------------------------------------
def build_prompt(p,facts,keywords):
    return json.dumps({'task':'Generate Amazon listing copy from confirmed facts only.','marketplace':p.get('marketplace'),'language':p.get('language') or MARKETS.get(p.get('marketplace'),'English'),'product':p,'facts':facts,'seller_sprite_keywords':keywords,'requirements':{'title':'72-75 characters when facts and language allow','highlights':'119-125 characters','bullets':'five bullets, 190-200 characters each when feasible','description':'950-1000 characters when facts and language allow','search_terms':'real relevant backend terms, do not invent or repeat frontend terms','return_keys':['title','highlights','bullets','description','search_terms','claims','keyword_assignments','semantic_checks']},'notes':'If evidence or real keywords are insufficient, keep the output conservative and list the gap in semantic_checks.'},ensure_ascii=False)

def fallback_listing(p, facts, keywords):
    name=p.get('product_name') or 'Product'; brand=p.get('brand') or ''; specs=p.get('specs') or ''; features=p.get('features') or ''
    language=p.get('language') or MARKETS.get(p.get('marketplace'),'English')
    foreign=language.lower() not in ('chinese','中文')
    # Never paste Chinese source text into a non-Chinese listing when the provider failed.
    if foreign and has_cjk(name): name='Product'
    if foreign and has_cjk(brand): brand=''
    if foreign and has_cjk(specs): specs=''
    if foreign and has_cjk(features): features=''
    title=' '.join(x for x in [brand,name,specs] if x).strip() or 'Product Listing'
    kw=' '.join(keywords[:8])
    return {'title':title,'highlights':features or 'Designed for practical everyday use based on the confirmed product information.','bullets':[f'{name}: Review the confirmed product details before purchase.',f'Materials and dimensions: {specs or "See the supplied specifications"}.',f'Everyday use: {features or "Designed for the intended use described in the product information."}.','Please review dimensions and compatibility before ordering.','Package contents and limitations follow the supplied product information.'],'description':f'{title}. {features or "This listing is based only on the confirmed product information."} {specs}'.strip(),'search_terms':kw,'claims':[],'keyword_assignments':[],'semantic_checks':[{'dimension':'provider','status':'REVIEW','detail':'未获得可用的 MiniMax 结构化响应，使用保守草稿。'}]}

def facts_from_input(p, task_dir):
    facts=[]
    fields=[('product_name',p.get('product_name','')),('brand',p.get('brand','')),('category',p.get('category','')),('specs',p.get('specs','')),('features',p.get('features',''))]
    for i,(attr,val) in enumerate(fields,1): facts.append({'id':f'fact-{i}','attribute':attr,'value':val,'status':'confirmed' if val else 'unknown','scope':'own_product','source':'用户输入','critical':attr in ('product_name','specs')})
    return facts

def validate_listing(listing,p,keywords,provider_error=None):
    bullets=listing.get('bullets') or []; issues=[]
    title=str(listing.get('title','')); highlights=str(listing.get('highlights','')); description=str(listing.get('description','')); search_terms=str(listing.get('search_terms',''))
    if not isinstance(bullets,list) or len(bullets)!=5: issues.append('五点必须恰好 5 条')
    text=' '.join([title,highlights]+[str(x) for x in bullets]+[description])
    unique=set(re.findall(r'\b[a-zA-Z][a-zA-Z0-9-]{2,}\b',text.lower()))
    if len(unique)<15: issues.append(f'前台不同词根仅 {len(unique)} 个，未达到 15 个目标')
    if not title: issues.append('缺少 Title')
    if not keywords: issues.append('未获得卖家精灵真实关键词；未提供竞品 ASIN 或 MCP 未返回可用词')
    if title and len(title)<72: issues.append(f'Title 仅 {len(title)} 字符，低于 Skill 的 72 字符目标')
    if highlights and len(highlights)<119: issues.append(f'Highlights 仅 {len(highlights)} 字符，低于 Skill 的 119 字符目标')
    for i,b in enumerate(bullets,1):
        if len(str(b))<190: issues.append(f'Bullet {i} 仅 {len(str(b))} 字符，低于 Skill 的 190 字符目标')
    if description and len(description)<950: issues.append(f'Description 仅 {len(description)} 字符，低于 Skill 的 950 字符目标')
    if len(search_terms)>250: issues.append('Search Terms 超过 250 字符')
    if provider_error: issues.append(provider_error)
    return {'status':'REVIEW' if issues else 'PASS','issues':issues,'keyword_count':len(unique),'seller_sprite_keyword_count':len(keywords)}

def make_report(result):
    l=result['listing']; sections=[]
    for key,label in [('title','Title'),('highlights','Highlights'),('description','Description'),('search_terms','Search Terms')]: sections.append(f'<article><h2>{label}</h2><p>{html.escape(str(l.get(key,"")))}</p><small>{len(str(l.get(key,"")))} characters</small></article>')
    for i,b in enumerate(l.get('bullets',[]),1): sections.append(f'<article><h2>Bullet {i}</h2><p>{html.escape(str(b))}</p><small>{len(str(b))} characters</small></article>')
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Amazon Listing Report</title><style>body{font-family:Arial;max-width:920px;margin:40px auto;line-height:1.6;color:#171817}article{border:1px solid #ddd;border-radius:10px;padding:18px;margin:12px 0}small{color:#777}.review{color:#9a6a00}</style><h1>Amazon Listing Report</h1><p class="review">状态：'+html.escape(result['validation']['status'])+'</p>'+''.join(sections)+'<h2>校验说明</h2><pre>'+html.escape(json.dumps(result['validation'],ensure_ascii=False,indent=2))+'</pre></html>'

def run_task(tid):
    d=TASKS/tid; p=json.loads((d/'input.json').read_text('utf-8')); settings=read_settings()
    def state(status='running',idx=0,message=''): (d/'state.json').write_text(json.dumps({'status':status,'stage_index':idx,'message':message},ensure_ascii=False),'utf-8')
    try:
        state(idx=0,message='正在核对站点、ASIN 和产品参数…'); time.sleep(.25)
        facts=facts_from_input(p,d); (d/'facts.json').write_text(json.dumps(facts,ensure_ascii=False,indent=2),'utf-8')
        state(idx=1,message='已建立产品事实台账，正在读取图片并准备模型分析…')
        images=sorted((d/'images').glob('*'))
        seller=call_sellersprite(settings,p.get('marketplace','US'),p.get('asins',[]),d)
        keywords=seller.get('keywords',[])
        state(idx=2,message=seller.get('note','正在整理关键词…')); (d/'keywords.json').write_text(json.dumps(seller,ensure_ascii=False,indent=2),'utf-8')
        parsed,error=call_minimax(settings,build_prompt(p,facts,keywords),images)
        # If image reasoning times out, keep the task usable with a text-only provider pass.
        if error and images:
            text_parsed,text_error=call_minimax(settings,build_prompt(p,facts,keywords),[])
            if text_parsed is not None: parsed=text_parsed; error=None
            elif text_error: error=f'{error}；文本生成也失败：{text_error}'
        # Vision calls can return an evidence object. Run a second text-only pass to turn those facts into Listing fields.
        if parsed is not None and not (isinstance(parsed,dict) and any(k in parsed for k in ('title','listing'))):
            facts_with_image=facts+[{'id':'image-evidence','attribute':'image_observation','value':json.dumps(parsed,ensure_ascii=False),'status':'confirmed','scope':'own_product','source':'MiniMax 图片分析','critical':False}]
            parsed2,error2=call_minimax(settings,build_prompt(p,facts_with_image,keywords),[])
            if parsed2 is not None: parsed=parsed2; error=error2
            elif error2: error=error2
        # Models sometimes return a validation object or wrap the listing. Accept only a complete listing shape.
        candidate=parsed.get('listing') if isinstance(parsed,dict) and isinstance(parsed.get('listing'),dict) else parsed
        if isinstance(candidate,dict):
            for list_key in ('highlights','search_terms'):
                if isinstance(candidate.get(list_key),list): candidate[list_key]='; '.join(str(x) for x in candidate[list_key])
            if isinstance(candidate.get('bullets'),list): candidate['bullets']=[str(x) for x in candidate['bullets']]
        required=['title','highlights','description','search_terms']
        valid_live=isinstance(candidate,dict) and all(isinstance(candidate.get(k),str) and candidate.get(k).strip() for k in required) and isinstance(candidate.get('bullets'),list) and len(candidate.get('bullets'))>=5
        if not valid_live:
            if parsed and not error: error='MiniMax 返回 JSON 结构不完整，缺少 Listing 字段；已降级为保守草稿。'
            listing=fallback_listing(p,facts,keywords)
            provider_status='fallback'
        else:
            listing=candidate; provider_status='live'
        if not isinstance(listing.get('bullets'),list): listing['bullets']=[]
        listing['bullets']=(listing['bullets']+['']*5)[:5]
        validation=validate_listing(listing,p,keywords,error if provider_status=='fallback' else None)
        result={'marketplace':p.get('marketplace'),'language':p.get('language') or MARKETS.get(p.get('marketplace'),'English'),'listing':listing,'facts':facts,'keywords':seller.get('raw',[]),'keyword_candidates':keywords,'validation':validation,'provider':{'minimax':provider_status,'sellersprite':'live' if seller.get('ok') and seller.get('keywords') else 'unavailable'}}
        (d/'listing.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8'); (d/'validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2),'utf-8'); (d/'report.html').write_text(make_report(result),'utf-8')
        state('completed',4,'真实 provider 已完成；结果已生成并标记校验状态。'); st=json.loads((d/'state.json').read_text('utf-8'));st['result']=result;(d/'state.json').write_text(json.dumps(st,ensure_ascii=False),'utf-8')
    except Exception as exc: state('failed',0,f'任务失败：{exc}')

# ---- HTTP API ------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def send_json(self,obj,status=200):
        b=json.dumps(obj,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
    def body(self): return self.rfile.read(int(self.headers.get('Content-Length','0')))
    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/api/settings':
            s=read_settings();return self.send_json({'sellersprite_configured':bool(s.get('sellersprite_url')),'minimax_base_url':s.get('minimax_base_url','https://api.minimaxi.com/v1'),'minimax_model':s.get('minimax_model','MiniMax-M3'),'minimax_configured':bool(s.get('minimax_key'))})
        if path=='/api/tasks/latest':
            dirs=sorted([x for x in TASKS.iterdir() if x.is_dir() and (x/'state.json').exists()],key=lambda x:x.stat().st_mtime,reverse=True)
            for d in dirs:
                try:
                    state=json.loads((d/'state.json').read_text('utf-8'))
                    if state.get('status')=='completed': state['task_id']=d.name; return self.send_json(state)
                except Exception: pass
            return self.send_json({'status':'empty'})
        if path.startswith('/api/tasks/'):
            bits=path.split('/');tid=bits[3] if len(bits)>3 else '';d=TASKS/tid
            if len(bits)>4 and bits[4]=='report' and (d/'report.html').exists():
                b=(d/'report.html').read_bytes();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b);return
            if (d/'state.json').exists(): return self.send_json(json.loads((d/'state.json').read_text('utf-8')))
            return self.send_json({'error':'not found'},404)
        file=ROOT/('index.html' if path=='/' else path.lstrip('/'))
        if file.exists() and file.is_file():
            b=file.read_bytes();self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(str(file))[0] or 'application/octet-stream');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b);return
        return self.send_json({'error':'not found'},404)
    def do_PUT(self):
        if urlparse(self.path).path!='/api/settings': return self.send_json({'error':'not found'},404)
        incoming=json.loads(self.body() or '{}');s=read_settings();s.update({k:v for k,v in incoming.items() if v!=''});write_settings(s);return self.send_json({'ok':True})
    def do_POST(self):
        path=urlparse(self.path).path
        if path=='/api/tasks':
            p=json.loads(self.body() or '{}');tid=uuid.uuid4().hex[:12];d=TASKS/tid;d.mkdir();(d/'images').mkdir();(d/'input.json').write_text(json.dumps(p,ensure_ascii=False,indent=2),'utf-8');(d/'state.json').write_text(json.dumps({'status':'queued','stage_index':0,'message':'任务已创建'},ensure_ascii=False),'utf-8');threading.Thread(target=run_task,args=(tid,),daemon=True).start();return self.send_json({'task_id':tid})
        if path.startswith('/api/tasks/') and path.endswith('/images'):
            tid=path.split('/')[3];d=TASKS/tid/'images';ctype,pdict=cgi.parse_header(self.headers.get('Content-Type',''));pdict['boundary']=pdict.get('boundary','').encode();form=cgi.parse_multipart(self.rfile,pdict)
            for i,b in enumerate(form.get('file',[])): (d/f'upload_{len(list(d.iterdir()))+i}.bin').write_bytes(b)
            return self.send_json({'ok':True})
        if path in ['/api/settings/test-sellersprite','/api/settings/test-minimax']:
            incoming={}
            try: incoming=json.loads(self.body() or '{}')
            except Exception: pass
            s=read_settings();s.update({k:v for k,v in incoming.items() if v});kind=path.split('/')[-1]
            try:
                if 'seller' in kind:
                    endpoint,key=split_seller_credential(s.get('sellersprite_url',''))
                    if not endpoint: return self.send_json({'ok':False,'message':'请填写卖家精灵 MCP URL 密钥。'})
                    headers={'Accept':'application/json, text/event-stream'}; headers.update({'Authorization':f'Bearer {key}'} if key else {})
                    request_json(endpoint,{'jsonrpc':'2.0','id':uuid.uuid4().hex,'method':'tools/list','params':{}},headers=headers,timeout=15)
                    return self.send_json({'ok':True,'message':'卖家精灵 MCP 已连接，tools/list 请求成功。'})
                key=s.get('minimax_key','').strip();base=s.get('minimax_base_url','https://api.minimaxi.com/v1').rstrip('/');model=s.get('minimax_model','MiniMax-M3')
                if not key: return self.send_json({'ok':False,'message':'请填写 MiniMax API Key。'})
                reply=request_json(base+'/chat/completions',{'model':model,'messages':[{'role':'user','content':'Reply with OK only.'}],'max_tokens':4,'temperature':0},headers={'Authorization':f'Bearer {key}'},timeout=20)
                if not reply.get('choices'): raise ValueError('响应缺少 choices')
                return self.send_json({'ok':True,'message':f'MiniMax 已连接，模型 {model} 可用。'})
            except HTTPError as exc:
                return self.send_json({'ok':False,'message':f'连接失败：HTTP {exc.code}，请检查 URL、密钥和接口协议。'})
            except Exception as exc:
                return self.send_json({'ok':False,'message':f'连接失败：{exc}'})
        return self.send_json({'error':'not found'},404)

if __name__=='__main__':
    host=os.getenv('HOST','127.0.0.1');port=int(os.getenv('PORT','3000'));print(f'Copycraft Python server: http://{host}:{port}');ThreadingHTTPServer((host,port),Handler).serve_forever()







