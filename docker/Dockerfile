# syntax=docker/dockerfile:1.7

# ── Shared base (system deps + Python env) ───────────────────────────────────
FROM ubuntu:22.04 AS base

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG DEBIAN_FRONTEND=noninteractive

# 替换为阿里云 apt 镜像
RUN sed -i 's|http://archive.ubuntu.com/ubuntu|http://mirrors.aliyun.com/ubuntu|g' /etc/apt/sources.list && \
    sed -i 's|http://security.ubuntu.com/ubuntu|http://mirrors.aliyun.com/ubuntu|g' /etc/apt/sources.list

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    pkg-config \
    git \
    curl \
    gnupg \
    software-properties-common \
    openssh-client \
    libusb-1.0-0-dev \
    libgl1 \
    libegl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    ffmpeg \
    libavformat-dev \
    libavcodec-dev \
    libavdevice-dev \
    libavutil-dev \
    libswscale-dev \
    libswresample-dev \
    libavfilter-dev \
    usbutils \
    udev \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-dev \
    python3.12-venv \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:/root/.local/bin:${PATH}"
ENV UV_LINK_MODE=copy
ENV UV_COMPILE_BYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple

WORKDIR /workspace

COPY pyproject.toml ./
COPY src ./src
COPY tests ./tests
COPY configs ./configs

RUN uv venv --python /usr/bin/python3.12 "${VIRTUAL_ENV}" && \
    uv pip install --python "${VIRTUAL_ENV}/bin/python" pytest numpy opencv-python-headless && \
    uv pip install --python "${VIRTUAL_ENV}/bin/python" -e .[recording]

# ── RealSense / Orbbec ────────────────────────────────────────────────────────
FROM base AS realsense

ARG INSTALL_REALSENSE=1
ARG INSTALL_ORBBEC=0
ARG PYORBBECSDK_REPO=git@github.com:orbbec/pyorbbecsdk.git

RUN if [ "${INSTALL_REALSENSE}" = "1" ]; then \
      uv pip install --python "${VIRTUAL_ENV}/bin/python" pyrealsense2; \
    fi

RUN --mount=type=ssh if [ "${INSTALL_ORBBEC}" = "1" ]; then \
      git clone --depth 1 "${PYORBBECSDK_REPO}" /tmp/pyorbbecsdk && \
      uv pip install --python "${VIRTUAL_ENV}/bin/python" pybind11 wheel setuptools && \
      mkdir -p /tmp/pyorbbecsdk/build && \
      cd /tmp/pyorbbecsdk/build && \
      cmake .. -Dpybind11_DIR="$("${VIRTUAL_ENV}/bin/python" -m pybind11 --cmakedir)" && \
      cmake --build . -j"$(nproc)" && \
      cmake --install . && \
      cd /tmp/pyorbbecsdk && \
      uv pip install --python "${VIRTUAL_ENV}/bin/python" . && \
      rm -rf /tmp/pyorbbecsdk; \
    fi

ENTRYPOINT ["python3", "-m", "sensor_proto.stream_main"]
CMD ["--config", "configs/mock-session.json"]

# ── Hikrobot / MVS SDK ────────────────────────────────────────────────────────
FROM base AS hikrobot

COPY hik-sdk/MvCamCtrlSDK_Runtime-4.7.0_x86_64_20251113.deb /tmp/mvs-runtime.deb
RUN apt-get update && \
    dpkg -i /tmp/mvs-runtime.deb; \
    apt-get install -f -y --no-install-recommends && \
    rm /tmp/mvs-runtime.deb && \
    rm -rf /var/lib/apt/lists/*

ENV LD_LIBRARY_PATH="/opt/MVS/lib/64${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
ENV PYTHONPATH="/opt/MVS/Samples/64/Python${PYTHONPATH:+:${PYTHONPATH}}"

ENTRYPOINT ["python3", "-m", "sensor_proto.stream_main"]
CMD ["--config", "configs/hikrobot-stream.json"]
