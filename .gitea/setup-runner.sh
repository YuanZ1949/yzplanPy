#!/bin/bash
# ============================================================
#  Gitea Act Runner 安装脚本 (NAS Linux)
#  用法: 在 NAS 上以 root 运行此脚本
# ============================================================

set -e

# ---------- 配置 ----------
GITEA_URL="http://yuannas.local:3000"
RUNNER_NAME="nas-linux-runner"
RUNNER_LABELS="self-hosted:host,linux:host,ubuntu-latest:docker://gitea/runner-images:ubuntu-latest"
INSTALL_DIR="/usr/local/bin"
CONFIG_DIR="/etc/act_runner"

echo "========================================="
echo "  Gitea Act Runner 安装"
echo "========================================="

# 1. 检查是否已安装 Docker (可选，用于容器模式)
if command -v docker &> /dev/null; then
    echo "[INFO] 检测到 Docker，可使用容器模式"
    DOCKER_AVAILABLE=true
else
    echo "[INFO] 未检测到 Docker，将使用主机模式 (host mode)"
    DOCKER_AVAILABLE=false
    RUNNER_LABELS="self-hosted:host,linux:host"
fi

# 2. 下载 act_runner 二进制
echo "[INFO] 下载 act_runner..."
ARCH=$(uname -m)
case $ARCH in
    x86_64)  ARCH="amd64" ;;
    aarch64) ARCH="arm64" ;;
    armv7l)  ARCH="armv6" ;;
    *)       echo "[ERROR] 不支持的架构: $ARCH"; exit 1 ;;
esac

# 从 Gitea releases 页面获取最新版本
RUNNER_VERSION=$(curl -s "https://gitea.com/gitea/act_runner/releases" | grep -oP 'v[\d.]+' | head -1)
if [ -z "$RUNNER_VERSION" ]; then
    RUNNER_VERSION="v3.3.2"  # 备用版本
fi

DOWNLOAD_URL="https://gitea.com/gitea/act_runner/releases/download/${RUNNER_VERSION}/gitea-runner-${RUNNER_VERSION#v}-linux-${ARCH}"
curl -fsSL "$DOWNLOAD_URL" -o /usr/local/bin/act_runner
chmod +x /usr/local/bin/act_runner
echo "[OK] act_runner 已安装到 /usr/local/bin/act_runner"

# 3. 生成配置文件
mkdir -p "$CONFIG_DIR"
act_runner config generate > "$CONFIG_DIR/config.yaml"

# 4. 修改配置: 使用主机模式
sed -i 's/^container:/# container:/' "$CONFIG_DIR/config.yaml"
sed -i 's/^  network:.*/  # network: host/' "$CONFIG_DIR/config.yaml"

echo "[OK] 配置文件已生成: $CONFIG_DIR/config.yaml"

# 5. 注册 Runner
echo ""
echo "========================================="
echo "  注册 Runner"
echo "========================================="
echo ""
echo "请先在 Gitea 网页上获取注册 Token:"
echo "  1. 打开 $GITEA_URL"
echo "  2. 进入仓库设置 → Actions → Runners"
echo "  3. 点击 'Create new Runner'"
echo "  4. 复制 Token"
echo ""
read -p "请输入注册 Token: " REG_TOKEN

if [ -z "$REG_TOKEN" ]; then
    echo "[ERROR] Token 不能为空"
    exit 1
fi

act_runner register \
    --name "$RUNNER_NAME" \
    --labels "$RUNNER_LABELS" \
    --instance "$GITEA_URL" \
    --token "$REG_TOKEN" \
    --config "$CONFIG_DIR/config.yaml"

echo "[OK] Runner 注册成功"

# 6. 创建 systemd 服务
cat > /etc/systemd/system/act_runner.service << EOF
[Unit]
Description=Gitea Actions Runner
After=network.target

[Service]
Type=simple
WorkingDirectory=$CONFIG_DIR
ExecStart=/usr/local/bin/act_runner daemon --config $CONFIG_DIR/config.yaml
Restart=always
RestartSec=10
User=root

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable act_runner
systemctl start act_runner

echo ""
echo "========================================="
echo "  安装完成!"
echo "========================================="
echo ""
echo "Runner 状态: systemctl status act_runner"
echo "查看日志:   journalctl -u act_runner -f"
echo "停止服务:   systemctl stop act_runner"
echo ""
echo "注意: 此 Runner 使用主机模式 (host mode)"
echo "      工作流将直接在 NAS 上执行"
