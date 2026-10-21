import {body,send,settings} from './_shared.js';
export default async function handler(req,res){
  if(req.method==='OPTIONS'){res.status(204).end();return}
  const s=settings();
  if(req.method==='GET'){send(res,200,{sellersprite_configured:!!s.sellersprite_url,minimax_base_url:s.minimax_base_url,minimax_model:s.minimax_model,minimax_configured:!!s.minimax_key,remote:true});return}
  if(req.method==='PUT'){await body(req);send(res,200,{ok:true,message:'远程部署请通过 Vercel 环境变量管理密钥。'});return}
  send(res,405,{error:'method not allowed'});
}
