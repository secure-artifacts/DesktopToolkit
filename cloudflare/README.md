# 跨网传文件中转（Cloudflare Worker）

本目录提供零存储 WebSocket 房间中转：只转发信令与文件块，不落盘。

## 部署

```bat
npx wrangler login
cd cloudflare
npx wrangler deploy
```

将输出的地址填入应用「跨网传文件」中的中转地址，例如：

- HTTPS：`https://your-worker.example.workers.dev`
- WebSocket：`wss://your-worker.example.workers.dev`

应用内使用 `wss://` 形式。

## 说明

- 免费套餐请求额度按 Cloudflare 账户计
- WebSocket 建连计请求，连接后传数据块通常不计请求
