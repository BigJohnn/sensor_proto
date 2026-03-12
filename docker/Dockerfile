# syntax=docker/dockerfile:1.7
FROM osrf/ros2:devel


SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG DEBIAN_FRONTEND=noninteractive
ARG INSTALL_REALSENSE=1
ARG INSTALL_ORBBEC=1
ARG PYORBBECSDK_REPO=git@github.com:orbbec/pyorbbecsdk.git

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

WORKDIR /workspace

COPY pyproject.toml ./
COPY src ./src
COPY tests ./tests
COPY configs ./configs

RUN uv venv --python /usr/bin/python3.12 "${VIRTUAL_ENV}" && \
    uv pip install --python "${VIRTUAL_ENV}/bin/python" pytest numpy opencv-python-headless && \
    uv pip install --python "${VIRTUAL_ENV}/bin/python" -e .[recording]

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

ENTRYPOINT ["python", "-m", "sensor_proto.main"]
CMD ["--config", "configs/mock-session.json"]
