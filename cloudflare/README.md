# 跨网传文件中转（Cloudflare Worker）

本目录提供零存储 WebSocket 房间中转：只转发信令与文件块，不落盘。

**必须启用 Durable Objects 房间**（本仓库 `wrangler.toml` 已默认开启），否则发送方与接收方可能被分到不同 Cloudflare 实例，表现为「已进房间但一直等对方超时」。

## 部署 / 更新

**一键（Windows）：** 双击 `deploy.bat`（需已安装 Node.js；首次会打开浏览器登录 Cloudflare）。

或手动：

```bash
npx wrangler login
cd cloudflare
npx wrangler deploy
```

首次启用 Durable Objects 时，`wrangler deploy` 会自动应用 migration `v1`（免费套餐使用 `new_sqlite_classes = ["Room"]`）。

将输出的地址填入应用「跨网传文件」中的中转地址，例如：

- HTTPS：`https://desktop-toolkit-p2p.<你的子域>.workers.dev`
- 应用内也可用：`wss://desktop-toolkit-p2p.<你的子域>.workers.dev`

## 自检

浏览器打开：

- `https://你的地址/health` → 应返回 `"ok": true`，且 **`"durable_rooms": true`**
- `https://你的地址/usage` → 今日请求用量

若 `durable_rooms` 为 `false`，说明还是旧 Worker 或未绑定 ROOMS，请重新 `wrangler deploy`。

## 使用顺序

1. 双方填**完全相同**的中转地址 + 房间号（区分大小写会被统一成大写）
2. **接收方先点「等待接收」**
3. 发送方再点「发送文件」

## 说明

- 免费套餐请求额度按 Cloudflare 账户计
- WebSocket 建连计请求，连接后传数据块通常不计请求
- 文件不落盘，只在双方在线时内存转发
