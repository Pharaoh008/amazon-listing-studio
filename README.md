# Copycraft · Amazon Listing Studio

一个本地优先的 Amazon Listing 文案工作台。Python 负责任务编排、图片上传、MiniMax 和 SellerSprite MCP 调用，前端只负责工作台交互与结果展示。

## 本地运行

```powershell
python app.py
```

打开 <http://127.0.0.1:3000/>，在「设置」里填写：

- SellerSprite MCP URL 密钥（单字段）
- MiniMax API Key
- MiniMax Base URL 和模型名

本地密钥写入 `data/settings/config.json`，该文件已加入 `.gitignore`，不会提交到 GitHub。

## 部署

GitHub Pages 前端地址：<https://pharaoh008.github.io/amazon-listing-studio/>

GitHub Pages 只托管静态前端。当前生产 API 已部署到 Vercel：`https://amazon-listing-studio-api.vercel.app`，前端通过 `config.js` 连接它；本地 Python 服务仍可用 `python app.py` 运行。仓库也保留了 `render.yaml`，便于迁移到 Render。

部署环境变量：

```text
HOST=0.0.0.0
MINIMAX_API_KEY=你的 MiniMax 密钥
MINIMAX_API_URL=https://api.minimaxi.com/v1
MINIMAX_MODEL=MiniMax-M3
SELLERSPRITE_MCP_URL=你的卖家精灵 URL 密钥
```

不要把真实密钥写进 HTML、JavaScript、任务目录、日志或报告。

## 验证

```powershell
python -m py_compile app.py
node --check app.js
```
