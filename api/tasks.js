import {body,send,settings,factsFromInput,buildPrompt,seller,minimax,fallback,validate,report} from './_shared.js';

export default async function handler(req,res){
  if(req.method==='OPTIONS'){res.status(204).end();return}
  if(req.method!=='POST'){send(res,405,{error:'method not allowed'});return}
  try{
    const p=await body(req);const s=settings();const facts=factsFromInput(p);
    const sellerResult=await seller(s.sellersprite_url,p.marketplace||'US',p.asins||[]);
    const keywords=sellerResult.keywords||[];
    let [parsed,error]=await minimax(s,buildPrompt(p,facts,keywords),p.images||[]);
    if(error&&p.images?.length){const retry=await minimax(s,buildPrompt(p,facts,keywords),[]);if(retry[0]){parsed=retry[0];error=null}else if(retry[1])error=`${error}；文本生成也失败：${retry[1]}`}
    let candidate=parsed?.listing&&typeof parsed.listing==='object'?parsed.listing:parsed;
    if(candidate&&Array.isArray(candidate.highlights))candidate.highlights=candidate.highlights.join('; ');
    if(candidate&&Array.isArray(candidate.search_terms))candidate.search_terms=candidate.search_terms.join('; ');
    if(candidate&&Array.isArray(candidate.bullets))candidate.bullets=candidate.bullets.map(String);
    const valid= candidate&&['title','highlights','description','search_terms'].every(k=>typeof candidate[k]==='string'&&candidate[k].trim())&&Array.isArray(candidate.bullets)&&candidate.bullets.length>=5;
    const listing=valid?{...candidate,bullets:candidate.bullets.slice(0,5)}:fallback(p,facts,keywords);
    const providerStatus=valid?'live':'fallback';const validation=validate(listing,p,keywords,providerStatus==='fallback'?error:null);
    const result={marketplace:p.marketplace,language:p.language,listing,facts,keywords:sellerResult.raw||[],keyword_candidates:keywords,validation,provider:{minimax:providerStatus,sellersprite:sellerResult.ok&&keywords.length?'live':'unavailable'},provider_note:error||sellerResult.note};
    result.report_html=report(result);
    send(res,200,{task_id:crypto.randomUUID(),status:'completed',stage_index:4,message:'真实 provider 已完成；结果已生成并标记校验状态。',result});
  }catch(e){send(res,500,{error:e.message||String(e)})}
}
