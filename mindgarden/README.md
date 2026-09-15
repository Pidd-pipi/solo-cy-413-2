# 🌻 心晴花园 MindGarden

一款**开箱即用**的心理健康与情绪日记应用：记录心情、浇灌花园、完成心理测评、写下私密日记。

> 零第三方依赖 —— 只需要 Python 3.8+，不需要安装任何东西，不需要 Docker。

## 快速启动

```bash
cd mindgarden
python3 server.py
```

然后打开浏览器访问 **http://localhost:8000**

首次启动会自动建库、建表并写入种子数据（3 份示例测评 + 管理员账号）。

| 内置账号 | 密码 | 角色 |
| --- | --- | --- |
| `admin` | `admin123` | 管理员（可创建测评） |

普通用户在登录页点「立即注册」即可自助注册。生产部署时请通过环境变量 `ADMIN_PASSWORD` 覆盖默认管理员密码。

## 功能一览（六条主流程）

| 流程 | 页面 | 说明 |
| --- | --- | --- |
| 注册登录 | `#/register` `#/login` | 注册即登录；会话 Cookie 保持 7 天，刷新不掉线 |
| 心情花园 | `#/garden` | 每条心情开成一朵花；连续记录天数、本周曲线、快速记录 |
| 情绪记录 | `#/moods` | 记一笔心情（1-5 级 + 备注 + 日期）；**同一条记录同时进入本周曲线和按日筛选** |
| 心理测评 | `#/assessments` | 答题 → 服务端计分 → 生成报告；**只有管理员能创建测评** |
| 日记本 | `#/diary` | 写日记、编辑、删除；时间轴可**按同一套 1-5 心情等级**筛选、搜索 |
| 个人资料 | `#/profile` | 改昵称/头像/简介；查看**我的测评报告**与数据统计 |

## 设计要点（与需求的对应关系）

**数据与页面状态可回读**
- 数据存在 SQLite 文件（`data/mindgarden.db`），重启服务器不丢
- 页面状态：hash 路由（刷新后仍在原页）+ 会话 Cookie（刷新后仍登录）+ `sessionStorage` 记住上次页面

**权限与归属**
- 未登录访问任何 `/api/*` 私人接口一律 `401`
- 所有私人查询都带 `user_id` 条件；跨账号读/改/删返回 `404`（不泄露数据是否存在）
- 创建测评接口校验 `role = admin`，普通用户得到 `403`

**口径一致（同一结论）**
- 心情等级 1-5 全站只有一份定义：后端 `app/db.py: MOOD_LEVELS`，前端 `public/js/ui.js: MOOD_LEVELS`
- 本周曲线与按日筛选读同一张 `moods` 表；测评提交即写入 `assessment_results`，个人报告直接读该表；日记筛选与情绪记录共用同一等级列
- 集成测试专门验证：同一条记录在周曲线与按日筛选中的数值一致、改日记等级后筛选结果同步变化

**测评区间配置完整性**
- 保存/编辑测评时，按**题目实际可达总分集合**（子集和，稀疏分值不误伤）校验结果区间：漏空、重叠、倒序一律 400 拒绝，并指明具体位置（如「总分 6 没有被任何结果区间覆盖（漏空）」）
- 历史遗留的坏配置：提交答案时拦截，返回 `409` + 可修正的具体原因，**不写入残缺报告**；管理员在测评列表能看到「⚠️ 区间配置有误」标记，点「编辑」修复后即可恢复作答
- 已有报告是提交时的快照，编辑测评不影响历史报告与个人报告汇总

**可见反馈**
- 空数据：花园空、当日无记录、本周无曲线、无日记、无测评报告，均有插画式空状态
- 非法输入：服务端统一 `400` + 中文提示（如「心情等级必须在 1-5 之间」），前端表单内联展示
- 服务不可用：网络失败或 5xx 时页面顶部出现「服务暂时不可用」横幅并可一键重试；设置 `MAINTENANCE=1` 可演示维护模式（API 返回 503）

**明确不做**：音频、支付、社交。

## 项目结构

