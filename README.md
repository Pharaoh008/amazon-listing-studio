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

GitHub Pages 只托管静态前端，完整生成流程仍需要部署 Python 服务。仓库已包含 `render.yaml`，连接 GitHub 仓库后可使用 Render Web Service。拿到后端公网地址后，将 `config.js` 中的 `window.COPYCRAFT_API_BASE` 改为该地址并推送，Pages 会自动重新发布。

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
