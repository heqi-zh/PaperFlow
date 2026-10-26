# 自用版 ChatGPT 登录接入

本仓库是 OpenRaiser/PaperFlow 的个人修改版。新增适配让 PaperFlow 自己管理论文工作流，通过官方 Sign in with ChatGPT DevKit 完成 OAuth 和直接模型推理；不会启动 Codex CLI 或读取 Codex 登录文件。

## 安装与启动

当前新增的凭据加密使用 macOS Keychain。请从源码运行，准备 Python 3.10+、Git、Node.js 24.5+，以及 pnpm 或 npm。Node 24.5+ 用于支持环境中已有的 HTTP(S)_PROXY。

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[openai,local,fetch,parsing]'
cp .env.example .env
python scripts/setup_chatgpt.py
```

在本地 `.env` 中设置以下配置。不要把真实配置写进 `.env.example`：

```dotenv
PAPERFLOW_LLM_PROVIDER=chatgpt
PAPERFLOW_LLM_MODEL=auto
PAPERFLOW_EMBED_PROVIDER=sentence_transformers
PAPERFLOW_EMBED_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
PAPERFLOW_EMBED_DIMENSIONS=384
HF_HOME=.local/huggingface
```

如果 Node 不在 PATH，可在 `.env` 用 `PAPERFLOW_NODE` 指定本机 Node 可执行文件。不要提交个人的绝对路径。

```sh
paperflow gui --host 127.0.0.1 --port 8766
```

打开 `http://127.0.0.1:8766/chatgpt-connect.html`，点击 Continue with ChatGPT，再在自己常用的浏览器完成官方授权。然后加载可用模型、保存模型选择，并测试真实调用。`auto` 会按账号模型目录的顺序选择首个模型；建议根据实际返回的列表自行选择。

本地 embedding 首次使用会下载模型。模型可用性、计划额度和授权权限由服务端决定。本地 GUI 本身不自动定时执行。

## 凭据与数据

- HTML 不包含账号或 Token；账号信息由本机后端在运行时提供，登录页可能显示当前账号的姓名和邮箱。
- OAuth Token 加密保存在 `data/chatgpt-auth/`；AES-256-GCM 加密密钥位于 macOS 钥匙串的 `PaperFlow.ChatGPT` 项。
- `.env`、`data/`、`.local/`、个人研究草稿和模型缓存不提交到 Git；不要强制添加这些文件或把整个工作目录打包公开。
- 本地凭据不会发送给仓库作者；OAuth 和模型请求发送给 OpenAI。发给模型的论文内容、画像或问题也会随推理请求发送。
- 服务默认只监听本机。它不是可直接公开部署的多用户网站，也不应该通过 GitHub Pages 或公网转发来提供本地授权功能。
- 点击退出可断开当前连接；授权管理入口在登录页内。

## 实现与依赖

`paperflow/providers/chatgpt.py` 调用 Node 传输桥 `scripts/chatgpt-bridge.mjs`；桥接复用官方 SDK 处理授权、刷新、账号切换和 Responses 流。

官方 SDK 源码：[openai/sign-in-with-chatgpt-devkit](https://github.com/openai/sign-in-with-chatgpt-devkit)，固定提交 `0a36fefeb913055c8c7a1a29b63d82b96b2e841a`，由安装脚本下载到 `.local/siwc-devkit`，不随本仓库提交。

上游 SDK 的许可证和第三方声明保留在其下载目录内。新增适配暂不支持 Windows/Linux 凭据加密；需要替换为对应系统的安全凭据存储。

参考：[模型与推理](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)。