```
mindgarden/
├── server.py              # 入口：HTTP 服务、路由表、静态文件、安全头、维护模式
├── app/
│   ├── db.py              # SQLite 连接、六张表 schema、种子数据、心情等级唯一定义
│   ├── security.py        # PBKDF2 密码哈希、会话令牌、登录限流
│   ├── validate.py        # 全部输入校验（非法输入 → 400 + 中文提示）
│   └── handlers.py        # 业务逻辑：认证/资料/情绪/日记/测评/报告/花园
├── public/                # 前端 SPA（原生 ES Module，无需构建）
│   ├── index.html
│   ├── styles.css
│   └── js/
│       ├── api.js         # fetch 封装：401 跳登录、5xx/断网亮服务不可用横幅
│       ├── ui.js          # 共享组件：心情选择器、周曲线 SVG、空状态、Toast
│       ├── pages.js       # 六个页面的渲染与交互
│       └── app.js         # hash 路由 + 导航守卫
├── tests/
│   ├── test_api.py            # 72 项 API 集成测试（权限/隔离/一致性/校验）
│   └── test_frontend_smoke.mjs # 17 项前端无头冒烟测试（需 Node）
├── data/                  # SQLite 数据库文件（运行时生成）
└── run.sh                 # 一键启动脚本
```

## API 一览

所有响应均为 JSON；错误统一为 `{"error": "中文提示"}` + 对应状态码。
写操作需要会话 Cookie 和 `X-Requested-With: fetch` 头（CSRF 防护）。

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/api/health` | 健康检查（维护模式下也可用） | 公开 |
| POST | `/api/auth/register` | 注册（用户名/邮箱/密码） | 公开 |
| POST | `/api/auth/login` | 登录 | 公开 |
| POST | `/api/auth/logout` | 登出 | 登录 |
| GET | `/api/auth/me` | 当前用户 | 登录 |
| GET / PUT | `/api/profile` | 个人资料与统计 | 登录 |
| GET | `/api/moods?date=YYYY-MM-DD` | 按日筛选情绪记录 | 本人 |
| GET | `/api/moods/week` | 本周曲线（7 天均值） | 本人 |
| POST | `/api/moods` | 记录心情（level 1-5） | 本人 |
| DELETE | `/api/moods/{id}` | 删除情绪记录 | 本人 |
| GET | `/api/garden` | 心情花园（近 30 天 + 连续天数） | 本人 |
| GET / POST | `/api/diaries` | 日记列表（`mood`/`q` 筛选）/ 写日记 | 本人 |
| GET / PUT / DELETE | `/api/diaries/{id}` | 日记详情 / 编辑 / 删除 | 本人 |
| GET | `/api/assessments` | 测评列表（管理员可见 `configError` 体检结果） | 登录 |
| POST | `/api/assessments` | 创建测评（保存时校验区间不重不漏） | **仅管理员** |
| GET | `/api/assessments/{id}` | 测评详情（普通用户不含分值，防作弊；管理员含完整配置） | 登录 |
| PUT | `/api/assessments/{id}` | 编辑测评（同样校验区间，用于修复坏配置） | **仅管理员** |
| POST | `/api/assessments/{id}/submit` | 提交答案，服务端计分；配置损坏时 409 且不写报告 | 登录 |
| GET | `/api/reports` `/api/reports/{id}` | 我的测评报告 | 本人 |

## 运行测试

```bash
# API 集成测试（72 项：注册登录、未登录 401、跨账号 404、非管理员 403、
# 周曲线与按日筛选一致、测评计分入库、日记等级筛选、非法输入 400、CSRF）
python3 tests/test_api.py

# 前端冒烟测试（17 项，需要 Node.js）
node tests/test_frontend_smoke.mjs
```

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PORT` | `8000` | 服务端口 |
| `DB_PATH` | `./data/mindgarden.db` | SQLite 数据库文件路径 |
| `ADMIN_PASSWORD` | `admin123` | 首次初始化时的管理员密码 |
| `MAINTENANCE` | 空 | 设为 `1` 进入维护模式：API 返回 503，用于演示「服务暂时不可用」反馈 |

## 安全说明

- 密码使用 PBKDF2-SHA256（26 万次迭代 + 随机盐）哈希存储，绝不保存明文
- 会话令牌为 256 位随机数，存于 `HttpOnly; SameSite=Lax` Cookie，7 天过期
- 登录/注册接口按 IP 限流（5 分钟 10 次），防暴力破解
- 全部 SQL 使用参数化查询；所有用户内容输出前转义，防 XSS
- 写操作校验自定义请求头，配合 SameSite Cookie 抵御 CSRF
- 响应带安全头：`Content-Security-Policy`、`X-Frame-Options`、`X-Content-Type-Options` 等
- 生产部署请置于 HTTPS 反向代理之后，并修改 `ADMIN_PASSWORD`

## 免责声明

测评结果仅供自我了解，**不构成医学诊断**。如有持续的情绪困扰，请寻求专业心理帮助。

## License

MIT
