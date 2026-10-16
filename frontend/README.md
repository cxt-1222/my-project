# 撸铁记 IRON FLOW 前端原型

这是当前 `knowledge-agent` 后端的轻量前端，使用原生 HTML / CSS / JavaScript，不需要额外下载 npm 依赖。

## 启动前端

先确保 Docker Compose 中的后端 API 已启动并映射到宿主机 `8000` 端口，然后在 PowerShell 执行：

```powershell
Set-Location 'E:\健身项目开发\knowledge-agent\frontend'
node .\server.js
```

浏览器打开 **http://localhost:5173**。请使用 `localhost`，因为后端 CORS 已允许该来源；不要双击 `index.html` 或改用 `127.0.0.1` 地址。

后端 API 默认地址是 `http://localhost:8000`。如端口不同，在登录页展开“连接设置”修改并保存。

## 已接入接口

- `POST /user/login`、`POST /user/register`
- `GET /user/stats`
- `GET /chat/session`、`POST /chat/session`、`DELETE /chat/session/{session_id}`
- `GET /ai/invoke_stream`：Fetch + ReadableStream 解析 SSE
- `GET /pg/check_all`、`GET /pg/check?id=...`
- `GET /es/query?query=...`
- `POST /restfs/upload`
- `POST /knowledge_doc/publish?doc_id=...`

## 当前功能边界

- 身高、体重、目标、经验以及聊天消息展示仅保存在当前浏览器的 `localStorage`；健身档案和聊天内容并没有写入后端。
- 后端会话接口目前只保存会话标题，没有消息读写接口；并且 `/ai/invoke_stream` 每次只接收当前问题，不会把上一轮对话作为上下文。因此会话列表的标题同步到服务端，而消息历史只在本机恢复，每个问题由 AI 独立回答。
- 当前后端 `api/ai.py` 的系统提示词仍是“企业知识库助手”。前端可以连接并提问，但要让回答稳定聚焦健身，还需要后端调整提示词并上传适用的健身知识资料。
