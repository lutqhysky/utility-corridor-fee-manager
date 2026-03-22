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

- 综改水务
- 汾飞能源
- 国网太供
- 潇河园区
- 潇北污水处理厂
- 华芯二标段

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

健康检查地址：

```bash
http://127.0.0.1:8000/healthz
```

## GitHub 维护优先：推荐发布流程

为了避免“服务器手改代码”和“GitHub 仓库代码”不一致，推荐以后统一采用下面的流程发布：

### 1. GitHub 合并前检查清单

在 GitHub 上合并 PR 到 `main` 前，至少确认：

- `app/main.py` 已包含正确的应用入口顺序：
  - 先定义 `initialize_application()`
  - 再定义 `lifespan()`
  - 再定义 `create_app()`
  - 最后才是 `app = create_app()`
- `app/routes/health.py` 已存在，并提供 `/healthz`
- `docker-compose.yml` 已包含 `healthcheck`
- 如果本次涉及提醒功能，则确认 `app/services/reminder_service.py` 的环境变量解析和发送逻辑也在本次变更里

### 2. 服务器标准部署步骤

当 GitHub 的 `main` 合并完成后，服务器只做下面这些标准动作：

```bash
cd /root/utility-corridor-fee-manager
git pull
docker compose down --remove-orphans
docker compose up -d --build
docker logs corridor-fee-manager --tail=80
curl -i http://127.0.0.1:8000/healthz
curl -i http://127.0.0.1:8000/
```

### 3. 发布后的判断标准

- `/healthz` 返回 `200 OK`，说明应用进程和路由层已经正常
- 首页 `/` 返回 `200 OK`，说明模板渲染和数据库初始化没有阻塞启动
- `docker inspect --format='{{json .State.Health}}' corridor-fee-manager` 如果显示 `healthy`，说明容器自检也通过

### 4. 不推荐再做的事情

后续尽量避免下面这些做法：

- 直接在服务器里手改 `app/main.py`
- 只改服务器文件但不提交到 GitHub
- 不看 `/healthz`，直接反复重启容器排错

这样做的原因很简单：

**服务器代码、镜像代码、GitHub 代码一旦不一致，后面会非常难排查。**

### 收费提醒机器人配置

如果你希望系统自动对 **收费记录中状态为“未开始”且即将到达应收时间** 的数据发送机器人提醒，请直接进入 **收费记录** 页面，在“提醒配置”表单里填写：

- 提醒渠道（目前支持 `dingtalk`、`wecom`）
- 机器人 Webhook 地址
- 提前多少天触发提醒（默认 3 天）
- 后台检查间隔（默认 300 秒，最小 60 秒）

保存后，这些配置会直接写入数据库，作为系统的唯一提醒配置来源；**不需要把机器人配置写死在代码里，也不需要放到 `docker-compose.yml` 或环境变量里**。

配置完成后，系统会：

- 启动后自动轮询检查
- 只对状态为 `未开始` 的收费记录检查
- 当 `应收时间` 落在未来 N 天内时推送消息
- 同一条记录针对同一个应收日期只推送一次，避免重复轰炸
- 在下一次轮询时自动读取你刚刚在网页里保存的最新配置，无需重启服务

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
