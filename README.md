# 综合管廊有偿使用费管理系统（第二版）

这是一个基于 **FastAPI + Jinja2 + SQLAlchemy + SQLite + Docker** 的综合管廊收费管理项目原型。

这个版本不是演示空壳，而是已经按照你当前 Excel 业务结构，拆成了可以继续开发和部署的项目骨架。

## 这个版本已经包含什么

### 1. 核心数据模型
项目已经拆成 5 张核心业务表：

- `companies`：单位表
- `pipeline_entries`：入廊管线表
- `fee_standards`：收费标准表
- `fee_records`：收费记录表
- `contracts`：合同备案表

### 2. 已完成页面
- 首页概览
- 单位管理
- 单位详情页
- 入廊管线清单
- 收费记录
- 合同备案

### 3. 已体现的业务字段
收费记录页已经包含：

- 收费类型
- 收费期间
- 不含税金额
- 税率
- 税金
- 含税金额
- 应收时间
- 实收金额
- 实收时间
- 收缴状态
- 备注

单位详情页已经体现：

- 单位基本信息
- 入廊管线清单
- 管廊有偿使用费收缴情况
- 合同备案情况

### 4. 示例种子数据
项目首次启动时会自动写入几条示例数据，方便你直接看页面效果。
这些示例数据参考了你现有 Excel 中出现过的单位和项目名称，例如：

-XX水务


## 目录结构

```bash
utility-corridor-fee-manager-v2/
├── app/
│   ├── main.py
│   ├── database.py
│   ├── models/
│   ├── routes/
│   ├── services/
│   ├── templates/
│   └── static/
├── data/
├── uploads/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## 本地运行方式

### 方式一：直接用 Python 运行

先进入项目目录：

```bash
cd utility-corridor-fee-manager-v2
```

创建虚拟环境并安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

启动项目：

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

浏览器访问：

```bash
http://127.0.0.1:8000
```

### 收费提醒机器人配置

如果你希望系统自动对 **收费记录中状态为“未开始”且即将到达应收时间** 的数据发送机器人提醒，可以在启动前配置下面这些环境变量：

```bash
export FEE_REMINDER_CHANNEL=dingtalk
export FEE_REMINDER_WEBHOOK='你的机器人 webhook 地址'
export FEE_REMINDER_DAYS_AHEAD=3
export FEE_REMINDER_CHECK_INTERVAL_SECONDS=300
```

说明：

- `FEE_REMINDER_CHANNEL`：目前支持 `dingtalk`、`wecom`
- `FEE_REMINDER_WEBHOOK`：对应机器人的 Webhook 地址
- `FEE_REMINDER_DAYS_AHEAD`：提前多少天触发提醒，默认 3 天
- `FEE_REMINDER_CHECK_INTERVAL_SECONDS`：后台每隔多久检查一次，默认 300 秒

配置完成后，系统会：

- 启动后自动轮询检查
- 只对状态为 `未开始` 的收费记录检查
- 当 `应收时间` 落在未来 N 天内时推送消息
- 同一条记录针对同一个应收日期只推送一次，避免重复轰炸

另外，你也可以在 **收费记录** 页面点击“执行提醒检查”按钮，手动测试机器人是否配置成功。

---

### 方式二：使用 Docker Compose 运行

```bash
docker compose up -d --build
```

浏览器访问：

```bash
http://你的服务器IP:8000
```

## 上传到 GitHub 的标准流程

### 1. 新建 GitHub 仓库
仓库名建议：

```bash
utility-corridor-fee-manager-v2
```

### 2. 本地初始化 Git

```bash
git init
git add .
git commit -m "init corridor fee manager v2"
```

### 3. 关联远程仓库

```bash
git branch -M main
git remote add origin 你的仓库地址
git push -u origin main
```

## 部署到服务器的建议流程

### 1. 服务器安装 Docker
### 2. 拉取代码

```bash
git clone 你的仓库地址
cd utility-corridor-fee-manager-v2
```

### 3. 启动服务

```bash
docker compose up -d --build
```

### 4. 访问系统

```bash
http://服务器IP:8000
```

### 5. 后续可继续接入
- Nginx
- 域名
- HTTPS
- 反向代理
- 登录权限
- Excel 导入导出

## 接下来最适合继续开发的内容

建议下一步继续做下面这些：

### 第一优先级
- 编辑 / 删除功能
- 单位明细导出 Excel
- 汇总统计页
- 收费状态自动判断

### 第二优先级
- 入廊费税率与运维费税率自动带出
- 从现有 Excel 批量导入基础数据
- 收费提醒列表
- 欠费统计

### 第三优先级
- 登录权限
- 操作日志
- 合同附件上传
- PostgreSQL 版本

## 说明
当前版本重点是：

**先把 Excel 的业务结构搬成一个可以跑的系统骨架。**

也就是说，这个版本适合你：

- 上传到 GitHub
- 部署到服务器
- 在这个基础上继续迭代

而不是一次性就做成最终完整版。
