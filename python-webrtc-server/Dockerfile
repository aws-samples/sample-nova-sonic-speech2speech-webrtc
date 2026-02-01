# Nova S2S WebRTC - AgentCore Runtime Dockerfile
# 使用 ECR 中缓存的 Miniconda3 镜像（ARM64 架构）
# 镜像会在 buildspec.yml 的 pre_build 阶段从 Docker Hub 拉取并推送到 ECR
ARG AWS_ACCOUNT_ID
ARG AWS_REGION=ap-northeast-1
FROM --platform=linux/arm64 ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/miniconda3-arm64:latest

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# 安装系统依赖（curl 用于健康检查，gcc/g++ 用于编译 webrtcvad）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        gcc \
        g++ \
        make && \
    rm -rf /var/lib/apt/lists/*

# 复制环境配置文件
COPY environment.yml .
COPY requirements.txt .

# 创建 conda 环境并安装所有依赖
RUN echo "📦 Creating conda environment..." && \
    conda env create -f environment.yml && \
    echo "📦 Installing av via conda..." && \
    conda install -n nova-s2s-webrtc -c conda-forge av=11.0.0 -y && \
    echo "📦 Installing pip dependencies (excluding av and webrtcvad)..." && \
    conda run -n nova-s2s-webrtc pip install --no-cache-dir \
        $(grep -v "^av[>=<]" requirements.txt | grep -v "^webrtcvad" | grep -v "^#" | grep -v "^$" | tr '\n' ' ') && \
    echo "📦 Installing FastAPI and Uvicorn for AgentCore..." && \
    conda run -n nova-s2s-webrtc pip install --no-cache-dir \
        fastapi>=0.104.0 \
        uvicorn[standard]>=0.24.0 \
        pydantic>=2.0.0 && \
    echo "📦 Trying to install webrtcvad (optional)..." && \
    (conda run -n nova-s2s-webrtc pip install --no-cache-dir webrtcvad>=2.0.10 && echo "✅ webrtcvad installed") || echo "⚠️  webrtcvad installation failed (will use RMS fallback)" && \
    echo "🧹 Cleaning up..." && \
    conda clean -afy && \
    rm -rf /opt/conda/pkgs/* && \
    echo "✅ Dependencies installed successfully"

# 复制应用代码
COPY . .

# 创建日志目录
RUN mkdir -p /app/logs && \
    chmod 777 /app/logs

# 设置 conda 环境路径
ENV PATH=/opt/conda/envs/nova-s2s-webrtc/bin:$PATH \
    CONDA_DEFAULT_ENV=nova-s2s-webrtc

# AgentCore Runtime 要求暴露 8080 端口
EXPOSE 8080

# 健康检查
# 使用 /ping 端点检查服务状态
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/ping || exit 1

# 启动 AgentCore 包装器
# 使用 exec 形式确保信号正确传递
CMD ["python", "agentcore_wrapper.py"]
