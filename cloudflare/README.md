# Cloudflare 零存储跨网传文件（信令 / 中转）

本目录 Worker **不保存任何文件**，只负责：

1. 房间 WebSocket 牵线（双方加入同一 `room`）
2. 把消息/数据块实时转发给房间内另一端（内存转发即丢）

## 部署（约 3 分钟）

```bash
npm i -g wrangler
wrangler login
cd cloudflare
wrangler deploy
```

部署成功后会得到类似：

`https://quaker-parrot-p2p.<你的账号>.workers.dev`

在应用「跨网点对点传输」里填：

`wss://quaker-parrot-p2p.<你的账号>.workers.dev`

（也可只填域名，软件会自动加 `wss://` 和 `/ws`）

## 使用

1. **发送方**：生成房间号 → 点「发送文件」→ 把房间号发给对方  
2. **接收方**：填同一中转地址 + 房间号 → 点「等待接收」  
3. 进度条走完即完成；文件只经过双方电脑，Cloudflare 不落盘  

## 说明

- 免费 Workers 额度对「牵线 + 流式转发」通常足够日常使用  
- 超大文件或极严防火墙下，速度取决于双方上行/下行  
- 可选：在 `wrangler.toml` 启用 Durable Objects 提高多节点房间稳定性  

## 额度查询

应用内「跨网传输」面板有 **刷新额度**，或浏览器打开：

`https://<你的 worker>/usage`

返回今日本 Worker 近似请求数 / 相对免费上限（10 万/天）的剩余估计。  
注意：计数是边缘缓存近似值；官方账单以 Cloudflare 控制台为准；额度是**整个账户**共享。  
WebSocket **建连**计 1 次请求，连接后的消息/文件块**不计**请求。
